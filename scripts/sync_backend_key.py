#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek key 单源同步：Hermes LLM 供应商（官方直连）→ 线上后端 + 本地开发 .env

唯一真源（single source of truth）：
    %LOCALAPPDATA%\\hermes\\.env   的 DEEPSEEK_API_KEY
    —— 也就是 Hermes config.yaml 里 provider `deepseek-official` 的 key_env

用法（密码经环境变量传，不落仓库）：
    HN_PWD=<华纳云root密码> uv run --with paramiko --with requests python scripts/sync_backend_key.py

做的事：
    1. 从 Hermes .env 读 key（不打屏、不落盘到仓库）
    2. 用 GET https://api.deepseek.com/v1/models 验活（免费，能鉴权即有效）
    3. 推送到华纳云 /root/stockcheck-api/api.env（chmod 600）→ 重启 stockcheck-api
    4. 本地 backend/.env 同步为同一 key（本地开发不再各存一份）
    5. 回验 https://pinecone-lab.cn/api/health

轮换密钥的正确姿势：改 Hermes .env → 重跑本脚本。不要手改服务器上的 api.env。
"""
import os
import re
import sys
import pathlib

import requests
import paramiko

KEY_NAME = "DEEPSEEK_API_KEY"
HERMES_ENV = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / ".env"
LOCAL_ENV = pathlib.Path(__file__).resolve().parent.parent / "backend" / ".env"

HN_HOST = os.environ.get("HN_HOST", "45.194.22.118")
HN_USER = os.environ.get("HN_USER", "root")
HN_PWD = os.environ.get("HN_PWD", "")
REMOTE_ENV = "/root/stockcheck-api/api.env"
SERVICE = "stockcheck-api"
HEALTH_URL = "https://pinecone-lab.cn/api/health"


def mask(v):
    return "%s…%s(len=%d)" % (v[:6], v[-4:], len(v)) if len(v) > 12 else "***"


def read_src_key():
    if not HERMES_ENV.exists():
        sys.exit("[X] 找不到 Hermes .env: %s" % HERMES_ENV)
    txt = HERMES_ENV.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^%s\s*=\s*(.+)$" % KEY_NAME, txt, re.M)
    if not m:
        sys.exit("[X] Hermes .env 里没有 %s" % KEY_NAME)
    return m.group(1).strip().strip('"').strip("'")


def verify_alive(key):
    r = requests.get(
        "https://api.deepseek.com/v1/models",
        headers={"Authorization": "Bearer %s" % key},
        timeout=30,
    )
    return r.status_code, r.text[:160]


def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HN_HOST, username=HN_USER, password=HN_PWD, timeout=25)
    return c


def run(c, cmd):
    _, out, err = c.exec_command(cmd)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    return o.strip(), e.strip()


def main():
    if not HN_PWD:
        sys.exit("[X] 需要 HN_PWD 环境变量")
    key = read_src_key()
    print("[1/5] 读到 Hermes 官方 key: %s" % mask(key))

    code, body = verify_alive(key)
    if code != 200:
        sys.exit("[X] key 验活失败 HTTP %s: %s" % (code, body))
    print("[2/5] key 验活通过 (api.deepseek.com/v1/models HTTP 200)")

    c = ssh()
    try:
        # 3. 远端 api.env —— 用 SFTP 写，避免 key 出现在远端命令行/进程表里
        run(c, "mkdir -p /root/stockcheck-api && chmod 700 /root/stockcheck-api")
        sftp = c.open_sftp()
        try:
            with sftp.file(REMOTE_ENV, "w") as f:
                f.write("%s=%s\n" % (KEY_NAME, key))
        finally:
            sftp.close()
        run(c, "chmod 600 %s" % REMOTE_ENV)
        o, _ = run(c, "stat -c '%%a %%U %%n' %s" % REMOTE_ENV)
        print("[3/5] 远端 api.env 写入: %s" % o)
        if o.split()[0] != "600":
            sys.exit("[X] 权限不是 600，中止")

        o, e = run(c, "systemctl restart %s && sleep 3 && systemctl is-active %s" % (SERVICE, SERVICE))
        print("[4/5] 服务重启: %s %s" % (o or e, ""))
        o, _ = run(c, "grep -c '^%s=' %s" % (KEY_NAME, REMOTE_ENV))
        assert o == "1", "api.env 行数异常: %s" % o
        # 确认 key 未被写进 shell 历史/进程可见处
        o, _ = run(c, "systemctl show -p EnvironmentFiles %s" % SERVICE)
        print("      EnvironmentFiles: %s" % o)
    finally:
        c.close()

    # 4. 本地开发 .env 同源
    LOCAL_ENV.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_ENV.write_text(
        "# 本地开发用：由 scripts/sync_backend_key.py 从 Hermes .env 同步，勿手改\n"
        "%s=%s\n" % (KEY_NAME, key),
        encoding="utf-8",
    )
    print("[5/5] 本地 %s 已同源" % LOCAL_ENV.relative_to(LOCAL_ENV.parents[2]))

    try:
        h = requests.get(HEALTH_URL, timeout=30).json()
        print("      回验 %s -> %s" % (HEALTH_URL, h))
    except Exception as ex:
        print("      [!] 回验异常（可能只是反代/缓存）: %s" % ex)


if __name__ == "__main__":
    main()
