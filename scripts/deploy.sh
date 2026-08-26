#!/usr/bin/env bash
# 松果投资体系网站 · 一键构建部署（GitHub Pages gh-pages 分支）
# 用法：在 main 分支执行 bash scripts/deploy.sh
# 流程：build → dist 暂存 → 切 gh-pages 清旧产物 → 拷新 → push → 回 main
set -e
cd "$(dirname "$0")/.."

BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "main" ]; then
  echo "❌ 必须在 main 分支执行（当前: $BRANCH）"; exit 1
fi

echo "① 构建..."
npm run build

TMP="$LOCALAPPDATA/Temp/sg_dist_deploy"
mkdir -p "$TMP" && rm -rf "$TMP"/* && cp -r dist/* "$TMP"/
echo "② dist 暂存完成: $(ls "$TMP" | wc -l) 项"

echo "③ 更新 gh-pages 分支..."
git checkout -q gh-pages
# ⚠️ rm 清单不含 dist/node_modules（dist 已不入 gh-pages；node_modules 是 untracked，删了会丢 main 的依赖）
rm -rf index.html _astro about archive backtest favicon.ico favicon.svg macro methodology philosophy portfolio privacy ranking services strategies tools .nojekyll
cp -r "$TMP"/* . && touch .nojekyll
# ⚠️ 显式文件列表，禁止 git add -A（gh-pages 分支无 .gitignore，-A 会把 node_modules 提交进仓库并污染分支切换）
git add index.html _astro about archive backtest favicon.ico favicon.svg macro methodology philosophy portfolio privacy ranking services strategies tools .nojekyll
git commit -q -m "deploy: $(date +%Y%m%d-%H%M) 构建产物"
git push origin gh-pages 2>&1 | tail -1
git checkout -q main
git push origin main 2>&1 | tail -1
echo "✅ 部署完成: https://pineconexf.github.io/songguo-invest/"
