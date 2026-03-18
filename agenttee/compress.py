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


def strategy_agent(lines: list[str]) -> list[str]:
    """
    Strategy 4: Agent-optimized — maximum context reduction.

    Builds on the hybrid approach but adds aggressive techniques
    specifically designed to minimize tokens an AI agent must process:

    - Truncates verbose export/import lists in warnings to just the missing symbol
    - Collapses multi-worker duplicate warning blocks (same warning from N workers)
    - Summarizes asset listings into a count + size range
    - Groups repeated 2-line blocks (warning + code snippet pairs)
    - Compresses structlog-style repeated log lines
    """
    cleaned = [strip_ansi(line).strip() for line in lines]
    output = []
    i = 0

    while i < len(cleaned):
        line = cleaned[i]

        if not line:
            i += 1
            continue

        # --- Webpack progress collapse ---
        if line.startswith('<s> [webpack.Progress]'):
            start_i = i
            while i < len(cleaned) and cleaned[i].startswith('<s> [webpack.Progress]'):
                i += 1
            start_pct = _extract_pct(cleaned[start_i])
            end_pct = _extract_pct(cleaned[i - 1])
            phase_start = _extract_phase(cleaned[start_i])
            phase_end = _extract_phase(cleaned[i - 1])
            if phase_start == phase_end:
                output.append(f"[webpack] {phase_start}: {start_pct}→{end_pct} ({i - start_i} steps)")
            else:
                output.append(f"[webpack] {phase_start} {start_pct} → {phase_end} {end_pct} ({i - start_i} steps)")
            continue

        # --- Docker layer status collapse ---
        if re.match(r'^[0-9a-f]{12}: \w+', line):
            layers = defaultdict(set)
            start_i = i
            while i < len(cleaned):
                m = re.match(r'^([0-9a-f]{12}): (.+)', cleaned[i])
                if not m:
                    break
                layers[m.group(1)].add(m.group(2))
                i += 1
            status_counts = defaultdict(int)
            for statuses in layers.values():
                for s in statuses:
                    status_counts[s] += 1
            summary = ", ".join(f"{s}: {c}" for s, c in sorted(status_counts.items(), key=lambda x: -x[1]))
            output.append(f"[docker] {len(layers)} layers, {i - start_i} status updates ({summary})")
            continue

        # --- Webpack asset listing collapse ---
        if line.startswith('asset '):
            assets = []
            start_i = i
            total_size = 0.0
            while i < len(cleaned) and cleaned[i].startswith('asset '):
                assets.append(cleaned[i])
                size_m = re.search(r'(\d+(?:\.\d+)?)\s*(KiB|MiB|GiB|bytes)', cleaned[i])
                if size_m:
                    val = float(size_m.group(1))
                    unit = size_m.group(2)
                    if unit == 'MiB':
                        val *= 1024
                    elif unit == 'GiB':
                        val *= 1024 * 1024
                    elif unit == 'bytes':
                        val /= 1024
                    total_size += val
                i += 1
            if len(assets) > 3:
                if total_size > 1024:
                    output.append(f"[webpack] {len(assets)} assets ({total_size/1024:.1f} MiB total)")
                else:
                    output.append(f"[webpack] {len(assets)} assets ({total_size:.0f} KiB total)")
            else:
                output.extend(assets)
            continue

        # --- Webpack WARNING truncation ---
        if line.startswith('WARNING in '):
            warning_header = line
            detail_lines = []
            i += 1
            while i < len(cleaned) and cleaned[i] and not cleaned[i].startswith('WARNING in ') and not cleaned[i].startswith('webpack compiled') and not cleaned[i].startswith('<s> [') and not cleaned[i].startswith('['):
                detail_lines.append(cleaned[i])
                i += 1
            truncated = _truncate_warning(warning_header, detail_lines)
            output.append(truncated)
            continue

        # --- Structlog / time= repeated blocks ---
        if line.startswith('time="'):
            msg_match = re.search(r'msg="([^"]*)"', line)
            if msg_match:
                msg_pattern = _normalize_msg(msg_match.group(1))
                start_i = i
                unique_msgs = {msg_match.group(1)[:120]}
                while i < len(cleaned):
                    if not cleaned[i].startswith('time="'):
                        break
                    m2 = re.search(r'msg="([^"]*)"', cleaned[i])
                    if not m2 or _normalize_msg(m2.group(1)) != msg_pattern:
                        break
                    unique_msgs.add(m2.group(1)[:120])
                    i += 1
                run_len = i - start_i
                if run_len > 2:
                    t_start = _extract_time_val(cleaned[start_i])
                    t_end = _extract_time_val(cleaned[i - 1])
                    lvl = re.search(r'level=(\w+)', cleaned[start_i])
                    lvl_str = lvl.group(1) if lvl else "?"
                    if len(unique_msgs) == 1:
                        output.append(f"[{lvl_str}] \"{msg_pattern}\" ×{run_len} ({t_start}→{t_end})")
                    else:
                        output.append(f"[{lvl_str}] \"{msg_pattern}\" ×{run_len} ({len(unique_msgs)} variants, {t_start}→{t_end})")
                    continue
                else:
                    i = start_i

        # --- Identical line runs ---
        if i + 1 < len(cleaned):
            run_count = 1
            while i + run_count < len(cleaned) and cleaned[i + run_count] == line:
                run_count += 1
            if run_count > 2:
                output.append(f"{line}  (×{run_count})")
                i += run_count
                continue

        # --- Multi-line block dedup (e.g., same warning+code from N workers) ---
        block_size = _detect_repeating_block(cleaned, i)
        if block_size and block_size > 1:
            block = cleaned[i:i + block_size]
            repeat_count = 1
            j = i + block_size
            while j + block_size <= len(cleaned) and cleaned[j:j + block_size] == block:
                repeat_count += 1
                j += block_size
            if repeat_count > 1:
                for bl in block:
                    output.append(bl)
                output.append(f"  ↑ block repeated {repeat_count}× total")
                i = j
                continue

        output.append(line)
        i += 1

    return output


def _truncate_warning(header: str, details: list[str]) -> str:
    """Compress webpack warning to just the essential info."""
    full = " ".join(details)

    not_found_m = re.search(r"export '(\w+)'.*was not found in '([^']+)'", full)
    module_not_found = re.search(r"Module not found: Error: Can't resolve '(\w+)' in '([^']+)'", full)

    if not_found_m:
        export_name = not_found_m.group(1)
        source = not_found_m.group(2)
        return f"WARN {header.split('WARNING in ')[1].split()[0]}: missing export '{export_name}' from '{source}'"
    elif module_not_found:
        mod = module_not_found.group(1)
        return f"WARN {header.split('WARNING in ')[1].split()[0]}: can't resolve '{mod}' (needs polyfill?)"
    else:
        short_detail = full[:120] + "..." if len(full) > 120 else full
        return f"WARN {header.split('WARNING in ')[1]}: {short_detail}"


def _detect_repeating_block(lines: list[str], start: int, max_block_size: int = 12) -> int | None:
    """Check if lines[start:] begins a repeating block of size 2..max_block_size."""
    remaining = len(lines) - start
    for size in range(2, min(max_block_size + 1, remaining // 2 + 1)):
        block = lines[start:start + size]
        if lines[start + size:start + 2 * size] == block:
            return size
    return None


def strategy_agent_hybrid(lines: list[str]) -> list[str]:
    """
    Strategy 5: Agent + template dedup.

    Best of both worlds: agent-quality compression (truncated warnings,
    asset summaries, structured log grouping) followed by template-based
    dedup to catch any remaining repetitive patterns.
    """
    pass1 = strategy_agent(lines)
    pass2 = _template_dedup_clean(pass1)
    return pass2


def strategy_conservative(lines: list[str]) -> list[str]:
    """
    Conservative compression — keeps almost everything, only collapses the
    most obvious noise: long identical-line runs, progress bars, and docker
    layer chatter. Good when you want detail but not raw verbosity.
    """
    cleaned = [strip_ansi(line).strip() for line in lines]
    output = []
    i = 0

    while i < len(cleaned):
        line = cleaned[i]

        if not line:
            i += 1
            continue

        # Collapse webpack progress (50+ lines of percentage updates)
        if line.startswith('<s> [webpack.Progress]'):
            start_i = i
            while i < len(cleaned) and cleaned[i].startswith('<s> [webpack.Progress]'):
                i += 1
            count = i - start_i
            if count > 5:
                output.append(cleaned[start_i])
                output.append(f"  ... ({count - 2} webpack progress updates) ...")
                output.append(cleaned[i - 1])
            else:
                output.extend(cleaned[start_i:i])
            continue

        # Collapse docker layer lines (only if many)
        if re.match(r'^[0-9a-f]{12}: \w+', line):
            start_i = i
            while i < len(cleaned) and re.match(r'^[0-9a-f]{12}:', cleaned[i]):
                i += 1
            count = i - start_i
            if count > 10:
                output.append(cleaned[start_i])
                output.append(f"  ... ({count - 2} docker layer status lines) ...")
                output.append(cleaned[i - 1])
            else:
                output.extend(cleaned[start_i:i])
            continue

        # Collapse only long runs of truly identical lines (>3)
        if i + 1 < len(cleaned):
            run_count = 1
            while i + run_count < len(cleaned) and cleaned[i + run_count] == line:
                run_count += 1
            if run_count > 3:
                output.append(line)
                output.append(f"  ↑ repeated {run_count} times")
                i += run_count
                continue

        output.append(line)
        i += 1

    return output


STRATEGIES = {
    "conservative": strategy_conservative,
    "compact": strategy_agent_hybrid,
    "aggressive": strategy_agent_hybrid,
}


def compress(lines: list[str], mode: str = "compact") -> list[str]:
    """Compress log lines using the named mode."""
    fn = STRATEGIES.get(mode, strategy_agent_hybrid)
    return fn(lines)


def _normalize_msg(msg: str) -> str:
    """Normalize a structured log message for grouping — strip variable parts."""
    msg = re.sub(r'tunacuma/\S+', '<service>', msg)
    msg = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?', '<ip>', msg)
    msg = re.sub(r'https?://\S+', '<url>', msg)
    msg = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*', '<time>', msg)
    msg = re.sub(r':\d{2,5}', ':<port>', msg)
    return msg[:100]


def _extract_time_val(line: str) -> str:
    m = re.search(r'time="([^"]*)"', line)
    if m:
        t = m.group(1)
        time_m = re.search(r'(\d{2}:\d{2}:\d{2})', t)
        return time_m.group(1) if time_m else t
    return "?"


def _extract_timerange(first_line: str, last_line: str) -> str:
    def _get_time(line):
        m = re.search(r'time="([^"]*)"', strip_ansi(line))
        return m.group(1) if m else "?"
    t1, t2 = _get_time(first_line), _get_time(last_line)
    if t1 == t2:
        return t1
    return f"{t1} → {t2}"
