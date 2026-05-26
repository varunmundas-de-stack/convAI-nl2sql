#!/usr/bin/env bash
set -e
cd /home/ec2-user/nl2sql
git pull origin main
docker compose build backend frontend
docker compose up -d
echo "Done. Check: http://$(curl -s ifconfig.me):3000"
