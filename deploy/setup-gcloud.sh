#!/usr/bin/env bash
# PawPoller Google Cloud VM Setup Script
# Run on a fresh Debian/Ubuntu e2-micro instance (Always Free tier).
#
# Prerequisites:
#   - GCP firewall rule allowing TCP port 8420 (created via console or gcloud CLI)
#   - SSH access to the VM
#
# Usage:
#   chmod +x setup-gcloud.sh
#   ./setup-gcloud.sh <git-repo-url>
#
# Example:
#   ./setup-gcloud.sh https://github.com/youruser/PawPoller.git

set -euo pipefail

REPO_URL="${1:-}"
APP_DIR="$HOME/PawPoller"
PORT=8420

if [ -z "$REPO_URL" ]; then
    echo "Usage: $0 <git-repo-url>"
    echo "Example: $0 https://github.com/youruser/PawPoller.git"
    exit 1
fi

echo "=== PawPoller Google Cloud Setup ==="
echo ""

# ── Step 1: Install Docker ──
if ! command -v docker &>/dev/null; then
    echo "[1/4] Installing Docker..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    # Detect distro (Debian or Ubuntu)
    . /etc/os-release
    if [ "$ID" = "debian" ]; then
        DOCKER_REPO="https://download.docker.com/linux/debian"
    else
        DOCKER_REPO="https://download.docker.com/linux/ubuntu"
    fi
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] $DOCKER_REPO $VERSION_CODENAME stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker "$USER"
    echo "Docker installed. You may need to log out and back in for group changes."
    echo "(Running remaining commands with sudo for this session)"
else
    echo "[1/4] Docker already installed -- skipping."
fi

# ── Step 2: Clone repo ──
if [ -d "$APP_DIR" ]; then
    echo "[2/4] $APP_DIR exists -- pulling latest..."
    cd "$APP_DIR" && git pull
else
    echo "[2/4] Cloning repository..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── Step 3: Create .env ──
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[3/4] Creating .env from template..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "*** IMPORTANT: Edit $APP_DIR/.env with your credentials ***"
    echo "    nano $APP_DIR/.env"
    echo ""
else
    echo "[3/4] .env already exists -- skipping."
fi

# ── Step 4: Start containers ──
echo "[4/4] Building and starting PawPoller..."
cd "$APP_DIR"
sudo docker compose up -d --build

# ── Done ──
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "<your-public-ip>")
echo ""
echo "=== Setup Complete ==="
echo "Dashboard: http://$PUBLIC_IP:$PORT"
echo ""
echo "Useful commands:"
echo "  sudo docker compose logs -f          # View live logs"
echo "  sudo docker compose restart           # Restart"
echo "  sudo docker compose down              # Stop"
echo "  sudo docker compose up -d --build     # Rebuild after code changes"
