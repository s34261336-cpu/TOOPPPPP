#!/bin/bash
set -e

# The imported app is Python/uv-based; keep post-merge setup aligned with it.
# The previous Node/Drizzle command referenced a database package this app does
# not use and made otherwise successful Git merges fail during setup.
uv sync --frozen
