# Agent Instructions: Debugging with agenttee

This project uses [agenttee](https://github.com/TunaCuma/agenttee) for log
capture and compression. When debugging, use the agenttee MCP tools to read,
search, and compare logs instead of asking the user to paste output.

## Quick reference

| Tool              | When to use                                            |
| ----------------- | ------------------------------------------------------ |
| `list_sessions`   | Always call first -- see what log sessions exist       |
| `get_logs`        | Read compressed logs (compact mode is default)         |
| `tail`            | See latest output from a still-running service         |
| `search`          | Find errors/patterns across one or all sessions        |
| `diff_sessions`   | Compare before/after a code change                     |
| `get_traces`      | Retrieve AGENTTEE_TRACE lines you inserted             |
| `get_timeline`    | Interleave multiple services by wall-clock time        |
| `get_stats`       | Understand log structure before diving in              |

## Debugging playbook

1. **Check `list_sessions` first.** Existing sessions often already contain the
   information you need.

2. **No sessions?** Tell the user to capture output:
   `command | agenttee --name meaningful-name`

3. **Start with `get_logs` in compact mode** for an overview, then narrow down
   with `search` for specific errors.

4. **When adding debug prints**, use the `AGENTTEE_TRACE` keyword so
   `get_traces` can extract your instrumentation from framework noise:
   ```
   print(f"AGENTTEE_TRACE [tag] key={value}")
   ```

5. **After a fix**, capture a new session and use `diff_sessions` to confirm
   the error is resolved and nothing new broke.

6. **Multi-service debugging**: run each service through agenttee with
   different names, then use `get_timeline` to see the unified event order.

7. **CI log debugging**: when a CI run fails, capture with
   `gh run watch <run-id> | agenttee --name ci-run1`. Compression strips
   install noise and progress bars down to the actual failures. Capture
   multiple runs and `diff_sessions` them to debug flaky tests or verify
   a fix.
