---
name: Project import transition
description: Imported repositories can need reconciliation after moving a conversation into a persistent Replit project.
---

After a conversation is moved into a persistent project, verify that the imported repository is the project root rather than only a preserved copy under the conversation-workspace files area.

**Why:** The project handoff can retain a starter workspace alongside the imported repository, which makes Git appear clean while the visible root is not the user's app.

**How to apply:** Compare the root against the imported repository, restore the imported Git metadata and remote, exclude only system-owned transition folders, then validate status and the app workflow.