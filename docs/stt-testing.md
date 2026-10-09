# Testing speech input (stage 3)

Stage 3 adds speech input. Chrome's Web Speech API transcribes Korean in the browser, and the STT check page sends each segment to the server over the WebSocket. This guide covers:

1. a test with your own voice
2. routing audio through BlackHole
3. the recorded sermon evaluation, which needs the preacher's permission first

Chrome's Web Speech API sends the microphone audio to Google's speech service. Anything the page hears leaves the computer. With your own voice that is your choice. For a recorded sermon, see [Recorded sermon evaluation](#recorded-sermon-evaluation).

## Requirements

- macOS with Google Chrome. Safari and Firefox are not supported here.
- [uv](https://docs.astral.sh/uv/) for the backend (see [realtime/backend/README.md](../realtime/backend/README.md)).
- ffmpeg (`brew install ffmpeg`), for the evaluation scripts only.
- Node 20 or later, for the frontend unit tests only.

## A dedicated Chrome profile

Use a separate Chrome profile for testing. Its microphone choice and site permissions then stay apart from your everyday browsing. Start it like this:

```sh
open -na "Google Chrome" --args \
  --user-data-dir="$HOME/.liveverse-chrome" \
  --disable-background-timer-throttling \
  --disable-renderer-backgrounding \
  --disable-backgrounding-occluded-windows \
  http://127.0.0.1:8000/ui/stt-check/
```

The three `--disable-...` flags stop Chrome from slowing a page that is hidden or behind another window.

To choose the microphone in this profile, open `chrome://settings/content/microphone` and pick the device at the top of the page. You can also click the icon at the left of the address bar on the STT check page. The page shows the device it is using next to **Input** once you press **Start listening**.

## Test with your own voice

1. Start the server:

   ```sh
   cd realtime/backend
   uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. Open the test profile with the command above. Set the microphone to your Mac's built-in microphone or a headset.
3. Press **Start listening** and allow the microphone when Chrome asks. **Server** should read `connected` and **Speech** should read `listening`.
4. Speak in Korean. Some things to try:

   | Say | Expected |
   | --- | --- |
   | 요한복음 3장 16절 말씀입니다 | John 3:16 shows at once |
   | 17절을 보면 | John 3:17 (relative to the verse on screen) |
   | 로마서 8장 | waits dimmed; nothing new is shown |
   | (within 10 s) 28절 | Romans 8:28 shows |
   | 창세기 1장을 함께 읽겠습니다 | Genesis 1 shows (an announcement phrase) |

5. Check the page:
   - **Interim** shows text while you speak. **Recent finals** lists each finished segment.
   - The passage card shows the reference, a source badge (rule, context, quote, manual) and the confidence.
   - **Last update** shows the time from the end of your segment to the screen.
   - **Restarts** counts automatic restarts. Chrome ends recognition after silence or about a minute, and the page restarts it.
6. Try the search box (`요 3:16`, `John 3:16`), a click on an alternative, and **Clear screen**.
7. Press **Stop** when done. Latency for the session:

   ```sh
   curl 127.0.0.1:8000/api/metrics/latency
   ```

   The raw log is `realtime/backend/logs/latency-YYYYMMDD.jsonl`. It holds times, sequence numbers and references, and no transcript text.

**If something goes wrong:**

- **Speech shows an error about permission:** allow the microphone for `127.0.0.1` in `chrome://settings/content/microphone`, then reload.
- **Speech says `network`:** the page retries after 1, 2 and 4 seconds. Check the internet connection.
- **Server says `reconnecting`:** the server is not running or restarted. Finals are queued and sent once it is back.

## BlackHole (virtual audio device)

BlackHole passes audio from one app to another. Any audio sent to the BlackHole output arrives at the BlackHole input. The evaluation scripts use it to play a recording into Chrome as if it were a microphone.

**Install:**

```sh
brew install --cask blackhole-2ch
sudo killall coreaudiod   # or restart the Mac, so macOS finds the new device
```

Check that ffmpeg sees it:

```sh
cd realtime/backend
uv run python eval/play_to_device.py --list-devices
```

**Hearing the audio while it plays (Multi-Output Device):** BlackHole alone is silent to you. To hear the playback while Chrome gets it too:

1. Open **Audio MIDI Setup** (in Applications, Utilities).
2. Click **+** at the bottom left and choose **Create Multi-Output Device**.
3. Tick **BlackHole 2ch** and your speakers or headphones.
4. Set **Primary Device** (the clock source) to the speakers or headphones.
5. Tick **Drift Correction** for BlackHole 2ch.
6. Optionally rename it, for example to `LiveVerse Monitor`.

Then play into the Multi-Output Device (`--device "Multi-Output Device"`, or the new name) and keep Chrome's microphone set to **BlackHole 2ch**. The volume keys do not control a Multi-Output Device; set the volume in the playing app or on the speakers. Do not make the Multi-Output Device your system output during a run, or other sounds on the Mac will reach Chrome too.

## Recorded sermon evaluation

**Do not run this section until the preacher has agreed that the recording may be sent to Google's speech service.** `play_to_device.py` refuses to play without `--consent-confirmed`. It also plays dev set sermons only.

The corpus is in `~/liveverse-corpus` (or `$LIVEVERSE_CORPUS`). All commands below run from `realtime/backend`.

1. **Pick the window:** `--auto` chooses the 10 minutes with the most labeled references. `--dry-run` sends nothing:

   ```sh
   uv run python eval/play_to_device.py sermon-01 --auto --dry-run
   ```

2. **Prepare Chrome:**
   - Start the server and the test profile.
   - Set the microphone to **BlackHole 2ch**.
   - Tick **Evaluation capture** and press **Start listening**.

3. **Play the window:**

   ```sh
   uv run python eval/play_to_device.py sermon-01 --auto \
     --device "Multi-Output Device" --consent-confirmed
   ```

   This writes a run file, `~/liveverse-corpus/sermon-01/runs/<time>.json`, with the start time of the playback.

4. **Save the capture:** when playback ends, wait a few seconds, press **Stop**, then **Save transcript**. The file goes to Downloads.

5. **Put the capture on the recording's timeline:**

   ```sh
   uv run python eval/capture_to_segments.py ~/Downloads/webspeech-capture-<time>.json \
     ~/liveverse-corpus/sermon-01/runs/<time>.json
   ```

   This writes `~/liveverse-corpus/sermon-01/webspeech.<time>.json`. Then delete the capture from Downloads.

6. **Score it against the Whisper transcript, over the same range:**
   - Use the window start printed in step 1 for `--from` and that start plus 600 for `--to`.
   - Web Speech has no word times, so report both slack values: 1 s and 5 s.

   ```sh
   S="--from 180 --to 780"
   uv run python eval/score.py sermon-01 --transcript webspeech.<time>.json --name ws-01-s1 $S --slack 1
   uv run python eval/score.py sermon-01 --transcript webspeech.<time>.json --name ws-01-s5 $S --slack 5
   uv run python eval/score.py sermon-01 --transcript whisper.prompted.json --name wh-01-s1 $S --slack 1
   uv run python eval/score.py sermon-01 --transcript whisper.prompted.json --name wh-01-s5 $S --slack 5
   ```

   In zsh, write `${=S}` instead of `$S`.

7. **Latency** from the end of each spoken reference to the screen:

   ```sh
   uv run python eval/stt_latency.py ~/liveverse-corpus/sermon-01/runs/<time>.json \
     logs/latency-YYYYMMDD.jsonl
   ```

   It prints p50, p95 and max for:
   - speech recognition, from speech end until the final segment is sent
   - the server
   - drawing the screen
   - the total

Reproduce scores with the detector at the `eval-freeze-v1` tag where a comparison with earlier results matters.

### Whole sermons, unattended

After the 10 minute results look sound, a whole sermon can run overnight. Leave out `--auto` and give `--start 0 --duration <seconds>`. Two things keep the run alive:

- **Keep the Mac awake.** Wrap the playback in `caffeinate`, which keeps the display and system from sleeping until the command ends:

  ```sh
  caffeinate -dims uv run python eval/play_to_device.py sermon-01 --start 0 --duration 3000 \
    --device "BlackHole 2ch" --consent-confirmed
  ```

- **Keep Chrome in front.**
  - Start the test profile with the flags above.
  - Leave the STT check window visible: not minimized, not behind a full screen app, and not on another desktop (Space).
  - Turn off the screen saver and **Lock Screen** timers in System Settings for the night. A locked screen can stop the microphone.
  - Plug in the power adapter.

In the morning, check the **Restarts** and **Gaps** counters on the page before saving the capture. A large gap means part of the sermon was not heard.

## Whisper streaming worker (experiment)

The worker in `realtime/backend/stt_worker` is a second speech source that runs on the Mac itself. It uses Silero VAD and mlx-whisper (Apple Silicon only) and sends segments to the server like the browser does. Nothing leaves the computer.

Install its dependencies once:

```sh
cd realtime/backend
uv sync --group dev --group eval --group stt
```

**Offline, finals only, no server** (dev sermons only). Writes `whisperstream.<name>.json` next to the Whisper transcripts:

```sh
uv run python -m stt_worker --sermon sermon-01 --start 180 --duration 600 --no-interim --words --name s01
uv run python eval/score.py sermon-01 --transcript whisperstream.s01.json --name ws-s01 \
  --from 180 --to 780 --quotes
```

**At live pace into a server**, with interims. It also writes a run file for `eval/stt_latency.py`:

```sh
uv run python -m stt_worker --sermon sermon-01 --start 180 --duration 600 --realtime \
  --ws ws://127.0.0.1:8000/ws --name rt-s01
```

**From an input device** (a microphone, or BlackHole while `play_to_device.py` plays a recording):

```sh
uv run python -m stt_worker --device "BlackHole 2ch" --ws ws://127.0.0.1:8001/ws
```

Stop it with Ctrl+C. It writes a capture in the browser's format to the corpus `captures` folder, for `eval/capture_to_segments.py`.

To time single decoding calls on this computer: `uv run python eval/stt_bench.py sermon-01`.

## Frontend unit tests

The frontend modules (`realtime/frontend/shared`) have Node tests with fake recognition and socket objects:

```sh
cd realtime/frontend
node --test tests/
```
