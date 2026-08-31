"""Procedural memory: Skill loader and parser for AgentOS.

Discovers skills from global directory (~/.agents/skills) and workspace skills/ directory.
Supports SKILL.md with YAML frontmatter or Markdown formats.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import yaml


DESC_CAP = 200


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str = "Global"  # "Global", "Workspace", "Custom", "Project"
    content: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    user_invocable: bool = True
    disable_model_invocation: bool = False


def parse_skill_file(skill_md_path: Path, source: str = "Global") -> Skill | None:
    """Parses a SKILL.md file with YAML frontmatter or Markdown format."""
    try:
        raw = skill_md_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    name = skill_md_path.parent.name
    description = "Custom agent skill"
    allowed_tools: list[str] = []
    user_invocable = True
    disable_model_invocation = False
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
                    if "user-invocable" in fm:
                        user_invocable = bool(fm.get("user-invocable"))
                    elif "user_invocable" in fm:
                        user_invocable = bool(fm.get("user_invocable"))
                    if "disable-model-invocation" in fm:
                        disable_model_invocation = bool(fm.get("disable-model-invocation"))
                    elif "disable_model_invocation" in fm:
                        disable_model_invocation = bool(fm.get("disable_model_invocation"))
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
        user_invocable=user_invocable,
        disable_model_invocation=disable_model_invocation,
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
    3. `.agents/skills` walking from root up to the git root (nearest wins)
    4. Workspace directory (root / "skills") last on name collision
    """
    skills_map: dict[str, Skill] = {}

    def _ingest(folder: Path, source: str) -> None:
        if not folder.is_dir():
            return
        for p in sorted(folder.glob("*/SKILL.md")):
            skill = parse_skill_file(p, source=source)
            if skill:
                skills_map[skill.name] = skill

    g_dir = global_dir or (Path.home() / ".agents" / "skills")
    _ingest(g_dir, "Global")

    if custom_dirs:
        for c_dir in custom_dirs:
            _ingest(c_dir, "Custom")

    if root:
        for folder in _ancestor_skill_dirs(root):
            _ingest(folder, "Project")
        _ingest(root / "skills", "Workspace")

    return list(skills_map.values())


def _ancestor_skill_dirs(start: Path) -> list[Path]:
    """`.agents/skills` from git root (or start) down to start, so nearer wins."""
    try:
        start = start.resolve()
    except OSError:
        return []
    chain = [start, *start.parents]
    git_root = None
    for p in chain:
        if (p / ".git").exists():
            git_root = p
            break
    dirs: list[Path] = []
    for p in chain:
        dirs.append(p / ".agents" / "skills")
        if git_root is not None and p == git_root:
            break
        if git_root is None:
            break
    dirs.reverse()
    return dirs


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """Name + description + source only. Omits disable-model-invocation skills."""
    lines = ["Available procedural skills:"]
    shown = False
    for s in skills:
        if s.disable_model_invocation:
            continue
        desc = " ".join(s.description.split())
        if len(desc) > DESC_CAP:
            desc = desc[: DESC_CAP - 3] + "..."
        lines.append(f"- **{s.name}** ({s.source}): {desc}")
        shown = True
    return "\n".join(lines) if shown else ""


def find_skill(name: str, skills: list[Skill]) -> Skill | None:
    """Finds a skill by name (case-insensitive)."""
    norm = name.strip().lower()
    for s in skills:
        if s.name.lower() == norm:
            return s
    return None


def format_skill_turn(skill: Skill, args: str = "") -> str:
    """User-turn text that loads a skill body and the arguments after /name."""
    request = args.strip() or "Follow the skill instructions."
    return (
        f"[skill:{skill.name}]\n"
        "Follow this skill exactly.\n\n"
        f"{skill.content}\n\n"
        f"User request: {request}"
    )
