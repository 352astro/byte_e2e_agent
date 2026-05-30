---
name: e2e-self-verification
description: "MANDATORY when ANY frontend file is modified, created, or deleted — NO EXCEPTIONS. If you touched frontend/src/**, you MUST load this skill before claiming completion. Establishes the iron law that no frontend change is complete without browser verification: determine configured port from vite.config.ts, check if already running with ss, start with nohup only if needed, always curl with --noproxy '*', enumerate every page and feature, dispatch ONE BrowserInspect per feature (never batch multiple), kill service by port after verification. Evidence before assertions always."
---

# Frontend Development Criteria

This is not advice. This is the mandatory verification protocol for every frontend change. You do not have a choice. If you touched the frontend, you follow this protocol to the letter.

**Core principle:** You cannot see the screen. The browser tools are your only eyes. If you didn't use them, you are blind. And a blind engineer shipping frontend code is negligence.

**Violating any step of this protocol is violating the entire protocol.**

## The Iron Law

```
NO FRONTEND CHANGE IS COMPLETE WITHOUT BROWSER VERIFICATION.

IF YOU TOUCHED frontend/src/** → YOU MUST LOAD THIS SKILL → YOU MUST FOLLOW EVERY STEP.
```

There is no "quick fix," no "trivial change," no "I'm confident it works." If a file under `frontend/src/` was modified, you follow this protocol. End of discussion.

## When This Skill Applies

**ABSOLUTE triggers — you have NO discretion:**

- Any file under `frontend/src/` is created, modified, or deleted
- Any file under `frontend/public/` is created, modified, or deleted
- `frontend/package.json` or `frontend/vite.config.ts` is modified
- A backend API route consumed by the frontend is modified
- A UI bug is claimed as "fixed"
- A frontend task is about to be marked "done"

**The test is simple:** Could a user see or interact with something different because of this change? If the answer is even "maybe," the protocol applies.

## The Protocol

### Step 0: Load This Skill

Before you do anything else after a frontend change — before you mark a task done, before you commit, before you celebrate — load this skill and follow it.

### Step 1: Discover or Start the Service

The frontend dev server MUST be running. Follow this order — always check first, start only if needed.

#### 1a. Determine the configured port

Read `frontend/vite.config.ts`. Look for `server.port`. If not explicitly set,
the Vite default is `5173`. This is `<CONFIGURED_PORT>`.

Knowing the exact port is critical: `ss` may show several node processes from
other projects. `<CONFIGURED_PORT>` is your anchor to identify the right one.

#### 1b. Check if already running

```bash
ss -tlnp | grep <CONFIGURED_PORT>
```

**If a process IS bound to `<CONFIGURED_PORT>` →** the service is already
running. Set `<PORT>` = `<CONFIGURED_PORT>` and jump to step 1d (curl).
Do NOT start a second instance.

**If nothing is bound →** the service is not running. Proceed to 1c.

#### 1c. Start the service (only if 1b found nothing)

```bash
cd frontend && nohup npm run dev &
sleep 3
ss -tlnp | grep <CONFIGURED_PORT>
```

`nohup ... &` prints the background PID — note it.

If `ss` now shows `<CONFIGURED_PORT>`, set `<PORT>` = `<CONFIGURED_PORT>`.
If still nothing, wait 3 more seconds and retry `ss`. If still no port after
retries, the server may have crashed — read `frontend/nohup.out` for the error.

#### 1d. Verify the server responds

```bash
curl -s --noproxy '*' -o /dev/null -w "%{http_code}" http://localhost:<PORT>
```

**Why `--noproxy '*'` is MANDATORY:**

System environment variables like `http_proxy` / `https_proxy` (commonly
`http://127.0.0.1:7897`) cause curl to route EVEN localhost requests through
the proxy. The proxy doesn't know how to reach `localhost:<PORT>` and returns
502 — making a perfectly healthy server look dead. `--noproxy '*'` disables
proxy for ALL hosts and eliminates this false negative.

This is not curl-specific. `wget`, `axios`, `node-fetch`, and many other HTTP
clients also respect these environment variables. **Always bypass proxy when
talking to localhost.**

**If you get 502 or any curl error without `--noproxy '*'`:** DO NOT conclude
the server is down. Retry with `--noproxy '*'` first. The proxy trap is the
#1 cause of false "server not running" diagnoses in development environments.

If the response is not 200 even with `--noproxy '*'`, the server may have
actually crashed. Read `frontend/nohup.out` for the error and retry.

### Step 2: Enumerate All Verification Targets

Before touching the browser, list EVERY page and feature that needs verification. Write them out explicitly as a numbered checklist. Be exhaustive — this is your contract with yourself.

**For each target, specify:**
- The URL or route to open (using the `<PORT>` discovered in Step 1)
- The specific feature or behavior to verify
- The expected outcome
- The interaction steps (click this, type that, check the result)

Example (substitute `<PORT>` with the actual port from Step 1):

```
Verification Targets (port <PORT>):

1. Home page (/) — renders without console errors, shows project sidebar
2. Session list (/) — clicking a session opens its chat view
3. Chat input (/session/{sid}) — typing a message and pressing Enter sends it
4. SSE streaming (/session/{sid}) — agent response appears in real-time
5. Markdown rendering (/session/{sid}) — code blocks are syntax-highlighted
...
```

**Do NOT proceed to Step 3 until this list is complete and written out.** A missing target is a verification gap.

### Step 3: Verify One Feature at a Time

**THE CARDINAL RULE:**

```
ONE BrowserInspect dispatch = ONE feature verification.
NEVER batch multiple features into a single BrowserInspect call.
```

Each `BrowserInspect` sub-agent gets exactly one feature to verify. It reports back pass/fail. You read the report. Only then do you dispatch the next one.

**Correct — one feature per dispatch (use the `<PORT>` from Step 1):**

```
# Feature 1
BrowserInspect(prompt="Open http://localhost:<PORT>/. Verify: the home page renders without console errors. Check that the session sidebar is visible and lists existing sessions. Report PASS if the page loads cleanly with the sidebar present, FAIL with details otherwise.")

# Read report. If PASS → next. If FAIL → fix and re-verify this feature.

# Feature 2
BrowserInspect(prompt="Open http://localhost:<PORT>/. Click the first session in the sidebar. Verify: the chat view opens showing the message history for that session. Check that no console errors appear after navigation. Report PASS/FAIL with details.")
```

**Wrong — batching (FORBIDDEN):**

```
# ❌ NEVER DO THIS
BrowserInspect(prompt="Open http://localhost:<PORT>/. Verify: 1) home page renders, 2) sidebar works, 3) chat opens, 4) messages appear, 5) SSE works, 6) markdown renders...")
```

Batching causes the sub-agent to skip or shallow-check later items. One feature, one dispatch, one report. Sequential only.

**After each BrowserInspect report:**

| Report | Action |
|--------|--------|
| PASS | ✅ Mark that target verified. Move to next. |
| FAIL with details | 🔴 STOP. Fix the issue. Re-verify THIS feature before moving on. |
| FAIL due to timeout/error in BrowserInspect itself | Retry once. If still failing, investigate the BrowserInspect infrastructure, not the feature. |

**Do NOT proceed to the next feature until the current one passes.** A chain of verifications is only as strong as its weakest link.

### Step 4: Kill the Service by Port

After ALL verification targets pass, kill the frontend dev server. Target it by the port discovered in Step 1 — simple, precise, audit-clean:

```bash
fuser -k <PORT>/tcp
```

That's it. `fuser -k <PORT>/tcp` sends SIGTERM to whatever process is bound to the dev server port. No PID files, no wildcards, no scanning.

**ABSOLUTELY FORBIDDEN:**

```bash
# ❌ NEVER: wildcard / broadcast kill
killall node
pkill node
pkill -f ".*"
kill -9 $(pgrep node)

# ❌ NEVER: kill -9 as first resort
kill -9 ...
fuser -k -9 <PORT>/tcp
```

**The rule:** Kill ONLY the process on the discovered port. Use SIGTERM (`fuser -k`). Only if it doesn't exit within 3 seconds, and only with explicit user permission, use `fuser -k -9 <PORT>/tcp`. Never broadcast signals to all node processes.

## The Verification Report

After completing all steps, produce a verification report in this exact format:

```
📋 Frontend Verification Report
   Service: <already running | started with nohup>, port <PORT>
   Killed via: fuser -k <PORT>/tcp
   Targets identified: <N>
   Targets verified: <N>
   Targets passed: <N>
   Targets failed: <N>

   Results:
   1. <target description> — ✅ PASS / ❌ FAIL (<details>)
   2. <target description> — ✅ PASS / ❌ FAIL (<details>)
   ...

   Verdict: ALL PASS / <N> FAILURES REMAINING
```

If any target failed: do NOT mark the task complete. Do NOT commit. Fix the failures and re-verify.

## Common Rationalizations

| Excuse | Reality |
|--------|---------|
| "It's just a one-line CSS fix" | CSS changes break layouts silently. Verify. |
| "Tests pass, so it works" | Tests don't render pixels. Tests don't catch z-index bugs, overflow issues, or visual regressions. |
| "I only changed backend code" | Frontend consumes the backend. Changed response shape = broken UI. |
| "I'll verify all features in one BrowserInspect call" | Sub-agents skip details when given too many tasks. One feature per dispatch. Not negotiable. |
| "I don't need nohup, the server is already running" | Is it? Use ss to check. If not running, start with nohup. |
| "I can just killall node to clean up" | You just killed the user's terminal, editor, and other work. Kill by discovered port only. |
| "The change is too small to need all these steps" | The protocol scales down — for a one-line fix you may only have 1-2 targets. But you still follow every step. |
| "I already verified this feature earlier today" | Code changes. State drifts. Verify FRESH. |
| "BrowserInspect is slow" | Shipping broken UI is slower. One dispatch takes 15-30 seconds. |
| "I'll just assume port 5173" | Ports change. Configurations differ. Read vite.config.ts for the real port. |
| "curl returned 502 — the server is dead" | Did you use `--noproxy '*'`? http_proxy env vars hijack localhost requests through a proxy. The server is fine — your curl command is lying to you. Retry with `--noproxy '*'`. |

## Red Flags — STOP and Re-read This Skill

If you catch yourself thinking ANY of these:

- "Let me just batch these two features together"
- "I'll kill node processes to clean up"
- "This is too small to need the full protocol"
- "I verified it manually by curling the endpoint"
- "The build passed, so the UI must be fine"
- "Let me verify all 5 features in one go"
- "I don't need to write out the targets, I know what to check"
- "killall node should be fine"
- "I'll add some redirects and PID capture for safety"
- "It's probably port 5173, I'll just use that"
- "curl failed, server must be down — let me debug the server"

...you are rationalizing. STOP. Return to Step 0. Follow the protocol exactly.

## Tools Used

- `BrowserInspect` — The ONLY verification tool. Dispatches a sub-agent with browser + file + shell tools to verify ONE feature.
- `Shell` — Used only for: `nohup npm run dev &`, `ss -tlnp`, `curl --noproxy '*'`, `fuser -k <PORT>/tcp`. No other shell commands.
- `BrowserOpen` / `BrowserAct` — Used internally by BrowserInspect. Do NOT use these directly for verification; always go through BrowserInspect.

## Integration

**Order of operations for ANY frontend change:**

```
1. Write code
2. Tests pass (backend + frontend)
3. THIS PROTOCOL (Steps 0-4, in order, no skipping)
4. All targets PASS
5. verification-before-completion (general gate)
6. Mark task complete / commit / finishing-a-development-branch
```

**This protocol is a prerequisite for:**
- `verification-before-completion` — cannot claim completion until this protocol passes
- `finishing-a-development-branch` — cannot present merge options until this protocol passes
- `TaskUpdate(status="done")` — cannot mark a frontend task done until this protocol passes

## The Bottom Line

You are an AI agent. You cannot look at a screen. The browser tools are your only way to see what you built.

If you ship frontend code without browser verification, you are shipping blind. That is not engineering. That is gambling.

Follow the protocol. Every step. Every time. No exceptions.
