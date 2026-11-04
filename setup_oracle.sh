#!/bin/bash
# ============================================================
# LeadsOSINT — Oracle Cloud Free Tier One-Command Setup
# Run as: bash <(curl -fsSL https://raw.githubusercontent.com/Jude-Ogwu/LeadsOSINT/main/setup_oracle.sh)
# ============================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✔]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✘]${NC} $1"; exit 1; }

echo ""
echo "============================================"
echo "   LeadsOSINT — Oracle Cloud Setup Script"
echo "============================================"
echo ""

# ── 1. System update ─────────────────────────────────────────
info "Updating system packages..."
sudo apt-get update -qq && sudo apt-get upgrade -y -qq

# ── 2. Install Python 3.10 + essentials ──────────────────────
info "Installing Python and tools..."
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl nginx ufw

# ── 3. Playwright system dependencies ────────────────────────
info "Installing Chromium/Playwright system libraries..."
sudo apt-get install -y -qq \
  libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
  libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
  libgbm1 libpango-1.0-0 libcairo2 libasound2 libx11-xcb1 \
  fonts-liberation libappindicator3-1 xdg-utils

# ── 4. Clone / update repo ───────────────────────────────────
APP_DIR="/home/ubuntu/LeadsOSINT"
DATA_DIR="/home/ubuntu/osint_data"

if [ -d "$APP_DIR" ]; then
  info "Repo already exists — pulling latest..."
  cd "$APP_DIR" && git pull origin main
else
  info "Cloning LeadsOSINT repo..."
  git clone https://github.com/Jude-Ogwu/LeadsOSINT.git "$APP_DIR"
  cd "$APP_DIR"
fi

# ── 5. Python virtual environment ────────────────────────────
info "Setting up Python virtual environment..."
python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"

info "Installing Python packages..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ── 6. Playwright Chromium ────────────────────────────────────
info "Installing Playwright Chromium browser..."
playwright install chromium
playwright install-deps chromium || true

# ── 7. Data directory ─────────────────────────────────────────
info "Creating data directory..."
mkdir -p "$DATA_DIR"
chmod 755 "$DATA_DIR"

# ── 8. .env file ─────────────────────────────────────────────
info "Creating .env file..."
cat > "$APP_DIR/.env" <<EOF
BD_API_KEY=88c5b773-fbd9-4602-abcc-3772d16891cb
PORT=5050
OUT_DIR=/home/ubuntu/osint_data
EOF
chmod 600 "$APP_DIR/.env"

# ── 9. systemd service (auto-start + auto-restart) ───────────
info "Setting up LeadsOSINT as a system service..."
sudo tee /etc/systemd/system/leadsosint.service > /dev/null <<EOF
[Unit]
Description=LeadsOSINT Flask Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/LeadsOSINT
EnvironmentFile=/home/ubuntu/LeadsOSINT/.env
ExecStart=/home/ubuntu/LeadsOSINT/venv/bin/python app.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable leadsosint
sudo systemctl restart leadsosint

# ── 10. Nginx reverse proxy (port 80 → 5050) ─────────────────
info "Configuring Nginx reverse proxy..."
sudo tee /etc/nginx/sites-available/leadsosint > /dev/null <<EOF
server {
    listen 80;
    server_name _;
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/leadsosint /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
sudo systemctl enable nginx

# ── 11. OS Firewall ───────────────────────────────────────────
info "Opening firewall ports..."
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP (Nginx → app)
sudo ufw allow 443/tcp   # HTTPS future
sudo ufw --force enable

# ── 12. Final status check ────────────────────────────────────
sleep 3
echo ""
echo "============================================"
if systemctl is-active --quiet leadsosint; then
  info "LeadsOSINT is RUNNING! ✅"
else
  error "LeadsOSINT service failed to start. Check: sudo journalctl -u leadsosint -n 50"
fi

PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")
echo ""
echo -e "${GREEN}Your app is live at:${NC} http://${PUBLIC_IP}"
echo -e "${GREEN}Login:${NC}  admin / AdminOSINT2026!"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status leadsosint   # check status"
echo "  sudo journalctl -u leadsosint -f   # live logs"
echo "  sudo systemctl restart leadsosint  # restart app"
echo "============================================"
