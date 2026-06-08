#!/bin/bash
# Sets up HTTPS on the Oracle Cloud VM so Alexa can reach the skill endpoint.
#
# Prereqs (do these before running the script):
#
#   1. Open ports 80 and 443 in your OCI Security List if not already open:
#      OCI Console → Networking → VCNs → criacbot-vcn → Security Lists → criacbot-sl
#      Add two TCP ingress rules: port 80 and port 443, source 0.0.0.0/0
#
#   2. Create a free DuckDNS subdomain:
#      - Go to https://www.duckdns.org and sign in with Google/GitHub
#      - Create a subdomain (e.g. "mycriac")
#      - Set the IP to your VM's public IP
#      - Copy your token from the top of the page
#
#   3. Run this script on the VM:
#      DUCKDNS_TOKEN=your-token DUCKDNS_SUBDOMAIN=mycriac bash scripts/alexa_https_setup.sh
#
set -euo pipefail

if [ -z "${DUCKDNS_TOKEN:-}" ] || [ -z "${DUCKDNS_SUBDOMAIN:-}" ]; then
  echo ""
  echo "Usage: DUCKDNS_TOKEN=<token> DUCKDNS_SUBDOMAIN=<subdomain> bash $0"
  echo ""
  echo "See the comments at the top of this file for setup steps."
  exit 1
fi

DOMAIN="${DUCKDNS_SUBDOMAIN}.duckdns.org"
echo "==> Setting up HTTPS for ${DOMAIN}"

# ── open ports in the VM's OS firewall ────────────────────────────────────────
# Oracle Cloud VMs have an OS-level iptables rule that blocks inbound ports
# even when the OCI Security List allows them. Open 80 (certbot challenge)
# and 443 (HTTPS) explicitly.

echo "==> Opening ports 80 and 443 in iptables"
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
if command -v netfilter-persistent &>/dev/null; then
  sudo netfilter-persistent save
elif command -v iptables-save &>/dev/null; then
  sudo iptables-save | sudo tee /etc/iptables/rules.v4 > /dev/null
fi

# ── install nginx and certbot ─────────────────────────────────────────────────

echo "==> Installing nginx and certbot"
sudo apt-get update -q
sudo apt-get install -y -q nginx certbot python3-certbot-nginx

# ── DuckDNS IP renewal cron ───────────────────────────────────────────────────
# Keeps the DuckDNS record pointing at this VM's IP even if it changes.

echo "==> Installing DuckDNS renewal cron (every 5 minutes)"
CRON_CMD="*/5 * * * * curl -s 'https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=' > /dev/null"
(crontab -l 2>/dev/null | grep -v duckdns; echo "$CRON_CMD") | crontab -

# Force an immediate update so the DNS record is current before certbot runs.
curl -s "https://www.duckdns.org/update?domains=${DUCKDNS_SUBDOMAIN}&token=${DUCKDNS_TOKEN}&ip=" > /dev/null
echo "    DNS updated"

# ── nginx reverse-proxy config ────────────────────────────────────────────────

echo "==> Writing nginx config (HTTP, certbot will upgrade to HTTPS)"
sudo tee /etc/nginx/sites-available/alexa > /dev/null <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 30s;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/alexa /etc/nginx/sites-enabled/alexa
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# ── Let's Encrypt certificate ─────────────────────────────────────────────────

echo "==> Obtaining Let's Encrypt certificate for ${DOMAIN}"
sudo certbot --nginx -d "${DOMAIN}" \
  --non-interactive --agree-tos \
  -m "admin@${DOMAIN}" \
  --redirect

echo ""
echo "========================================"
echo "  HTTPS endpoint ready!"
echo "========================================"
echo ""
echo "  Alexa endpoint URL:"
echo "    https://${DOMAIN}/alexa"
echo ""
echo "  Health check:"
echo "    curl https://${DOMAIN}/health"
echo ""
echo "  Next steps:"
echo "    1. Add to your .env on this VM:"
echo "         ALEXA_SKILL_ID=amzn1.ask.skill.YOUR-SKILL-ID"
echo "       (fill in after creating the Alexa skill)"
echo ""
echo "    2. Restart the bot:"
echo "         sudo systemctl restart criacbot"
echo "       or if running directly: kill it and re-run python main.py"
echo ""
echo "    3. Go to the Alexa Developer Console and create the skill."
echo "       See alexa_skill_model.json in the repo for the interaction model."
echo "       Set the endpoint to: https://${DOMAIN}/alexa"
echo ""
