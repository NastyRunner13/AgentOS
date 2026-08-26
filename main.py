"""Boot the kernel. `python main.py --cli` is the Phase 1 surface."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from brain.master import Master
from brain.registry import Registry
from kernel import Bus, Gate, TaskManager
from memory import Episodic
from tools import NativeTools
from tools.operator import Operator

ROOT = Path(__file__).resolve().parent


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def collect_secrets(models_cfg: dict) -> list[str]:
    found = []
    for pcfg in (models_cfg.get("providers") or {}).values():
        env = pcfg.get("api_key_env")
        if env and os.environ.get(env):
            found.append(os.environ[env])
    return found


def boot(root: Path):
    load_dotenv(root / ".env")
    cfg_dir = root / "config"
    models_cfg = load_yaml(cfg_dir / "models.yaml")
    perm_cfg = load_yaml(cfg_dir / "permissions.yaml")
    kernel_cfg = load_yaml(cfg_dir / "kernel.yaml")
    mem_path = cfg_dir / "memory.yaml"
    mem_cfg = load_yaml(mem_path) if mem_path.is_file() else {}
    bus = Bus()
    slots = int(kernel_cfg.get("concurrent_slots", 4))
    gate = Gate(perm_cfg, bus)
    tasks = TaskManager(bus, concurrent_slots=slots)
    registry = Registry(models_cfg)
    data_dir = root / str(kernel_cfg.get("data_dir", "data"))
    memory = Episodic(data_dir / "events.db", cfg=mem_cfg, bus=bus)
    tools = NativeTools(
        root,
        perm_cfg,
        max_chars=int(kernel_cfg.get("tool_result_max_chars", 8000)),
    )
    tools.operator = Operator(
        perm_cfg,
        bus,
        memory,
        root,
        registry=registry,
        tools=tools,
    )
    prompts = models_cfg.get("prompts") or {}
    master = Master(
        registry,
        gate,
        tasks,
        memory,
        tools,
        bus,
        system_prompt=str(prompts.get("master") or "You are Friday."),
        clarify_prompt=str(prompts.get("clarify") or ""),
        clarify=bool(kernel_cfg.get("clarify", True)),
        max_tool_steps=int(kernel_cfg.get("max_tool_steps", 8)),
        secrets=collect_secrets(models_cfg),
    )
    return {
        "root": root,
        "bus": bus,
        "gate": gate,
        "tasks": tasks,
        "registry": registry,
        "memory": memory,
        "master": master,
        "models_cfg": models_cfg,
        "perm_cfg": perm_cfg,
        "kernel_cfg": kernel_cfg,
        "mem_cfg": mem_cfg,
    }


HELP = """\
/help                  this list
/task <title> <prompt> background turn (steer-able)
/steer <id> <text>     inject into a running task
/approve <id> [id...]  allow a card or memory proposal
/approve all           bulk-approve pending memory proposals
/deny <id> [id...]     deny a card or memory proposal
/facts                 confirmed facts
/proposals             pending memory proposals
/consolidate           librarian draft (proposals only)
/tasks                 list tasks
/roles                 print model roles
/reload                reread YAML configs
/quit                  exit
"""


async def run_cli(root: Path) -> None:
    stack = boot(root)
    bus: Bus = stack["bus"]
    gate: Gate = stack["gate"]
    tasks: TaskManager = stack["tasks"]
    master: Master = stack["master"]

    async def watch(topic: str, handler) -> None:
        q = bus.subscribe(topic)
        while True:
            handler(await q.get())

    def on_state(ev: dict) -> None:
        if ev.get("phase") == "token":
            sys.stdout.write(ev.get("text") or "")
            sys.stdout.flush()
        elif ev.get("phase") == "stuck":
            sys.stdout.write(f"\n[stuck] {ev.get('question')}\n")
            sys.stdout.flush()
        elif ev.get("phase") == "idle":
            sys.stdout.write("\n")
            sys.stdout.flush()

    def on_card(ev: dict) -> None:
        sys.stdout.write(
            f"\n[card {ev.get('id')}] ring {ev.get('ring')} {ev.get('action_preview')}\n"
            f"  {ev.get('reason')}  /approve {ev.get('id')}  |  /deny {ev.get('id')}\n"
        )
        sys.stdout.flush()

    def on_error(ev: dict) -> None:
        sys.stdout.write(f"\n[error] {ev.get('error')}\n")
        sys.stdout.flush()

    watchers = [
        asyncio.create_task(watch("agent.state", on_state)),
        asyncio.create_task(watch("approval.request", on_card)),
        asyncio.create_task(watch("error", on_error)),
    ]

    print("Friday CLI. /help for commands.")
    try:
        while True:
            line = await asyncio.to_thread(input, "Friday> ")
            line = line.strip()
            if not line:
                continue
            if line in ("/quit", "/exit"):
                break
            if line == "/help":
                print(HELP)
                continue
            if line == "/roles":
                print(stack["registry"].cfg.get("roles"))
                continue
            if line == "/tasks":
                for t in stack["tasks"].tasks.values():
                    print(f"  {t.id}  {t.status:16}  {t.title}")
                continue
            if line == "/reload":
                cfg_dir = root / "config"
                stack["registry"].cfg = load_yaml(cfg_dir / "models.yaml")
                stack["gate"].cfg = load_yaml(cfg_dir / "permissions.yaml")
                kcfg = load_yaml(cfg_dir / "kernel.yaml")
                master.clarify = bool(kcfg.get("clarify", True))
                master.max_tool_steps = int(kcfg.get("max_tool_steps", 8))
                prompts = stack["registry"].cfg.get("prompts") or {}
                master.system_prompt = str(prompts.get("master") or master.system_prompt)
                master.clarify_prompt = str(prompts.get("clarify") or master.clarify_prompt)
                master.secrets = collect_secrets(stack["registry"].cfg)
                mem_path = cfg_dir / "memory.yaml"
                if mem_path.is_file():
                    stack["memory"].cfg = load_yaml(mem_path)
                print("reloaded config/")
                continue
            if line == "/facts":
                facts = stack["memory"].valid_facts()
                if not facts:
                    print("(none)")
                for f in facts:
                    print(f"  {f['id']}  {f['statement']}")
                continue
            if line == "/proposals":
                pending = stack["memory"].pending()
                if not pending:
                    print("(none)")
                for p in pending:
                    payload = p["payload"]
                    preview = payload.get("statement") or payload.get("name") or payload
                    print(f"  {p['id']}  {p['kind']}  {preview}")
                continue
            if line == "/consolidate":
                from brain.librarian import draft

                result = await draft(stack["memory"], stack["registry"], bus)
                print(result)
                continue
            if line == "/approve all" or line == "/approve-all":
                applied = stack["memory"].approve_all()
                print(f"approved {len(applied)} proposals")
                continue
            if line.startswith("/approve "):
                ids = line.split(None, 1)[1].split()
                for cid in ids:
                    if gate.resolve(cid, True):
                        print(f"approved card {cid}")
                    elif stack["memory"].approve([cid]):
                        print(f"approved proposal {cid}")
                    else:
                        print(f"no such id {cid}")
                continue
            if line.startswith("/deny "):
                ids = line.split(None, 1)[1].split()
                for cid in ids:
                    if gate.resolve(cid, False):
                        print(f"denied card {cid}")
                    elif stack["memory"].reject([cid]):
                        print(f"rejected proposal {cid}")
                    else:
                        print(f"no such id {cid}")
                continue
            if line.startswith("/steer "):
                parts = line.split(None, 2)
                if len(parts) < 3:
                    print("usage: /steer <id> <text>")
                    continue
                try:
                    await tasks.steer(parts[1], parts[2])
                    print(f"steered {parts[1]}")
                except (KeyError, ValueError) as exc:
                    print(exc)
                continue
            if line.startswith("/task "):
                rest = line[6:].strip()
                title, _, prompt = rest.partition(" ")
                if not prompt:
                    print("usage: /task <title> <prompt>")
                    continue

                async def factory(task, prompt=prompt):
                    await master.turn(prompt, task=task)

                t = tasks.spawn(title, factory)
                print(f"task {t.id} queued")
                continue
            asyncio.create_task(master.turn(line))
    finally:
        for w in watchers:
            w.cancel()
        stack["memory"].close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentOS")
    parser.add_argument("--cli", action="store_true", help="interactive chat loop")
    parser.add_argument("--eval", action="store_true", help="run the Phase 2 eval suite")
    parser.add_argument("--root", default=str(ROOT), help="repo root (configs live in <root>/config)")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if args.eval:
        import json

        from evals.harness import run_suite

        path = asyncio.run(run_suite(root))
        summary = json.loads(path.read_text(encoding="utf-8"))
        print(path)
        print(
            f"success_pct={summary['success_pct']} latency_ms={summary['latency_ms']} "
            f"token_cost={summary['token_cost']} human_interventions={summary['human_interventions']} "
            f"cost_per_accepted_outcome={summary['cost_per_accepted_outcome']}"
        )
        return
    if args.cli:
        asyncio.run(run_cli(root))
        return
    parser.print_help()
    print("\nPhase 1 surface is the CLI: python main.py --cli")
    print("Phase 2 eval suite: python main.py --eval")


if __name__ == "__main__":
    main()
