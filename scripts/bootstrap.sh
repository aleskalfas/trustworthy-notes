#!/usr/bin/env bash
# One-command setup for the `tn` command on macOS / Linux.
#
#   bash scripts/bootstrap.sh
#
# Installs uv (if missing) and the `tn` command. Then, in a NEW terminal:
#   tn auth set-key
#   tn extract <pdf> --pages 14 --model claude-sonnet-4-6 --out data/notes
#
# This is all `tn` needs to be functional (the API-key path). `mise`/`ant` are
# only for the optional account-login path — see README.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "→ installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"   # so this script can use uv right away
fi

echo "→ installing the tn command…"
uv tool install --editable . --reinstall
uv tool update-shell || true

echo
echo "✓ Done. Open a NEW terminal (so PATH refreshes), then:"
echo "    tn auth set-key        # paste your Anthropic API key once"
echo "    tn extract \"<your.pdf>\" --pages 14 --model claude-sonnet-4-6 --out data/notes"
