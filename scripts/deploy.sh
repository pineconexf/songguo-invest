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

# ⚠️ 2026-09-19 加固①：中途失败（尤其 push 不通）会让仓库停在 gh-pages——该分支没有 src/scripts/package.json，
# 于是所有站点 cron 集体报「脚本不存在」，且下一次 deploy 也起不来。trap 保证无论成败都切回 main。
return_main() {
  cur=$(git branch --show-current 2>/dev/null || echo "")
  if [ "$cur" != "main" ]; then
    echo "↩ 部署异常中断，强制切回 main（原分支: $cur）"
    git checkout -q main 2>/dev/null || echo "⚠ 切回 main 失败，请手动处理（当前: $cur）"
  fi
}
trap return_main EXIT

# ⚠️ 2026-09-19 加固②：github.com 直连会被 reset（国内网络），本地代理在跑就走代理（与 web 插件同一策略）
GIT_PROXY_ARGS=""
if python -c "import socket;socket.create_connection(('127.0.0.1',10808),1).close()" 2>/dev/null; then
  GIT_PROXY_ARGS="-c http.proxy=http://127.0.0.1:10808"
  echo "ℹ 本地代理 10808 可用，git push/ls-remote 走代理"
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
# ⚠️ pay 已在 2026-09-14 下线，必须显式 rm 从 gh-pages 工作树删除（否则旧 pay/ 残留线上）
rm -rf index.html _astro about archive backtest favicon.ico favicon.png favicon.svg mascot.png logo-mascot.png macro methodology philosophy portfolio privacy ranking services strategies tools pay .nojekyll
cp -r "$TMP"/* . && touch .nojekyll
# ⚠️ 显式文件列表，禁止 git add -A（gh-pages 分支无 .gitignore，-A 会把 node_modules 提交进仓库并污染分支切换）
git add index.html _astro about archive backtest favicon.ico favicon.png favicon.svg mascot.png logo-mascot.png macro methodology philosophy portfolio privacy ranking services strategies tools .nojekyll
# 删除已下线目录在 gh-pages 上的残留（pay/ 付费落地页 2026-09-14 下线；rm -rf 只删工作区，需显式 stage 删除）
git add -u pay 2>/dev/null || true
git commit -q -m "deploy: $(date +%Y%m%d-%H%M) 构建产物"
# ⚠️ push 防假成功：`git push | tail` 管道吃掉退出码，且国内瞬断常见 → 带重试+显式校验远端 SHA
push_with_retry() {
  local ref="$1" sha local_sha attempt
  sha=$(git rev-parse "$ref")
  for attempt in 1 2 3; do
    if git $GIT_PROXY_ARGS push origin "$ref" 2>&1 | tail -2; then
      local_sha=$(git $GIT_PROXY_ARGS ls-remote origin "$ref" 2>/dev/null | cut -f1)
      if [ "$local_sha" = "$sha" ]; then echo "✓ $ref 已确认推送 ($sha)"; return 0; fi
    fi
    echo "⚠ push $ref 第 $attempt 次失败/未确认，3s 后重试..."; sleep 3
  done
  echo "❌ push $ref 三次失败，部署未完成（本地已 commit，远端未更新）"; return 1
}
push_with_retry gh-pages
git checkout -q main
if [ "$STASHED" = "1" ]; then
  git stash pop -q && echo "✓ 已恢复部署前的未提交改动" || echo "⚠ stash 恢复失败，请手动 git stash list 处理"
fi
push_with_retry main
echo "✅ 部署完成: https://pineconexf.github.io/songguo-invest/"
