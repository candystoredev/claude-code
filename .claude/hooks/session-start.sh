#!/bin/bash
set -euo pipefail

# Only run in remote (web) environments
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR/shopify-handles-generator"

# Install Python dependencies
# --break-system-packages: needed in container environments
# --ignore-installed: avoids conflicts with debian-managed packages
pip install --break-system-packages --ignore-installed -r requirements.txt

# Install linter for code quality checks
pip install --break-system-packages ruff
