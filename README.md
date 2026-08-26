# AgentOS — Friday

A resident desktop AI agent for Windows. One Python kernel process owns an asyncio event bus. A **master** agent clarifies ambiguous requests, wraps risky actions in **cards**, and delegates while you keep working. Long work runs as background **tasks** you can **steer**.

Phases 1–2 are implemented. Phase 3 is memory stage 1 (librarian proposals, confirmed-fact recall). Voice, the Tauri desktop, and the phone PWA are specified, not built.

## Quick start

Python 3.11+. From the repo root:

```
pip install -e ".[dev]"
copy .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env`. OpenRouter is the default provider. Swap any role in `config/models.yaml` without touching code.

```
python main.py --cli
python -m pytest -q
python main.py --eval
```

Inside the CLI, `/help` lists commands. `/reload` rereads `config/*.yaml` without a restart. `/approve <id>` resolves a **card** or a memory proposal.

## What works today

- Kernel event bus, concurrent **tasks**, mid-flight **steer**
- Permission **rings** 0–3 and expiring **cards** (ring 2+ waits)
- Model registry: OpenRouter / OpenAI / Anthropic / Ollama, roles `master` / `fast` / `vision` / `embeddings`
- Native tools: PowerShell, sandboxed files, Playwright browser
- Computer operator: UIA/a11y first, Set-of-Marks last, **verified** after every action, **stuck → ask**
- SQLite L2 episodic log (audit trail) plus stage-1 graph proposals
- Librarian drafts facts/entities/edges. Graph apply only after `/approve`
- Eval harness: `python main.py --eval` writes `{success%, latency, token cost, human interventions, cost per accepted outcome}`

## Documentation

| Doc | Open it when |
|---|---|
| [AGENTARCH.md](AGENTARCH.md) | Changing behavior. Phases, **DONE WHEN**, bus topics, **rings**, leading words. |
| [PRINCIPLES.md](PRINCIPLES.md) | Adding a **loop**, a **node**, a skill, a schedule, a verifier, a memory write path, or anything unattended. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Changing design rationale. Not the behavior spec. |
| [AGENTS.md](AGENTS.md) | Working in this tree as a coding agent. Commands, gotchas, reality vs plan. |
| [CONTRIBUTIONS.md](CONTRIBUTIONS.md) | Landing a patch: spec-first, tests, commit shape, review bar. |

## Layout

```
config/     models.yaml  permissions.yaml  kernel.yaml  memory.yaml
kernel/     bus, tasks, steer, permission gate
brain/      registry, master, librarian
memory/     SQLite L2 + stage-1 graph / proposals
tools/      shell, files, browser, computer
evals/      Phase 2 scenario suite
tests/      kernel, tools, master, phase 1–3 DONE WHEN
main.py     --cli  |  --eval
```

Directories named in ARCHITECTURE.md §11 (`voice/`, `mcp/`, `server/`, `ui/`, `desktop/`, `dashboard/`, `skills/`, `workflows/`) are not in the tree yet.
