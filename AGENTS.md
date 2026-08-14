# IconLabs Repository Instructions

This repository is the IconLabs project. GitHub is the canonical source of truth for the codebase; local files and prior Codex conversations are not substitutes for the current GitHub state.

## Before Editing

Before making any code change:

1. Check the current branch with `git branch --show-current`.
2. Check the working tree with `git status`.
3. Fetch origin and verify whether the local branch is behind `origin/main`.
4. Never begin editing from a stale checkout. If `origin/main` contains newer work, pull or otherwise safely synchronize before editing.

Do not overwrite, reset, or discard uncommitted work. If local changes prevent a safe sync, preserve them and resolve the situation deliberately before continuing.

## Multi-PC Safety

- Never make overlapping changes to the same branch from two PCs at the same time.
- Only one PC should actively modify `main` at a time.
- Do not assume prior Codex chats, local notes, or uncommitted files are available on another computer.
- The next PC must pull the latest GitHub state before editing.
- Use a feature branch when work may overlap or when `main` cannot be handed off cleanly.

## Handoff Requirements

Before handing work to another PC:

1. Finish the intended work.
2. Run the relevant tests and checks.
3. Review the diff and confirm no secrets or local runtime artifacts are included.
4. Commit the changes.
5. Push the commit to GitHub.
6. Confirm the remote branch contains the pushed commit.

Do not leave important production changes only as uncommitted local files. Do not deploy directly from local-only, uncommitted changes. If production deploys from `main`, push the reviewed commit and let the established GitHub integration deploy it.

## Project Integrity

- Preserve the existing IconLabs architecture, behavior, design system, and tests unless the task explicitly requires a change.
- Work with existing uncommitted changes instead of reverting unrelated user work.
- Run focused tests while developing and the appropriate broader checks before handoff.
- Keep secrets, local databases, generated QA files, logs, and machine-specific configuration out of Git.

