# AgentOS principles

How we build Friday so it stays a system we trust, including when it runs without us.

[ARCHITECTURE.md](ARCHITECTURE.md) is what the system is.
[AGENTARCH.md](AGENTARCH.md) is the phase, the contract, and the done-condition.

Open this file when adding a **loop**, a **node**, a skill, a schedule, a verifier, a memory write path, or anything that runs while the user is away.

Leading words (**verified**, **stuck**, **untrusted**, **earned**, **card**, **ring**, **steer**, **consolidate**, **loop**, **resume**, **charter**, **node**, **edge**) are defined in [AGENTARCH.md](AGENTARCH.md). This file uses them. It does not redefine them.

---

## Core

1. Ship a narrow path that works before adding breadth. Breadth sits on a path we already trust.
2. Assemble proven parts for wake word, STT, TTS, Playwright, embedded DBs, MCP. Write the kernel, the permissions, the memory stages, and the **loop**.
3. Every memory, skill, computer-use, and **loop** change ships with eval numbers: success rate, latency, cost, human interventions, cost per accepted outcome.
4. Every **loop**, operator, librarian, and miner has a fast path to "I'm wrong / I'm **stuck** → escalate or ask." Silent flailing is the bug.
5. Models, permissions, skills, MCP, and loop schedules live in git-friendly config. Rollback is a revert.

## Chat until the loop earns it

A **task** is one background shot the user can **steer**. A **loop** is a system that finds the work, prompts Friday, **verifies** the result, writes **resume**, and decides the next move.

The user designs the **loop**. Friday prompts from then on.

A **loop** earns its cost when all four hold:

1. The job recurs at least weekly. One-off work stays a chat.
2. Something independent can reject the output: test, build, lint, file exists, hash, window title, HTTP status, or `fast` scoring a stated goal. The maker's summary is not this signal.
3. Friday can run and observe what it changed (the operator's **verified** path, a shell, a browser).
4. The **loop** has a hard stop: token cap, iteration cap, or wall clock. Irreversible actions still need a **card**.

Voice, "open Spotify", one research question, architecture, auth, payments, and anything where "done" is a judgment call stay a chat.

First loops that fit: nightly Downloads or receipt triage, calendar briefing, CI failure draft, lint-and-fix on a repo with tests, "watch this folder until the PDF lands."

## Smallest loop, in this order

1. One manual chat run that already works.
2. One skill so the next run does not re-derive the procedure.
3. One **resume** file so tomorrow continues.
4. One **verified** signal that can fail the work.
5. Then schedule it (cadence), bind it to a goal, or hang it on an event.

Four parts, no swarm: one automation, one skill, one **resume**, one **verified** signal. Overnight output is a ring 0–1 draft (proposed file, draft PR, briefing). Ring 2–3 wait on a **card**. The user reads the overnight digest.

## Maker never accepts

The agent that produced the work does not mark it **verified**.

A checker is a different prompt, often `fast`, with no view of the maker's chain of thought. Prefer a machine signal (test, file, HTTP) over a second LLM. A second LLM with no machine signal is two opinions.

Three checker patterns, used where they pay (research claims, generated code, skill promotion). They stay off "open Spotify":

- Adversarial: N skeptics try to kill a finding. Majority must fail to kill it.
- Lens-diverse: correctness, security, "does it reproduce" as separate checkers.
- Judge panel: several attempts, scored, synthesize from the winner.

False-done (the maker emits "done" on a half-finished job) is a **stuck**-class bug. A goal-loop condition is scored by `fast` or a machine check, not by the maker's last sentence.

## Work is a graph

A sequential tool loop is a valid **node** chain for a single chat. Multi-item work is a graph.

- A **node** is one bounded job. Input is passed in, never assumed from a shared window. Output is a schema. Validation retries at the tool layer.
- An **edge** exists only when data moves. Flatten, dedupe, and filter on an **edge** are code. They are not another model turn.
- Independent **nodes** run together. "Research these 5 laptops" is five researcher **nodes**, a code reduce, one synthesizer.
- Wait for every **node** (a barrier) only when the next stage needs the whole set: dedupe, rank, compare. Otherwise stream item by item.
- Fan-in tolerates a missing input. A dead worker returns null. The rest still merge.
- Isolate writers: git worktrees for repo work, separate working roots for parallel file jobs. Isolation is for concurrent writes, not a tax on every spawn.
- A cycle (unknown-size discovery, librarian mining) stops after K consecutive rounds with nothing new. Dedupe against everything already seen, including rejects, or the cycle rediscovers dead ends forever.
- Tier models per **node**: extractors and classifiers on `fast`, merge and adjudication on `master`, screenshots on `vision`. A fan-out that inherits `master` for every **node** is how the bill arrives first.
- Skills are procedures. Saved graphs (workflows) are coordinated **nodes**, versioned next to skills, launched by name, by chat, or by a **loop**.

The master may write an orchestration script for a job that cannot be planned in advance. Build one hand-drawn diamond that works before that.

## Three files a loop reads

| File | Job |
|---|---|
| **charter** | Where to go. User goals and hard constraints. Reread every run so summarization cannot drop "never do X." Distinct from the system prompt. |
| **resume** | Where we are. `done`, `next`, `rejected[]`, spend, last **verified** result. Distinct from L2. |
| L2 episodic | What happened. Audit. |

L1 is the session scratchpad. A **loop** that only has L1 restarts every run.

## Caps, skills, connectors

Every **loop** declares max iterations, max tokens, max wall-clock, and the highest **ring** it may touch unattended. Chat `max_tool_steps` is not this cap.

Skills are how a **loop** stops re-deriving context. Community skills are **untrusted** until a human reads the source. Install is a **card**. The autonomy dial stays `suggest_only` until that audit path exists.

Connectors (MCP) exist so a **loop** can act: open the PR, update the ticket, ping the channel, watch the filesystem. Rank them by whether the **loop** can finish the job in the real environment.

## Measure, then unlock

Tracked per **loop** run: success %, latency, token cost, human interventions, cost per accepted outcome. If fewer than half of outputs survive **verified** (or the user's review), the **loop** is creating review work.

Eval suite includes: a known-bad artifact the **verified** signal rejects; **resume** after process restart; false-done (maker claims complete, checker or test says no); fan-out with one dead worker still merging; the token cap killing a runaway.

**earned** still means eval numbers, including for scheduling a **loop** and for removing the operator allowlist.

The user still reads diffs and overnight summaries. The live action feed is necessary. It does not replace reading what Friday changed on the machine. Loops stay on small, machine-checkable jobs. The day we debug a desktop no one has read costs more than the tokens.

## Unattended Friday

A **loop** at 3am is an attack surface at 3am.

- Ring 2–3 always wait on a **card**. Unattended work produces drafts.
- Screen, OCR, web, and skill text stay **untrusted**.
- Long runs use quiet logging. Secrets stay out of L2.
- Loop permissions are re-audited on a calendar (30 days). A briefing **loop** that quietly gained `shell` is a regression.
- Skill install from the internet is a **card**, after a human reads the source.

## Order

Phase 1's chat loop is trusted first. Then one real **loop** (manual → skill → **resume** → **verified** → schedule) before swarms, before self-drawn graphs, before community skills, before Stage-2 memory, before full-desktop operator.

Judgment-call work stays in chat with the user in the chair.

## Before you merge a loop, node, or schedule

- The four conditions hold, or it stays a chat.
- Maker and checker are different.
- **resume** and **charter** exist. L2 is not standing in for them.
- Caps are declared.
- Ring 2–3 still emit a **card**.
- Eval covers the **verified** signal actually rejecting bad work.
- Independent **nodes** run together. Reduce is code.
