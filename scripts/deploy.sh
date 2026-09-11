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

# 兜底：工作区若有未提交的已跟踪改动，git checkout gh-pages 会因「would be overwritten」直接失败，
# 导致部署静默不达（数据不更新）。这里临时 stash（非破坏性，untracked 不动），部署完回 main 再恢复。
STASHED=0
if [ -n "$(git status --porcelain -uno)" ]; then
  echo "⚠ 检测到未提交改动，临时 stash 后继续（部署完自动恢复）："
  git status --porcelain -uno | head -20
  STASH_NAME="deploy-auto-$(date +%s)"
  git stash push -q -m "$STASH_NAME" && STASHED=1
fi

TMP="$LOCALAPPDATA/Temp/sg_dist_deploy"
mkdir -p "$TMP" && rm -rf "$TMP"/* && cp -r dist/* "$TMP"/
echo "② dist 暂存完成: $(ls "$TMP" | wc -l) 项"

echo "③ 更新 gh-pages 分支..."
git checkout -q gh-pages
# ⚠️ rm 清单不含 dist/node_modules（dist 已不入 gh-pages；node_modules 是 untracked，删了会丢 main 的依赖）
rm -rf index.html _astro about archive backtest favicon.ico favicon.png favicon.svg mascot.png logo-mascot.png macro methodology philosophy portfolio privacy ranking services strategies tools pay .nojekyll
cp -r "$TMP"/* . && touch .nojekyll
# ⚠️ 显式文件列表，禁止 git add -A（gh-pages 分支无 .gitignore，-A 会把 node_modules 提交进仓库并污染分支切换）
git add index.html _astro about archive backtest favicon.ico favicon.png favicon.svg mascot.png logo-mascot.png macro methodology philosophy portfolio privacy ranking services strategies tools pay .nojekyll
git commit -q -m "deploy: $(date +%Y%m%d-%H%M) 构建产物"
git push origin gh-pages 2>&1 | tail -1
git checkout -q main
if [ "$STASHED" = "1" ]; then
  git stash pop -q && echo "✓ 已恢复部署前的未提交改动" || echo "⚠ stash 恢复失败，请手动 git stash list 处理"
fi
git push origin main 2>&1 | tail -1
echo "✅ 部署完成: https://pineconexf.github.io/songguo-invest/"
