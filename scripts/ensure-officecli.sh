#!/usr/bin/env bash
# ensure-officecli.sh
# 国内网络友好 + 离线优先的 OfficeCLI 环境自检与自动安装脚本 (macOS / Linux)
set -e

if command -v officecli >/dev/null 2>&1; then
    echo "READY: officecli ($(officecli --version)) is already in PATH."
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

# 1. 检查本地离线包
for candidate in "$SKILL_ROOT/bin/officecli" "$SKILL_ROOT/assets/officecli" "./officecli"; do
    if [ -f "$candidate" ]; then
        cp -f "$candidate" "$INSTALL_DIR/officecli"
        chmod +x "$INSTALL_DIR/officecli"
        export PATH="$INSTALL_DIR:$PATH"
        echo "READY (Offline/Local): Installed from $candidate"
        exit 0
    fi
done

# 2. 识别架构并走国内可访问的官方镜像 d.officecli.ai 及加速通道
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
if [ "$OS" = "darwin" ]; then
    [ "$ARCH" = "arm64" ] && ASSET="officecli-mac-arm64" || ASSET="officecli-mac-x64"
else
    [ "$ARCH" = "aarch64" ] && ASSET="officecli-linux-arm64" || ASSET="officecli-linux-x64"
fi

TMP_FILE="/tmp/officecli_bin"
URLS=(
    "https://d.officecli.ai/releases/latest/download/$ASSET"
    "https://ghfast.top/https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/$ASSET"
    "https://gh-proxy.com/https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/$ASSET"
    "https://github.com/iOfficeAI/OfficeCLI/releases/latest/download/$ASSET"
)

for url in "${URLS[@]}"; do
    echo "Trying: $url ..."
    if curl -fsSL --connect-timeout 15 --max-time 60 "$url" -o "$TMP_FILE" 2>/dev/null; then
        chmod +x "$TMP_FILE"
        if "$TMP_FILE" --version >/dev/null 2>&1; then
            mv -f "$TMP_FILE" "$INSTALL_DIR/officecli"
            export PATH="$INSTALL_DIR:$PATH"
            echo "READY (Online Mirror): $("$INSTALL_DIR/officecli" --version)"
            exit 0
        fi
    fi
done

# 3. 淘宝 npm 镜像兜底
if command -v npm >/dev/null 2>&1; then
    npm install -g @officecli/officecli --registry=https://registry.npmmirror.com && exit 0
fi

echo "ERROR: Could not install officecli."
exit 1
