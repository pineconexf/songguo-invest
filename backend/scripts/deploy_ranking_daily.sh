#!/usr/bin/env bash
# 松果基金排名 每日更新管线（交易日 19:00 cron 调用）
# 抓数(昨日收盘) → build → commit → push main → deploy gh-pages 上线
# 失败任一环节即退出非0，cron 通知可见
set -e
cd "D:/pineconeinvestfiles/松果投资体系网站/01_网站开发"

echo "① 抓取+打分（tushare 批量，约 4min）..."
python backend/scripts/fund_ranking_build.py

echo "② build..."
npm run build >/dev/null 2>&1

echo "③ commit + push main..."
git add src/data/fund_ranking.json backend/scripts/fund_ranking_build.py src/pages/tools/fund-ranking.astro src/pages/tools/fund-scorecard.astro
git commit -m "chore(fund-ranking): $(date +%Y%m%d) 排名数据更新上线" || echo "（无新改动，跳过 commit）"
git push origin main

echo "④ deploy 到 gh-pages..."
bash scripts/deploy.sh

echo "✅ 排名数据 $(date +%Y-%m-%d) 已更新上线"