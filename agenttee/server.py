"""
MCP server for agenttee: exposes captured log sessions to AI agents.

Tools:
  - list_sessions: show all captured sessions
  - get_logs: get raw or compressed logs from a session
  - tail: get latest lines from a session (live tailing)
  - search: regex search across one or all sessions
  - get_stats: template analysis for a session
  - get_timeline: interleave multiple sessions by wall-clock time
  - diff_sessions: compare two sessions or two runs of the same session
"""

import difflib
import re
import time

from mcp.server.fastmcp import FastMCP

from . import store
from .compress import (
    strategy_agent_hybrid, strategy_agent, strategy_conservative, compress,
)
from .templates import TemplateIndex
from .tokenizer import strip_ansi

mcp = FastMCP(
    "agenttee",
    instructions=(
        "Log compression server. Users pipe command output through `agenttee` "
        "to capture sessions (e.g., `my_server | agenttee --name api`). "
        "Use these tools to read, search, and analyze the captured logs. "
        "Logs are automatically compressed to save context. "
        "Use `list_sessions` first to see what's available. "
        "Use `diff_sessions` to compare logs between two runs."
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
    mode: str = "compact",
    head: int | None = None,
    offset: int = 0,
) -> str:
    """Get logs from a captured session.

    Args:
        session: Session name (from list_sessions)
        mode: Compression mode:
              "compact" (default) — aggressive compression, best for overview
              "conservative" — light compression, keeps more detail
              "raw" — no compression, ANSI stripped
        head: Max number of lines to return. Defaults to all.
        offset: Skip this many lines from the start (for pagination).

    Returns compressed logs by default — dramatically fewer lines while
    preserving all meaningful information.
    """
    raw = store.read_lines(session)
    if not raw:
        return f"Session '{session}' not found or empty."

    if mode == "raw":
        lines = [strip_ansi(l).strip() for l in raw]
    else:
        lines = compress(raw, mode)

    if offset:
        lines = lines[offset:]
    if head:
        lines = lines[:head]

    header = f"[{session}] {mode}: {len(lines)} lines"
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
    """Get a time-sorted interleaved view from multiple sessions.

    Lines are merged by their real wall-clock ingestion timestamps, so you
    can trace the actual order of events across services (e.g., API request
    hitting the worker).

    Args:
        sessions: List of session names to interleave
        grep: Optional regex filter
        compressed: Compress each session's output first (default True)
        tail_lines: Only show the last N lines from each session before merging
    """
    regex = None
    if grep:
        try:
            regex = re.compile(grep, re.IGNORECASE)
        except re.error as e:
            return f"Invalid regex: {e}"

    all_tl: list[store.TimestampedLine] = []
    for sname in sessions:
        tlines = store.read_timestamped(sname)
        if not tlines:
            continue

        if compressed:
            texts = [tl.text for tl in tlines]
            compressed_texts = strategy_agent_hybrid(texts)
            # Map compressed lines back to timestamps using best-effort matching
            # Since compression changes line count, use a simple heuristic:
            # distribute timestamps proportionally
            if tlines and compressed_texts:
                ratio = len(tlines) / len(compressed_texts)
                for j, ct in enumerate(compressed_texts):
                    src_idx = min(int(j * ratio), len(tlines) - 1)
                    tl = store.TimestampedLine(
                        ts=tlines[src_idx].ts, text=ct, session=sname,
                    )
                    all_tl.append(tl)
        else:
            for tl in tlines:
                tl.text = strip_ansi(tl.text).strip()
                all_tl.append(tl)

        if tail_lines:
            # Only keep the last N from this session
            session_lines = [tl for tl in all_tl if tl.session == sname]
            other_lines = [tl for tl in all_tl if tl.session != sname]
            all_tl = other_lines + session_lines[-tail_lines:]

    all_tl.sort(key=lambda tl: tl.ts)

    output_lines = []
    for tl in all_tl:
        line = f"[{tl.session}] {tl.text}"
        if regex and not regex.search(line):
            continue
        output_lines.append(line)

    if not output_lines:
        return f"No output from sessions: {', '.join(sessions)}"

    header = f"Timeline: {', '.join(sessions)} ({len(output_lines)} lines, sorted by wall-clock time)"
    return header + "\n" + "\n".join(output_lines)


@mcp.tool()
def diff_sessions(
    session_a: str,
    session_b: str,
    mode: str = "compact",
    context: int = 3,
) -> str:
    """Compare logs between two sessions (or two runs of the same service).

    Shows a unified diff of compressed logs so you can see what changed
    between runs — useful for comparing before/after a code change,
    spotting new errors, or seeing what a fix removed.

    Args:
        session_a: First session (the "before")
        session_b: Second session (the "after")
        mode: Compression mode for both sides: "compact", "conservative", "raw"
        context: Diff context lines (default 3)
    """
    raw_a = store.read_lines(session_a)
    raw_b = store.read_lines(session_b)

    if not raw_a:
        return f"Session '{session_a}' not found or empty."
    if not raw_b:
        return f"Session '{session_b}' not found or empty."

    if mode == "raw":
        lines_a = [strip_ansi(l).strip() for l in raw_a]
        lines_b = [strip_ansi(l).strip() for l in raw_b]
    else:
        lines_a = compress(raw_a, mode)
        lines_b = compress(raw_b, mode)

    diff = list(difflib.unified_diff(
        lines_a, lines_b,
        fromfile=session_a, tofile=session_b,
        n=context, lineterm="",
    ))

    if not diff:
        return f"No differences between '{session_a}' and '{session_b}' (mode={mode})."

    stats_add = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    stats_del = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    header = f"Diff: {session_a} → {session_b} (mode={mode}, +{stats_add} -{stats_del})"
    return header + "\n" + "\n".join(diff)


TRACE_KEYWORD = "AGENTTEE_TRACE"


@mcp.tool()
def get_traces(
    session: str | None = None,
    tag: str | None = None,
    context: int = 0,
) -> str:
    """Get trace lines you inserted into the codebase.

    HOW TO USE:
    1. Add print/log statements with the keyword AGENTTEE_TRACE to the code
       you want to trace, e.g.:
         print(f"AGENTTEE_TRACE [checkout] user={user.id} cart={len(items)}")
         logger.info(f"AGENTTEE_TRACE [db] query took {elapsed}ms")
    2. Run the service through agenttee:  my_server | agenttee --name api
    3. Call this tool to retrieve only your trace lines, cutting through
       all the framework noise.

    Use tags in brackets like [checkout], [db], [auth] to organize traces.
    The tag parameter filters by these bracket tags.

    Args:
        session: Session to search. If omitted, searches all sessions.
        tag: Optional tag filter (e.g., "checkout" matches [checkout]).
             Case-insensitive.
        context: Number of surrounding log lines to include around each
                 trace hit (default 0 — just the trace lines).
    """
    sessions_to_search = []
    if session:
        sessions_to_search = [session]
    else:
        sessions_to_search = [s.name for s in store.list_sessions()]

    if not sessions_to_search:
        return "No sessions. Pipe output through agenttee to create one."

    results = []
    total = 0

    for sname in sessions_to_search:
        tlines = store.read_timestamped(sname)
        if not tlines:
            continue

        hits = []
        for i, tl in enumerate(tlines):
            clean = strip_ansi(tl.text).strip()
            if TRACE_KEYWORD not in clean:
                continue
            if tag and f"[{tag}]".lower() not in clean.lower():
                continue

            if context > 0:
                start = max(0, i - context)
                end = min(len(tlines), i + context + 1)
                block = []
                for j in range(start, end):
                    c = strip_ansi(tlines[j].text).strip()
                    prefix = ">>> " if j == i else "    "
                    block.append(f"{prefix}{c}")
                hits.append("\n".join(block))
            else:
                hits.append(clean)
            total += 1

        if hits:
            results.append(f"── {sname} ({len(hits)} traces) ──")
            results.extend(hits)
            results.append("")

    if not results:
        searched = ", ".join(sessions_to_search)
        hint = f" with tag [{tag}]" if tag else ""
        return (
            f"No AGENTTEE_TRACE lines found{hint} in: {searched}\n\n"
            f"Add trace lines to your code like:\n"
            f"  print(\"AGENTTEE_TRACE [mytag] value={{val}}\")"
        )

    header = f"Traces: {total} hits"
    if tag:
        header += f" (tag: [{tag}])"
    return header + "\n\n" + "\n".join(results)


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
