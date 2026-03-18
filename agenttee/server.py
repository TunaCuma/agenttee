"""
MCP server for agenttee: exposes captured log sessions to AI agents.

Tools:
  - list_sessions: show all captured sessions
  - get_logs: get raw or compressed logs from a session
  - tail: get latest lines from a session (live tailing)
  - search: regex search across one or all sessions
  - get_stats: template analysis for a session
"""

import re
import time

from mcp.server.fastmcp import FastMCP

from . import store
from .compress import strategy_agent_hybrid, strategy_agent
from .templates import TemplateIndex
from .tokenizer import strip_ansi

mcp = FastMCP(
    "agenttee",
    instructions=(
        "Log compression server. Users pipe command output through `agenttee` "
        "to capture sessions (e.g., `my_server | agenttee --name api`). "
        "Use these tools to read, search, and analyze the captured logs. "
        "Logs are automatically compressed to save context. "
        "Use `list_sessions` first to see what's available."
    ),
)


@mcp.tool()
def list_sessions() -> str:
    """List all captured log sessions.

    Shows session name, status (active/done), line count, and size.
    Use this first to discover what sessions are available before querying logs.
    """
    sessions = store.list_sessions()
    if not sessions:
        return "No sessions found. Pipe output through agenttee to create one:\n  some_command | agenttee --name myservice"

    lines = []
    for s in sessions:
        status = "ACTIVE" if s.active else "done"
        age = _format_age(s.started_at)
        size = _format_bytes(s.byte_count)
        lines.append(f"  {s.name:<20s} [{status}]  {s.line_count:>6d} lines  {size:>8s}  started {age}")

    return "Sessions:\n" + "\n".join(lines)


@mcp.tool()
def get_logs(
    session: str,
    compressed: bool = True,
    head: int | None = None,
    offset: int = 0,
) -> str:
    """Get logs from a captured session.

    Args:
        session: Session name (from list_sessions)
        compressed: If True (default), returns agent-optimized compressed logs.
                   If False, returns raw logs (ANSI stripped).
        head: Max number of lines to return. Defaults to all.
        offset: Skip this many lines from the start (for pagination).

    Returns compressed logs by default — dramatically fewer lines while
    preserving all meaningful information. Use compressed=False only when
    you need exact raw output.
    """
    raw = store.read_lines(session)
    if not raw:
        return f"Session '{session}' not found or empty."

    if compressed:
        lines = strategy_agent_hybrid(raw)
    else:
        lines = [strip_ansi(l).strip() for l in raw]

    if offset:
        lines = lines[offset:]
    if head:
        lines = lines[:head]

    header = f"[{session}] {'compressed' if compressed else 'raw'}: {len(lines)} lines"
    if offset:
        header += f" (offset={offset})"
    return header + "\n" + "\n".join(lines)


@mcp.tool()
def tail(session: str, lines: int = 50, compressed: bool = False) -> str:
    """Get the latest lines from a session — useful for watching live output.

    Args:
        session: Session name
        lines: Number of recent lines to return (default 50)
        compressed: Whether to compress the tail output (default False for recency)
    """
    raw = store.read_tail(session, n=lines * 3 if compressed else lines)
    if not raw:
        return f"Session '{session}' not found or empty."

    if compressed:
        output = strategy_agent(raw)[-lines:]
    else:
        output = [strip_ansi(l).strip() for l in raw[-lines:]]

    meta = store.read_meta(session)
    status = "ACTIVE" if meta and meta.active else "done"
    return f"[{session}] tail ({status}, last {len(output)} lines):\n" + "\n".join(output)


@mcp.tool()
def search(
    pattern: str,
    session: str | None = None,
    context: int = 2,
    max_results: int = 30,
) -> str:
    """Search logs with a regex pattern across one or all sessions.

    Args:
        pattern: Regex pattern to search for (case-insensitive)
        session: Session name to search. If omitted, searches all sessions.
        context: Number of context lines before/after each match (default 2)
        max_results: Maximum matches to return (default 30)

    Useful for finding errors, specific log messages, or tracing requests
    across multiple services.
    """
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex: {e}"

    sessions_to_search = []
    if session:
        sessions_to_search = [session]
    else:
        sessions_to_search = [s.name for s in store.list_sessions()]

    if not sessions_to_search:
        return "No sessions to search."

    results = []
    total_matches = 0

    for sname in sessions_to_search:
        raw = store.read_lines(sname)
        clean = [strip_ansi(l).strip() for l in raw]

        matches_in_session = []
        for i, line in enumerate(clean):
            if regex.search(line):
                start = max(0, i - context)
                end = min(len(clean), i + context + 1)
                ctx_lines = []
                for j in range(start, end):
                    prefix = ">>> " if j == i else "    "
                    ctx_lines.append(f"{prefix}{j+1}: {clean[j]}")
                matches_in_session.append("\n".join(ctx_lines))
                total_matches += 1
                if total_matches >= max_results:
                    break

        if matches_in_session:
            results.append(f"── {sname} ({len(matches_in_session)} matches) ──")
            results.extend(matches_in_session)
            results.append("")

        if total_matches >= max_results:
            break

    if not results:
        searched = ", ".join(sessions_to_search)
        return f"No matches for /{pattern}/ in: {searched}"

    header = f"Search: /{pattern}/ — {total_matches} matches"
    if total_matches >= max_results:
        header += f" (showing first {max_results})"
    return header + "\n\n" + "\n".join(results)


@mcp.tool()
def get_stats(session: str) -> str:
    """Get template analysis stats for a session.

    Shows what kinds of log lines are present, how repetitive the output is,
    and which templates dominate. Useful for understanding log structure
    before querying specific content.
    """
    raw = store.read_lines(session)
    if not raw:
        return f"Session '{session}' not found or empty."

    idx = TemplateIndex()
    idx.ingest(raw)
    stats = idx.stats()

    lines = [
        f"[{session}] Template Analysis:",
        f"  Total lines:       {stats['total_lines']}",
        f"  Unique templates:  {stats['unique_templates']}",
        f"  Top 10 cover:      {stats['top10_cover_pct']}% of all lines",
        "",
        "  Top templates:",
    ]
    for sig, count, rep in stats["top10"]:
        pct = count / stats['total_lines'] * 100
        lines.append(f"    {count:5d} ({pct:5.1f}%)  {rep[:80]}")

    compressed = strategy_agent_hybrid(raw)
    ratio = (1 - len(compressed) / len(raw)) * 100 if raw else 0
    lines.append("")
    lines.append(f"  Compression: {len(raw)} → {len(compressed)} lines ({ratio:.0f}% reduction)")

    return "\n".join(lines)


@mcp.tool()
def get_timeline(
    sessions: list[str],
    grep: str | None = None,
    compressed: bool = True,
    tail_lines: int | None = None,
) -> str:
    """Get an interleaved timeline from multiple sessions.

    Useful for seeing how two services interact — e.g., an API server and a
    worker processing requests. Lines are prefixed with the session name.

    Args:
        sessions: List of session names to interleave
        grep: Optional regex filter
        compressed: Compress each session's output first (default True)
        tail_lines: Only show the last N lines from each session
    """
    regex = None
    if grep:
        try:
            regex = re.compile(grep, re.IGNORECASE)
        except re.error as e:
            return f"Invalid regex: {e}"

    all_lines = []
    for sname in sessions:
        raw = store.read_lines(sname)
        if not raw:
            continue

        if compressed:
            lines = strategy_agent_hybrid(raw)
        else:
            lines = [strip_ansi(l).strip() for l in raw]

        if tail_lines:
            lines = lines[-tail_lines:]

        for line in lines:
            if regex and not regex.search(line):
                continue
            all_lines.append(f"[{sname}] {line}")

    if not all_lines:
        return f"No output from sessions: {', '.join(sessions)}"

    header = f"Timeline: {', '.join(sessions)} ({len(all_lines)} lines)"
    return header + "\n" + "\n".join(all_lines)


def _format_age(timestamp: float) -> str:
    delta = time.time() - timestamp
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def run_server():
    mcp.run(transport="stdio")
