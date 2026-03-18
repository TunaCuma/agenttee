"""CLI entry point for agenttee log compression."""

import sys
import time
from pathlib import Path

from .compress import strategy_template_dedup, strategy_semantic, strategy_hybrid
from .templates import TemplateIndex


STRATEGIES = {
    "template_dedup": ("Template-based deduplication", strategy_template_dedup),
    "semantic": ("Semantic compression", strategy_semantic),
    "hybrid": ("Hybrid (semantic + template dedup)", strategy_hybrid),
}


def main():
    if len(sys.argv) < 2:
        print("Usage: agenttee <logfile> [--output-dir DIR] [--stats]")
        sys.exit(1)

    logfile = Path(sys.argv[1])
    show_stats = "--stats" in sys.argv

    output_dir_idx = None
    for i, arg in enumerate(sys.argv):
        if arg == "--output-dir" and i + 1 < len(sys.argv):
            output_dir_idx = i + 1
    output_dir = Path(sys.argv[output_dir_idx]) if output_dir_idx else logfile.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_lines = logfile.read_text().splitlines()
    print(f"Input: {logfile} ({len(raw_lines)} lines, {logfile.stat().st_size:,} bytes)")
    print()

    if show_stats:
        _print_stats(raw_lines)
        print()

    for name, (desc, fn) in STRATEGIES.items():
        t0 = time.perf_counter()
        compressed = fn(raw_lines)
        elapsed = time.perf_counter() - t0

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


def _print_stats(lines: list[str]):
    idx = TemplateIndex()
    idx.ingest(lines)
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


if __name__ == "__main__":
    main()
