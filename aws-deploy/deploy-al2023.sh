#!/bin/bash
# Deploy script for Amazon Linux 2023 (shared VM — touch NOTHING outside nl2sql)
set -e

EC2_PUBLIC_IP="3.6.178.118"
APP_DIR="/home/ec2-user/nl2sql"
REPO_URL="https://github.com/varunmundas-de-stack/convAI-nl2sql.git"
COMPOSE_FILE="aws-deploy/docker-compose.prod.nl2sql.yml"

echo "=== [1/6] Install Docker (if not present) ==="
if ! command -v docker &>/dev/null; then
    sudo dnf install -y docker
    sudo systemctl enable --now docker
    sudo usermod -aG docker ec2-user
    echo "Docker installed. Re-run this script if group change hasn't taken effect."
    newgrp docker || true
fi

echo "=== [2/6] Clone or update repo ==="
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR" && git pull --rebase
else
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

echo "=== [3/6] Write .env (only if missing) ==="
if [ ! -f "$APP_DIR/.env" ]; then
    cat > "$APP_DIR/.env" <<EOF
ANTHROPIC_API_KEY=REPLACE_WITH_YOUR_KEY
ANTHROPIC_MODEL_ID=claude-haiku-4-5-20251001
APP_JWT_SECRET=$(openssl rand -hex 16)
POSTGRES_PASSWORD=$(openssl rand -hex 8)
EC2_PUBLIC_IP=${EC2_PUBLIC_IP}
EOF
    echo ">>> .env created — EDIT IT NOW: nano $APP_DIR/.env"
    echo ">>> Set ANTHROPIC_API_KEY then re-run this script."
    exit 0
fi

# Abort if key is still placeholder
if grep -q "REPLACE_WITH_YOUR_KEY" "$APP_DIR/.env"; then
    echo "ERROR: ANTHROPIC_API_KEY not set in .env. Edit it first."
    exit 1
fi

echo "=== [4/6] Build and start containers ==="
cd "$APP_DIR"
export EC2_PUBLIC_IP="$EC2_PUBLIC_IP"
docker compose -f "$COMPOSE_FILE" pull --ignore-pull-failures 2>/dev/null || true
docker compose -f "$COMPOSE_FILE" up -d --build

echo "=== [5/6] Wait for health checks ==="
sleep 15
docker compose -f "$COMPOSE_FILE" ps

echo "=== [6/6] Done ==="
echo ""
echo "  Frontend : http://${EC2_PUBLIC_IP}:3010"
echo "  Backend  : http://${EC2_PUBLIC_IP}:8010/health"
echo ""
echo "  Logs     : docker compose -f $APP_DIR/$COMPOSE_FILE logs -f"
