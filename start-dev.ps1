# Error handling
$ErrorActionPreference = "Stop"

function Start-DockerDesktop {
    if (!(Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) {
        Write-Host "🐋 Starting Docker Desktop..." -ForegroundColor Yellow
        Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
        
        # Wait for Docker daemon
        Write-Host "⏳ Waiting for Docker Engine" -NoNewline
        $maxAttempts = 60
        $attempt = 0
        
        while ($attempt -lt $maxAttempts) {
            try {
                docker info 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host " ✓" -ForegroundColor Green
                    return $true
                }
            } catch {}
            
            Write-Host "." -NoNewline
            Start-Sleep -Seconds 2
            $attempt++
        }
        
        Write-Host " ✗" -ForegroundColor Red
        throw "Docker Desktop failed to start within 2 minutes"
    }
    Write-Host "✓ Docker Desktop already running" -ForegroundColor Green
    return $true
}

function Stop-Services {
    Write-Host "`n🧹 Cleaning up Docker services..." -ForegroundColor Yellow
    Set-Location $PSScriptRoot
    docker compose down
    
    # Stop Docker Desktop
    Write-Host "🛑 Stopping Docker Desktop..." -ForegroundColor Yellow
    $dockerProcess = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
    
    if ($dockerProcess) {
        # Graceful shutdown
        Stop-Process -Name "Docker Desktop" -Force
        
        # Also stop the backend processes
        Get-Process "com.docker.*" -ErrorAction SilentlyContinue | Stop-Process -Force
        
        # Wait a moment to ensure clean shutdown
        Start-Sleep -Seconds 2
        Write-Host "✓ Docker Desktop stopped" -ForegroundColor Green
    } else {
        Write-Host "✓ Docker Desktop already stopped" -ForegroundColor Gray
    }
    
    Write-Host "✓ Cleanup complete" -ForegroundColor Green
}

# Register cleanup handler for Ctrl+C
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Stop-Services
}

try {
    # Start Docker
    Start-DockerDesktop
    
    # Start services
    Write-Host "🚀 Starting Docker Compose services..." -ForegroundColor Cyan
    docker compose up -d
    
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed to start services"
    }
    
    # Wait for postgres to be healthy
    Write-Host "⏳ Waiting for PostgreSQL to be healthy" -NoNewline
    $maxAttempts = 30
    $attempt = 0
    
    while ($attempt -lt $maxAttempts) {
        $health = docker inspect --format='{{.State.Health.Status}}' nl2sql-postgres 2>$null
        if ($health -eq "healthy") {
            Write-Host " ✓" -ForegroundColor Green
            break
        }
        
        $status = docker inspect --format='{{.State.Status}}' nl2sql-postgres 2>$null
        if ($status -eq "running" -and !$health) {
            Write-Host " ✓ (running)" -ForegroundColor Green
            break
        }
        
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
        $attempt++
    }
    
    if ($attempt -eq $maxAttempts) {
        throw "PostgreSQL failed to become healthy"
    }
    
    # 🆕 Populate database
    Write-Host "📊 Populating database..." -ForegroundColor Cyan
    
    $sqlFiles = Get-ChildItem -Path ".\cube\data" -Filter "*.sql" | Sort-Object Name
    if ($sqlFiles.Count -gt 0) {
        foreach ($file in $sqlFiles) {
            Write-Host "  Executing $($file.Name)..." -NoNewline
            Get-Content $file.FullName | docker exec -i nl2sql-postgres psql -U postgres -d sales_analytics 2>&1 | Out-Null
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host " ✓" -ForegroundColor Green
            } else {
                Write-Host " ✗ (Failed, continuing...)" -ForegroundColor Yellow
            }
        }
        Write-Host "✓ Database scripts executed successfully" -ForegroundColor Green
    } else {
        Write-Warning "No SQL files found in .\cube\data (skipping population)"
    }
    
    # Start FastAPI
    Write-Host "🎯 Starting FastAPI server..." -ForegroundColor Cyan
    Set-Location backend
    
    ..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    
} catch {
    Write-Error $_.Exception.Message
    exit 1
} finally {
    Stop-Services
}