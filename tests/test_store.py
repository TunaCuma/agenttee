import time
import pytest
from pathlib import Path
from agenttee import store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Redirect store to a temp directory so tests don't touch ~/.agenttee."""
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "sessions")


class TestSessionLifecycle:
    def test_create_and_read_meta(self):
        store.create_session("test-svc")
        meta = store.read_meta("test-svc")
        assert meta is not None
        assert meta.name == "test-svc"
        assert meta.active is True
        assert meta.line_count == 0

    def test_append_and_read_lines(self):
        store.create_session("test-svc")
        store.append_lines("test-svc", ["line 1", "line 2", "line 3"])
        lines = store.read_lines("test-svc")
        assert lines == ["line 1", "line 2", "line 3"]

    def test_append_preserves_timestamps(self):
        store.create_session("ts-test")
        now = time.time()
        store.append_lines("ts-test", ["hello", "world"], [now, now + 1.0])
        tlines = store.read_timestamped("ts-test")
        assert len(tlines) == 2
        assert tlines[0].text == "hello"
        assert tlines[1].text == "world"
        assert tlines[1].ts > tlines[0].ts

    def test_finish_marks_inactive(self):
        store.create_session("test-svc")
        store.finish_session("test-svc")
        meta = store.read_meta("test-svc")
        assert meta.active is False

    def test_read_tail(self):
        store.create_session("tail-test")
        store.append_lines("tail-test", [f"line {i}" for i in range(100)])
        tail = store.read_tail("tail-test", n=5)
        assert len(tail) == 5
        assert tail[-1] == "line 99"

    def test_list_sessions(self):
        store.create_session("svc-a")
        store.create_session("svc-b")
        sessions = store.list_sessions()
        names = [s.name for s in sessions]
        assert "svc-a" in names
        assert "svc-b" in names

    def test_meta_line_count_updates(self):
        store.create_session("counter")
        store.append_lines("counter", ["a", "b"])
        store.append_lines("counter", ["c"])
        meta = store.read_meta("counter")
        assert meta.line_count == 3


class TestTimestampedLines:
    def test_session_name_attached(self):
        store.create_session("named")
        store.append_lines("named", ["test"])
        tlines = store.read_timestamped("named")
        assert tlines[0].session == "named"

    def test_timestamp_ordering(self):
        store.create_session("ordered")
        t1 = 1000.0
        t2 = 2000.0
        store.append_lines("ordered", ["first", "second"], [t1, t2])
        tlines = store.read_timestamped("ordered")
        assert tlines[0].ts == t1
        assert tlines[1].ts == t2

    def test_nonexistent_session(self):
        assert store.read_lines("nope") == []
        assert store.read_timestamped("nope") == []
        assert store.read_meta("nope") is None
