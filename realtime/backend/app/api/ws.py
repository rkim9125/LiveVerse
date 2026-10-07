"""WebSocket protocol for the interpreter screen (design 3.14).

Client to server
    transcript  {seq, text, is_final, lang?, t_client?, t_audio?}  STT segment.
                t_audio (seconds into a recording) replaces the server clock for
                the session's timing, so a recording can be replayed faster
                than real time.
    switch      {candidate_id}                          show an alternative
    search      {query}                                 show a typed reference
    clear       {}                                      empty the screen
    rendered    {seq, t_render}                         when the screen drew a state
    ping        {t_client}                              clock offset estimate

Server to client
    state       session state + seq, t_recv, t_sent     sent to every screen on a change
    preview     {seq, candidates}                       for interim segments, no change
    pong        {t_client, t_server}
    error       {message}
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.stt.base import Segment, SegmentSink

router = APIRouter()


class Hub:
    """The connected screens. One session, possibly several screens."""

    def __init__(self) -> None:
        self.sockets: set[WebSocket] = set()

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.sockets):
            try:
                await ws.send_json(message)
            except (RuntimeError, WebSocketDisconnect):
                self.sockets.discard(ws)


def _is_local(ws: WebSocket) -> bool:
    from app.main import LOCAL_HOSTS

    host = ws.client.host if ws.client else ""
    return ws.app.state.settings.allow_remote or host in LOCAL_HOSTS


@router.websocket("/ws")
async def interpreter_socket(ws: WebSocket) -> None:
    if not _is_local(ws):
        await ws.close(code=1008, reason="localhost only")
        return
    await ws.accept()
    app = ws.app
    session, hub = app.state.session, app.state.hub
    sink = SegmentSink(session, hub.broadcast, app.state.latency)
    offsets: list[float] = []  # receive time minus client send time, from pings
    conn = uuid.uuid4().hex[:8]
    hub.sockets.add(ws)
    await ws.send_json(session.state() | {"seq": None, "t_sent": time.time()})
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except ValueError:
                await ws.send_json({"type": "error", "message": "messages must be JSON objects"})
                continue
            t_recv = time.time()
            kind = msg.get("type") if isinstance(msg, dict) else None
            # The smallest sample has the least queueing in it (as in NTP).
            offset = min(offsets) if offsets else None

            if kind == "transcript":
                # The browser is a speech source: its segments go to the same sink a
                # server side Whisper source would use (app/stt/base.py).
                text, seq = msg.get("text"), msg.get("seq")
                if not isinstance(text, str) or not isinstance(seq, int):
                    await ws.send_json(
                        {"type": "error", "message": "transcript needs text and seq"}
                    )
                    continue
                t_audio = msg.get("t_audio")
                t_client = msg.get("t_client")
                segment = Segment(
                    text=text,
                    is_final=bool(msg.get("is_final", False)),
                    seq=seq,
                    t_client=t_client if isinstance(t_client, (int, float)) else None,
                    t_audio=float(t_audio) if isinstance(t_audio, (int, float)) else None,
                    lang=str(msg.get("lang", "ko-KR")),
                    conn=conn,
                    clock_offset=offset,
                    t_recv=t_recv,
                )
                reply = await sink.submit(segment)
                if reply is not None:
                    await ws.send_json(reply)

            elif kind in ("switch", "search", "clear"):
                try:
                    if kind == "switch":
                        changed = session.switch(str(msg.get("candidate_id")), now=t_recv)
                    elif kind == "search":
                        changed = session.search(str(msg.get("query", "")), now=t_recv)
                    else:
                        changed = session.clear(now=t_recv)
                except (KeyError, ValueError) as e:
                    await ws.send_json({"type": "error", "message": str(e).strip("'")})
                    continue
                if changed:
                    await hub.broadcast(
                        session.state() | {"seq": None, "t_recv": t_recv, "t_sent": time.time()}
                    )

            elif kind == "rendered":
                if isinstance(msg.get("seq"), int):
                    app.state.latency.rendered(conn, msg["seq"], msg.get("t_render"), offset)

            elif kind == "ping":
                t_client = msg.get("t_client")
                if isinstance(t_client, (int, float)):
                    offsets.append(t_recv - t_client)
                    del offsets[:-5]
                await ws.send_json({"type": "pong", "t_client": t_client, "t_server": t_recv})

            else:
                await ws.send_json({"type": "error", "message": f"unknown message type {kind!r}"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.sockets.discard(ws)
