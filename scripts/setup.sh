#!/bin/bash
# CriacBot — one-shot server setup for Ubuntu 22.04 (Oracle Cloud ARM)
# Run as the ubuntu user: bash setup.sh
set -euo pipefail

REPO_DIR="$HOME/criacbot"
SERVICE="criacbot"

echo "==> Updating system packages"
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

echo "==> Installing Python, git, curl"
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl

echo "==> Installing Node.js 20.x"
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - > /dev/null
sudo apt-get install -y -qq nodejs

echo "==> Installing Claude Code CLI"
sudo npm install -g @anthropic-ai/claude-code --silent

echo "==> Cloning repository"
if [ -d "$REPO_DIR" ]; then
  echo "    Directory already exists — pulling latest"
  git -C "$REPO_DIR" pull
else
  git clone https://github.com/DRourke-87/criac.git "$REPO_DIR"
fi

cd "$REPO_DIR"

echo "==> Creating Python virtual environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Setting up .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "    .env created from template. Fill it in:"
  echo "    nano $REPO_DIR/.env"
else
  echo "    .env already exists — skipping"
fi

echo "==> Installing systemd service"
sudo tee /etc/systemd/system/${SERVICE}.service > /dev/null << EOF
[Unit]
Description=CriacBot Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO_DIR
EnvironmentFile=$REPO_DIR/.env
ExecStart=$REPO_DIR/.venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE}

echo ""
echo "========================================"
echo "  Setup complete. Next steps:"
echo "========================================"
echo ""
echo "  1. Fill in your secrets:"
echo "     nano $REPO_DIR/.env"
echo ""
echo "  2. Copy your Google Calendar files from your local machine:"
echo "     (run these on YOUR LOCAL machine, not this server)"
echo "     scp credentials.json token.json ubuntu@<YOUR_VM_IP>:$REPO_DIR/"
echo ""
echo "  3. Authenticate Claude (opens browser — use SSH tunnelling or run locally first):"
echo "     claude setup-token"
echo "     Then paste the token into .env as CLAUDE_CODE_OAUTH_TOKEN"
echo ""
echo "  4. Start the bot:"
echo "     sudo systemctl start ${SERVICE}"
echo "     sudo journalctl -u ${SERVICE} -f"
echo ""
