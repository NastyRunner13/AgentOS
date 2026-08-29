# AGENTS.md

Python 3.11+ desktop agent kernel ("Friday") for Windows. Phases 1–2 are implemented; Phase 3 is memory stage 1 (librarian proposals, confirmed-fact recall).

## Start here

- [AGENTARCH.md](AGENTARCH.md) — the working contract: build phases with DONE WHEN acceptance criteria, bus topics, permission rings, leading-word definitions. **Behavior changes are specified here first**, then implemented.
- [PRINCIPLES.md](PRINCIPLES.md) — mandatory before adding a **loop**, **node**, skill, schedule, verifier, memory write path, or anything unattended.
- [ARCHITECTURE.md](ARCHITECTURE.md) — design *rationale* only, not the behavior spec.
- [CONTRIBUTIONS.md](CONTRIBUTIONS.md) — how a patch lands: spec-first, tests, commit shape, review bar.
- Tokens (**verified**, **card**, **ring**, **loop**, **resume**, **charter**, **node**, **edge**, **stuck**, **untrusted**, **earned**, **steer**) have exact meanings in AGENTARCH.md — use them precisely in docs, prompts, and reviews.

## Commands

- Install dev deps: `pip install -e ".[dev]"`
- Tests (offline, fast): `python -m pytest -q`
- One test: `python -m pytest tests/test_phase1.py::test_c_ring2_shell_blocks_until_approved`
- App: `python main.py --cli` — the only entrypoint. `/reload` inside the CLI re-reads `config/*.yaml` without restart.
- No lint/typecheck config exists yet.

## Reality vs plan

- Existing packages: `kernel/` (bus, tasks, permission gate), `brain/` (registry, master, librarian), `memory/` (SQLite L2 + stage-1 graph/proposals), `tools/` (shell/files/browser/computer/kb_*), plus `config/` and `tests/`.
- Directories in ARCHITECTURE.md §11 (`voice/`, `mcp/`, `server/`, `ui/`, `desktop/`, `dashboard/`, `skills/`, `workflows/`) do **not** exist yet — don't import or build against them.

## Gotchas

- Adding a tool to `SPECS` in `tools/specs.py`: `Gate.classify` in `kernel/gate.py` returns ring 2 (card required) for unknown tools unless you add a case. `tests/test_kernel.py::test_every_spec_has_explicit_ring` fails if the case is missing.
- `tests/test_phase1.py` loads the real `config/permissions.yaml` and asserts `config/models.yaml` contents (default provider, roles). Editing those files can break tests.
- Graph writes happen only in `Episodic.approve`. `propose` / `kb_propose` / the librarian insert *proposals*. `tests/test_phase3.py::test_c_grep_no_automatic_graph_vector_writes` greps `STAGE 2 AUTO-CONSOLIDATE: LOCKED` in AGENTARCH.md, `config/memory.yaml` `stage` ∈ {0,1}, and `INSERT INTO facts|entities|edges` only inside `_apply` in `memory/graph.py`.
- Async tests need no `@pytest.mark.asyncio` — `asyncio_mode = "auto"` is set in pyproject.toml. Tests use `FakeAdapter` (scripted per model id); no API keys needed.
- Run pytest/python from the repo root — imports (`from kernel import ...`) rely on `pythonpath = ["."]`; `main.py` takes `--root` otherwise.
- `.env` loads from repo root; OpenRouter is the default provider (`OPENROUTER_API_KEY` in `.env.example`). Secrets never enter prompts, logs, or the episodic DB — pass user/error text through `Master.scrub`.
- Every turn and tool result must be written to the episodic log (`memory.write`) — L2 is the audit trail and a Phase 1 done-condition.
- Recall injects confirmed, currently-valid facts — never pending proposals, never L2 turns as facts. CLI: `/approve <id>` resolves a card or a memory proposal; `/approve all` bulk-approves proposals; `/consolidate` runs the librarian.
- Ship behavior changes as `config/` YAML diffs where possible; if a config schema changes, update the matching section of AGENTARCH.md in the same commit.
