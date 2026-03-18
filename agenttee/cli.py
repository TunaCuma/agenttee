"""
CLI entry point for agenttee.

Three modes:
  1. Pipe capture:  some_command | agenttee --name myservice
  2. MCP server:    agenttee serve
  3. File analysis:  agenttee <logfile> [--stats]
"""

import sys
import os
from pathlib import Path


def main():
    args = sys.argv[1:]

    # Pipe capture — stdin is piped, no subcommand given
    if not sys.stdin.isatty() and (not args or args[0] not in ("serve", "sessions")):
        name = _get_name_arg(args)
        from .pipe import run_pipe
        run_pipe(name)
        return

    if not args:
        _print_usage()
        sys.exit(1)

    # Mode 1: MCP server
    if args[0] == "serve":
        from .server import run_server
        run_server()
        return

    # Mode 2: List sessions
    if args[0] == "sessions":
        from . import store
        sessions = store.list_sessions()
        if not sessions:
            print("No sessions. Pipe output through agenttee to create one:")
            print("  some_command | agenttee --name myservice")
            return
        for s in sessions:
            status = "ACTIVE" if s.active else "done"
            print(f"  {s.name:<20s} [{status}]  {s.line_count:>6d} lines  {s.byte_count:>8d} bytes")
        return

    # Mode 3: File analysis
    if Path(args[0]).exists():
        _run_file_analysis(args)
        return

    _print_usage()
    sys.exit(1)


def _get_name_arg(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg == "--name" and i + 1 < len(args):
            return args[i + 1]
    return _auto_name()


def _auto_name() -> str:
    """Derive a session name from context: parent command, then cwd basename."""
    import subprocess
    ppid = os.getppid()
    try:
        result = subprocess.run(
            ["ps", "-p", str(ppid), "-o", "command="],
            capture_output=True, text=True, timeout=2,
        )
        cmd = result.stdout.strip()
        if cmd:
            # Extract the meaningful part: first non-shell token
            parts = cmd.split("|")[0].strip().split()
            for part in parts:
                base = Path(part).stem
                if base not in ("bash", "zsh", "sh", "fish", "env", "noglob", "uv", "python", "python3", "node", "npm", "npx"):
                    # Sanitize for filesystem
                    clean = "".join(c if c.isalnum() or c in "-_." else "-" for c in base)
                    return clean[:40]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    cwd = Path.cwd().name
    if cwd:
        return cwd[:40]

    import time
    return f"session-{int(time.time())}"


def _print_usage():
    print("agenttee — log compression for AI agents")
    print()
    print("Usage:")
    print("  some_command | agenttee --name myservice   Capture logs to a session")
    print("  some_command | agenttee                    Auto-names from command/cwd")
    print("  agenttee serve                             Start MCP server (stdio)")
    print("  agenttee sessions                          List captured sessions")
    print("  agenttee <logfile> [--stats]               Analyze a log file")
    print()
    print("MCP config (add to cursor settings):")
    print('  { "mcpServers": { "agenttee": { "command": "agenttee", "args": ["serve"] } } }')


def _run_file_analysis(args: list[str]):
    import time as time_mod
    from .compress import (
        strategy_template_dedup, strategy_semantic, strategy_hybrid,
        strategy_agent, strategy_agent_hybrid,
    )
    from .templates import TemplateIndex

    STRATEGIES = {
        "template_dedup": ("Template-based deduplication", strategy_template_dedup),
        "semantic": ("Semantic compression", strategy_semantic),
        "hybrid": ("Hybrid (semantic + template dedup)", strategy_hybrid),
        "agent": ("Agent-optimized (smart compression)", strategy_agent),
        "agent_hybrid": ("Agent + template dedup (max compression)", strategy_agent_hybrid),
    }

    logfile = Path(args[0])
    show_stats = "--stats" in args

    output_dir_idx = None
    for i, arg in enumerate(args):
        if arg == "--output-dir" and i + 1 < len(args):
            output_dir_idx = i + 1
    output_dir = Path(args[output_dir_idx]) if output_dir_idx else logfile.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_lines = logfile.read_text().splitlines()
    print(f"Input: {logfile} ({len(raw_lines)} lines, {logfile.stat().st_size:,} bytes)")
    print()

    if show_stats:
        idx = TemplateIndex()
        idx.ingest(raw_lines)
        stats = idx.stats()
        print(f"Template Analysis:")
        print(f"  Total lines:       {stats['total_lines']}")
        print(f"  Unique templates:  {stats['unique_templates']}")
        print(f"  Top 10 cover:      {stats['top10_cover_pct']}% of all lines")
        print()
        print(f"  Top templates:")
        for sig, count, rep in stats["top10"]:
            pct = count / stats['total_lines'] * 100
            print(f"    {count:5d} ({pct:5.1f}%)  {sig[:40]:<40s}  {rep[:60]}")
        print()

    for name, (desc, fn) in STRATEGIES.items():
        t0 = time_mod.perf_counter()
        compressed = fn(raw_lines)
        elapsed = time_mod.perf_counter() - t0

        out_path = output_dir / f"{name}.log"
        out_path.write_text("\n".join(compressed) + "\n")

        original_bytes = sum(len(l.encode()) for l in raw_lines)
        compressed_bytes = sum(len(l.encode()) for l in compressed)
        ratio = (1 - compressed_bytes / original_bytes) * 100 if original_bytes else 0

        print(f"  {desc}")
        print(f"    {len(raw_lines)} → {len(compressed)} lines ({ratio:.1f}% smaller)")
        print(f"    Output: {out_path} ({compressed_bytes:,} bytes)")
        print(f"    Time: {elapsed:.2f}s")
        print()


if __name__ == "__main__":
    main()
