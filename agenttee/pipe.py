"""
Pipe capture: reads stdin line by line, stores to session, passes through to stdout.

Usage: some_command | agenttee --name myservice
Behaves like tee — output still appears in the terminal.
"""

import sys
import signal
from . import store


def run_pipe(name: str):
    """Capture stdin to a named session while passing through to stdout."""
    store.create_session(name)

    batch = []
    batch_size = 50

    def flush_batch():
        if batch:
            store.append_lines(name, batch)
            batch.clear()

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
            batch.append(line)
            if len(batch) >= batch_size:
                flush_batch()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        flush_batch()
        store.finish_session(name)
