"""Server side speech recognition worker (Whisper streaming).

Runs natively on the host (mlx needs the Metal GPU, which Docker cannot reach)
and sends segments to the server over /ws like the browser does.
"""
