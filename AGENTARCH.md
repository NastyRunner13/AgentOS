# AGENTARCH — build & operate AgentOS

The agent-facing contract for this repo: build order, done-conditions, runtime rules.
[ARCHITECTURE.md](ARCHITECTURE.md) is the single source of truth for _why_ — reach it when changing design rationale, not behavior. Behavior changes happen here first.
[PRINCIPLES.md](PRINCIPLES.md) is how we build: **loop** vs chat, maker vs checker, graphs of **nodes**, **resume** + **charter**, caps, unattended threat. Open it when adding a **loop**, a **node**, a skill, a schedule, a verifier, a memory write path, or anything that runs while the user is away.

## Leading words

Tokens with exact meanings across this repo's docs, prompts, code reviews. Use them as tokens; expand them only in definitions:

| Token | Meaning |
|---|---|
| **verified** | Work counts as done only after an independent signal confirms it. UI action: re-read state. Code: test / build / lint. Loop goal: a machine check (file, HTTP, hash) or `fast` scoring the stated condition. The maker never marks its own work **verified**. Unverified = not done. |
| **stuck** | 2 failed verifications or low-confidence grounding → halt, attach evidence, ask. Includes false-done: the maker emitted "done" on a half-finished job. Blind retries are the bug, not the fix. |
| **untrusted** | Text scraped from screens, OCR, web pages, and unaudited skill descriptions. May inform decisions; never triggers tools or alters permissions. |
| **earned** | Unlocked solely by eval numbers (success %, latency, cost, interventions, cost per accepted outcome). Nothing grants itself **earned** status. |
| **card** | Approval request: what / why / exact command preview / risk **ring**; expiry defaults to deny. |
| **ring** | Risk tier 0–3 attached to every tool call (table in Safety). |
| **steer** | A user message routed into a running task mid-flight without restarting it. |
| **consolidate** | Librarian pass converting episodes into facts/skills. Runs in stages; never ahead of its stage gate. |
| **loop** | Cadence, goal, or event system that prompts Friday, **verifies** the result, writes **resume**, and stops on a cap or a **card**. Distinct from a **task** (one background shot). |
| **resume** | Durable loop state: done, next, rejected, spend, last **verified** result. L2 is the audit log; **resume** is how tomorrow continues. |
| **charter** | Standing user-level goals and hard constraints, reread every **loop** run. Distinct from the system prompt. |
| **node** | One bounded job, schema in, schema out. Input is passed in, never assumed from a shared window. |
| **edge** | Data actually moves from one **node** to another. Flatten / dedupe / filter on an **edge** is code. |

## The system in one paragraph

One Python kernel process owns an asyncio event bus. Clients (desktop app, orb overlay, phone PWA, CLI) and the voice stack hang off that bus. A **master agent** (model chosen in `config/models.yaml`, swappable without code changes) clarifies ambiguous requests, wraps risky actions in **cards**, and delegates to sub-agents (coder, researcher, operator, librarian). Every tool call passes the permission gate (**rings**) and lands in the SQLite episodic log. Long work runs as background **tasks** you can **steer**. Recurring machine-checkable work runs as **loops** that resume from disk. Multi-item work is a graph of **nodes**. The conversation never blocks.

## Build sequence

Work phases in order. Each ends when its done-condition holds — a phase is complete or it isn't; partial credit does not exist here.

### Phase 1 — trustworthy core

Kernel event bus + task manager (concurrent slots, **steer** routing) · model registry (anthropic/openai/ollama/openrouter adapters; roles `master/fast/vision/embeddings`) · master agent with clarify-first scoring and **card** emission · native tools (shell, files) + Playwright browser · SQLite episodic logging · CLI loop (`main.py --cli`).

**DONE WHEN:** from a fresh clone plus configs: (a) a chat round-trip streams through the registry-selected model; (b) two concurrent tasks both accept **steer** messages routed correctly; (c) a ring-2 shell call blocks until a **card** is approved, and executes after approval; (d) every turn writes ≥1 episodic row; (e) swapping `roles.master` in YAML alone changes the responding model.

### Phase 1b — first loop

After Phase 1. May run beside Phase 2. Required before Phase 6. One recurring, machine-checkable job. The manual run already works in Phase 1 chat. Then one skill, one **resume**, one **verified** signal, then a schedule or event. Caps declared (iterations, tokens, wall-clock, max **ring** unattended). Overnight output is a ring 0–1 draft. No swarm, no self-drawn graph, no community skill install. Rules: [PRINCIPLES.md](PRINCIPLES.md).

**DONE WHEN:** (a) a killed process resumes the same **loop** from **resume** without re-deriving the job; (b) a known-bad artifact is rejected by the **verified** signal; (c) the token or iteration cap stops a runaway; (d) ring-2 actions still emit a **card**; (e) cost per accepted outcome is written into the eval JSON.

### Phase 2 — reliability layer

Operator sub-agent: UIA/a11y ladder first, Set-of-Marks screenshots last, **verified** after every action, **stuck → ask** protocol. Allowlist-mode v1 (known apps + browser, single monitor). Eval harness v1: repeatable scenario suite emitting `{success%, latency, token cost, human interventions, cost per accepted outcome}` per run.

**DONE WHEN:** (a) the suite runs end-to-end from one command and writes metrics JSON; (b) every operator action in the trace carries a verify result; (c) a deliberately broken scenario terminates via **stuck → ask** with evidence attached rather than retrying; (d) pixels-path fires only when the a11y path returned nothing usable.

### Phase 3 — memory stages 0→1

Stage 0 ships inside Phase 1 (verbatim episodic + user-confirmed facts only). Stage 1 adds the librarian drafting facts/entities as reviewable proposals with bulk-approve, minimal graph schema, supersede-with-`valid_to`.

`config/memory.yaml` `stage` is the sole write-path authority:

| stage | What may land in the graph |
|---|---|
| 0 | L2 events always. Facts/entities/edges only after a human **approve**. No librarian. |
| 1 | Librarian may insert *proposals*. Graph apply still only after **approve**. Bulk-approve allowed. |
| 2 | Auto-consolidate after each session. **Not earned.** |

**STAGE 2 AUTO-CONSOLIDATE: LOCKED**

Stage 1 graph lives in the same SQLite file as L2 (`entities`, `facts`, `edges`, `proposals`) matching `Person/Project/Preference/Fact` plus `OWNS/ABOUT/SUPERSEDES`. Kuzu and L3 vectors wait for Stage 2. `facts`/`entities`/`edges` rows are written only inside `Episodic.approve`. Supersede sets `valid_to`; nothing is deleted. Recall injects confirmed, currently-valid facts — never pending proposals, never L2 turns as facts.

**DONE WHEN:** (a) the recall-after-N-turns eval passes using confirmed facts alone; (b) proposals appear in the approval queue, never auto-applied; (c) grep proves zero automatic graph/vector write paths outside the stage gates.

### Phase 4 — voice

Local pipeline first: openWakeWord → faster-whisper → Piper, silero VAD, `tts.amplitude` events at ~30fps. Cloud adapters after local works. Realtime mode last.

**DONE WHEN:** (a) wake → spoken response measured under the latency budget in `config/voice.yaml`; (b) barge-in cancels playback within one VAD frame; (c) orb receives amplitude events during speech; (d) every component swap is a YAML edit, verified by running twice with different stacks.

### Phase 5 — surfaces

Desktop app (Tauri): main window with live action feed + approval inbox; orb overlay with pop/bounce spring states. Phone PWA over Tailscale last — optional early, desktop + voice carries daily use.

**DONE WHEN:** (a) feed shows each tool call within one event-loop tick of execution; (b) orb transitions idle→waking→listening→speaking driven purely by bus events; (c) a **card** raised on kernel appears simultaneously on desktop and phone.

### Phase 6 — **earned** autonomy

Each unlocks only when Phase 2's harness shows the numbers: stage-2 auto-consolidation (recall accuracy up, contradiction rate down), passive skill mining (candidate precision acceptable), full-desktop operator freedom (allowlist removed by measurement, not mood), further **loops** and saved graphs. Autonomy dial stays `suggest_only` until explicitly changed. Phase 1b's first **loop** is already **earned** before this phase starts.

**DONE WHEN:** each feature's unlocking metric is quoted in the PR that flips it.

## Reference

Harness layers (prompt, skill-on-demand, web research) are specified here. Voice and desktop stay later clients of the same bus; do not add a second brain.

### Event contracts

Bus topics every client may subscribe: `agent.state`, `task.update`, `tool.call`, `tool.result`, `approval.request`, `approval.resolved`, `tts.amplitude`, `error`. Task shape: `{id, title, status: queued|running|blocked|waiting_approval|done|failed, progress}`. **Card** payload: `{action_preview, reason, ring, expires_at}`. `agent.state` phases: `thinking` (turn started), `token` (streamed text; model reasoning is wrapped in `<think>`…`</think>` and is not part of the assistant reply), `stuck`, `idle` (turn finished).

### CLI surface

`python main.py --cli` is the Phase 1 interactive surface (`ui/`). It is a prompt loop, not a full-screen TUI.

**Header.** The banner names the workspace directory (home abbreviated to `~`), the current git branch when the workspace is a repo (omitted otherwise; detached HEAD shows the short hash), the session id, model, and mode.

**Transcript.** Each foreground turn prints: the user line; a thinking block (dim, collapsed to `thought <duration>` when the first non-thought token or tool arrives); one row per `tool.call` / `tool.result` (name, short args, **ring**, elapsed); the assistant reply as rendered markdown, not raw markers; a footer with wall-clock time, tool count, and **card** count. The CLI subscribes to `tool.call`, `tool.result`, and `approval.resolved` as well as `agent.state` / `approval.request` / `error`.

**Composer.** Input is a framed text box (not a raw `>` prompt). Placeholder `message or /command`. Enter sends. The box is hidden during a foreground stream and redrawn after `idle` (or an error). Background **task** turns still run on the task manager and may print into the transcript while the prompt is idle. `patch_stdout` keeps those prints from eating the prompt. `/exit` (alias `/quit`) stops the process.

**Cards.** A **card** raised during a foreground turn asks `y` allow / `n` deny inline (the main prompt is not up, so `/approve` would deadlock). `/approve` and `/deny` remain for background **tasks** and for anyone who skipped the inline prompt. Ring 0–1 tools still run silent.

**Sessions.** `data/sessions/<id>.json` stores CLI `history` (the same list `Master` uses) plus title, mode, timestamps. L2 is still the audit log; session files are not facts and are never recalled as facts. `/new` (alias `/reset`) writes the current session if it has turns, clears the screen, starts a blank conversation, and reprints the banner with the new session id. `/resume` with no argument opens a picker of recent sessions; `/resume <id>` loads that session. After a load, the CLI clears the screen, reprints the banner, and replays saved `history` so the window shows the past conversation. `/sessions` lists without switching. `/rename <title>` sets the title. Auto-save on `idle`. `/clear` only clears the screen and reprints the banner.

**Skills as slash commands.** A loaded skill with `user-invocable` true (default) runs as `/<name> [args]`. `/skill <name> [args]` is the same. Built-in commands keep the bare name; a colliding skill is `/skill:<name>`. The invocation is a foreground turn: skill body plus the user's arguments. `/skills` lists. Unknown `/foo` is not sent to the model.

### Clarify-first

`config/kernel.yaml` `clarify` (default true) scores each chat turn with `fast` before master. Prompt: `config/models.yaml` `prompts.clarify`.

- Input: current user text plus the last 3 foreground `history` turns. No tools on the scorer.
- `unclear` is only a missing user choice that would change the action (which path, which app, which person). Friday already has `files`, `shell`, `browser`, `computer`, `web_search`, `web_fetch`, `skill`, and kb tools. An omitted path is the working directory. "Look up X" / "research Y" is **clear**.
- `unclear` asks at most 3 questions, writes them to L2 and `history`, and returns without master. The next foreground user turn skips the scorer and runs master with that `history`.
- `trivial` appends `[assumption]` and continues to master. `clear` continues.
- Background **task** turns still score; they neither set nor consume the skip, and they do not receive CLI `history`.

### Permission rings

| Ring | Scope | Gate |
|---|---|---|
| 0 | reads: screen, files, web fetch | silent |
| 1 | app launch, writes in approved roots, browser actions | silent, logged |
| 2 | shell outside allowlist, installs | **card**, scoped grants allowed |
| 3 | deletes above threshold, purchases, sends, credentials | explicit confirm, no scope grants |

Chat tools and their default rings (`config/permissions.yaml`). Unknown names are ring 2.

| Tool | Ring | Role |
|---|---|---|
| `files` read/search | 0 | sandbox inside approved roots |
| `web_search` | 0 | DuckDuckGo HTML query → `{title, url, snippet}`, wrapped **untrusted** |
| `web_fetch` | 0 | HTTP GET `http:`/`https:` only; block localhost and private IPs (127/10/172.16–31/192.168); wrapped **untrusted**; truncated to `tool_result_max_chars` |
| `skill` | 0 | return a SKILL.md body by name |
| `spawn_task` / `kb_read` | 0 | |
| `files` write / `browser` / `computer` / `kb_propose` / `kb_consolidate` | 1 | |
| `shell` allowlisted | 1 | |
| `shell` other | 2 | **card** |
| `files` delete | 2–3 | size threshold |

`config/kernel.yaml` `max_tool_steps` (16) caps chained tool calls per chat turn. It is not a **loop** cap. Browser snapshot text is clipped to `tool_result_max_chars` inside the **untrusted** wrap.

Hardening: **untrusted** content is labeled at ingestion and stripped of tool-trigger power; permission config is the sole authority over execution; secrets exist only in `.env`, scrubbed from context; MCP servers pinned by version; L2 records everything for audit. A **loop** at 3am is an attack surface at 3am: overnight work stays ring 0–1 and produces drafts; ring 2–3 wait on a **card**; loop permissions are re-audited on a 30-day calendar. Full unattended rules: [PRINCIPLES.md](PRINCIPLES.md).

### Memory layers

L2 episodic (SQLite + FTS5) always-on audit log → L3 semantic (vector recall) → L4 graph (KuzuDB: `Person/Project/Fact/Preference/SkillRef`, edges carry confidence + validity). Retrieval = parallel vector + graph-walk + BM25, reranked, injected. Write path obeys stage gates; supersession replaces deletion. A **loop** also reads **charter** (where to go) and **resume** (where we are). L2 does not stand in for either.

### Skills

Discovery, nearest wins on name: `~/.agents/skills/*/SKILL.md` (or `kernel.yaml` `skills_dir`), then `.agents/skills/*/SKILL.md` walking from the workspace up to the git root (or `root` if there is no git), then workspace `skills/*/SKILL.md` last. Optional `.claude/skills` is not loaded.

The master prompt gets a catalog of name + description + source (`format_skills_for_prompt`; descriptions capped ~200 characters). Bodies stay out of the system prompt. The `skill` tool `{name}` (ring 0) returns the body, or an error string if the name is unknown or `disable-model-invocation` is set. `/name` and `/skill <name>` still inject the body via `format_skill_turn` as a foreground turn.

`disable-model-invocation: true` hides a skill from the catalog and from the `skill` tool; slash still works.

When a skill is active on that turn (slash load or a `skill` tool call) and `allowed-tools` is non-empty, any other tool returns `skill forbids this tool` (still logged). An empty list adds no restriction. The permission gate still applies.

Community skill bodies are **untrusted** for tool-trigger purposes. Loading is not executing; scripts inside a skill still go through `shell` / rings.

Triggers in trust order: active suggestion after novel multi-step success → explicit teaching → gated passive mining. Pipeline: trajectory → generalized `SKILL.md` with `{{parameters}}` → dry-run validation → approval queue. Two consecutive failures auto-suspend a skill pending review. Versions are rollback points; user edits outrank agent edits. Community skill descriptions are **untrusted**; install is a **card** after a human reads the source.

### Config surface

Versioned source of truth, one file per concern: `models.yaml`, `voice.yaml`, `permissions.yaml`, `memory.yaml`, `mcp_servers.json`, `voice.yaml` latency budget. Behavior changes ship as config diffs wherever possible; schema changes require updating the matching section here in the same commit.

`models.yaml` `prompts.master` teaches tool choice (files vs `web_search`/`web_fetch` vs `browser` vs `computer` vs `shell` vs `skill`) and forbids claiming success without a tool result. `prompts.clarify` lists the same tools; research asks are **clear**.

`permissions.yaml` `web:` (`search_ring`, `fetch_ring`, `search_max_results`, `fetch_timeout_seconds`, `user_agent`). DuckDuckGo HTML needs no API key.

`kernel.yaml`: `concurrent_slots`, `max_tool_steps` (chat tool-loop cap, 16), `clarify`, `tool_result_max_chars`, `skills_dir`.

`memory.yaml`: `stage` (0/1/2), `recall_limit`, `consolidate_episode_limit`, `max_proposals_per_pass`, `librarian_fail_stuck`. Stage 2 stays locked until the Phase 6 eval unlocks it.

### Later (specified, not this tree)

Voice (Phase 4): STT emits the same user text the CLI already sends to `Master.turn`. TTS consumes assistant text + `tts.amplitude`. Open/close of allowlisted apps is `computer`. Do not add a second voice-tools API.

Desktop (Phase 5): subscribe to existing bus topics (`agent.state`, `tool.call`, `approval.request`, `tts.amplitude`). Cards already have a payload. The CLI is one client; Tauri is another.

Typed sub-agents: `spawn_task` stays. A later `spawn_subagent(role, prompt)` (depth 1, isolated history, schema `{status, result, artifacts[]}`) waits until `files` can be capability-gated. Not a swarm.

Markdown command templates (`$ARGUMENTS`) wait; skills-as-slash is enough. Builtins own `/name`; colliding skills are `/skill:name`.
