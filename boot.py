"""Composition root: YAML → bus, gate, registry, master."""

from __future__ import annotations

import os
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


def collect_secrets(
    models_cfg: dict,
    perm_cfg: dict | None = None,
    voice_cfg: dict | None = None,
    env_path: Path | None = None,
) -> list[str]:
    found = []
    seen: set[str] = set()
    names: list[str] = []
    for pcfg in (models_cfg.get("providers") or {}).values():
        env = pcfg.get("api_key_env")
        if env:
            names.append(env)
    web = (perm_cfg or {}).get("web") or {}
    names.append(str(web.get("brave_api_key_env") or "BRAVE_API_KEY"))
    stt = (voice_cfg or {}).get("stt") or {}
    names.append(str(stt.get("api_key_env") or "GROQ_API_KEY"))
    names.extend(["GEMINI_API_KEY", "GOOGLE_API_KEY"])
    for env in names:
        val = os.environ.get(env)
        if val and val not in seen:
            seen.add(val)
            found.append(val)
    if env_path and env_path.is_file():
        from dotenv import dotenv_values

        for val in dotenv_values(env_path).values():
            if val and len(val) >= 4 and val not in seen:
                seen.add(val)
                found.append(val)
    return found


def boot(root: Path):
    load_dotenv(root / ".env")
    cfg_dir = root / "config"
    models_cfg = load_yaml(cfg_dir / "models.yaml")
    perm_cfg = load_yaml(cfg_dir / "permissions.yaml")
    kernel_cfg = load_yaml(cfg_dir / "kernel.yaml")
    mem_path = cfg_dir / "memory.yaml"
    mem_cfg = load_yaml(mem_path) if mem_path.is_file() else {}
    voice_path = cfg_dir / "voice.yaml"
    voice_cfg = load_yaml(voice_path) if voice_path.is_file() else {}
    bus = Bus()
    slots = int(kernel_cfg.get("concurrent_slots", 4))
    session_grants: set[str] = set()
    gate = Gate(perm_cfg, bus, session_grants=session_grants)
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
        session_grants=session_grants,
    )
    prompts = models_cfg.get("prompts") or {}
    custom_skills_dir = kernel_cfg.get("skills_dir")
    global_skills_dir = Path(custom_skills_dir).expanduser() if custom_skills_dir else None
    from brain.skills import load_skills

    skills = load_skills(root, global_dir=global_skills_dir)

    master = Master(
        registry,
        gate,
        tasks,
        memory,
        tools,
        bus,
        system_prompt=str(prompts.get("master") or "You are Friday."),
        clarify_prompt=str(prompts.get("clarify") or ""),
        architect_prompt=str(prompts.get("architect") or ""),
        clarify=bool(kernel_cfg.get("clarify", True)),
        max_tool_steps=int(kernel_cfg.get("max_tool_steps", 16)),
        secrets=collect_secrets(models_cfg, perm_cfg, voice_cfg, env_path=root / ".env"),
        skills=skills,
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
        "voice_cfg": voice_cfg,
        "skills": skills,
    }
