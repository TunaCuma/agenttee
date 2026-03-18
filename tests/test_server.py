"""Tests for MCP server tool functions (called directly, not via MCP protocol)."""

import time
import pytest
from agenttee import store
from agenttee.server import (
    list_sessions, get_logs, tail, search, get_stats,
    get_timeline, diff_sessions,
)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "sessions")


def _create_session_with_lines(name: str, lines: list[str], timestamps=None):
    store.create_session(name)
    if timestamps:
        store.append_lines(name, lines, timestamps)
    else:
        store.append_lines(name, lines)
    store.finish_session(name)


class TestListSessions:
    def test_no_sessions(self):
        result = list_sessions()
        assert "No sessions" in result

    def test_shows_sessions(self):
        _create_session_with_lines("api", ["hello"])
        result = list_sessions()
        assert "api" in result
        assert "done" in result


class TestGetLogs:
    def test_compact_mode(self):
        lines = [f"INFO request {i}" for i in range(50)]
        _create_session_with_lines("svc", lines)
        result = get_logs("svc", mode="compact")
        assert "[svc] compact:" in result

    def test_conservative_mode(self):
        lines = [f"INFO request {i}" for i in range(50)]
        _create_session_with_lines("svc", lines)
        result = get_logs("svc", mode="conservative")
        assert "[svc] conservative:" in result

    def test_raw_mode(self):
        _create_session_with_lines("svc", ["hello", "world"])
        result = get_logs("svc", mode="raw")
        assert "hello" in result
        assert "world" in result

    def test_pagination(self):
        lines = [f"line {i}" for i in range(20)]
        _create_session_with_lines("svc", lines)
        result = get_logs("svc", mode="raw", head=5, offset=0)
        assert "line 0" in result
        assert "line 5" not in result

    def test_missing_session(self):
        result = get_logs("nope")
        assert "not found" in result


class TestTail:
    def test_returns_recent_lines(self):
        lines = [f"line {i}" for i in range(100)]
        _create_session_with_lines("svc", lines)
        result = tail("svc", lines=5)
        assert "line 99" in result
        assert "line 0" not in result

    def test_compressed_tail(self):
        lines = ["same log message"] * 100
        _create_session_with_lines("svc", lines)
        result = tail("svc", lines=5, compressed=True)
        assert "[svc]" in result


class TestSearch:
    def test_finds_pattern(self):
        _create_session_with_lines("svc", ["INFO started", "ERROR connection failed", "INFO ok"])
        result = search("error")
        assert "1 matches" in result
        assert "connection failed" in result

    def test_no_matches(self):
        _create_session_with_lines("svc", ["hello", "world"])
        result = search("nonexistent_pattern_xyz")
        assert "No matches" in result

    def test_search_specific_session(self):
        _create_session_with_lines("api", ["ERROR api crash"])
        _create_session_with_lines("worker", ["INFO ok"])
        result = search("error", session="api")
        assert "api" in result

    def test_invalid_regex(self):
        result = search("[invalid")
        assert "Invalid regex" in result


class TestGetStats:
    def test_shows_stats(self):
        lines = ["INFO request handled"] * 20 + ["ERROR db timeout"] * 3
        _create_session_with_lines("svc", lines)
        result = get_stats("svc")
        assert "Template Analysis" in result
        assert "Total lines" in result
        assert "Compression" in result

    def test_missing_session(self):
        result = get_stats("nope")
        assert "not found" in result


class TestGetTimeline:
    def test_interleaves_sessions(self):
        t = time.time()
        _create_session_with_lines("api", ["api: request in", "api: response out"],
                                   [t, t + 2.0])
        _create_session_with_lines("worker", ["worker: job received", "worker: job done"],
                                   [t + 1.0, t + 3.0])
        result = get_timeline(["api", "worker"], compressed=False)
        assert "Timeline:" in result
        lines = result.strip().split("\n")[1:]
        # Verify interleaving by timestamp order
        assert "[api]" in lines[0]
        assert "[worker]" in lines[1]
        assert "[api]" in lines[2]
        assert "[worker]" in lines[3]

    def test_grep_filter(self):
        t = time.time()
        _create_session_with_lines("svc", ["INFO ok", "ERROR bad"], [t, t + 1])
        result = get_timeline(["svc"], grep="error", compressed=False)
        assert "ERROR bad" in result
        assert "INFO ok" not in result

    def test_empty_sessions(self):
        result = get_timeline(["nonexistent"])
        assert "No output" in result


class TestDiffSessions:
    def test_shows_diff(self):
        _create_session_with_lines("before", ["line 1", "line 2", "line 3"])
        _create_session_with_lines("after", ["line 1", "line CHANGED", "line 3"])
        result = diff_sessions("before", "after", mode="raw")
        assert "Diff:" in result
        assert "-line 2" in result
        assert "+line CHANGED" in result

    def test_identical_sessions(self):
        _create_session_with_lines("a", ["same", "content"])
        _create_session_with_lines("b", ["same", "content"])
        result = diff_sessions("a", "b", mode="raw")
        assert "No differences" in result

    def test_compressed_diff(self):
        lines_a = ["INFO handled"] * 50
        lines_b = ["INFO handled"] * 50 + ["ERROR new crash"]
        _create_session_with_lines("run1", lines_a)
        _create_session_with_lines("run2", lines_b)
        result = diff_sessions("run1", "run2", mode="compact")
        assert "Diff:" in result

    def test_missing_session(self):
        _create_session_with_lines("exists", ["hello"])
        result = diff_sessions("exists", "nope")
        assert "not found" in result
