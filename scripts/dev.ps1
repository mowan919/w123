<#
.SYNOPSIS
    VCTN 开发辅助脚本 —— 启动 / 停止 / 检查 / 测试 / 静态检查 / 迁移。

.DESCRIPTION
    统一入口，避免多个零散脚本造成行为漂移。
    Windows PowerShell 5.1 兼容（不使用 && / || / 三元运算符）。

.EXAMPLE
    .\scripts\dev.ps1 -Action check
    .\scripts\dev.ps1 -Action start
    .\scripts\dev.ps1 -Action test
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        'start', 'stop', 'check',
        'test', 'lint', 'typecheck', 'verify',
        'migrate', 'migrate-sql',
        'db-check',
        'compose-up', 'compose-down'
    )]
    [string]$Action,

    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Uvicorn = Join-Path $ProjectRoot '.venv\Scripts\uvicorn.exe'
$Alembic = Join-Path $ProjectRoot '.venv\Scripts\alembic.exe'
$Ruff = Join-Path $ProjectRoot '.venv\Scripts\ruff.exe'
$Mypy = Join-Path $ProjectRoot '.venv\Scripts\mypy.exe'

function Assert-Venv {
    if (-not (Test-Path $Python)) {
        Write-Host "[FAIL] 未找到虚拟环境：$Python" -ForegroundColor Red
        Write-Host "       请先执行：python -m venv .venv"
        exit 1
    }
}

function Get-ListeningPid {
    param([int]$LocalPort)
    $conn = Get-NetTCPConnection -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue
    if ($null -eq $conn) { return $null }
    return ($conn | Select-Object -First 1).OwningProcess
}

Push-Location $ProjectRoot
try {
    Assert-Venv

    # 中文 Windows 控制台默认 GB2312，而 Python 默认输出 UTF-8，
    # 会导致脚本内中文提示乱码。统一为 UTF-8 输出。
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

    Write-Host "=== VCTN dev.ps1 [$Action] ===" -ForegroundColor Cyan
    Write-Host "project root : $ProjectRoot"
    Write-Host "python       : $(& $Python --version)"
    Write-Host ""

    switch ($Action) {

        'start' {
            Write-Host "启动开发服务器 http://${HostAddress}:${Port} ..." -ForegroundColor Green
            & $Uvicorn app.main:app --host $HostAddress --port $Port --reload
        }

        'stop' {
            $ownerPid = Get-ListeningPid -LocalPort $Port
            if ($null -eq $ownerPid) {
                Write-Host "[OK] 端口 $Port 无监听进程，无需停止。" -ForegroundColor Yellow
            }
            else {
                Write-Host "停止 PID $ownerPid ..." -ForegroundColor Yellow
                Stop-Process -Id $ownerPid -Force
                Write-Host "[OK] 已停止。" -ForegroundColor Green
            }
        }

        'db-check' {
            # 本地开发直连远程 PostgreSQL / Redis，不需要 Docker。
            Write-Host "检查 PostgreSQL / Redis 连通性（只读探测）..."
            & $Python (Join-Path $ProjectRoot 'scripts\check_deps.py')
            exit $LASTEXITCODE
        }

        'check' {
            Write-Host "--- 应用存活检查 ---"
            $ok = $true
            try {
                $resp = Invoke-WebRequest -Uri "http://${HostAddress}:${Port}/health" -UseBasicParsing -TimeoutSec 5
                Write-Host "[OK] GET /health -> $($resp.StatusCode)"
                Write-Host $resp.Content
            }
            catch {
                Write-Host "[FAIL] GET /health 失败：$($_.Exception.Message)" -ForegroundColor Red
                $ok = $false
            }

            Write-Host ""
            Write-Host "--- 就绪检查（database + redis）---"
            try {
                $resp = Invoke-WebRequest -Uri "http://${HostAddress}:${Port}/api/v1/admin/health/ready" -UseBasicParsing -TimeoutSec 10
                Write-Host "[OK] GET /health/ready -> $($resp.StatusCode)"
                Write-Host $resp.Content
            }
            catch {
                # 503 = 依赖不可用，属于预期内的降级，不算脚本失败
                Write-Host "[WARN] GET /health/ready 未返回 200：$($_.Exception.Message)" -ForegroundColor Yellow
            }

            if (-not $ok) { exit 1 }
        }

        'test' {
            & $Python -m pytest -q
            exit $LASTEXITCODE
        }

        'lint' {
            & $Ruff check .
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            & $Ruff format --check .
            exit $LASTEXITCODE
        }

        'typecheck' {
            & $Mypy
            exit $LASTEXITCODE
        }

        'verify' {
            Write-Host "--- ruff check ---"
            & $Ruff check .
            if ($LASTEXITCODE -ne 0) { exit 1 }
            Write-Host "--- ruff format --check ---"
            & $Ruff format --check .
            if ($LASTEXITCODE -ne 0) { exit 1 }
            Write-Host "--- mypy ---"
            & $Mypy
            if ($LASTEXITCODE -ne 0) { exit 1 }
            Write-Host "--- pytest ---"
            & $Python -m pytest -q
            if ($LASTEXITCODE -ne 0) { exit 1 }
            Write-Host ""
            Write-Host "[OK] 全部检查通过。" -ForegroundColor Green
        }

        'migrate' {
            Write-Host "执行 alembic upgrade head ..."
            & $Alembic upgrade head
            exit $LASTEXITCODE
        }

        'migrate-sql' {
            Write-Host "离线生成迁移 SQL（不连接数据库）..."
            & $Alembic upgrade head --sql
            exit $LASTEXITCODE
        }

        'compose-up' {
            # 注意：本地开发**不需要** Docker，直接连远程 PostgreSQL / Redis。
            # 该动作仅用于部署环境验证 Compose 配置。
            Write-Host "启动 PostgreSQL + Redis 容器（仅部署验证用）..." -ForegroundColor Yellow
            docker compose up -d postgres redis
            exit $LASTEXITCODE
        }

        'compose-down' {
            Write-Host "停止容器（仅部署验证用）..." -ForegroundColor Yellow
            docker compose down
            exit $LASTEXITCODE
        }
    }
}
finally {
    Pop-Location
}
