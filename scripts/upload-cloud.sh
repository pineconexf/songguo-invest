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
# ⚠️ 2026-10-18 修复：在 Git Bash 下直接把 ASTRO_BASE=/ 传给 npm，MSYS 会把 `/` 路径转换成
#    Git Bash 安装根目录（实测产物里出现 href="/C:/Program Files/WorkBuddyAI/.../` `_astro/...css`），
#    整站 CSS/JS 全部 404。加 MSYS_NO_PATHCONV + MSYS2_ARG_CONV_EXCL='*' 关掉路径转换。
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' ASTRO_SITE=https://pinecone-lab.cn ASTRO_BASE=/ npm run build

# 2. 把源码里硬编码的 /songguo-invest/ 前缀统一替换为根路径（构建产物层处理，源码零改）
# ⚠️ 2026-10-18 修复：原来只 sed *.html，但 JS chunk 里也有硬编码路径
#    （实测 etf-allocator 的 chunk 有 2 处 fetch('/songguo-invest/data/...')），
#    线上表现为 ETF 分配器取不到数据。这里 html/css/js 一起处理。
find dist -type f \( -name '*.html' -o -name '*.css' -o -name '*.js' \) \
  -exec sed -i 's|/songguo-invest/|/|g' {} +

# 2.5 兜底校验：构建产物里不允许再出现 Git Bash 安装路径或子路径，否则整站静态资源 404
if grep -rl 'songguo-invest' dist >/dev/null 2>&1; then
  echo "❌ dist 中仍有 /songguo-invest/ 残留：" >&2
  grep -rl 'songguo-invest' dist >&2
  exit 1
fi
if grep -rl 'Program Files' dist >/dev/null 2>&1; then
  echo "❌ 构建产物被 MSYS 路径转换污染（含 Program Files），检查 MSYS_NO_PATHCONV 是否生效：" >&2
  grep -rl 'Program Files' dist >&2
  exit 1
fi
echo "✓ 构建产物路径校验通过"

# 3. 打包（tar 用 MSYS 路径 /c/...；python 用 Windows 路径 C:\\...，二者格式不同！）
TMP_MSYS="$(cygpath -u "$LOCALAPPDATA")/Temp"
tar -czf "$TMP_MSYS/pinecone-site.tgz" -C dist .

# 4. 推送至服务器（paramiko 上传 -> 解压 -> 权限 -> nginx reload -> 验证）
TMP_WIN="${LOCALAPPDATA}\\Temp"
export CLOUD_HOST CLOUD_USER CLOUD_PWD TMP="$TMP_WIN"
uv run --with paramiko python "$(dirname "$0")/cloud_push.py"

echo "=== 云端部署完成 ==="
