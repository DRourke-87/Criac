#!/bin/bash
# CriacBot — pull latest code and restart the bot
# Run on the server: bash scripts/deploy.sh
set -euo pipefail

REPO_DIR="$HOME/criacbot"
SERVICE="criacbot"

echo "==> Pulling latest code"
git -C "$REPO_DIR" pull

echo "==> Updating Python dependencies"
"$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"

echo "==> Restarting service"
sudo systemctl restart "$SERVICE"

echo "==> Status"
sudo systemctl status "$SERVICE" --no-pager
