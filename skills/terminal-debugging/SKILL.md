---
name: terminal-debugging
description: Protocol for diagnosing compilation errors, build failures, and runtime crashes using terminal and build tools.
allowed-tools:
  - shell
  - files
---

# Terminal Debugging & Build Recovery Procedure

Use this skill when encountering broken builds, syntax errors, or test failures.

## 1. Clean Diagnostics
1. Execute the build/run command via `shell` (e.g., `npm run build`, `cargo check`, `pytest -q`, or custom build runner).
2. Capture the full error log, specifically the first error and stack trace.
3. Identify the exact file, line number, and error type.

## 2. Root Cause Analysis
1. Read the failing source file and surrounding context: `files(action="read", path="...")`.
2. Inspect imported definitions, types, or recent git diffs (`git diff HEAD~1`).
3. Formulate a minimal hypotheses for why the failure occurred.

## 3. Atomic Patch Application
1. Apply targeted edits using `files(action="write")`.
2. Avoid changing unrelated logic or formatting.

## 4. Independent Verification
1. Re-run the exact build or test command that failed earlier.
2. If exit code == 0, mark milestone verified.
3. If failure repeats 2 times with no progress, invoke the stuck protocol with the full error diff.
