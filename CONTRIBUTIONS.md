# Contributing to AgentOS

How a patch lands. [AGENTS.md](AGENTS.md) is the coding-agent operating manual. This file is the bar a change has to clear before it is committed.

Leading words (**verified**, **card**, **ring**, **loop**, **resume**, **charter**, **node**, **edge**, **stuck**, **untrusted**, **earned**, **steer**) mean what [AGENTARCH.md](AGENTARCH.md) says. Use them as tokens.

## Spec first

1. Behavior lives in [AGENTARCH.md](AGENTARCH.md). Edit the contract, then the code. A code change that contradicts AGENTARCH is a bug in the patch, not a silent rewrite of the contract.
2. Open [PRINCIPLES.md](PRINCIPLES.md) before adding a **loop**, a **node**, a skill, a schedule, a verifier, a memory write path, or anything that runs while the user is away.
3. [ARCHITECTURE.md](ARCHITECTURE.md) is rationale only. Do not treat it as a behavior spec.
4. Prefer a `config/` YAML diff when the schema already exists. If you change a config schema, update the matching AGENTARCH section in the same commit.

## Local loop

Python 3.11+. From the repo root:

```
pip install -e ".[dev]"
python -m pytest -q
python main.py --cli
python main.py --eval
```

Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` (or retarget `config/models.yaml`). Tests use `FakeAdapter` and do not need keys.

`/reload` in the CLI rereads `config/*.yaml` without a process restart.

## What to change, by kind

| Kind of change | Where it goes |
|---|---|
| Model id, prompt, provider | `config/models.yaml` |
| **Ring**, allowlist, **card** expiry, operator apps | `config/permissions.yaml` |
| Slots, tool-step cap, clarify | `config/kernel.yaml` |
| Memory **consolidate** stage and limits | `config/memory.yaml` (`stage` stays 0 or 1) |
| Bus, tasks, **steer**, **card** wait | `kernel/` |
| Registry, master, librarian | `brain/` |
| L2 log, proposals, graph apply | `memory/` (`INSERT` into `facts`/`entities`/`edges` only inside `_apply` in `memory/graph.py`) |
| Shell, files, browser, computer | `tools/` |
| CLI renderer, slash menu, session files | `ui/` |
| Scenario suite | `evals/` |
| DONE WHEN coverage | `tests/test_phaseN.py` |

Directories named in ARCHITECTURE.md §11 that are still absent (`voice/`, `mcp/`, `server/`, `desktop/`, `dashboard/`, `skills/`, `workflows/`) — do not import them. Do not scaffold them as empty packages. `ui/` is the CLI surface (`python main.py --cli`).

## Tests

- Offline and fast. `python -m pytest -q` from the repo root. `pythonpath = ["."]` is set in `pyproject.toml`.
- Async tests need no `@pytest.mark.asyncio`. `asyncio_mode = "auto"`.
- Phase tests are the acceptance suite: `tests/test_phase1.py`, `tests/test_phase2.py`, `tests/test_phase3.py` map to AGENTARCH **DONE WHEN** clauses. A phase is complete or it is not.
- `tests/test_phase1.py` loads the real `config/permissions.yaml` and asserts `config/models.yaml` (`default_provider`, roles). Editing those files can fail that file.
- `tests/test_phase3.py::test_c_grep_no_automatic_graph_vector_writes` greps `STAGE 2 AUTO-CONSOLIDATE: LOCKED`, `config/memory.yaml` `stage` ∈ {0,1}, and `INSERT INTO facts|entities|edges` only inside `_apply` in `memory/graph.py`.
- A memory, skill, computer-use, or **loop** change ships with eval numbers: success %, latency, token cost, human interventions, cost per accepted outcome. `python main.py --eval` writes JSON under `evals/runs/` (gitignored).

## Adding a tool

1. Add the spec to `SPECS` in `tools/specs.py`.
2. Add an explicit `Gate.classify` case in `kernel/gate.py`. Unknown tools are ring 2 (**card** required). `tests/test_kernel.py::test_every_spec_has_explicit_ring` fails if the case is missing.
3. Dispatch it in `NativeTools.execute` (or the operator for `computer`).
4. Every turn and tool result writes to the episodic log (`memory.write`). L2 is the audit trail and a Phase 1 done-condition.

## Safety

- **Ring** 0–1 execute. Ring 2–3 wait on a **card**. Cards expire to deny.
- Screen, OCR, web, and unaudited skill text is **untrusted**. It may inform a decision. It does not trigger tools or change permissions.
- Secrets live in `.env`. Pass user text and tool errors through `Master.scrub`. Secrets never enter prompts, logs, or the episodic DB.
- Autonomy stays `suggest_only` until a Phase 6 eval **earned** a flip, and then only by an explicit config change.

## Memory

- `propose` / `kb_propose` / the librarian insert *proposals*. Graph rows land only in `Episodic.approve`.
- Recall injects confirmed, currently-valid facts. Never pending proposals. Never L2 turns as facts.
- Stage 2 auto-consolidate is locked. Do not set `AUTO_CONSOLIDATE_UNLOCKED = True`. Do not set `config/memory.yaml` `stage: 2`.
- CLI: `/approve <id>` resolves a **card** or a proposal. `/approve all` bulk-approves proposals. `/consolidate` runs the librarian.

## Commits

One concern per commit. A config schema change and its AGENTARCH section travel together.

Subject line: `area: what changed`, imperative, under 72 characters.

```
feat(kernel): wait on a card for ring-2 shell
fix(memory): recall skips facts with valid_to set
docs: lock stage-2 auto-consolidate in AGENTARCH
config: add notepad to the operator allowlist
test: cover stuck after two failed verifies
```

Areas that match the tree: `kernel`, `brain`, `memory`, `tools`, `evals`, `config`, `docs`, `test`. `feat` / `fix` / `docs` / `config` / `test` / `chore` are enough.

The body says why, and which **DONE WHEN** or PRINCIPLES rule it serves, when that is not obvious from the subject.

Do not commit `.env`, `data/`, `*.db`, `evals/runs/`, `__pycache__/`, or `*.egg-info/`.

## Review bar

A patch is ready when:

- AGENTARCH (and PRINCIPLES, if the change is a **loop** / **node** / unattended path) already describes the new behavior.
- `python -m pytest -q` passes from a fresh `pip install -e ".[dev]"`.
- New tools have an explicit **ring**.
- Graph writes still go only through `approve`.
- Secrets still cannot appear in L2.
- The maker does not mark its own work **verified**.

## What this repo is not yet

Phase 1–2 are implemented. Phase 3 is memory stage 1 (librarian proposals, confirmed-fact recall). Phase 1b (first **loop**) is specified, not shipped. Voice, surfaces, MCP, and **earned** autonomy wait on their phase gates. Nothing grants itself **earned** status.
