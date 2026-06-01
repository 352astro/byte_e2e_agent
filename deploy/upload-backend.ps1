# 打包 backend 源码 → 上传服务器 → 安装依赖并启动 uvicorn
#
# 用法（PowerShell，项目根目录）:
#   .\deploy\upload-backend.ps1
#   .\deploy\upload-backend.ps1 -SshKey $env:USERPROFILE\.ssh\id_rsa
#   .\deploy\upload-backend.ps1 -StartOnly          # 仅重启，不上传
#
# 打包时已排除 .env；服务器上需自行维护 backend/.env
#
# 首次部署前请在服务器准备: Python 3.14、uv、backend/.env
#
# 依赖: tar, scp, ssh（OpenSSH 客户端）

param(
    [string]$Server = "124.223.29.15",
    [string]$SshUser = "root",
    [string]$RemoteDir = "/opt/e2e_agent/backend",
    [int]$Port = 8000,
    [string]$SshKey = "",
    [switch]$StartOnly,
    [switch]$UploadOnly
)

$ErrorActionPreference = "Stop"

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "未找到命令: $Name"
    }
}

function Get-SshBaseArgs([string]$Key) {
    $args = @("-o", "StrictHostKeyChecking=accept-new")
    if ($Key) {
        $args += @("-i", $Key)
    }
    else {
        $args += @(
            "-o", "PreferredAuthentications=password",
            "-o", "PubkeyAuthentication=no"
        )
    }
    return $args
}

Require-Command "tar"
Require-Command "ssh"
Require-Command "scp"

$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Remote = "${SshUser}@${Server}"
$RemoteArchive = "/tmp/e2e-backend-deploy.tar.gz"
$LocalArchive = Join-Path $env:TEMP "e2e-backend-deploy-$(Get-Date -Format 'yyyyMMddHHmmss').tar.gz"
$RemoteStartScript = "/tmp/e2e-remote-start-backend.sh"
$LocalStartScript = Join-Path $PSScriptRoot "remote-start-backend.sh"

$SshBase = Get-SshBaseArgs $SshKey
$SshArgs = $SshBase
$ScpArgs = $SshBase

Write-Host "==> 项目根目录: $Root"
Write-Host "==> 后端目录:   $Backend"
Write-Host "==> 部署目标:   ${Remote}:${RemoteDir}"
Write-Host "==> 监听端口:   $Port"
Write-Host ""

if (-not $StartOnly) {
    if (-not (Test-Path $Backend)) {
        throw "backend 目录不存在: $Backend"
    }

    # ── 1. 打包 ───────────────────────────────────────
    Write-Host "==> [1/4] 打包 backend 源码..."
    $exclude = @(
        ".venv", ".env", ".env.*",
        "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", "*.pyc", ".byte_agent"
    )
    $tarExclude = $exclude | ForEach-Object { "--exclude=$_" }

    Push-Location $Backend
    try {
        & tar -czf $LocalArchive @tarExclude .
        if ($LASTEXITCODE -ne 0) { throw "tar 打包失败" }
    }
    finally {
        Pop-Location
    }

    $sizeMb = [math]::Round((Get-Item $LocalArchive).Length / 1MB, 2)
    Write-Host "    已生成: $LocalArchive ($sizeMb MB)"
    Write-Host ""

    # ── 2. 上传压缩包 ─────────────────────────────────
    Write-Host "==> [2/4] scp 上传..."
    & scp @ScpArgs $LocalArchive "${Remote}:${RemoteArchive}"
    if ($LASTEXITCODE -ne 0) {
        throw "scp 失败。若 Permission denied，请用 -SshKey 指定私钥，或确认服务器已开启密码登录。"
    }
    Write-Host ""

    # ── 3. 解压 ───────────────────────────────────────
    Write-Host "==> [3/4] ssh 解压到 ${RemoteDir}..."
    $extractCmd = "set -e; mkdir -p '${RemoteDir}'; tar xzf '${RemoteArchive}' -C '${RemoteDir}'; rm -f '${RemoteArchive}'"
    & ssh @SshArgs $Remote $extractCmd
    if ($LASTEXITCODE -ne 0) { throw "ssh 解压失败" }

    Remove-Item -Force $LocalArchive -ErrorAction SilentlyContinue
    Write-Host ""
}

if ($UploadOnly) {
    Write-Host "上传完成（-UploadOnly，未启动服务）"
    exit 0
}

# ── 4. 上传启动脚本并执行 ─────────────────────────────
Write-Host "==> [4/4] 启动后端..."
if (-not (Test-Path $LocalStartScript)) {
    throw "缺少启动脚本: $LocalStartScript"
}

& scp @ScpArgs $LocalStartScript "${Remote}:${RemoteStartScript}"
if ($LASTEXITCODE -ne 0) { throw "scp 启动脚本失败" }

$startCmd = "sed -i 's/\r$//' '${RemoteStartScript}' && chmod +x '${RemoteStartScript}' && bash '${RemoteStartScript}' '${RemoteDir}' '${Port}'"
& ssh @SshArgs $Remote $startCmd
if ($LASTEXITCODE -ne 0) { throw "远程启动失败" }

& ssh @SshArgs $Remote "rm -f '${RemoteStartScript}'"

Write-Host ""
Write-Host "=============================================="
Write-Host "  后端部署完成"
Write-Host "  目录: ${RemoteDir}"
Write-Host "  API:  http://${Server}:${Port}/docs"
Write-Host "  日志: $(Split-Path $RemoteDir -Parent)/logs/backend.log"
Write-Host "=============================================="
