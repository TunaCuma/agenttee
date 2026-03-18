Right. No helper functions, no `_trace()`, no touching source at all. The agent adds `print("user_id:", user_id)` like it naturally would, and the tool figures out which lines are the agent's and which are the framework's. Pure signal separation.

This is actually a well-defined problem if you think about it the right way.

## The Observation

Look at real mixed output again:

```
[2026-03-18 10:23:01] INFO django.server "GET /api/auth/ HTTP/1.1" 200
[2026-03-18 10:23:01] DEBUG django.db.backends (0.003) SELECT * FROM auth_user WHERE id=42
[2026-03-18 10:23:01] INFO django.request Request finished in 0.023s
user_id: 42
[2026-03-18 10:23:02] WARNING django.security.csrf CSRF cookie not set
[2026-03-18 10:23:02] DEBUG kafka.consumer Heartbeat sent
[2026-03-18 10:23:02] DEBUG kafka.consumer Heartbeat sent
token_value: eyJhbGciOiJIUzI1NiJ9...
[2026-03-18 10:23:03] INFO django.server "POST /api/refresh/ HTTP/1.1" 401
refresh_result: False
```

A human can instantly see three lines don't belong. Your eyes do this effortlessly. Why? Because framework logs have **structure** and bare prints don't. That structural difference is the signal.

## What Makes a Framework Log Line a Framework Log Line

Every logging framework in every language produces output with a recognizable anatomy. The specifics vary but the structural properties are remarkably consistent:

**Timestamps.** Almost every framework log starts with or contains a timestamp. ISO 8601, epoch, `HH:MM:SS`, `Mar 18 10:23:01` — the format varies but the presence of a date/time pattern at a consistent position is near-universal. A bare `print()` almost never has a timestamp unless the developer explicitly added one.

**Log level tokens.** `INFO`, `DEBUG`, `WARNING`, `ERROR`, `WARN`, `TRACE`, `VERBOSE` — these appear in framework logs and essentially never in agent-inserted prints. An agent writes `print(f"token: {token}")`, not `print(f"DEBUG token: {token}")`.

**Logger namespaces.** `django.server`, `kafka.consumer`, `org.springframework.web`, `express:router`, `hyper::proto::h1` — dot-separated or colon-separated module paths. This is a very strong signal. No `print()` statement produces these.

**Consistent templating.** Framework lines from the same logger follow the same format template. If you see 20 lines that all match `[timestamp] LEVEL namespace message`, that's a framework pattern. Bare prints have no consistent template with the framework lines.

## The Algorithm: Template Induction

This is the core idea. Instead of maintaining a regex database of every framework's log format, you **learn the templates from the output itself** in real time.

**Step 1: Tokenize each line into typed segments.**

```
"[2026-03-18 10:23:01] INFO django.server "GET /api/auth/" 200"
→ [TIMESTAMP] [LEVEL] [NAMESPACE] [STRING] [NUMBER]

"user_id: 42"
→ [WORD] [COLON] [NUMBER]

"DEBUG kafka.consumer Heartbeat sent"
→ [LEVEL] [NAMESPACE] [WORD] [WORD]
```

The token types would be: `TIMESTAMP` (regex family for common date/time formats), `LEVEL` (the ~10 known log level keywords), `NAMESPACE` (dot-separated identifiers like `a.b.c`), `NUMBER`, `IP`, `URL`, `PATH` (file paths), `QUOTED_STRING`, `WORD`, and `SYMBOL`.

**Step 2: Cluster lines by template signature.**

Lines that share the same token-type sequence are likely from the same logger. From the example above:

```
Template A: [TIMESTAMP] [LEVEL] [NAMESPACE] ...  → 7 lines match
Template B: [WORD] [COLON] ...                   → 3 lines match (the agent's prints)
```

**Step 3: Score templates by "framework-ness."**

A template gets a high framework score if it contains `TIMESTAMP` (strong signal that it's from a logging library), contains `LEVEL` (almost definitive), contains `NAMESPACE` (very strong), has high occurrence count (frameworks log a lot, agent adds a few prints), and was seen in a baseline run (see below). A template gets a low framework score (likely agent trace) if it lacks timestamp, level, and namespace, has low occurrence count, and has a simple structure like `WORD COLON VALUE` or just `VALUE`.

**Step 4: Classify.** Lines matching high-framework-score templates go in the "framework" bucket. Lines matching low-score templates go in the "agent trace" bucket.

## The Baseline Trick

This makes classification dramatically more reliable. The first time the agent calls `capture_run("python manage.py runserver")`, before adding any prints, the MCP server captures the output for a few seconds. This is the **baseline**. It learns: "these are the templates this process normally produces."

Any subsequent run, after the agent has added instrumentation, gets compared against the baseline. **New templates that weren't in the baseline are almost certainly agent traces.**

```
MCP Server lifecycle:

1. Agent calls: start_session(command="python manage.py runserver")
   → Server launches process, captures 5s of output
   → Learns baseline templates: [A, B, C, D]
   → Returns: session_id

2. Agent modifies source code, adds prints

3. Agent calls: capture(session_id, trigger="reproduce the bug")
   → Server captures output during reproduction
   → Sees templates: [A, B, C, D, E, F]
   → E and F are NEW → classified as agent traces

4. Agent calls: get_traces(session_id)
   → Returns ONLY lines matching templates E and F

5. Agent calls: get_logs(session_id, level="ERROR")
   → Returns only framework lines matching ERROR level
```

The baseline doesn't need to be perfect. Even a few seconds of normal operation gives you the framework's log templates. After that, distinguishing agent prints is trivial.

## Edge Cases and How to Handle Them

**"What if the agent's print happens to look like a framework log?"**

Unlikely but possible — if someone writes `print(f"[{datetime.now()}] DEBUG auth: user_id={user_id}")`. But this is an adversarial case. In practice, agents write the simplest possible print: `print(user_id)`, `print(f"user_id: {user_id}")`, `print("HERE")`, `print(f">>> {response.status_code}")`. The simplicity IS the signal.

**"What if the app prints unstructured output as part of normal operation?"**

Like a CLI tool that writes `Processing item 42...` to stdout. The baseline captures this. If that template exists in the baseline, it's not an agent trace. If the agent adds a print that happens to match an existing template, you might miss it — but this is very rare because the agent's variable dumps have different content patterns.

**"What about apps that don't use a logging framework at all?"**

If everything is bare `print()` statements, the baseline captures all the normal prints. The agent's new prints are still new templates not seen in the baseline. The template approach degrades gracefully — it just relies more on the baseline diff and less on structural analysis.

**"What about stderr vs stdout?"**

Many frameworks log to stderr while prints go to stdout. The MCP server captures them as separate streams, which gives you a free separation channel in many cases. Even when mixed, the template approach still works.

## What the Token Type Recognizer Looks Like

This is the actual code at the heart of the system. It's a lexer that scans each line and produces a template signature:

```
Input:  "[2026-03-18 10:23:01] INFO django.server GET /api/auth/ 200"
Lexer:   ←TIMESTAMP→         ←LVL→ ←NAMESPACE→  ←W→  ←PATH→   ←N→
Signature: "TS_LVL_NS_W_PATH_N"

Input:  "user_id: 42"
Lexer:   ←WORD→  ←N→
Signature: "W_COLON_N"

Input:  "token_value: eyJhbGciOiJIUzI1NiJ9..."
Lexer:   ←WORD→       ←ALPHANUM→
Signature: "W_COLON_ALPHANUM"
```

The two agent lines share a similar signature family (`W_COLON_*`) that's structurally different from any framework template. And they don't exist in the baseline.

## The MCP Tool Surface (Revised)

With this signal processing approach, the tools become:

**`start_session(command, warmup_seconds?)`** — launches the process, captures baseline output for N seconds, learns framework templates. Returns `session_id`.

**`capture(session_id, duration?, until_pattern?)`** — captures output from the running process, classifies lines against baseline. The `until_pattern` is nice for "capture until you see a 500 error" type flows.

**`get_traces(session_id)`** — returns ONLY lines classified as agent-inserted (new templates not in baseline). This is the primary tool the agent uses after adding prints.

**`get_framework_logs(session_id, level?, namespace?, grep?)`** — returns framework-classified lines, filterable. For when the agent wants to see Django's own error logs.

**`get_all(session_id, annotated?)`** — returns everything, optionally with each line tagged as `[TRACE]` or `[FRAMEWORK:django.server]` or `[FRAMEWORK:kafka.consumer]`. Useful for the agent to see the full timeline.

**`get_templates(session_id)`** — returns the learned template signatures and their classification. Debugging tool for the tool itself — the agent or user can check what patterns were learned.

---

The thing I find elegant about this is that it mirrors how an experienced developer actually reads logs. You don't read every line — your eyes jump to the lines that look "different" from the framework noise pattern you've unconsciously learned. The template induction is just making that unconscious pattern recognition explicit and deterministic.

And it needs zero configuration per framework. No Django profile, no Express profile, no Kafka profile. The baseline captures whatever this specific app's noise pattern is, and the classification falls out of the structural analysis. It's truly general.

Want to dig into the lexer design for the template tokenizer, or start thinking about the MCP server lifecycle and state management?
