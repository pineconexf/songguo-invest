# -*- coding: utf-8 -*-
"""把打分卡后端装到阿里云那台机器上，并把 nginx 的 /api/ 从腾讯云切到本机。

用法（本地执行）：
  CLOUD_HOST=47.104.103.33 CLOUD_USER=root CLOUD_PWD=xxx \
  DEEPSEEK_KEY=sk-xxx \
  uv run --with paramiko python scripts/deploy_aliyun_backend.py

参数（环境变量）：
  CLOUD_HOST     阿里云 IP，默认 47.104.103.33
  CLOUD_USER     默认 root
  CLOUD_PWD      密码（与 upload-cloud.sh 同一套）
  DEEPSEEK_KEY   DeepSeek 密钥。不给则从腾讯云现有后端读取（ssh 密钥已通）
  REMOTE_DIR     远端目录，默认 /root/stockcheck-api
  SWITCH_NGINX   1=把 /api/ 切到 127.0.0.1:8080（默认 1）；0=只装后端不动 nginx
  INSTALL_CRON   1=同时挂板块快照每日 cron（默认 0，确认 push2 可达后再开）

做的事（全部幂等，可重复跑）：
  1. 建目录、传 6 个 py + 2 个 json
  2. venv + pip 安装 fastapi/uvicorn/requests
  3. 写 api.env（600）与 systemd unit，enable + restart
  4. 自测 /api/health 与 /api/stockscore_resolve
  5. 备份 nginx 配置 → 改 location /api/ → nginx -t → reload（失败自动回滚）
"""
import io
import os
import re
import sys
import time

import paramiko

HOST = os.environ.get('CLOUD_HOST', '47.104.103.33')
USER = os.environ.get('CLOUD_USER', 'root')
PWD = os.environ.get('CLOUD_PWD', '')
REMOTE = os.environ.get('REMOTE_DIR', '/root/stockcheck-api')
SWITCH_NGINX = os.environ.get('SWITCH_NGINX', '1') == '1'
INSTALL_CRON = os.environ.get('INSTALL_CRON', '0') == '1'
LOCAL_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend')
LOCAL_BACKEND = os.path.normpath(LOCAL_BACKEND)

FILES = ['api.py', 'stockscore.py', 'stockscore_v3.py', 'stockscore_resolve.py',
         'stockscore_narrative.py', 'chain_structure.py', 'collect_board_snapshot.py',
         'chain_map_v1.json', 'data/industry_taxonomy.json']

UNIT = """[Unit]
Description=Songguo stock scoring API (V3)
After=network-online.target

[Service]
Type=simple
WorkingDirectory={remote}
EnvironmentFile=-{remote}/api.env
ExecStart={remote}/venv/bin/python -m uvicorn api:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""

NGINX_API = """    location /api/ {{
        proxy_pass http://127.0.0.1:8080/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_connect_timeout 15s;
        proxy_send_timeout 240s;
        # 冷启动建全市场宇宙 84-143s，默认 60s 会被截断成 504
        proxy_read_timeout 240s;
    }}
"""


def main():
    if not PWD:
        sys.exit('需要 CLOUD_PWD')

    key = (os.environ.get('DEEPSEEK_KEY') or '').strip()
    if not key:
        # 从腾讯云现有后端取，避免再抄一遍密钥
        import subprocess
        try:
            key = subprocess.check_output(
                ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                 'root@45.194.22.118',
                 "grep -m1 DEEPSEEK_API_KEY /root/stockcheck-api/api.env | cut -d= -f2-"],
                stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            key = ''
    if not key:
        sys.exit('没有拿到 DeepSeek 密钥：请设置 DEEPSEEK_KEY')

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PWD, timeout=20)

    def run(cmd, t=180, quiet=False):
        _, so, se = c.exec_command(cmd, timeout=t)
        out = so.read().decode('utf-8', 'replace') + se.read().decode('utf-8', 'replace')
        if not quiet:
            print('$ ' + cmd)
            print(out.strip()[:600])
        return out

    # ---------- 1. 目录与文件 ----------
    run(f'mkdir -p {REMOTE}/data {REMOTE}/data/board_snapshots {REMOTE}/data/narrative')
    sftp = c.open_sftp()
    for rel in FILES:
        local = os.path.join(LOCAL_BACKEND, rel.replace('/', os.sep))
        if not os.path.exists(local):
            print(f'⚠ 跳过缺失文件 {rel}')
            continue
        remote = f'{REMOTE}/{rel}'
        run(f'mkdir -p {os.path.dirname(remote)}', quiet=True)
        sftp.put(local, remote)
        print(f'↑ {rel}')
    sftp.close()

    # ---------- 2. venv 与依赖 ----------
    run(f'test -x {REMOTE}/venv/bin/python || python3 -m venv {REMOTE}/venv', t=300)
    run(f'{REMOTE}/venv/bin/pip install -q --upgrade pip', t=300)
    run(f'{REMOTE}/venv/bin/pip install -q fastapi "uvicorn[standard]" requests', t=600)

    # ---------- 3. 密钥与 systemd ----------
    run(f'printf "DEEPSEEK_API_KEY=%s\\n" \'{key}\' > {REMOTE}/api.env && chmod 600 {REMOTE}/api.env')
    unit_path = '/etc/systemd/system/stockcheck-api.service'
    sftp = c.open_sftp()
    with sftp.open(unit_path, 'w') as f:
        f.write(UNIT.format(remote=REMOTE))
    sftp.close()
    run('systemctl daemon-reload && systemctl enable stockcheck-api >/dev/null 2>&1; '
        'systemctl restart stockcheck-api && sleep 4 && systemctl is-active stockcheck-api')

    # ---------- 4. 自测 ----------
    health = run('curl -s -m 8 http://127.0.0.1:8080/api/health', quiet=True)
    print('health:', health.strip()[:120])
    if 'ok' not in health:
        run('journalctl -u stockcheck-api -n 30 --no-pager', quiet=False)
        sys.exit('❌ 后端没起来，先看上面的日志')

    # ---------- 5. nginx 切换 ----------
    if SWITCH_NGINX:
        confs = run("grep -rl 'pinecone-lab.cn' /etc/nginx/ 2>/dev/null | grep -v '\\.bak' | head -5",
                    quiet=True).split()
        confs = [x for x in confs if x.endswith('.conf')]
        if not confs:
            print('⚠ 没找到 pinecone-lab.cn 的 nginx 配置，跳过切换（后端已装好）')
        for conf in confs:
            text = run(f'cat {conf}', quiet=True)
            if 'server_name' not in text or 'pinecone-lab.cn' not in text:
                continue
            block = NGINX_API.format()
            if re.search(r'location\s+/api/\s*\{', text):
                new = re.sub(r'location\s+/api/\s*\{[^}]*\}', block.rstrip(), text, count=1)
                action = '替换'
            else:
                new = re.sub(r'(server_name[^;]*;)', r'\1\n' + block, text, count=1)
                action = '插入'
            if new == text:
                print(f'⚠ {conf} 未改动（未匹配到 server_name）')
                continue
            bak = f'{conf}.bak_{time.strftime("%Y%m%d_%H%M")}'
            run(f'cp -a {conf} {bak}', quiet=True)
            sftp = c.open_sftp()
            with sftp.open(conf, 'w') as f:
                f.write(new)
            sftp.close()
            print(f'✓ {action} location /api/ → 127.0.0.1:8080（备份 {bak}）')
            ok = run('nginx -t 2>&1', quiet=True)
            if 'successful' not in ok:
                print(ok)
                run(f'cp -a {bak} {conf}', quiet=True)
                sys.exit('❌ nginx 配置检查失败，已回滚')
            run('systemctl reload nginx')
            break

    # ---------- 6. cron ----------
    if INSTALL_CRON:
        sftp = c.open_sftp()
        with sftp.open(f'{REMOTE}/collect_boards_cron.sh', 'w') as f:
            f.write('#!/bin/bash\n'
                    '# 板块快照采集（cron 入口）：push2 不通就静默跳过，通了自动开始积累\n'
                    f'cd {REMOTE} || exit 0\n'
                    'curl -sf -m 10 -o /dev/null \\\n'
                    '  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&fs=m:90+t:3&fields=f12" \\\n'
                    '  -H "User-Agent: Mozilla/5.0" -H "Referer: https://quote.eastmoney.com/" || exit 0\n'
                    'venv/bin/python collect_board_snapshot.py >> data/collect_boards.log 2>&1\n')
        sftp.close()
        run(f'chmod +x {REMOTE}/collect_boards_cron.sh', quiet=True)
        run("(crontab -l 2>/dev/null | grep -v collect_boards_cron; "
            f"echo '15 18 * * 1-5 {REMOTE}/collect_boards_cron.sh') | crontab -", quiet=True)
        print('✓ 已挂板块快照 cron（工作日 18:15，push2 不通时自动跳过）')

    # ---------- 7. 公网验收 ----------
    time.sleep(1)
    run("curl -s -m 20 -o /dev/null -w 'public /api/health: %{http_code}\\n' "
        "https://pinecone-lab.cn/api/health")
    run("curl -s -m 20 'https://pinecone-lab.cn/api/stockscore_resolve?q=%E8%8C%85%E5%8F%B0' | head -c 200")
    c.close()
    print('\n=== 阿里云后端部署完成 ===')


if __name__ == '__main__':
    main()
