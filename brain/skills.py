"""Procedural memory: Skill loader and parser for AgentOS.

Discovers skills from global directory (~/.agents/skills) and workspace skills/ directory.
Supports SKILL.md with YAML frontmatter or Markdown formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Any
import yaml


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str = "Global"  # "Global", "Workspace", "Custom"
    content: str = ""
    allowed_tools: list[str] = field(default_factory=list)


def parse_skill_file(skill_md_path: Path, source: str = "Global") -> Skill | None:
    """Parses a SKILL.md file with YAML frontmatter or Markdown format."""
    try:
        raw = skill_md_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    name = skill_md_path.parent.name
    description = "Custom agent skill"
    allowed_tools: list[str] = []
    content = raw

    # Check for YAML frontmatter: --- ... ---
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            content = parts[2].strip()
            try:
                fm = yaml.safe_load(fm_text) or {}
                if isinstance(fm, dict):
                    if fm.get("name"):
                        name = str(fm["name"]).strip()
                    if fm.get("description"):
                        description = str(fm["description"]).strip()
                    tools = fm.get("allowed-tools") or fm.get("allowed_tools")
                    if isinstance(tools, list):
                        allowed_tools = [str(t) for t in tools]
            except Exception:
                pass

    # Fallback to extracting first paragraph if description wasn't found in frontmatter
    if description == "Custom agent skill" and content:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        for line in lines:
            if line.startswith("#"):
                continue
            description = line[:140]
            break

    return Skill(
        name=name,
        description=description,
        path=skill_md_path,
        source=source,
        content=content,
        allowed_tools=allowed_tools,
    )


def load_skills(
    root: Path | None = None,
    custom_dirs: list[Path] | None = None,
    global_dir: Path | None = None,
) -> list[Skill]:
    """
    Discovers and loads skills from:
    1. Global directory (default: ~/.agents/skills or custom global_dir)
    2. Any custom directories provided
    3. Workspace directory (root / "skills" if root is provided)

    If skills with identical names exist, workspace skills override global skills.
    """
    skills_map: dict[str, Skill] = {}

    # 1. Global directory (~/.agents/skills)
    g_dir = global_dir or (Path.home() / ".agents" / "skills")
    if g_dir.is_dir():
        for p in sorted(g_dir.glob("*/SKILL.md")):
            skill = parse_skill_file(p, source="Global")
            if skill:
                skills_map[skill.name] = skill

    # 2. Custom dirs if provided
    if custom_dirs:
        for c_dir in custom_dirs:
            if c_dir.is_dir():
                for p in sorted(c_dir.glob("*/SKILL.md")):
                    skill = parse_skill_file(p, source="Custom")
                    if skill:
                        skills_map[skill.name] = skill

    # 3. Workspace directory (root / "skills")
    if root:
        ws_dir = root / "skills"
        if ws_dir.is_dir():
            for p in sorted(ws_dir.glob("*/SKILL.md")):
                skill = parse_skill_file(p, source="Workspace")
                if skill:
                    skills_map[skill.name] = skill

    return list(skills_map.values())


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """Formats skills as a concise markdown list for inclusion in system prompt."""
    if not skills:
        return ""
    lines = ["Available procedural skills:"]
    for s in skills:
        lines.append(f"- **{s.name}** ({s.source}): {s.description}")
    return "\n".join(lines)


def find_skill(name: str, skills: list[Skill]) -> Skill | None:
    """Finds a skill by name (case-insensitive)."""
    norm = name.strip().lower()
    for s in skills:
        if s.name.lower() == norm:
            return s
    return None
