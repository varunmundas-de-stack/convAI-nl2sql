#!/usr/bin/env bash
# =============================================================================
# CPG Sales Assistant — AWS EC2 Setup Script
# Run this ONCE on a fresh Ubuntu 22.04 EC2 instance
# Usage: bash setup.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
section() { echo -e "\n${GREEN}===== $* =====${NC}"; }

# ── Check we are NOT root ─────────────────────────────────────────────────────
if [[ "$EUID" -eq 0 ]]; then
  warn "Do not run as root. Run as 'ubuntu' user."
  exit 1
fi

section "1. System update"
sudo apt-get update -y
sudo apt-get upgrade -y

section "2. Install Docker"
sudo apt-get install -y \
    ca-certificates curl gnupg lsb-release git nginx certbot python3-certbot-nginx

curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Allow ubuntu user to run docker without sudo
sudo usermod -aG docker ubuntu
info "Docker installed"

section "3. Clone / update repository"
REPO_DIR="$HOME/cpg-sales-assistant"
REPO_URL="${REPO_URL:-}"   # set via: export REPO_URL=https://github.com/yourorg/yourrepo.git

if [[ -z "$REPO_URL" ]]; then
  warn "REPO_URL not set. Skipping git clone."
  warn "Manually: git clone <your-repo> $REPO_DIR"
  REPO_DIR="."
else
  if [[ -d "$REPO_DIR/.git" ]]; then
    info "Repo exists — pulling latest"
    git -C "$REPO_DIR" pull
  else
    git clone "$REPO_URL" "$REPO_DIR"
  fi
fi

section "4. Create .env file (if not present)"
ENV_FILE="$REPO_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  FLASK_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  CUBEJS_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  cat > "$ENV_FILE" <<EOF
FLASK_SECRET_KEY=${FLASK_SECRET}

USE_CLAUDE_API=true
ANTHROPIC_API_KEY=PASTE_YOUR_KEY_HERE
ANONYMIZE_SCHEMA=false

CUBEJS_API_SECRET=${CUBEJS_SECRET}
CUBEJS_URL=http://cubejs:4000

NODE_ENV=production
EOF
  warn ".env created at $ENV_FILE — edit ANTHROPIC_API_KEY before starting!"
else
  info ".env already exists — skipping"
fi

section "5. Configure Nginx"
sudo cp "$REPO_DIR/aws-deploy/nginx.conf" /etc/nginx/sites-available/cpg-sales
sudo ln -sf /etc/nginx/sites-available/cpg-sales /etc/nginx/sites-enabled/cpg-sales
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
info "Nginx configured on port 80"

section "6. Build and start Docker containers"
cd "$REPO_DIR"
# Use newgrp trick to pick up docker group without re-login
sg docker -c "docker compose -f aws-deploy/docker-compose.prod.yml --env-file .env up -d --build"

section "7. Set Docker containers to start on boot"
sudo systemctl enable docker

section "Done!"
PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "<your-ec2-ip>")
echo ""
echo "  App URL  :  http://${PUBLIC_IP}"
echo "  Login    :  nestle_admin / admin123"
echo ""
warn "Remember to:"
warn "  1. Edit .env and set your ANTHROPIC_API_KEY"
warn "  2. Run: sg docker -c 'docker compose -f aws-deploy/docker-compose.prod.yml restart app'"
warn "  3. (Optional) Add SSL: sudo certbot --nginx -d your.domain.com"
echo ""
