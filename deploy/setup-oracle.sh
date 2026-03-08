#!/usr/bin/env bash
# PawPoller Oracle Cloud VM Setup Script
# Run on a fresh Ubuntu 22.04+ ARM instance (Always Free tier).
#
# Prerequisites:
#   - Oracle Cloud VCN Security List: add ingress rule for TCP port 8420
#   - SSH access to the VM
#
# Usage:
#   chmod +x setup-oracle.sh
#   ./setup-oracle.sh <git-repo-url>
#
# Example:
#   ./setup-oracle.sh https://github.com/youruser/PawPoller.git

set -euo pipefail

REPO_URL="${1:-}"
APP_DIR="$HOME/PawPoller"
PORT=8420

if [ -z "$REPO_URL" ]; then
    echo "Usage: $0 <git-repo-url>"
    echo "Example: $0 https://github.com/youruser/PawPoller.git"
    exit 1
fi

echo "=== PawPoller Oracle Cloud Setup ==="
echo ""

# ── Step 1: Install Docker ──
if ! command -v docker &>/dev/null; then
    echo "[1/5] Installing Docker..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources-list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker "$USER"
    echo "Docker installed. You may need to log out and back in for group changes."
else
    echo "[1/5] Docker already installed -- skipping."
fi

# ── Step 2: Open port in iptables ──
echo "[2/5] Opening port $PORT in iptables (Oracle internal firewall)..."
if ! sudo iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport "$PORT" -j ACCEPT
    sudo netfilter-persistent save 2>/dev/null || sudo sh -c "iptables-save > /etc/iptables/rules.v4" 2>/dev/null || true
    echo "Port $PORT opened."
else
    echo "Port $PORT already open."
fi

# ── Step 3: Clone repo ──
if [ -d "$APP_DIR" ]; then
    echo "[3/5] $APP_DIR exists -- pulling latest..."
    cd "$APP_DIR" && git pull
else
    echo "[3/5] Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── Step 4: Create .env ──
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[4/5] Creating .env from template..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "*** IMPORTANT: Edit $APP_DIR/.env with your credentials ***"
    echo "    nano $APP_DIR/.env"
    echo ""
else
    echo "[4/5] .env already exists -- skipping."
fi

# ── Step 5: Start containers ──
echo "[5/5] Building and starting PawPoller..."
cd "$APP_DIR"
docker compose up -d --build

# ── Done ──
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "<your-public-ip>")
echo ""
echo "=== Setup Complete ==="
echo "Dashboard: http://$PUBLIC_IP:$PORT"
echo ""
echo "Useful commands:"
echo "  docker compose logs -f          # View live logs"
echo "  docker compose restart           # Restart"
echo "  docker compose down              # Stop"
echo "  docker compose up -d --build     # Rebuild after code changes"
