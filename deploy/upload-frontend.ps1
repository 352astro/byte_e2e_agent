# 构建前端并上传到服务器（SSH 密码在终端手动输入）
#
# 用法（PowerShell，在项目根目录）:
#   .\deploy\upload-frontend.ps1
#
# 若提示无法执行脚本:
#   powershell -ExecutionPolicy Bypass -File .\deploy\upload-frontend.ps1
#
# 依赖: Node.js (npm)、OpenSSH 客户端（ssh / scp）
#   Windows: 设置 → 应用 → 可选功能 → 安装「OpenSSH 客户端」

param(
    [string]$Server = "124.223.29.15",
    [string]$SshUser = "root",
    [string]$RemoteDir = "/opt/e2e_agent/frontend",
    [string]$SshKey = ""
)

$ErrorActionPreference = "Stop"

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "未找到命令: $Name。请先安装并加入 PATH。"
    }
}

Require-Command "npm"
Require-Command "ssh"
Require-Command "scp"
Require-Command "tar"

$Root = Split-Path -Parent $PSScriptRoot
$Frontend = Join-Path $Root "frontend"
$Dist = Join-Path $Frontend "dist"
$Remote = "${SshUser}@${Server}"
$RemoteArchive = "/tmp/e2e-frontend-deploy.tar.gz"
$LocalArchive = Join-Path $env:TEMP "e2e-frontend-deploy-$(Get-Date -Format 'yyyyMMddHHmmss').tar.gz"

$SshArgs = @()
$ScpArgs = @()
if ($SshKey) {
    $SshArgs += @("-i", $SshKey)
    $ScpArgs += @("-i", $SshKey)
}

Write-Host "==> 项目根目录: $Root"
Write-Host "==> 目标服务器: ${Remote}:${RemoteDir}"
Write-Host ""

# ── 1. 构建前端 ─────────────────────────────────────
Write-Host "==> [1/3] 构建前端 (npm run build)..."
Push-Location $Frontend
try {
    if (-not (Test-Path "node_modules")) {
        Write-Host "    node_modules 不存在，执行 npm install..."
        npm install
        if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build 失败" }
}
finally {
    Pop-Location
}

if (-not (Test-Path $Dist)) {
    throw "构建产物不存在: $Dist"
}
Write-Host "    构建完成: $Dist"
Write-Host ""

# ── 2. 打包 dist ─────────────────────────────────────
Write-Host "==> [2/3] 打包 dist..."
tar -czf $LocalArchive -C $Dist .
if ($LASTEXITCODE -ne 0) { throw "tar 打包失败" }
Write-Host "    本地包: $LocalArchive"
Write-Host ""

# ── 3. 上传并解压（两次 SSH 密码提示：scp + ssh）────
Write-Host "==> [3/3] 上传到服务器（将提示输入 SSH 密码，共 2 次）..."
Write-Host "    (1/2) scp 上传压缩包..."
& scp @ScpArgs $LocalArchive "${Remote}:${RemoteArchive}"
if ($LASTEXITCODE -ne 0) { throw "scp 上传失败" }

Write-Host "    (2/2) ssh 解压到 ${RemoteDir}..."
$RemoteCmd = "rm -rf '$RemoteDir' && mkdir -p '$RemoteDir' && tar xzf '$RemoteArchive' -C '$RemoteDir' && rm -f '$RemoteArchive'"
& ssh @SshArgs $Remote $RemoteCmd
if ($LASTEXITCODE -ne 0) { throw "ssh 解压失败" }

Remove-Item -Force $LocalArchive -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=============================================="
Write-Host "  前端部署完成"
Write-Host "  远程路径: ${Remote}:${RemoteDir}/"
Write-Host "  请确认 nginx 的 root 指向该目录，且 /api 反代后端"
Write-Host "=============================================="
