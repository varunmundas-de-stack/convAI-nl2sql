# AWS Deployment Guide — CPG Sales Assistant

## Quick Reference

| Step | Command |
|------|---------|
| First-time setup | `bash aws-deploy/setup.sh` |
| Update after code change | `bash aws-deploy/deploy.sh` |
| View live logs | `docker logs cpg_sales_assistant -f` |
| Stop app | `docker compose -f aws-deploy/docker-compose.prod.yml down` |
| Restart app | `docker compose -f aws-deploy/docker-compose.prod.yml restart app` |

---

## Pre-requisites (do this before running setup.sh)

### 1. Launch EC2 in AWS Console
```
AMI            : Ubuntu Server 22.04 LTS
Instance type  : t3.medium  (2 vCPU / 4 GB RAM)
Storage        : 20 GB gp3
Key pair       : create new → save .pem file
```

### 2. Security Group
| Type  | Port | Source |
|-------|------|--------|
| SSH   | 22   | Your IP only |
| HTTP  | 80   | 0.0.0.0/0 |
| HTTPS | 443  | 0.0.0.0/0 |

### 3. Allocate Elastic IP (stable URL)
```
EC2 → Elastic IPs → Allocate → Associate → select your instance
```

### 4. SSH into the instance
```bash
chmod 400 your-key.pem
ssh -i your-key.pem ubuntu@<elastic-ip>
```

---

## First-Time Deployment

```bash
# On the EC2 instance:
export REPO_URL=https://github.com/yourorg/yourrepo.git
bash <(curl -s https://raw.githubusercontent.com/yourorg/yourrepo/main/aws-deploy/setup.sh)

# OR clone manually then run:
git clone <your-repo-url> ~/cpg-sales-assistant
cd ~/cpg-sales-assistant
bash aws-deploy/setup.sh
```

After setup, **edit the .env file**:
```bash
nano ~/cpg-sales-assistant/.env
# Set: ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
```

Then restart:
```bash
cd ~/cpg-sales-assistant
sg docker -c "docker compose -f aws-deploy/docker-compose.prod.yml restart app"
```

---

## Updating the App

Every time you push new code:
```bash
ssh -i your-key.pem ubuntu@<elastic-ip>
cd ~/cpg-sales-assistant
bash aws-deploy/deploy.sh
```

---

## Adding SSL (HTTPS) — Optional but Recommended

You need a domain name pointing to your Elastic IP first (Route 53 or any DNS).

```bash
sudo certbot --nginx -d your-domain.com
# Certbot auto-renews every 90 days
```

---

## Cost Estimate

| Resource | $/month |
|----------|---------|
| EC2 t3.medium (on-demand 24/7) | ~$30 |
| EBS 20 GB gp3 | ~$1.60 |
| Elastic IP (attached) | Free |
| Data transfer (demo usage) | < $1 |
| **Total** | **~$33/month** |

> **Tip:** Stop the instance on nights/weekends to reduce cost to ~$10/month.

---

## Useful Commands on the Server

```bash
# Live logs
docker logs cpg_sales_assistant -f

# Check container status
docker ps

# Shell into the container
docker exec -it cpg_sales_assistant bash

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Restart nginx
sudo systemctl restart nginx
```
