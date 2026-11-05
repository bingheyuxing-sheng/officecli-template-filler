# Ensure-OfficeCLI.ps1
# 国内网络友好 + 离线优先的 OfficeCLI 环境自检与自动安装脚本
$ErrorActionPreference = "Stop"

# 1. 如果已在 PATH 中，直接返回
if (Get-Command officecli -ErrorAction SilentlyContinue) {
    $ver = & officecli --version 2>&1
    Write-Output "READY: officecli ($ver) is already in PATH."
    exit 0
}

# 2. 检查常见本地安装位置或 Skill 自带的离线二进制 (bin/officecli.exe)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Split-Path -Parent $scriptDir
$localCandidates = @(
    "$env:LOCALAPPDATA\OfficeCLI\officecli.exe",
    "$skillRoot\bin\officecli.exe",
    "$skillRoot\assets\officecli.exe",
    ".\officecli.exe"
)

$installDir = "$env:LOCALAPPDATA\OfficeCLI"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

foreach ($candidate in $localCandidates) {
    if (Test-Path $candidate) {
        if ($candidate -ne "$installDir\officecli.exe") {
            Copy-Item -Force $candidate "$installDir\officecli.exe"
        }
        $env:Path = "$installDir;$env:Path"
        $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
        if ($userPath -notlike "*$installDir*") {
            [Environment]::SetEnvironmentVariable("Path", "$userPath;$installDir", "User")
        }
        $ver = & "$installDir\officecli.exe" --version 2>&1
        Write-Output "READY (Offline/Local): Installed from $candidate ($ver)"
        exit 0
    }
}

# 3. 在线下载：优先使用国内可直连的官方镜像 d.officecli.ai 和多个国内加速通道，不直接裸连 GitHub
$arch = if ($env:PROCESSOR_ARCHITEW6432 -eq "ARM64" -or $env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "x64" }
$asset = "officecli-win-$arch.exe"
$tempFile = "$env:TEMP\officecli.exe"

$urls = @(
    "https://d.officecli.ai/releases/latest/download/$asset",
    "https://ghfast.top/https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/$asset",
    "https://gh-proxy.com/https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/$asset",
    "https://mirror.ghproxy.com/https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/$asset",
    "https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/$asset"
)

$downloaded = $false
foreach ($url in $urls) {
    try {
        Write-Host "Trying: $url ..."
        Invoke-WebRequest -Uri $url -OutFile $tempFile -TimeoutSec 25 -UseBasicParsing -ErrorAction Stop
        if ((Get-Item $tempFile).Length -gt 1000000) {
            $ver = & $tempFile --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                $downloaded = $true
                Write-Host "Successfully downloaded from $url ($ver)"
                break
            }
        }
    } catch {
        Write-Host "Skipped unreachable source: $url"
    }
}

# 4. 如果镜像下载均受限，尝试通过 npm 淘宝镜像 (npmmirror) 安装
if (-not $downloaded -and (Get-Command npm -ErrorAction SilentlyContinue)) {
    try {
        Write-Host "Trying npm with China mirror (registry.npmmirror.com)..."
        & npm install -g @officecli/officecli --registry=https://registry.npmmirror.com
        if (Get-Command officecli -ErrorAction SilentlyContinue) {
            Write-Output "READY (via npmmirror): $(officecli --version)"
            exit 0
        }
    } catch {
        Write-Host "npm fallback failed."
    }
}

if ($downloaded) {
    Copy-Item -Force $tempFile "$installDir\officecli.exe"
    Remove-Item -Force $tempFile -ErrorAction SilentlyContinue
    $env:Path = "$installDir;$env:Path"
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$installDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$installDir", "User")
    }
    Write-Output "READY (Online Mirror): $(& "$installDir\officecli.exe" --version)"
    exit 0
}

Write-Error "ERROR: Could not download officecli from mirrors. Please place officecli.exe into $installDir."
exit 1
