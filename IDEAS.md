# agenttee — Ideas & Future Use Cases

## Implemented

- **Pipe capture** — `some_command | agenttee --name svc` streams logs while storing them
- **Auto-naming** — falls back to parent command name or cwd if `--name` omitted
- **Timestamped ingestion** — every line gets a wall-clock timestamp for cross-session merging
- **Compression modes** — conservative (light), compact (aggressive), raw
- **Timeline merge** — interleave multiple sessions sorted by real time
- **Diff between runs** — unified diff of compressed logs to see what changed
- **Search** — regex across sessions with context
- **Template analysis** — understand log structure and repetition

## Use Cases to Explore

### Multi-service debugging
Run `api | agenttee --name api` and `worker | agenttee --name worker` side by side.
Use `get_timeline(["api", "worker"], grep="request-id-123")` to trace a single request
across both services. The wall-clock timestamps let you see the real ordering.

### Before/after a code change
Run your service, capture as `run1`. Make a change, capture as `run2`.
`diff_sessions("run1", "run2")` shows what the change did to logs —
new errors, removed warnings, different startup sequence.

### CI/CD log analysis
Pipe CI output through agenttee, then ask an agent "why did the build fail?"
Compression removes the 500 lines of `npm install` noise and surfaces the error.

### Log-driven test assertions
Capture test runner output. Use `search` to verify expected log patterns
appeared (or didn't). More flexible than parsing structured test output.

### Flaky test investigation
Capture multiple test runs. Diff them to find what varies between
passing and failing runs — timing differences, resource contention, order-dependent state.

### Production incident replay
Pipe kubectl/docker logs through agenttee during an incident. Later,
an agent can search and analyze without scrolling through thousands of lines.

### Long-running process monitoring
For dev servers that run for hours, `tail` gives recent state and `search`
finds when something went wrong without loading the entire history.

## Feature Ideas

### Session snapshots / versioning
Allow `agenttee snapshot --name api` to create a named checkpoint of the current
session state. Then `diff_sessions("api@snapshot1", "api@snapshot2")` would work
across checkpoints of the same session, not just different sessions.

### Log level filtering
`get_logs(session, level="error")` — parse log levels and filter by severity.
Useful when you only want to see errors/warnings from a verbose service.

### Anomaly detection
Use template frequency baselines to flag unusual log patterns:
"This template appeared 500x in run1 but 0x in run2" or
"New template never seen before appeared 50 times."

### Watch mode / streaming
`agenttee watch --name api --grep error` — live tail that only shows
lines matching a pattern, with compression applied to the buffer window.

### Correlation IDs
Automatically detect request/trace IDs in logs and group related lines.
`get_trace("req-abc123")` would pull all lines mentioning that ID across
all active sessions.

### Export / share
`agenttee export --name api --format markdown` — produce a compressed
log summary suitable for pasting into a GitHub issue or Slack thread.

### Auto-compress on disk
For very long sessions, periodically compress older segments on disk
to save space while keeping recent lines raw for fast tailing.

### Multi-machine support
`agenttee --name api --host prod-1` — tag sessions by host. Timeline
merge across machines for distributed system debugging.

### Pattern bookmarks
Let agents bookmark interesting log ranges: "the crash happened between
lines 450-460." Other agents or future sessions can reference these.

### Retention policies
Auto-cleanup sessions older than N hours/days. Configurable per-session
or globally. Important for long-running dev environments.

### Integration with structured logging
Parse JSON/structlog lines and expose fields as searchable metadata.
`search(field="user_id", value="12345")` instead of regex.

### Log diffing with semantic awareness
Instead of line-by-line diff, diff at the template level:
"run2 has 50 more timeout warnings and a new crash template that
run1 didn't have" — more useful than a raw unified diff for agents.
