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

# Install Doppler CLI
curl -sLf --retry 3 --tlsv1.2 --proto "=https" "https://cli.doppler.com/install.sh" | sh

# Pull secrets from Doppler and write them to the Claude env file
if [ -n "${DOPPLER_TOKEN_CANDY_DESCRIPTIONS:-}" ]; then
  DOPPLER_TOKEN="$DOPPLER_TOKEN_CANDY_DESCRIPTIONS" doppler secrets download --no-file --format env \
    | while IFS= read -r line; do
        echo "export $line" >> "$CLAUDE_ENV_FILE"
      done
fi
