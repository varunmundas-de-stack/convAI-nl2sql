# =============================================================================
# nl2sql — AWS EC2 Deployment Script (PowerShell)
# =============================================================================
# Usage:
#   .\deploy.ps1                        # deploy everything
#   .\deploy.ps1 -Service backend       # rebuild + push only one service
#   .\deploy.ps1 -SkipBuild             # rsync code + restart, no image rebuild
#
# Prerequisites on local machine:
#   - Docker Desktop running
#   - ssh.exe available (Windows 10+ built-in, or Git for Windows)
#   - scp.exe available (same)
#
# Prerequisites on EC2:
#   - Amazon Linux 2 / Ubuntu with Docker + Docker Compose plugin installed
#   - Port 22 open in Security Group (your IP)
#   - Ports 3000, 8000, 4000 open as needed
# =============================================================================

param(
    [string]$Service   = "",        # optional: backend | frontend | "" (all)
    [switch]$SkipBuild = $false,    # skip docker build, just sync + restart
    [switch]$EnvOnly   = $false     # push .env only, then restart
)

# ---------------------------------------------------------------------------
# CONFIGURATION — edit these once, then never touch the script body
# ---------------------------------------------------------------------------

$EC2_HOST   = "32.192.99.187"                             # cpg-sales-demo  i-0b6417d555dc43e03  us-east-1b
$EC2_USER   = "ec2-user"                                  # amazon linux = ec2-user, ubuntu = ubuntu
$PEM_KEY    = "$env:USERPROFILE\Downloads\cpg-sales-key.pem"
$REMOTE_DIR = "/home/ec2-user/nl2sql"                     # deployment root on server

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

function ssh_run([string]$cmd) {
    ssh -i $PEM_KEY -o StrictHostKeyChecking=no "${EC2_USER}@${EC2_HOST}" $cmd
}

function scp_put([string]$local, [string]$remote) {
    scp -i $PEM_KEY -o StrictHostKeyChecking=no $local "${EC2_USER}@${EC2_HOST}:${remote}"
}

function scp_put_dir([string]$local, [string]$remote) {
    scp -i $PEM_KEY -o StrictHostKeyChecking=no -r $local "${EC2_USER}@${EC2_HOST}:${remote}"
}

# ---------------------------------------------------------------------------
# 0. Validate config
# ---------------------------------------------------------------------------

if (-not $EC2_HOST) {
    Write-Error "ERROR: EC2_HOST is empty in deploy.ps1."
    exit 1
}

if (-not (Test-Path $PEM_KEY)) {
    Write-Error "ERROR: PEM key not found at $PEM_KEY"
    exit 1
}

Write-Host "`n== nl2sql deploy → $EC2_HOST ==" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Push .env (always — contains API keys, never committed to git)
# ---------------------------------------------------------------------------

Write-Host "`n[1/5] Pushing .env..." -ForegroundColor Yellow
scp_put ".\\.env" "$REMOTE_DIR/.env"

if ($EnvOnly) {
    Write-Host "[env-only] Restarting services with new env..." -ForegroundColor Yellow
    ssh_run "cd $REMOTE_DIR && docker compose up -d"
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# 2. Sync code files (fast — no rebuild needed for pure Python/TS changes)
# ---------------------------------------------------------------------------

Write-Host "`n[2/5] Syncing project files..." -ForegroundColor Yellow

# Core files always synced
scp_put ".\\docker-compose.yml"             "$REMOTE_DIR/docker-compose.yml"
scp_put_dir ".\\backend\\app"               "$REMOTE_DIR/backend/app"
scp_put_dir ".\\backend\\catalog"           "$REMOTE_DIR/backend/catalog"
scp_put ".\\backend\\requirements.txt"      "$REMOTE_DIR/backend/requirements.txt"
scp_put ".\\backend\\Dockerfile"            "$REMOTE_DIR/backend/Dockerfile"
scp_put_dir ".\\cube\\model"                "$REMOTE_DIR/cube/model"
scp_put ".\\cube\\cube.js"                  "$REMOTE_DIR/cube/cube.js"
scp_put_dir ".\\frontend\\src"              "$REMOTE_DIR/frontend/src"
scp_put ".\\frontend\\package.json"         "$REMOTE_DIR/frontend/package.json"
scp_put ".\\frontend\\Dockerfile"           "$REMOTE_DIR/frontend/Dockerfile"

if ($SkipBuild) {
    Write-Host "[skip-build] Restarting services without rebuild..." -ForegroundColor Yellow
    ssh_run "cd $REMOTE_DIR && docker compose restart backend"
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

# ---------------------------------------------------------------------------
# 3. Build images on server (avoids shipping large image over network)
# ---------------------------------------------------------------------------

Write-Host "`n[3/5] Building images on EC2..." -ForegroundColor Yellow

if ($Service -eq "backend" -or $Service -eq "") {
    ssh_run "cd $REMOTE_DIR && docker compose build backend"
}
if ($Service -eq "frontend" -or $Service -eq "") {
    ssh_run "cd $REMOTE_DIR && docker compose build frontend"
}

# ---------------------------------------------------------------------------
# 4. Pull latest base images + bring stack up
# ---------------------------------------------------------------------------

Write-Host "`n[4/5] Pulling base images + starting stack..." -ForegroundColor Yellow
ssh_run "cd $REMOTE_DIR && docker compose pull postgres redis cube 2>/dev/null; true"

if ($Service -ne "") {
    ssh_run "cd $REMOTE_DIR && docker compose up -d $Service"
} else {
    ssh_run "cd $REMOTE_DIR && docker compose up -d"
}

# ---------------------------------------------------------------------------
# 5. Health check
# ---------------------------------------------------------------------------

Write-Host "`n[5/5] Waiting for backend health check..." -ForegroundColor Yellow
Start-Sleep -Seconds 10
$health = ssh_run "curl -sf http://localhost:8000/health && echo OK || echo FAIL"
if ($health -like "*OK*") {
    Write-Host "Backend healthy." -ForegroundColor Green
} else {
    Write-Host "Backend health check failed — check logs:" -ForegroundColor Red
    ssh_run "cd $REMOTE_DIR && docker compose logs backend --tail 40"
}

Write-Host "`n== Deploy complete ==" -ForegroundColor Cyan
Write-Host "Frontend : http://${EC2_HOST}:3000"
Write-Host "Backend  : http://${EC2_HOST}:8000"
Write-Host "Logs     : .\deploy.ps1  # then: ssh and docker compose logs -f"
