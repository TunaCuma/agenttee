"""
Pipe capture: reads stdin line by line, stores to session, passes through to stdout.

Usage: some_command | agenttee --name myservice
Behaves like tee — output still appears in the terminal.
Each line is timestamped on ingestion so cross-session timelines can be merged.
"""

import sys
import signal
import time
from . import store


def run_pipe(name: str):
    """Capture stdin to a named session while passing through to stdout."""
    store.create_session(name)
    sys.stderr.write(f"agenttee: capturing to session '{name}'\n")

    batch_lines: list[str] = []
    batch_ts: list[float] = []
    batch_size = 50

    def flush_batch():
        if batch_lines:
            store.append_lines(name, batch_lines, batch_ts)
            batch_lines.clear()
            batch_ts.clear()

    def handle_signal(sig, frame):
        flush_batch()
        store.finish_session(name)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        for line in sys.stdin:
            line = line.rstrip("\n")
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            batch_lines.append(line)
            batch_ts.append(time.time())
            if len(batch_lines) >= batch_size:
                flush_batch()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        flush_batch()
        store.finish_session(name)
