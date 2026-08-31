"""Unit tests for procedural memory skill loader and parser."""

from __future__ import annotations

from pathlib import Path
import pytest

from brain.skills import (
    DESC_CAP,
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


def test_load_skills_ancestor_agents_override(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    root_skill = tmp_path / ".agents" / "skills" / "shared"
    root_skill.mkdir(parents=True)
    (root_skill / "SKILL.md").write_text(
        "---\nname: shared\ndescription: from git root\n---\nROOT BODY\n",
        encoding="utf-8",
    )
    only_root = tmp_path / ".agents" / "skills" / "only-root"
    only_root.mkdir(parents=True)
    (only_root / "SKILL.md").write_text(
        "---\nname: only-root\ndescription: only at git root\n---\nX\n",
        encoding="utf-8",
    )
    project = tmp_path / "app"
    project.mkdir()
    child = project / ".agents" / "skills" / "shared"
    child.mkdir(parents=True)
    (child / "SKILL.md").write_text(
        "---\nname: shared\ndescription: from project\n---\nPROJECT BODY\n",
        encoding="utf-8",
    )
    skills = load_skills(root=project, global_dir=tmp_path / "no-global")
    shared = find_skill("shared", skills)
    assert shared is not None
    assert shared.source == "Project"
    assert shared.description == "from project"
    assert "PROJECT BODY" in shared.content
    assert find_skill("only-root", skills) is not None


def test_catalog_omits_body_and_caps_description():
    long = "x" * 300
    skills = [
        Skill(
            name="alpha",
            description=long,
            path=Path("/a"),
            source="Global",
            content="SECRET BODY PROCEDURE",
        ),
        Skill(
            name="hidden",
            description="should not appear",
            path=Path("/h"),
            disable_model_invocation=True,
            content="hidden body",
        ),
    ]
    block = format_skills_for_prompt(skills)
    assert "SECRET BODY PROCEDURE" not in block
    assert "hidden" not in block
    assert "should not appear" not in block
    alpha = next(line for line in block.splitlines() if "alpha" in line)
    assert "..." in alpha
    assert len(alpha) < 80 + DESC_CAP


def test_parse_disable_model_invocation(tmp_path: Path):
    skill_dir = tmp_path / "internal"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: internal\ndescription: Hidden from catalog\n"
        "disable-model-invocation: true\n---\nBody\n",
        encoding="utf-8",
    )
    skill = parse_skill_file(skill_dir / "SKILL.md")
    assert skill is not None
    assert skill.disable_model_invocation is True
