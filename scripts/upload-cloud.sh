#!/bin/bash
# 云端正式站一键部署（2026-09-05）
# 用：CLOUD_HOST=47.104.103.33 CLOUD_USER=root CLOUD_PWD=<密码> bash scripts/upload-cloud.sh
# 密码也可放临时文件：CLOUD_PWD=$(cat /path/pwd.txt) bash scripts/upload-cloud.sh
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${CLOUD_HOST:=47.104.103.33}"
: "${CLOUD_USER:=root}"
: "${CLOUD_PWD:?需要设置 CLOUD_PWD}"

# 1. 云端根路径构建（base=/，与 GitHub Pages 子路径构建互不影响）
ASTRO_SITE=https://pinecone-lab.cn ASTRO_BASE=/ npm run build

# 2. 把源码里硬编码的 /songguo-invest/ 前缀统一替换为根路径（构建产物层处理，源码零改）
find dist -name '*.html' -exec sed -i 's|/songguo-invest/|/|g' {} +

# 3. 打包（tar 用 MSYS 路径 /c/...；python 用 Windows 路径 C:\\...，二者格式不同！）
TMP_MSYS="$(cygpath -u "$LOCALAPPDATA")/Temp"
tar -czf "$TMP_MSYS/pinecone-site.tgz" -C dist .

# 4. 推送至服务器（paramiko 上传 -> 解压 -> 权限 -> nginx reload -> 验证）
TMP_WIN="${LOCALAPPDATA}\\Temp"
export CLOUD_HOST CLOUD_USER CLOUD_PWD TMP="$TMP_WIN"
uv run --with paramiko python "$(dirname "$0")/cloud_push.py"

echo "=== 云端部署完成 ==="
