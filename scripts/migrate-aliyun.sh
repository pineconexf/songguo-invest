#!/bin/bash
# 阿里云单机上线（2026-10-19）
# 用法：CLOUD_PWD=<阿里云root密码> bash scripts/migrate-aliyun.sh
#
# 把整站搬到阿里云 47.104.103.33：
#   ① 静态：根路径构建 → 上传 /var/www/pinecone-lab
#   ② 后端：传代码 + venv + systemd → 127.0.0.1:8080
#   ③ nginx：/api/ 从腾讯云 45.194.22.118 切到本机 127.0.0.1:8080
#
# 每一步都可单独重跑；nginx 改动失败会自动回滚。
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${CLOUD_HOST:=47.104.103.33}"
: "${CLOUD_USER:=root}"
: "${CLOUD_PWD:?需要设置 CLOUD_PWD（阿里云 root 密码）}"
export CLOUD_HOST CLOUD_USER CLOUD_PWD

echo "=== ① 静态站构建并上传 ==="
bash scripts/upload-cloud.sh

echo
echo "=== ② 后端安装（venv + systemd）==="
uv run --with paramiko python scripts/deploy_aliyun_backend.py

echo
echo "=== ③ 验收 ==="
for p in / /tools/stockscore/ /api/health; do
  printf '%-22s ' "$p"
  curl -s -m 20 -o /dev/null -w '%{http_code}\n' "https://pinecone-lab.cn$p"
done
echo
echo "打分卡首页: https://pinecone-lab.cn/tools/stockscore/"
echo "（GitHub Pages 镜像仍可用，前端会自动直连云站 API）"
