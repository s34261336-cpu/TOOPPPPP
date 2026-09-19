---
name: Python uv projects
description: Runtime and post-merge expectations for this imported Python application.
---

Use `uv sync --frozen` before starting this project with `uv run --no-sync`; skipping the sync leaves runtime imports unavailable in the Replit environment.

**Why:** The app is Python/uv-based while the inherited workspace template included Node/Drizzle setup commands that do not apply to this project.

**How to apply:** Keep the workflow and post-merge setup aligned with `pyproject.toml` and `uv.lock`, and avoid restoring the old Node database command.

In this artifact workspace, a healthy legacy Python workflow can answer `200` on its bound port while the shared root proxy still returns `404`; do not enter a restart loop when logs show `0.0.0.0:5000` and direct health checks pass.

**Why:** The application is not registered as a path-routed artifact, so proxy forwarding can be separate from the process health.

**How to apply:** Verify the workflow logs and direct local port first; treat repeated proxy-only `404` responses as routing configuration/platform state rather than an application crash.