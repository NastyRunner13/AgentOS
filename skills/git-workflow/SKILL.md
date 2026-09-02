---
name: git-workflow
description: Procedure for inspecting repository issues, creating branches, running builds, committing, and opening PRs.
allowed-tools:
  - shell
  - files
---

# Git & GitHub Autonomous Workflow

Use this skill when tasked with inspecting, modifying, and submitting code changes to a repository.

## 1. Context & Reproduction
1. If addressing an issue, run `gh issue view <id>` via `shell` to extract error traces, repro steps, and expectations.
2. Run `git status` and `git branch` to ensure the working tree is clean.
3. Check out a dedicated branch: `git checkout -b fix/<short-topic>`.

## 2. Minimal Diagnostic & Edit
1. Locate suspect files using `files(action="search", query="...")`.
2. Read the implementation and tests using `files(action="read", path="...")`.
3. Apply the minimal necessary fix using `files(action="write", path="...", content="...")`.

## 3. Verification Gate (Maker-Checker)
1. Run project test suite or build command (e.g. `pytest`, `npm test`, `cargo test`, or `grok build`).
2. If tests fail or compiler errors appear:
   - Do NOT mark work verified.
   - Read compiler diagnostics, apply corrections, and re-run.
   - If failing twice on the same error, halt with the error trace and ask for guidance.
3. Run `git diff` via `shell` to inspect all modifications and ensure zero stray files or secrets.

## 4. Commit & Publish
1. Stage modified files: `git add <files>`.
2. Commit with conventional commit message: `git commit -m "fix: <concise explanation>"`.
3. If requested by the user, push and create a PR via `gh pr create --fill`.
