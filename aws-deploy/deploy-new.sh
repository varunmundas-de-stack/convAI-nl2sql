#!/bin/bash
set -e

EC2_IP="$(curl -s http://checkip.amazonaws.com/ 2>/dev/null || hostname -I | awk '{print $1}')"
APP_DIR="/home/ubuntu/nl2sql"

echo "=== Step 1: Stop OLD app ==="
cd /home/ubuntu/cpg-sales-demo 2>/dev/null && docker compose down --remove-orphans 2>/dev/null || true
docker stop $(docker ps -q) 2>/dev/null || true

echo "=== Step 2: Install deps ==="
sudo apt-get update -qq
sudo apt-get install -y docker.io docker-compose-plugin nginx curl git

echo "=== Step 3: Clone/update new app ==="
if [ -d "$APP_DIR" ]; then
  cd "$APP_DIR" && git pull
else
  git clone https://github.com/$(git remote get-url origin | sed 's/.*github.com[:/]//') "$APP_DIR" 2>/dev/null || \
  { echo "Manual upload needed — rsync or scp the project to $APP_DIR"; exit 1; }
fi

echo "=== Step 4: Set env ==="
cat > "$APP_DIR/.env" <<EOF
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
CUBEJS_API_SECRET=prod-cube-secret-$(openssl rand -hex 8)
APP_JWT_SECRET=prod-jwt-secret-$(openssl rand -hex 16)
POSTGRES_PASSWORD=prod-pg-$(openssl rand -hex 8)
EC2_PUBLIC_IP=${EC2_IP}
EOF

echo "=== Step 5: Build and start ==="
cd "$APP_DIR"
export EC2_PUBLIC_IP="$EC2_IP"
docker compose -f aws-deploy/docker-compose.prod.new.yml up -d --build

echo "=== Step 6: Configure Nginx ==="
sudo cp aws-deploy/nginx.new.conf /etc/nginx/sites-available/nl2sql
sudo ln -sf /etc/nginx/sites-available/nl2sql /etc/nginx/sites-enabled/nl2sql
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

echo ""
echo "✅ App live at: http://${EC2_IP}"
echo "   Backend API: http://${EC2_IP}/api/"
