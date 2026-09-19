---
name: Legacy import preview routing
description: Imported non-artifact web apps can run correctly while the shared artifact proxy has no root route.
---

Imported legacy web apps should be verified both through their workflow port and through the shared preview route; a healthy local response does not guarantee that the artifact proxy has a root mapping.

**Why:** The workspace may retain artifact-based routing while the imported repository uses a traditional `.replit` workflow.

**How to apply:** Prefer the repository's existing workflow and port for import work. Treat a proxy 404 as a routing/configuration issue, not an application failure, until the workflow port and logs are checked.