#!/usr/bin/env bash
# =============================================================================
# CPG Sales Assistant — Re-deploy / Update Script
# Run this every time you push new code and want to update the server
# Usage: bash deploy.sh
# =============================================================================

set -euo pipefail
GREEN='\033[0;32m'; NC='\033[0m'
section() { echo -e "\n${GREEN}===== $* =====${NC}"; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

section "1. Pull latest code"
git pull

section "2. Rebuild and restart containers"
sg docker -c "docker compose -f aws-deploy/docker-compose.prod.yml up -d --build"

section "3. Clean up old images"
docker image prune -f

section "Done — app updated!"
echo "Check logs: docker logs cpg_sales_assistant -f"
