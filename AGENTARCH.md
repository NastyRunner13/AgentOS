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

Kernel event bus + task manager (concurrent slots, **steer** routing) · model registry (anthropic/openai/ollama/openrouter/groq/gemini adapters; roles `master/fast/vision/embeddings`) · master agent with clarify-first scoring and **card** emission · native tools (shell, files) + Playwright browser · SQLite episodic logging · CLI loop (`main.py --cli`).

**DONE WHEN:** from a fresh clone plus configs: (a) a chat round-trip streams through the registry-selected model; (b) two concurrent tasks both accept **steer** messages routed correctly; (c) a ring-2 shell call blocks until a **card** is approved, and executes after approval; (d) every turn writes ≥1 episodic row; (e) swapping `roles.master` in YAML alone changes the responding model.

### Phase 1b — first loop

After Phase 1. May run beside Phase 2. Required before Phase 6. One recurring, machine-checkable job. The manual run already works in Phase 1 chat. Then one skill, one **resume**, one **verified** signal, then a schedule or event. Caps declared (iterations, tokens, wall-clock, max **ring** unattended). Overnight output is a ring 0–1 draft. No swarm, no self-drawn graph, no community skill install. Rules: [PRINCIPLES.md](PRINCIPLES.md).

**DONE WHEN:** (a) a killed process resumes the same **loop** from **resume** without re-deriving the job; (b) a known-bad artifact is rejected by the **verified** signal; (c) the token or iteration cap stops a runaway; (d) ring-2 actions still emit a **card**; (e) cost per accepted outcome is written into the eval JSON.

### Phase 2 — reliability layer

Operator sub-agent: UIA/a11y ladder first, Set-of-Marks screenshots last, **verified** after every action, **stuck → ask** protocol. Allowlist-mode v1 (known apps + browser, single monitor). An app on `operator.allowlist` runs silent (ring 1). An app not on that list still uses `computer` but is ring 2: a **card**, then a process-lifetime session grant — not a write to `permissions.yaml`. Eval harness v1: repeatable scenario suite emitting `{success%, latency, token cost, human interventions, cost per accepted outcome}` per run.

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

Voice is a client of the kernel, not a second brain. STT emits the same user text the CLI already sends to `Master.turn`. TTS consumes assistant text and publishes `tts.amplitude`. Open/close of allowlisted apps is `computer`. Long spoken work uses `spawn_task` so the mic loop stays free. Ring 2–3 still emit a **card**; if the turn came from voice, Friday speaks the **card** and the next utterance `yes` / `no` resolves it (CLI `y`/`n` and `/approve` still work). Do not add a voice-tools API. `voice/` must not import `Master`.

Local cascade first. Cloud STT/TTS adapters after the bus contract works. Realtime mode last. Wake, VAD, and barge-in stay on-device even when STT posts a clip to Groq (file POST, not a barge-in socket). Self-TTS is not barge-in: mute or gate the mic against the playback envelope.

`python main.py --cli` stays the entrypoint. `--voice` or `voice.yaml` `enabled: true` starts `VoiceIO` on the same process. Push-to-talk is `/listen` (Enter stops), the YAML `hotkey`, and orb click (`VoiceIO.toggle_listen`). `/listen <text>` injects a transcript without the mic (debug). Always-on "Hey Friday" is wake-word once `wake_word.engine` is not `none`; it is not a **loop**.

Build order inside this phase (narrow path; a later step does not skip an earlier one):

1. Push-to-talk → STT → `Master.turn` → TTS of the reply. `tts.amplitude` during playback. Cancel API for barge-in. No wake.
2. Energy VAD ends orb utterances after `vad.stop_secs` of silence. Mic frames drop while TTS plays (self-TTS is not barge-in). Silero VAD + cancel within one VAD frame still open.
3. openWakeWord always-on with a custom `hey_friday.onnx` (bundled community models are CC BY-NC-SA 4.0; inference is ONNX Runtime on Windows).
4. Sentence-stream TTS; speak `tool.call` titles as the operator starts.
5. YAML-swappable cloud STT (Groq) and alternate local STT (Parakeet).

Default local stack: WASAPI shared capture, openWakeWord, energy (then Silero) VAD, faster-whisper (or Parakeet), Kokoro-82M speech, Piper only for latency-critical blips. `roles.fast` must be a low-latency model for trivial spoken turns; the master model stays on hard tool work.

**DONE WHEN:** (a) wake (or, until wake ships, `/listen` / final transcript / orb click) → first spoken PCM under `config/voice.yaml` `latency_budget_ms.wake_to_first_audio`; (b) barge-in cancels playback within one VAD frame (`barge_in_frame_ms`); (c) subscribers receive `tts.amplitude` during speech at about `amplitude_fps` (the orb only subscribes; the CLI prints `[speaking]`); (d) every component swap is a YAML edit, verified by running twice with different stacks.

### Phase 5 — surfaces

Slice 1 (this tree): Python overlay orb in `orb/`. Frameless, always-on-top, square, bottom-center above the taskbar (`orb.size` px, default 140). Visual is the ElevenLabs UI Orb shader (`agentState`: `null` idle, `listening`, `thinking`, `talking`; source `orb/orb.html`). Bus `agent.state` maps: `idle`/`hidden` → idle; `waking`/`listening` → listening; `thinking` → thinking; `speaking` → talking; `stuck` → thinking with a red palette. Listening input volume follows `mic.amplitude`; talking output volume follows `tts.amplitude`. Tkinter draws the shader on a worker thread (the CLI owns the main thread; pywebview cannot). Subscribes to `agent.state`, `tts.amplitude`, `mic.amplitude`, `approval.request`, `approval.resolved`. Never opens a capture stream. Click the orb, YAML `hotkey`, and `/listen` reach VoiceIO, not the overlay. Right-click: mute mic, sleep (hide and mute), close overlay (CLI keeps running). **Card** pending paints the orb amber. Mute greys it. Tauri main window and phone PWA stay later slices.

`python main.py --cli --voice` starts VoiceIO and the orb when `orb.enabled` is true (default). `/orb` hides or shows the overlay.

**DONE WHEN:** slice 1: (b) orb transitions idle→listening→thinking→talking driven purely by bus events; `orb/` does not import `sounddevice` or `Master`; a **card** paints the orb amber until `approval.resolved`. Later: (a) feed shows each tool call within one event-loop tick of execution; (c) a **card** raised on kernel appears simultaneously on desktop and phone.

### Phase 6 — **earned** autonomy

Each unlocks only when Phase 2's harness shows the numbers: stage-2 auto-consolidation (recall accuracy up, contradiction rate down), passive skill mining (candidate precision acceptable), full-desktop operator freedom (allowlist removed by measurement, not mood), further **loops** and saved graphs. Autonomy dial stays `suggest_only` until explicitly changed. Phase 1b's first **loop** is already **earned** before this phase starts.

**DONE WHEN:** each feature's unlocking metric is quoted in the PR that flips it.

## Reference

Harness layers (prompt, skill-on-demand, web research) are specified here. The plan that landed them is [HARNESS-PLAN.md](HARNESS-PLAN.md). Voice is a client of the same bus; desktop stays Phase 5. Do not add a second brain.

### Event contracts

Bus topics every client may subscribe: `agent.state`, `task.update`, `tool.call`, `tool.result`, `approval.request`, `approval.resolved`, `tts.amplitude`, `mic.amplitude`, `error`. Task shape: `{id, title, status: queued|running|blocked|waiting_approval|done|failed, progress}`. **Card** payload: `{action_preview, reason, ring, expires_at}`. `agent.state` phases: `waking` (wake word), `listening` (capturing an utterance), `thinking` (turn started), `token` (streamed text; model reasoning is wrapped in `<think>`…`</think>` and is not part of the assistant reply), `speaking` (TTS playback), `stuck`, `idle` (turn finished or playback ended). `tts.amplitude` and `mic.amplitude` payload: `{rms, t}` at `config/voice.yaml` `amplitude_fps` (last event of an utterance has `rms` 0).

### CLI surface

`python main.py --cli` is the Phase 1 interactive surface (`ui/`). It is a prompt loop, not a full-screen TUI.

**Header.** The banner names the workspace directory (home abbreviated to `~`), the current git branch when the workspace is a repo (omitted otherwise; detached HEAD shows the short hash), the session id, model, and mode. Below ~80 columns the logo drops; below ~52 columns the banner is a single line. Tables and the composer toolbar follow the current terminal width.

**Transcript.** Each foreground turn prints: the user line (`❯` plus the text); a thinking spinner that collapses in place to `thought <duration>` when the first non-thought token or tool arrives; one row per tool (running is replaced by done: name, short args, **ring**, elapsed; `files` writes also show a short content preview); the assistant reply as rendered markdown, not raw markers; a footer with wall-clock time, tool count, and **card** count. The CLI subscribes to `tool.call`, `tool.result`, and `approval.resolved` as well as `agent.state` / `approval.request` / `error`. `/plan` shows the session's waiting plan, else the latest saved plan, else workspace `plan.md` when that file exists; it does not invent a plan. `/plan <id>` reprints a saved plan. `/plans` lists `data/plans/`.

**Composer.** Input is a framed text box (not a raw `>` prompt). Placeholder `message, @file, or /command`. Enter sends; Ctrl+J inserts a newline (Esc+Enter on non-Windows; on Windows Alt+Enter is the console fullscreen chord). Shift+Tab cycles Code / Architect / Ask / Fast. Ctrl+X opens shortcuts. Ctrl+Q exits (same as `/exit`). `@path` (Tab-complete from the workspace / `--root`) attaches that file's contents to the turn; the transcript keeps the `@path`, the model sees the body. Mentions are relative to the workspace and stay inside approved roots. The box is hidden during a foreground stream and redrawn after `idle` (or an error). On Windows, a focus change that does not alter columns/rows is not treated as a resize — those events used to reprint the inline frame a second time. Background **task** turns still run on the task manager and may print into the transcript while the prompt is idle. `patch_stdout` wraps the whole CLI loop so those prints do not eat the prompt. `/exit` (alias `/quit`) stops the process.

**Architect.** Shift+Tab or `/mode Architect` is plan mode. `Master.turn` receives `mode=Architect` for that foreground turn. Allowed tools: `files` read/search, `web_search`, `web_fetch`, `kb_read`, `skill`, `ask_user`. The only write is `files` write to workspace-root `plan.md`. Any other tool returns `architect mode forbids this tool; write only plan.md` and does not raise a **card**. Background **task** turns stay Code. `config/models.yaml` `prompts.architect` is appended to the system prompt. Architect is chat, not a **loop**.

**Plan approval.** After an Architect turn that writes `plan.md`, the CLI upserts `data/plans/<id>.json` (`waiting_approval`; not L2; never recalled as facts) and prints a line-numbered plan viewer in the transcript: action row `a approve | s request changes | c comment | q quit plan`, then `◆ Waiting on plan approval`. The turn is already **idle**. The composer legend becomes `plan approval`. Empty-buffer keys: `a` approve, `s` request changes, `c` comment, `q` quit; Tab lets the next keys type instead of firing those actions. Typed text while waiting is a comment. Exact `a`/`s`/`c`/`q` (or the composer tokens) are the same actions when the composer cannot bind keys. Plan approval is not a permission **card** and does not wait on `Gate`.

- `a` — status `approved`, mode Code, one execute turn with the plan body in context (rings still apply).
- `s` / `c` — collect feedback, stay Architect, next turn revises `plan.md`.
- `q` — status `discarded`, leave plan approval, do not execute.

`/plan <id>` on a waiting plan restores `a`/`s`/`c`/`q`. `/new` clears the waiting composer and does not discard the file. Milestone **resume** in `brain/planner.py` is execution after approve, not this UI.

**Cards.** A **card** raised during a foreground turn asks `y` allow / `n` deny inline (the main prompt is not up, so `/approve` would deadlock). `/approve` and `/deny` remain for background **tasks** and for anyone who skipped the inline prompt. Ring 0–1 tools still run silent. A **card** on a voice-originated turn is also spoken; the next utterance `yes` / `no` resolves it.

**Voice.** `python main.py --cli --voice` (or `voice.yaml` `enabled: true`) starts `VoiceIO` beside the composer and, unless `orb.enabled` is false, the bottom-center orb. `/listen` is push-to-talk: record until Enter, STT, then the same foreground `Master.turn` as typed text. `/listen <text>` skips the mic. Orb click and the YAML hotkey call `VoiceIO.toggle_listen`: record until a second click or energy-VAD silence (`vad.engine: energy`), then the same turn path. A click while TTS plays cancels playback (does not start a new capture). Replies are spoken. Mic frames drop while TTS plays. The orb uses ElevenLabs `agentState` idle / listening / thinking / talking; listening volume follows `mic.amplitude`, talking volume follows `tts.amplitude`. `[speaking]` prints while `tts.amplitude` is non-zero. Wake-word always-on waits on `wake_word.engine`. `/reload` re-reads `config/voice.yaml`. `/orb` hides or shows the overlay.

**Sessions.** `data/sessions/<id>.json` stores CLI `history` (the same list `Master` uses) plus title, mode, timestamps. L2 is still the audit log; session files are not facts and are never recalled as facts. `/new` (alias `/reset`) writes the current session if it has turns, clears the screen, starts a blank conversation, and reprints the banner with the new session id. `/resume` with no argument opens a picker of recent sessions; `/resume <id>` loads that session. After a load, the CLI clears the screen, reprints the banner, and replays saved `history` so the window shows the past conversation. `/sessions` lists without switching. `/rename <title>` sets the title. Auto-save on `idle`. `/clear` only clears the screen and reprints the banner.

**Skills as slash commands.** A loaded skill with `user-invocable` true (default) runs as `/<name> [args]`. `/skill <name> [args]` is the same. Built-in commands keep the bare name; a colliding skill is `/skill:<name>`. The invocation is a foreground turn: skill body plus the user's arguments. `/skills` lists. Unknown `/foo` is not sent to the model.

### Clarify-first

`config/kernel.yaml` `clarify` (default true) scores each chat turn with `fast` before master. Prompt: `config/models.yaml` `prompts.clarify`. Default is act, not ask. Do not ask every turn.

- Input: current user text plus the last 3 foreground `history` turns. No tools on the scorer.
- Default is `clear`. Underspecified is not unclear. Friday already has `files`, `shell`, `browser`, `computer`, `web_search`, `web_fetch`, `skill`, and kb tools.
- `unclear` is rare: Friday cannot start without a user choice among 2 or more mutually exclusive next actions, and no safe default exists (which person, which of two named apps, which of two existing folders). Architecture, stack, library, style, how to implement, omitted path, research, review, and follow-ups are `clear` or `trivial`. An omitted path is the working directory. "Look up X" / "research Y" is **clear**.
- `unclear` asks at most 3 questions, writes them to L2 and `history`, and returns without master. The next foreground user turn skips the scorer and runs master with that `history`.
- `trivial` appends `[assumption]` and continues to master. `clear` continues.
- Mid-turn `ask_user` uses the same bar. Do not use it to pick a stack, confirm a plan, or ask follow-ups after finishing. Operator **stuck** (two failed verifications) still asks with evidence.
- Background **task** turns still score; they neither set nor consume the skip, and they do not receive CLI `history`.

### Permission rings

| Ring | Scope | Gate |
|---|---|---|
| 0 | reads: screen, files, web fetch | silent |
| 1 | app launch, writes in approved roots, browser actions | silent, logged |
| 2 | shell outside allowlist, installs, `computer` on an app not on `operator.allowlist` | **card**, scoped grants allowed |
| 3 | deletes above threshold, purchases, sends, credentials | explicit confirm, no scope grants |

Chat tools and their default rings (`config/permissions.yaml`). Unknown names are ring 2.

| Tool | Ring | Role |
|---|---|---|
| `files` read/search | 0 | sandbox inside approved roots |
| `web_search` | 0 | Query a search provider → numbered `{n, title, url, domain, snippet}`, wrapped **untrusted**. Default provider is DuckDuckGo HTML (no key). Optional args: `site`, `max_results`. A DuckDuckGo interstitial (HTTP 202, `anomaly-modal`) is **blocked**, not empty results; then `web.fallback` runs if configured. |
| `web_fetch` | 0 | HTTP GET `http:`/`https:` only; block localhost and private IPs (127/10/172.16–31/192.168); HTML extracted to text (headings, lists, code kept); optional `pattern` returns matching slices; wrapped **untrusted**; truncated to `tool_result_max_chars` |
| `skill` | 0 | return a SKILL.md body by name |
| `spawn_task` / `kb_read` | 0 | |
| `files` write / `browser` / `kb_propose` / `kb_consolidate` | 1 | |
| `computer` allowlisted app, or `see` / `snapshot` / `list_windows` | 1 | silent launch / screen read |
| `computer` app not on `operator.allowlist` | 2 | **card**. Approval grants that app name for this process only; it does not write `permissions.yaml`. Put the app in the YAML allowlist when it should stay silent after restart. |
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

`models.yaml` `prompts.master` teaches tool choice (files vs `web_search`/`web_fetch` vs `browser` vs `computer` vs `shell` vs `skill`) and forbids claiming success without a tool result. `ask_user` is only a fork with no default, not every turn. `prompts.architect` is appended in Architect (inspect, write only `plan.md`, stop). `prompts.clarify` lists the same tools; default is **clear**; `unclear` is a rare fork with no default. Research asks are **clear**.

OpenAI-compatible chat fills `tool_call` ids when the model omitted them, and sends empty assistant `content` as null. If the provider errors after a tool result (404/400 — common on some OpenRouter `:free` Nvidia endpoints that accept the first tool call then reject `role=tool`), master retries once with tools flattened to text so the turn still answers.

`permissions.yaml` `web:` (`search_ring`, `fetch_ring`, `search_max_results`, `fetch_timeout_seconds`, `user_agent`, `provider` (`duckduckgo` default), `fallback` (optional `brave`), `brave_api_key_env`). DuckDuckGo HTML needs no API key. Brave needs `BRAVE_API_KEY` in `.env` (scrubbed). Fallback is a no-op without the key.

`kernel.yaml`: `concurrent_slots`, `max_tool_steps` (chat tool-loop cap, 16), `clarify`, `tool_result_max_chars`, `skills_dir`.

`memory.yaml`: `stage` (0/1/2), `recall_limit`, `consolidate_episode_limit`, `max_proposals_per_pass`, `librarian_fail_stuck`. Stage 2 stays locked until the Phase 6 eval unlocks it.

`voice.yaml`: `enabled`, `mode` (`local` | `cloud` | `realtime`), `latency_budget_ms.wake_to_first_audio`, `latency_budget_ms.barge_in_frame_ms`, `wake_word.engine` (`none` | `openwakeword` | `porcupine`), `wake_word.model`, `wake_word.threshold`, `hotkey`, `mic_device`, `stt.engine` (`fake` | `faster-whisper` | `groq` | `parakeet-sherpa`), `stt.model`, `stt.language`, `stt.api_key_env`, `tts.engine` (`fake` | `kokoro` | `piper`), `tts.voice`, `tts.model`, `tts.voices`, `tts.piper_voice`, `vad.engine` (`none` | `energy` | `silero`), `vad.stop_secs`, `vad.threshold`, `turn` (`off` | `smart_turn_v3`), `amplitude_fps`, `sample_rate`, `orb.enabled`, `orb.size`. Capture is WASAPI shared, never exclusive. A schema change updates this section in the same commit.

### Later (specified, not this tree)

Tauri desktop (later Phase 5): main window + action feed. The Python orb in `orb/` is slice 1 (this tree) and already subscribes to `agent.state`, `tool.call`, `approval.request`, `tts.amplitude`, `mic.amplitude`. Cards already have a payload. The CLI is one client; the orb is another; Tauri is a later client. The overlay never owns the mic.

Typed sub-agents: `spawn_task` stays. A later `spawn_subagent(role, prompt)` (depth 1, isolated history, schema `{status, result, artifacts[]}`) waits until `files` can be capability-gated. Not a swarm.

Markdown command templates (`$ARGUMENTS`) wait; skills-as-slash is enough. Builtins own `/name`; colliding skills are `/skill:name`.
