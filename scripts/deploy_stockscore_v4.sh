#!/usr/bin/env bash
# 松果个股打分卡 V4 —— 一键部署
#   后端  → 华纳云 45.194.22.118:8080（SSH 密钥，服务 stockcheck-api）
#   静态站 → 阿里云杭州 47.104.103.33（nginx，root=/var/www/pinecone-lab）
#   公网   → https://pinecone-lab.cn （阿里云 nginx 的 /api/ 反代到华纳云）
#
# 用法（在 01_网站开发 目录下）：
#   bash scripts/deploy_stockscore_v4.sh              # 全流程：预检 → git → 后端 → 静态站 → 公网验收
#   bash scripts/deploy_stockscore_v4.sh preflight    # 只跑本地预检（不碰服务器）
#   bash scripts/deploy_stockscore_v4.sh check        # 只读巡检后端现状（不改任何文件）
#   bash scripts/deploy_stockscore_v4.sh git          # 只提交并推 GitHub
#   bash scripts/deploy_stockscore_v4.sh backend      # 只部署后端（含备份/自动回滚/冒烟）
#   bash scripts/deploy_stockscore_v4.sh site         # 只重建并上传静态站
#   bash scripts/deploy_stockscore_v4.sh verify       # 只跑公网验收（只读）
#   bash scripts/deploy_stockscore_v4.sh rollback     # 后端用最近备份回滚
#
# 开关（环境变量）：
#   MIRROR=1     部署后端前把 _cloud_src/*.py 镜像回仓库 backend/ 并一并提交（默认 0）
#   SKIP_DEEP=1  后端冒烟跳过 deep 端点（deep 冷启动 30s+）
#   SS3_CODE=000001   换测试标的（默认 600519）
#   DRY=1        后端只列计划不连服务器
#   NO_COMMIT=1  只 push 不提交
#   SKIP_SITE=1  跳过静态站
#
# 凭证：静态站读 CLOUD_PWD 或 CLOUD_PWD_FILE（默认 hermes/secrets/cloud_site_pwd.txt）；
#       后端默认走 SSH 密钥（45.194.22.118 已通），可用 BE_PWD 覆盖。
# 退出码：0 成功；1 预检/推送失败；3 后端健康失败（已回滚）；4 冒烟未达标
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export CLOUD_HOST="${CLOUD_HOST:-47.104.103.33}"   # 静态站（阿里云）
export CLOUD_USER="${CLOUD_USER:-root}"
export CLOUD_PWD_FILE="${CLOUD_PWD_FILE:-$LOCALAPPDATA/hermes/secrets/cloud_site_pwd.txt}"
if [ -z "${CLOUD_PWD:-}" ] && [ -f "$CLOUD_PWD_FILE" ]; then
  CLOUD_PWD="$(tr -d '\r\n' < "$CLOUD_PWD_FILE")"
  export CLOUD_PWD
fi
export BE_HOST="${BE_HOST:-45.194.22.118}"          # 后端（华纳云）
export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-https://mirrors.aliyun.com/pypi/simple/}"
export UV_INDEX_URL="$UV_DEFAULT_INDEX"

SRC="${SS3_SRC:-D:/hermesfiles/松果工具产品/01_个股打分卡/_cloud_src}"
FRONT="src/scripts/stockscore-v3.js"
DEPLOYER="scripts/deploy_stockscore_v4.py"
PY="${PY:-python}"
STAGE="${1:-all}"

ok()   { printf '✓ %s\n' "$*"; }
warn() { printf '! %s\n' "$*"; }
bad()  { printf '✗ %s\n' "$*" >&2; }

# ---------- 1. 本地预检 ----------
preflight() {
  echo "【1/5 本地预检】"
  local fail=0

  if [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" != "main" ]; then
    warn "当前分支不是 main（$(git rev-parse --abbrev-ref HEAD 2>/dev/null)）——推送前请确认"
  fi

  if command -v node >/dev/null; then
    if node --check "$FRONT" 2>/dev/null; then ok "JS 语法 $FRONT"; else bad "JS 语法错误 $FRONT"; fail=1; fi
  else warn "未找到 node，跳过 JS 语法检查"; fi

  $PY -m py_compile "$SRC"/*.py 2>/tmp/pycompile_ss3.log \
    && ok "Python 语法 _cloud_src/*.py" \
    || { bad "Python 语法错误：$(tail -3 /tmp/pycompile_ss3.log)"; fail=1; }
  $PY -m py_compile "$DEPLOYER" 2>/dev/null || { bad "部署器语法错误 $DEPLOYER"; fail=1; }

  # V4 关键特征：缺任一说明推的不是 V4 代码
  local mark
  for mark in "stockscore_v3_core" "_v4_neutral" "tags"; do
    if grep -q "$mark" "$SRC/api.py" "$SRC/stockscore_v3.py" "$SRC/stockscore.py"; then
      ok "后端特征 $mark"
    else bad "后端缺特征 $mark"; fail=1; fi
  done
  for mark in "stockscore_v3_core" "_v4_neutral" "tagC" "ss3-l3-"; do
    if grep -q -- "$mark" "$FRONT"; then ok "前端特征 $mark"; else bad "前端缺特征 $mark"; fail=1; fi
  done

  local f
  for f in api.py stockscore.py stockscore_v3.py stockscore_modules.py stockscore_research.py \
           stockscore_narrative.py stockscore_summary.py stockscore_job.py stockscore_resolve.py \
           stockscore_persist.py; do
    [ -f "$SRC/$f" ] || { bad "缺 $SRC/$f"; fail=1; }
  done

  local hhmm; hhmm="$(date +%H%M)"
  if [ "$hhmm" -gt 2315 ] && [ "$hhmm" -lt 2345 ]; then
    warn "现在 $(date +%H:%M)，23:30 的云端站同步 cron 要触发，静态站上传可能撞版本（后端不受影响）"
  fi

  [ -n "${CLOUD_PWD:-}" ] && ok "静态站密码已载入（$CLOUD_PWD_FILE）" \
    || warn "未读到静态站密码，site 段会失败：设 CLOUD_PWD 或写入 $CLOUD_PWD_FILE"
  ok "后端走 SSH 密钥（$BE_HOST，无需密码）"

  git status --short -- "$FRONT" backend 2>/dev/null | sed 's/^/  改动 /'
  [ "$fail" = 0 ] || { bad "预检未通过，已中止（未触碰任何远端）"; return 1; }
  ok "预检通过"
}

# ---------- 2. GitHub ----------
stage_git() {
  echo "【2/5 推送 GitHub】"
  if [ "${MIRROR:-0}" = "1" ]; then
    cp -f "$SRC"/*.py backend/ && echo "  已把 _cloud_src 镜像到 backend/（MIRROR=1）"
  fi
  if [ "${NO_COMMIT:-0}" != "1" ]; then
    git add -A -- "$FRONT" scripts/deploy_stockscore_v4.py scripts/deploy_stockscore_v4.sh
    git add -u -- backend   # 只收已跟踪文件的修改，不把 .bak/deep_out*/data 临时产物扫进仓库
    if git diff --cached --quiet; then
      ok "无可提交改动"
    else
      git commit -q -m "stockscore v4: 分段返回+中性口径+角标+三层折叠+真实模块+一键部署脚本" \
        && ok "已提交 $(git log --oneline -1)"
    fi
  fi
  local i
  for i in 1 2 3; do
    if git push -q origin main 2>/tmp/gitpush_ss3.log; then ok "已推送 origin/main"; return 0; fi
    warn "第 $i 次推送失败：$(tail -1 /tmp/gitpush_ss3.log)"
    sleep 8
  done
  bad "推送失败 3 次，检查网络/代理后手动重试：git push origin main"
  return 1
}

# ---------- 3. 后端 → 华纳云 ----------
stage_backend() {
  echo "【3/5 部署后端 → 华纳云 $BE_HOST】"
  local extra=()
  [ "${DRY:-0}" = "1" ] && extra+=(--dry-run)
  uv run --with paramiko "$PY" "$DEPLOYER" "${extra[@]}"
  local rc=$?
  [ $rc -eq 0 ] && ok "后端部署+冒烟通过" \
    || bad "后端部署异常（exit=$rc；3=已自动回滚，4=冒烟未达标需人工看）"
  return $rc
}

# ---------- 4. 静态站 → 阿里云 ----------
stage_site() {
  echo "【4/5 重建并上传静态站 → 阿里云 ${CLOUD_HOST}】"
  if [ -z "${CLOUD_PWD:-}" ]; then bad "缺 CLOUD_PWD，跳过静态站"; return 1; fi
  bash scripts/upload-cloud.sh
  local rc=$?
  [ $rc -eq 0 ] && ok "静态站已上传" || bad "静态站上传失败（exit=$rc）"
  return $rc
}

# ---------- 5. 公网验收 ----------
stage_verify() {
  echo "【5/5 公网验收（code=${SS3_CODE:-600519}）】"
  "$PY" "$DEPLOYER" --verify-only --public
  local rc=$?
  case $rc in
    0) ok "公网验收通过" ;;
    4) bad "公网验收未达标（详见上方 ✗ 项）" ;;
    *) bad "验收执行失败（exit=$rc）" ;;
  esac
  return $rc
}

echo "=== 松果个股打分卡 V4 部署 · $(date '+%F %T') · stage=$STAGE ==="
rc=0
case "$STAGE" in
  preflight) preflight ;;
  check)     uv run --with paramiko "$PY" "$DEPLOYER" --check ;;
  git)       stage_git ;;
  backend)   stage_backend ;;
  site)      stage_site ;;
  verify)    stage_verify ;;
  rollback)  uv run --with paramiko "$PY" "$DEPLOYER" --rollback ;;
  all)
    preflight || rc=$?
    [ $rc -eq 0 ] && { stage_git || rc=$?; }
    [ $rc -eq 0 ] && { stage_backend || rc=$?; }
    [ $rc -eq 0 ] && [ "${SKIP_SITE:-0}" != "1" ] && { stage_site || rc=$?; }
    [ $rc -eq 0 ] && { stage_verify || rc=$?; }
    ;;
  *) bad "未知 stage：$STAGE（可选 all/preflight/check/git/backend/site/verify/rollback）"; exit 2 ;;
esac

echo "=== 结束：exit=$rc ==="
exit $rc
