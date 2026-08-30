"""Unit tests for procedural memory skill loader and parser."""

from __future__ import annotations

from pathlib import Path
import pytest

from brain.skills import (
    Skill,
    find_skill,
    format_skill_turn,
    format_skills_for_prompt,
    load_skills,
    parse_skill_file,
)


def test_parse_skill_with_frontmatter(tmp_path: Path):
    skill_dir = tmp_path / "deploy-app"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: deploy-app
description: Deploys the application to staging or production.
allowed-tools:
  - shell
  - files
---

# Deploy App Instructions
Run docker build and deploy.
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_file, source="Global")
    assert skill is not None
    assert skill.name == "deploy-app"
    assert skill.description == "Deploys the application to staging or production."
    assert skill.source == "Global"
    assert skill.allowed_tools == ["shell", "files"]
    assert skill.user_invocable is True
    assert "Run docker build" in skill.content


def test_parse_skill_without_frontmatter(tmp_path: Path):
    skill_dir = tmp_path / "format-code"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """# Code Formatter
Runs ruff and black across the entire codebase to maintain consistency.

Details here.
""",
        encoding="utf-8",
    )

    skill = parse_skill_file(skill_file, source="Workspace")
    assert skill is not None
    assert skill.name == "format-code"
    assert "Runs ruff and black" in skill.description
    assert skill.source == "Workspace"


def test_load_skills_hierarchy_and_override(tmp_path: Path):
    global_dir = tmp_path / "global_skills"
    workspace_dir = tmp_path / "workspace"

    # Global skill 1
    s1_dir = global_dir / "test-runner"
    s1_dir.mkdir(parents=True)
    (s1_dir / "SKILL.md").write_text(
        "---\nname: test-runner\ndescription: Global test runner\n---\nProcedure",
        encoding="utf-8",
    )

    # Global skill 2
    s2_dir = global_dir / "linter"
    s2_dir.mkdir(parents=True)
    (s2_dir / "SKILL.md").write_text(
        "---\nname: linter\ndescription: Global linter\n---\nProcedure",
        encoding="utf-8",
    )

    # Workspace skill (overriding test-runner)
    ws_s1_dir = workspace_dir / "skills" / "test-runner"
    ws_s1_dir.mkdir(parents=True)
    (ws_s1_dir / "SKILL.md").write_text(
        "---\nname: test-runner\ndescription: Workspace-specific pytest runner\n---\nWorkspace Procedure",
        encoding="utf-8",
    )

    skills = load_skills(root=workspace_dir, global_dir=global_dir)
    assert len(skills) == 2

    test_runner = find_skill("test-runner", skills)
    assert test_runner is not None
    assert test_runner.source == "Workspace"
    assert test_runner.description == "Workspace-specific pytest runner"

    linter = find_skill("linter", skills)
    assert linter is not None
    assert linter.source == "Global"


def test_format_skills_for_prompt():
    skills = [
        Skill(name="alpha", description="Alpha skill", path=Path("/a"), source="Global"),
        Skill(name="beta", description="Beta skill", path=Path("/b"), source="Workspace"),
    ]
    prompt_block = format_skills_for_prompt(skills)
    assert "Available procedural skills:" in prompt_block
    assert "- **alpha** (Global): Alpha skill" in prompt_block
    assert "- **beta** (Workspace): Beta skill" in prompt_block


def test_parse_skill_user_invocable_false(tmp_path: Path):
    skill_dir = tmp_path / "internal"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: internal\ndescription: Hidden from slash\nuser-invocable: false\n---\nBody\n",
        encoding="utf-8",
    )
    skill = parse_skill_file(skill_dir / "SKILL.md")
    assert skill is not None
    assert skill.user_invocable is False


def test_format_skill_turn():
    skill = Skill(name="commit", description="Commit", path=Path("/c"), content="Write a commit.")
    text = format_skill_turn(skill, "fix the build")
    assert text.startswith("[skill:commit]")
    assert "Write a commit." in text
    assert "User request: fix the build" in text
    bare = format_skill_turn(skill, "")
    assert "Follow the skill instructions." in bare
