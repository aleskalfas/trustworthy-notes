#!/usr/bin/env bash
# One-command setup for the `tnotes` command on macOS / Linux.
#
#   bash scripts/bootstrap.sh
#
# Installs uv (if missing) and the `tnotes` command. Then, in a NEW terminal:
#   tnotes auth set-key
#   tnotes extract <pdf> --pages 14 --model claude-sonnet-4-6 --out data/notes
#
# This is all `tnotes` needs to be functional (the API-key path). `mise`/`ant` are
# only for the optional account-login path — see README.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "→ installing uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"   # so this script can use uv right away
fi

echo "→ installing the tnotes command…"
uv tool install --editable . --reinstall
uv tool update-shell || true

echo
echo "✓ Done. Open a NEW terminal (so PATH refreshes), then:"
echo "    tnotes auth set-key        # paste your Anthropic API key once"
echo "    tnotes extract \"<your.pdf>\" --pages 14 --model claude-sonnet-4-6 --out data/notes"
