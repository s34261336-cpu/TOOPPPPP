---
name: Python uv projects
description: Runtime and post-merge expectations for this imported Python application.
---

Use `uv sync --frozen` before starting this project with `uv run --no-sync`; skipping the sync leaves runtime imports unavailable in the Replit environment.

**Why:** The app is Python/uv-based while the inherited workspace template included Node/Drizzle setup commands that do not apply to this project.

**How to apply:** Keep the workflow and post-merge setup aligned with `pyproject.toml` and `uv.lock`, and avoid restoring the old Node database command.