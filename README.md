# agenttee

Like `tee`, but for AI agents. Pipe your command output through `agenttee` and let agents read, search, and diff your logs through an MCP server — with smart compression that cuts thousands of lines down to what actually matters.

```
my_server | agenttee --name api
```

## Why

Dev logs are noisy. A typical `npm run dev` or `docker compose up` dumps thousands of lines — progress bars, layer statuses, repeated warnings, asset listings — but the signal is maybe 50 lines. If you're working with an AI agent, all that noise eats context window for breakfast.

agenttee sits between your command and your terminal. It passes everything through (you still see full output), but stores a timestamped copy that the agent can query through an MCP server. When the agent asks for logs, they come back compressed — 97% smaller in real-world tests — while keeping every unique piece of information.

## Install

Requires Python 3.12+.

```bash
git clone https://github.com/TunaCuma/agenttee.git
pip install ./agenttee
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/TunaCuma/agenttee.git
uv tool install -e ./agenttee
```

After the installation you will have a global `agenttee` command.

## Quick Start

### 1. Capture logs

```bash
# Explicit name
my_server | agenttee --name api

# Auto-names from the command or working directory
docker compose up | agenttee
```

### 2. Add the MCP server to your editor

**Cursor / Claude Desktop** — add to your MCP settings:

```json
{
  "mcpServers": {
    "agenttee": {
      "command": "agenttee",
      "args": ["serve"]
    }
  }
}
```

### 3. Ask your agent about the logs

The agent now has access to these tools:

| Tool            | What it does                                                         |
| --------------- | -------------------------------------------------------------------- |
| `list_sessions` | Show all captured sessions with status, line count, size             |
| `get_logs`      | Read logs with compression mode: `compact`, `conservative`, or `raw` |
| `tail`          | Get the latest N lines (useful for active sessions)                  |
| `search`        | Regex search across one or all sessions with context                 |
| `get_stats`     | Template analysis — understand log structure and repetition          |
| `get_timeline`  | Interleave multiple sessions by wall-clock time                      |
| `diff_sessions` | Unified diff between two sessions (compressed)                       |
| `get_traces`    | Retrieve trace lines you added with the `AGENTTEE_TRACE` keyword     |

## Features

### Smart compression

Multiple compression strategies, from light to aggressive:

- **conservative** — only collapses the most obvious noise (long progress bars, docker layer chatter, 4+ identical lines). Use when you want detail.
- **compact** (default) — aggressive compression. Collapses webpack progress, truncates verbose warnings to their essential info, summarizes asset listings, groups repeated structured log messages, deduplicates by template signature. Tested at 97% reduction on real dev logs.
- **raw** — no compression, just ANSI stripping.

### Timestamped ingestion

Every line gets a wall-clock timestamp when it arrives. This means `get_timeline` can interleave logs from two services in the order things actually happened — not just concatenated.

```bash
# Terminal 1
my_api | agenttee --name api

# Terminal 2
my_worker | agenttee --name worker
```

Then the agent calls `get_timeline(["api", "worker"])` and sees a unified chronological view.

### Session diffing

Run your service, capture as `run1`. Make a change, run again as `run2`. The agent calls `diff_sessions("run1", "run2")` and gets a unified diff of the compressed logs — new errors, removed warnings, changed startup sequence.

### Auto-naming

If you don't pass `--name`, agenttee detects the parent process command (e.g., `django` from `python manage.py runserver`) or falls back to the working directory name. No need to think about session names for quick captures.

### Tracing

Add `AGENTTEE_TRACE` print statements to your code and pull just those lines out of the noise:

```python
print(f"AGENTTEE_TRACE [checkout] user={user.id} total={cart.total}")
print(f"AGENTTEE_TRACE [db] query took {elapsed}ms rows={count}")
```

The agent calls `get_traces()` to see only trace output, or `get_traces(tag="db")` to filter by tag. Use `context=2` to include surrounding log lines for each hit.

### CI log debugging

Pipe `gh run watch` through agenttee to capture CI output as it streams, then let the agent figure out why the build failed — without scrolling through hundreds of lines of install noise:

```bash
gh run watch 12345 | agenttee --name ci
```

The agent calls `get_logs("ci")` and gets a compressed view with dependency installation, progress bars, and repeated linter output collapsed down to the actual failures. For flaky tests, capture passing and failing runs as separate sessions and diff them:

```bash
# First run
gh run watch 12345 | agenttee --name ci-run1

# Second run after a change
gh run watch 12350 | agenttee --name ci-run2
```

Then `diff_sessions("ci-run1", "ci-run2")` shows exactly what changed between the two runs.

### Cross-session search

`search("connection refused")` scans all sessions at once with context lines. Useful during incidents when you're running multiple services and need to find which one is failing.

## CLI Reference

```
# Capture logs to a named session
some_command | agenttee --name myservice

# Capture with auto-naming
some_command | agenttee

# Start the MCP server (stdio transport)
agenttee serve

# List captured sessions
agenttee sessions

# Analyze a log file directly (without MCP)
agenttee app.log --stats
```

## How Compression Works

agenttee uses a pipeline of techniques:

1. **Tokenization** — each log line is parsed into typed tokens (TIMESTAMP, LEVEL, NAMESPACE, IP, URL, PATH, etc.)
2. **Template signatures** — the sequence of token types becomes a fingerprint for the line's structure
3. **Semantic rules** — pattern-specific handlers for webpack progress, Docker layers, asset listings, and structured log messages
4. **Template deduplication** — consecutive runs of lines with the same structure get collapsed into first + count + last
5. **Message normalization** — variable parts of structured logs (IPs, timestamps, service names) are abstracted for better grouping

The `compact` mode chains semantic compression with template dedup for maximum reduction. The `conservative` mode only applies the most aggressive semantic rules.

## Project Structure

```
agenttee/
  tokenizer.py    # Line tokenization and ANSI stripping
  templates.py    # Template clustering and framework-ness scoring
  compress.py     # All compression strategies
  store.py        # Session storage (~/.agenttee/sessions/)
  pipe.py         # stdin capture with pass-through
  server.py       # MCP server (8 tools)
  cli.py          # CLI entry point
tests/            # 70 tests
IDEAS.md          # Future use cases and feature ideas
```

## Development

```bash
git clone https://github.com/TunaCuma/agenttee.git
cd agenttee
uv sync

# Run tests
uv run pytest tests/ -v

# Run file analysis (without MCP)
agenttee some_logfile.log --stats
```

## License

MIT
