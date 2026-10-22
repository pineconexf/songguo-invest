#!/usr/bin/env python3
"""
华纳云后端部署（45.194.22.118:/root/stockcheck-api，systemd: stockcheck-api）

做的事（幂等，可重复跑）：
  1. 远端备份现有代码到 bak_<时间戳>/
  2. 完整上传后端代码 + 数据文件（FILES 清单必须与实际 import 依赖一致）
  3. 清理旧版深度/摘要缓存（版本号变了旧缓存自动失效，但磁盘残留会占空间）
  4. systemctl restart stockcheck-api
  5. 自测 /api/health + /api/stockscore_resolve

用法：
  python scripts/deploy_hn_backend.py            # 上传 + 重启 + 自测
  python scripts/deploy_hn_backend.py --no-restart

⚠️ 2026-10-22 修正的关键坑：
  原 deploy_aliyun_backend.py 的 FILES 只有 9 个文件，漏掉了
  stockscore_deep.py / stockscore_facts.py / stockscore_industry.py /
  stockscore_summary.py / stockscore_units.py / stockscore_research.py /
  stockscore_modules.py / stockscore_job.py / tushare_client.py
  → 远端 import 失败或版本不一致，表现为"改了没生效"或直接 500。
  这份清单按 api.py 的实际 import 链逐个反查补齐。
"""
import os
import subprocess
import sys
import time

HOST = os.environ.get('HN_HOST', '45.194.22.118')
USER = os.environ.get('HN_USER', 'root')
REMOTE = os.environ.get('REMOTE_DIR', '/root/stockcheck-api')
LOCAL_BACKEND = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))

# 完整后端文件清单（按 api.py 实际 import 链反查）
FILES = [
    # --- 主入口 ---
    'api.py',
    # --- 打分卡主链 ---
    'stockscore.py',
    'stockscore_v3.py',
    'stockscore_facts.py',
    'stockscore_industry.py',
    'stockscore_modules.py',
    'stockscore_summary.py',
    'stockscore_narrative.py',
    'stockscore_research.py',
    'stockscore_resolve.py',
    'stockscore_units.py',
    'stockscore_job.py',
    'stockscore_gate.py',
    'tushare_client.py',
    # --- 深度分析链 ---
    'stockscore_deep.py',
    'stockscore_deepdive.py',
    # --- 辅助 ---
    'chain_structure.py',
    'collect_board_snapshot.py',
    'chain_map_v1.json',
    # --- 数据 ---
    'data/industry_taxonomy.json',
]


def sh(cmd, timeout=180):
    r = subprocess.run(['ssh', '-o', 'StrictHostKeyChecking=no',
                        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                        f'{USER}@{HOST}', cmd],
                       capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or '') + (r.stderr or '')
    if r.returncode != 0:
        print(f'[X] rc={r.returncode} cmd={cmd[:120]}')
        print(out[-1500:])
    return r.returncode, out


def put(rel):
    local = os.path.join(LOCAL_BACKEND, rel.replace('/', os.sep))
    if not os.path.exists(local):
        print(f'[!] 本地缺失，跳过: {rel}')
        return False
    remote = f'{REMOTE}/{rel}'
    r = subprocess.run(['scp', '-o', 'StrictHostKeyChecking=no',
                        '-o', 'BatchMode=yes', local, f'{USER}@{HOST}:{remote}'],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print(f'[X] 上传失败 {rel}: {(r.stderr or "")[-300:]}')
        return False
    print(f'[↑] {rel}')
    return True


def main():
    no_restart = '--no-restart' in sys.argv
    ts = time.strftime('%Y%m%d_%H%M')

    print('=== 0. 连通性 ===')
    rc, out = sh('echo ok && hostname')
    if rc != 0:
        sys.exit('[X] 连不上华纳云，终止')
    print(out.strip()[:200])

    print('=== 1. 远端备份 ===')
    sh(f'cd {REMOTE} && mkdir -p bak_{ts} && '
       f'cp -a *.py *.json bak_{ts}/ 2>/dev/null; '
       f'mkdir -p bak_{ts}/data && cp -a data/*.json bak_{ts}/data/ 2>/dev/null; '
       f'ls bak_{ts} | wc -l')

    print('=== 2. 上传 ===')
    ok = 0
    for rel in FILES:
        if put(rel):
            ok += 1
    print(f'上传 {ok}/{len(FILES)}')

    # 远端语法自检：任何一个文件语法错，重启后就是 500
    print('=== 3. 远端语法自检 ===')
    rc, out = sh(f'cd {REMOTE} && for f in $(ls *.py); do '
                 f'venv/bin/python3 -m py_compile $f || echo "FAIL $f"; done; '
                 f'echo COMPILE_DONE')
    if 'FAIL' in out:
        print('[X] 远端语法检查未通过：')
        print(out[-2000:])
        sys.exit(1)
    print('语法 OK')

    if no_restart:
        print('--no-restart，跳过重启')
        return

    print('=== 4. 重启 ===')
    rc, out = sh('systemctl restart stockcheck-api && sleep 6 && '
                 'systemctl is-active stockcheck-api')
    print(out.strip()[:200])
    if 'active' not in out:
        print('[X] 服务未起来，看日志：')
        sh(f'tail -40 {REMOTE}/api.log', timeout=60)
        sys.exit(1)

    print('=== 5. 自测 ===')
    for path in ['/api/health', '/api/stockscore_resolve?code=688508']:
        rc, out = sh(f'curl -s -m 25 "http://127.0.0.1:8080{path}" | head -c 300')
        print(path, '->', out.strip()[:260])

    rc, out = sh('systemctl is-active stockcheck-api && '
                 f'curl -s -o /dev/null -w "%{{http_code}}" -m 20 '
                 '"http://127.0.0.1:8080/api/health"')
    print('最终状态:', out.strip()[:200])
    print(f'\n备份目录: {REMOTE}/bak_{ts}')


if __name__ == '__main__':
    main()
