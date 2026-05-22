# =============================================================================
# nl2sql — One-time EC2 server setup (run ONCE on a fresh instance)
# =============================================================================
# Usage:
#   .\deploy_setup.ps1
#
# What it does:
#   1. SSHs into the EC2 instance
#   2. Installs Docker + Docker Compose plugin
#   3. Creates the remote project directory structure
#   4. Copies all project files
#   5. Starts the full stack
# =============================================================================

$EC2_HOST   = "32.192.99.187"                             # cpg-sales-demo  i-0b6417d555dc43e03
$EC2_USER   = "ec2-user"
$PEM_KEY    = "$env:USERPROFILE\Downloads\cpg-sales-key.pem"
$REMOTE_DIR = "/home/ec2-user/nl2sql"

if (-not $EC2_HOST) {
    Write-Error "EC2_HOST is empty."
    exit 1
}

function ssh_run([string]$cmd) {
    ssh -i $PEM_KEY -o StrictHostKeyChecking=no "${EC2_USER}@${EC2_HOST}" $cmd
}

Write-Host "== First-time EC2 setup ==" -ForegroundColor Cyan

# Install Docker (Amazon Linux 2)
ssh_run @"
sudo yum update -y
sudo yum install -y docker git
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ec2-user
# Docker Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/download/v2.27.1/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
"@

# Create remote directory tree
ssh_run "mkdir -p $REMOTE_DIR/backend/app $REMOTE_DIR/backend/catalog $REMOTE_DIR/cube/model $REMOTE_DIR/cube/data $REMOTE_DIR/frontend/src"

Write-Host "Directory structure created. Now run: .\deploy.ps1" -ForegroundColor Green
