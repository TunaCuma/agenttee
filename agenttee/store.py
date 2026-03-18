"""
Session store: shared state between pipe capture processes and the MCP server.

Each session is a named log stream stored at ~/.agenttee/sessions/<name>/.
Pipe processes append lines in real-time. The MCP server reads them.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

STORE_DIR = Path.home() / ".agenttee" / "sessions"


@dataclass
class SessionMeta:
    name: str
    started_at: float = 0.0
    pid: int = 0
    line_count: int = 0
    byte_count: int = 0
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMeta":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def session_dir(name: str) -> Path:
    return STORE_DIR / name


def ensure_store():
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def create_session(name: str) -> Path:
    """Create a new session directory, clearing any previous data."""
    sdir = session_dir(name)
    sdir.mkdir(parents=True, exist_ok=True)
    log_path = sdir / "raw.log"
    log_path.write_text("")
    meta = SessionMeta(
        name=name,
        started_at=time.time(),
        pid=os.getpid(),
        line_count=0,
        byte_count=0,
        active=True,
    )
    _write_meta(sdir, meta)
    return sdir


def append_lines(name: str, lines: list[str]):
    """Append lines to a session's log file."""
    sdir = session_dir(name)
    log_path = sdir / "raw.log"
    text = "\n".join(lines) + "\n"
    with open(log_path, "a") as f:
        f.write(text)
    meta = read_meta(name)
    if meta:
        meta.line_count += len(lines)
        meta.byte_count += len(text.encode())
        _write_meta(sdir, meta)


def finish_session(name: str):
    """Mark a session as no longer actively receiving input."""
    sdir = session_dir(name)
    meta = read_meta(name)
    if meta:
        meta.active = False
        _write_meta(sdir, meta)


def read_meta(name: str) -> SessionMeta | None:
    meta_path = session_dir(name) / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return SessionMeta.from_dict(json.loads(meta_path.read_text()))
    except (json.JSONDecodeError, KeyError):
        return None


def read_lines(name: str) -> list[str]:
    """Read all lines from a session."""
    log_path = session_dir(name) / "raw.log"
    if not log_path.exists():
        return []
    return log_path.read_text().splitlines()


def read_tail(name: str, n: int = 100) -> list[str]:
    """Read the last N lines from a session efficiently."""
    log_path = session_dir(name) / "raw.log"
    if not log_path.exists():
        return []
    with open(log_path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        if size == 0:
            return []
        # Read backwards in chunks to find N newlines
        chunk_size = min(size, n * 200)
        f.seek(max(0, size - chunk_size))
        data = f.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    return lines[-n:]


def list_sessions() -> list[SessionMeta]:
    """List all sessions with their metadata."""
    ensure_store()
    sessions = []
    if not STORE_DIR.exists():
        return sessions
    for sdir in sorted(STORE_DIR.iterdir()):
        if sdir.is_dir():
            meta = read_meta(sdir.name)
            if meta:
                # Refresh line count from actual file
                log_path = sdir / "raw.log"
                if log_path.exists():
                    meta.byte_count = log_path.stat().st_size
                sessions.append(meta)
    return sessions


def _write_meta(sdir: Path, meta: SessionMeta):
    meta_path = sdir / "meta.json"
    meta_path.write_text(json.dumps(meta.to_dict(), indent=2) + "\n")
