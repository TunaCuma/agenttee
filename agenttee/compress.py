"""
Compression strategies for log output.

Each strategy takes raw log lines and returns compressed output lines.
"""

import re
from collections import defaultdict

from .tokenizer import strip_ansi, tokenize_line, TokenType
from .templates import TemplateIndex


def strategy_template_dedup(lines: list[str]) -> list[str]:
    """
    Strategy 1: Template-based deduplication.

    Collapse consecutive runs of lines with the same template signature
    into a single representative line + count. Preserves ordering and
    keeps first/last of each run for context.
    """
    output = []
    if not lines:
        return output

    idx = TemplateIndex()
    idx.ingest(lines)

    i = 0
    while i < len(lines):
        sig, _ = idx.line_order[i]
        cluster = idx.clusters[sig]
        tl = cluster.lines[idx.line_order[i][1]]

        run_start = i
        while i < len(lines) and idx.line_order[i][0] == sig:
            i += 1
        run_len = i - run_start

        first_line = cluster.lines[idx.line_order[run_start][1]].clean
        last_line = cluster.lines[idx.line_order[i - 1][1]].clean

        if run_len == 1:
            output.append(first_line)
        elif run_len == 2:
            output.append(first_line)
            output.append(last_line)
        elif run_len <= 5:
            output.append(first_line)
            output.append(f"  ... ({run_len - 2} similar lines) ...")
            output.append(last_line)
        else:
            output.append(first_line)
            output.append(f"  ... ({run_len - 2} more lines matching template [{sig}]) ...")
            output.append(last_line)

    return output


def strategy_semantic(lines: list[str]) -> list[str]:
    """
    Strategy 2: Semantic compression.

    Understands common log patterns and compresses them intelligently:
    - Collapses progress bars into start→end summaries
    - Deduplicates identical lines (keeps first + count)
    - Groups Docker layer status updates
    - Collapses repeated warnings
    - Strips ANSI codes
    """
    output = []
    i = 0

    while i < len(lines):
        clean = strip_ansi(lines[i]).strip()

        if not clean:
            i += 1
            continue

        # Progress bar collapse: <s> [webpack.Progress] NN% ...
        if clean.startswith('<s> [webpack.Progress]'):
            progress_start = clean
            start_i = i
            while i < len(lines) and strip_ansi(lines[i]).strip().startswith('<s> [webpack.Progress]'):
                i += 1
            end_line = strip_ansi(lines[i - 1]).strip()

            start_pct = _extract_pct(progress_start)
            end_pct = _extract_pct(end_line)
            phase_start = _extract_phase(progress_start)
            phase_end = _extract_phase(end_line)

            if phase_start == phase_end:
                output.append(f"[webpack] {phase_start}: {start_pct}→{end_pct} ({i - start_i} updates)")
            else:
                output.append(f"[webpack] {phase_start} {start_pct} → {phase_end} {end_pct} ({i - start_i} updates)")
            continue

        # Docker layer status collapse: hash: Status
        if re.match(r'^[0-9a-f]{12}: \w+', clean):
            layers = defaultdict(lambda: {"statuses": set(), "count": 0})
            start_i = i
            while i < len(lines):
                c = strip_ansi(lines[i]).strip()
                m = re.match(r'^([0-9a-f]{12}): (.+)', c)
                if not m:
                    break
                layers[m.group(1)]["statuses"].add(m.group(2))
                layers[m.group(1)]["count"] += 1
                i += 1

            status_counts = defaultdict(int)
            for layer_info in layers.values():
                for s in layer_info["statuses"]:
                    status_counts[s] += 1

            status_summary = ", ".join(f"{s}: {c}" for s, c in sorted(status_counts.items(), key=lambda x: -x[1]))
            output.append(f"[docker push] {len(layers)} layers ({i - start_i} status lines) — {status_summary}")
            continue

        # Repeated identical lines (e.g., teleport warnings, grpc channel logs)
        if i + 1 < len(lines):
            run_count = 1
            while i + run_count < len(lines) and strip_ansi(lines[i + run_count]).strip() == clean:
                run_count += 1
            if run_count > 2:
                output.append(clean)
                output.append(f"  ↑ repeated {run_count} times")
                i += run_count
                continue

        # Consecutive lines with same prefix pattern (like time="..." level=warning msg="could not map pods...")
        if clean.startswith('time="'):
            msg_match = re.search(r'msg="([^"]*)"', clean)
            if msg_match:
                msg_key = msg_match.group(1)[:60]
                start_i = i
                while i < len(lines):
                    c = strip_ansi(lines[i]).strip()
                    if not c.startswith('time="'):
                        break
                    m2 = re.search(r'msg="([^"]*)"', c)
                    if not m2 or m2.group(1)[:60] != msg_key:
                        break
                    i += 1
                run_len = i - start_i
                if run_len > 2:
                    output.append(clean)
                    output.append(f"  ↑ repeated {run_len} times ({_extract_timerange(lines[start_i], lines[i-1])})")
                    continue
                else:
                    i = start_i  # reset, handle normally below

        output.append(clean)
        i += 1

    return output


def strategy_hybrid(lines: list[str]) -> list[str]:
    """
    Strategy 3: Hybrid — template clustering + semantic awareness.

    First pass: semantic compression (understands webpack, docker, etc).
    Second pass: template dedup on the remaining output to catch
    any remaining repetitive patterns.
    """
    pass1 = strategy_semantic(lines)
    pass2 = _template_dedup_clean(pass1)
    return pass2


def _template_dedup_clean(lines: list[str]) -> list[str]:
    """Template dedup on already-clean lines (no ANSI)."""
    output = []
    idx = TemplateIndex()
    idx.ingest(lines)

    i = 0
    while i < len(lines):
        sig, _ = idx.line_order[i]
        cluster = idx.clusters[sig]

        run_start = i
        while i < len(lines) and idx.line_order[i][0] == sig:
            i += 1
        run_len = i - run_start

        first_clean = cluster.lines[idx.line_order[run_start][1]].clean
        last_clean = cluster.lines[idx.line_order[i - 1][1]].clean

        if run_len <= 2:
            for j in range(run_start, i):
                tl = cluster.lines[idx.line_order[j][1]]
                output.append(tl.clean)
        elif run_len <= 5:
            output.append(first_clean)
            output.append(f"  ... ({run_len - 2} similar) ...")
            output.append(last_clean)
        else:
            output.append(first_clean)
            output.append(f"  ... ({run_len - 2} more, template: {sig}) ...")
            output.append(last_clean)

    return output


def _extract_pct(line: str) -> str:
    m = re.search(r'(\d{1,3})%', line)
    return m.group(0) if m else "?"


def _extract_phase(line: str) -> str:
    m = re.search(r'\d+%\s+(\S+(?:\s+\S+)?)', line)
    return m.group(1) if m else "?"


def _extract_timerange(first_line: str, last_line: str) -> str:
    def _get_time(line):
        m = re.search(r'time="([^"]*)"', strip_ansi(line))
        return m.group(1) if m else "?"
    t1, t2 = _get_time(first_line), _get_time(last_line)
    if t1 == t2:
        return t1
    return f"{t1} → {t2}"
