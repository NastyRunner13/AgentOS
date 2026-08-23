# AgentOS — "Friday"

A resident desktop AI agent for Windows: wake-word voice loop, model-agnostic multi-agent
brain, layered knowledge base, MCP integration, vision-driven computer control, and a
self-hosted phone/dashboard interface.

One Python kernel process owns an asyncio event bus. Clients (desktop app, orb overlay,
phone PWA, CLI) and the voice stack hang off that bus. A master agent clarifies ambiguous
requests, wraps risky actions in approval cards, and delegates to sub-agents while you
keep working — long tasks run in the background and can be steered mid-flight.

## Highlights

- **Model-agnostic brain** — master/coder/fast/vision roles mapped to any provider
  (Anthropic, OpenAI, Ollama, OpenRouter) via `config/models.yaml`; swap with zero code changes.
- **Hybrid memory** — SQLite episodic log, vector recall, and an embedded graph (entities,
  facts, preferences), rolled out in eval-gated stages so memory never runs ahead of trust.
- **Self-created skills** — Friday distills successful multi-step tasks into reviewable
  `SKILL.md` procedures with success-rate tracking.
- **Verified computer control** — browser (Playwright DOM) first, Windows UIA second,
  screenshot Set-of-Marks last; every action verified before it counts as done.
- **Voice stack, all configurable** — openWakeWord → faster-whisper → Piper locally, cloud
  adapters optional, realtime mode included.
- **Surfaces** — Tauri desktop app with live action feed and approvals, an always-on orb
  overlay, and a phone PWA over Tailscale.
- **Safety rings 0–3** — every tool call passes a permission gate; risky actions wait on
  approval cards that expire to deny.

## Status

Design phase. The full system plan lives in [ARCHITECTURE.md](ARCHITECTURE.md); the phased
build sequence starts with the trustworthy core loop (kernel bus, model registry, master
agent, basic tools, episodic logging).

## Documentation

| Doc | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Single source of truth for *why* — system design, rationale, safety model |
| `AGENTARCH.md` | Agent-facing build & operate contract (build order, done-conditions, runtime rules) — kept untracked by [.gitignore](.gitignore) |

## Planned layout

```
AgentOS/
├─ config/        # models.yaml · voice.yaml · permissions.yaml · mcp_servers.json
├─ kernel/        # event bus, sessions, task manager, permission gate
├─ brain/         # model registry, master agent, sub-agent factory
├─ memory/        # sqlite events, vectors, kuzu graph, librarian
├─ voice/         # wakeword / stt / tts / realtime / vad
├─ tools/         # shell, files, apps, browser, computer_use
├─ mcp/           # MCP client manager
├─ server/        # FastAPI + WS gateway
├─ ui/            # shared React components
├─ desktop/       # Tauri 2 app: main window + orb overlay
├─ dashboard/     # phone PWA
├─ skills/        # SKILL.md library
└─ main.py        # entrypoint
```
