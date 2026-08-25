#!/usr/bin/env bash
# 松果网站 · 本地模拟服务（模拟线上 GitHub Pages 目录结构）
# 用法：bash scripts/serve-local.sh [端口]
# 访问：http://127.0.0.1:<端口>/songguo-invest/   ← 与线上 URL 结构一致，base 资源不 404
# 说明：astro preview 不挂载 base 前缀 → 页面 CSS/JS 404 → 必须用目录结构模拟
set -e
cd "$(dirname "$0")/.."

PORT="${1:-4321}"
SIM="_local_sim"

echo "① 构建..."
npm run build 2>&1 | tail -1

echo "② 组装模拟目录（dist → $SIM/songguo-invest/）..."
rm -rf "$SIM"
mkdir -p "$SIM/songguo-invest"
cp -r dist/* "$SIM/songguo-invest/"

echo "③ 启动静态服务 http://127.0.0.1:$PORT/songguo-invest/ ..."
python -m http.server "$PORT" --bind 127.0.0.1 --directory "$SIM"
