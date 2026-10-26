# -*- coding: utf-8 -*-
"""个股打分卡 V4 后端部署器。

拓扑（2026-10-26 实况核对，勿凭记忆改）：
  静态站：阿里云杭州 47.104.103.33，root=/var/www/pinecone-lab（由 scripts/upload-cloud.sh 更新）
  后端  ：华纳云 45.194.22.118:8080，目录 /root/stockcheck-api，systemd 服务 stockcheck-api
          阿里云 nginx 的 /api/ → http://45.194.22.118:8080/api/
本脚本只管【后端】这一段：备份 → 上传源码 → 清缓存 → 重启 → 冒烟，任一步失败自动回滚。
静态站由一键脚本 deploy_stockscore_v4.sh 的第 4 段负责。

用法（在 01_网站开发 目录下）：
  uv run --with paramiko python scripts/deploy_stockscore_v4.py            # 部署 + 本机冒烟 + 公网冒烟
  uv run --with paramiko python scripts/deploy_stockscore_v4.py --check    # 只读巡检（不改任何文件）
  uv run --with paramiko python scripts/deploy_stockscore_v4.py --dry-run  # 只列将上传的文件
  uv run --with paramiko python scripts/deploy_stockscore_v4.py --verify-only --public   # 只验公网
  uv run --with paramiko python scripts/deploy_stockscore_v4.py --rollback  # 用最近备份回滚

环境变量：
  BE_HOST      默认 45.194.22.118
  BE_USER      默认 root
  BE_PWD       默认空 → 走 SSH 密钥（本机 root 密钥已通）；设了就用密码
  BE_KEY       私钥路径，默认 paramiko 自动查找
  REMOTE_DIR   默认 /root/stockcheck-api
  SS3_SRC      后端源码目录，默认 D:\\hermesfiles\\松果工具产品\\01_个股打分卡\\_cloud_src
  SS3_CODE     冒烟股票，默认 600519
  SKIP_DEEP    1=跳过 deep 端点（deep 冷启动 30s+，验收最长等 15 分钟）

退出码：0 成功；2 参数/环境/连接错；3 健康检查失败（已回滚）；4 冒烟未达标（未回滚）
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BE_HOST = os.environ.get('BE_HOST', '45.194.22.118')
BE_USER = os.environ.get('BE_USER', 'root')
BE_PWD = os.environ.get('BE_PWD', '') or None
BE_KEY = os.environ.get('BE_KEY', '') or None
REMOTE = os.environ.get('REMOTE_DIR', '/root/stockcheck-api')
SERVICE = 'stockcheck-api'
SITE = 'https://pinecone-lab.cn'
SRC = os.environ.get('SS3_SRC', r'D:\hermesfiles\松果工具产品\01_个股打分卡\_cloud_src')
CODE = os.environ.get('SS3_CODE', '600519')
SKIP_DEEP = os.environ.get('SKIP_DEEP', '0') == '1'
BAK_DIR = '/root/backups_ss3v4'
KEEP_BAK = 5

# 必须存在的文件（缺一个就说明 SS3_SRC 指错了，拒绝部署）
REQUIRED = ['api.py', 'stockscore.py', 'stockscore_v3.py', 'stockscore_resolve.py',
            'stockscore_narrative.py', 'stockscore_modules.py', 'stockscore_research.py',
            'stockscore_summary.py', 'stockscore_job.py', 'stockscore_persist.py']
SKIP_PREFIX = ('.', '__')
SKIP_NAME = {'api.env'}


def log(msg):
    print(msg, flush=True)


def die(msg, code=2):
    log('✗ ' + msg)
    sys.exit(code)


# ---------------- 远端会话 ----------------

class Remote:
    """华纳云后端：SSH（默认密钥，可用 BE_PWD 走密码）+ 远端 curl 取数。"""

    def __init__(self, host, user, pwd=None, key=None):
        import paramiko
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kw = dict(timeout=20, banner_timeout=30, auth_timeout=30)
        if pwd:
            kw['password'] = pwd
            kw['look_for_keys'] = False
        else:
            kw['look_for_keys'] = True
            kw['allow_agent'] = True
            if key:
                kw['key_filename'] = key
        self.c.connect(host, username=user, **kw)
        self.sftp = self.c.open_sftp()

    def run(self, cmd, timeout=180, quiet=False):
        _in, out, err = self.c.exec_command(cmd, timeout=timeout)
        o = out.read().decode('utf-8', 'replace')
        e = err.read().decode('utf-8', 'replace')
        rc = out.channel.recv_exit_status()
        if not quiet and (o.strip() or rc != 0):
            for line in (o + e).strip().splitlines():
                log('    | ' + line)
        return rc, o + e

    def put(self, local, remote):
        self.sftp.put(local, remote)

    def _curl(self, path, payload=None, timeout=600):
        if payload is None:
            cmd = 'curl -s -m %d http://127.0.0.1:8080%s' % (timeout, path)
        else:
            cmd = ("curl -s -m %d -X POST http://127.0.0.1:8080%s "
                   "-H 'Content-Type: application/json' -d '%s'"
                   % (timeout, path, json.dumps(payload)))
        rc, out = self.run(cmd, timeout=timeout + 30, quiet=True)
        return out

    def get_json(self, path, timeout=60):
        return 200, json.loads(self._curl(path, None, timeout))

    def post_json(self, path, payload, timeout=600):
        raw = self._curl(path, payload, timeout)
        try:
            return 200, json.loads(raw)
        except Exception:
            raise RuntimeError('返回非 JSON（前 200 字）：%s' % raw[:200])

    def close(self):
        try:
            self.sftp.close()
            self.c.close()
        except Exception:
            pass


class LocalHTTP:
    """公网取数：走阿里云 nginx → 华纳云后端。"""

    def get_json(self, path, timeout=30):
        with urllib.request.urlopen(SITE + path, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8', 'replace'))

    def post_json(self, path, payload, timeout=600):
        req = urllib.request.Request(SITE + path, data=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8', 'replace'))


# ---------------- 冒烟验证 ----------------

def smoke(tr, label, deep=True):
    """tr: Remote（服务器本机 8080）或 LocalHTTP（公网）。返回 (ok, 明细, 失败项)。"""
    rows, fails = [], []

    def check(name, fn, hard=True):
        try:
            ok, detail = fn()
        except urllib.error.HTTPError as e:
            ok, detail = False, 'HTTP %s' % e.code
        except Exception as e:
            ok, detail = False, '%s: %s' % (type(e).__name__, str(e)[:120])
        rows.append(('✓' if ok else ('✗' if hard else '!'), name, detail))
        if not ok and hard:
            fails.append('%s（%s）' % (name, detail))

    def _health():
        st, d = tr.get_json('/api/health')
        return st == 200 and d.get('status') == 'ok', 'status=%s' % d.get('status')

    def _core():
        st, d = tr.post_json('/api/stockscore_v3_core', {'code': CODE}, timeout=600)
        if d.get('contract') != 'core_v1':
            return False, 'contract=%r（服务端还是旧代码，没有 V4 口径）' % d.get('contract')
        if d.get('total') is None:
            return False, 'total 为空'
        v4 = d.get('_v4_neutral') or {}
        tagged = [x.get('key') for x in (d.get('dims') or []) if x.get('tags')]
        hint = '总分 %s/%s，v4=%s，有角标维度=%s' % (d.get('total'), d.get('tier'),
                                                sorted(v4.keys()), tagged or '无')
        if not v4:
            return False, hint + '；_v4_neutral 缺失'
        return True, hint

    def _neutral():
        """合规硬检查：对外页面/public 载荷不得出现内部策略术语。"""
        banned = ['策略状态', '真空带', 'VC系数', '该买', '该卖', '删票', '不补位']
        st, core = tr.post_json('/api/stockscore_v3_core', {'code': CODE}, timeout=600)
        st2, deep = tr.post_json('/api/stockscore_v3_deep', {'code': CODE}, timeout=600)
        blob = json.dumps(core, ensure_ascii=False) + json.dumps(deep, ensure_ascii=False)
        hit = [w for w in banned if w in blob]
        one = ((core.get('overview') or {}).get('one_liner') or '')
        if hit:
            return False, '出现禁用词 %s' % hit
        if not one:
            return False, 'overview.one_liner 为空'
        return True, '无禁用词；one_liner=%s…' % one[:38]

    def _modules():
        st, d = tr.post_json('/api/stockscore_v3_modules', {'code': CODE}, timeout=600)
        vb = len(((d.get('valuation') or {}).get('facts')) or [])
        kb = len(((d.get('risk') or {}).get('facts')) or [])
        if vb == 0 and kb == 0:
            return False, '估值 fact %d / 风险 fact %d' % (vb, kb)
        return (vb >= 5 and kb >= 5), '估值 fact %d / 风险 fact %d%s' % (
            vb, kb, '' if (vb >= 5 and kb >= 5) else '（低于预期 5）')

    def _deep():
        st, d = tr.post_json('/api/stockscore_v3_deep', {'code': CODE}, timeout=900)
        cnt = d.get('research_reports')
        if cnt is None:
            cnt = (d.get('research') or {}).get('count') or 0
        secs = len(d.get('sections') or [])
        chars = d.get('total_chars') or 0
        ok = secs >= 4 and chars >= 1000
        return ok, '研报 %s 篇，正文 %s 段/%s 字，改写=%s' % (cnt, secs, chars, d.get('rewritten'))

    log('\n【冒烟验证 · %s】' % label)
    check('健康检查', _health)
    check('core 端点（V4）', _core)
    check('中性口径', _neutral)
    check('modules 端点', _modules, hard=False)
    if SKIP_DEEP:
        rows.append(('-', 'deep 端点', 'SKIP_DEEP=1 跳过'))
    elif deep:
        check('deep 端点', _deep, hard=False)

    for mark, name, detail in rows:
        log('  %s %-18s %s' % (mark, name, detail))
    return (not fails), rows, fails


# ---------------- 动作 ----------------

def collect_sources():
    if not os.path.isdir(SRC):
        die('源码目录不存在：%s（可用 SS3_SRC 指定）' % SRC)
    files = []
    for fn in sorted(os.listdir(SRC)):
        p = os.path.join(SRC, fn)
        if not os.path.isfile(p) or not fn.endswith('.py'):
            continue
        if fn.startswith(SKIP_PREFIX) or fn in SKIP_NAME:
            continue
        files.append(p)
    names = {os.path.basename(f) for f in files}
    missing = [r for r in REQUIRED if r not in names]
    if missing:
        die('源码目录缺关键文件 %s（防止推错目录）' % missing)
    if 'stockscore_v3_core' not in open(os.path.join(SRC, 'api.py'), encoding='utf-8').read():
        die('api.py 里没有 stockscore_v3_core 端点，不是 V4 代码')
    return files


def do_backup(rm):
    ts = time.strftime('%Y%m%d_%H%M%S')
    tgz = '%s/ss3v4_%s.tgz' % (BAK_DIR, ts)
    rc, _ = rm.run('mkdir -p %s && cd %s && tar -czf %s --exclude=data --exclude=venv '
                   '--exclude=__pycache__ --exclude="bak_*" .' % (BAK_DIR, REMOTE, tgz), timeout=300)
    if rc != 0:
        die('远端备份失败，停止部署（不覆盖线上代码）')
    rm.run("ls -1t %s/ss3v4_*.tgz 2>/dev/null | tail -n +%d | xargs -r rm -f"
           % (BAK_DIR, KEEP_BAK + 1), quiet=True)
    log('  备份：%s' % tgz)
    return tgz


def do_upload(rm, files):
    log('\n【上传后端源码 %d 个】' % len(files))
    for p in files:
        name = os.path.basename(p)
        rm.put(p, '%s/%s' % (REMOTE, name))
        log('  → %-24s %7d B' % (name, os.path.getsize(p)))


def do_compile(rm):
    log('\n【远端语法自检】')
    rc, out = rm.run('cd %s && ./venv/bin/python -m py_compile *.py && echo COMPILE_OK' % REMOTE,
                     timeout=300)
    ok = 'COMPILE_OK' in out
    log('  py_compile %s' % ('全部通过' if ok else '失败'))
    return ok


def do_clear_cache(rm):
    log('\n【清 V4 缓存（不清会继续下发旧 payload）】')
    rc, out = rm.run('B=%s/data/persist; N=$(ls -1 $B/ss3* $B/ss3f_* $B/ss3m_* $B/ss3r_* 2>/dev/null '
                     '| wc -l); rm -f $B/ss3* $B/ss3f_* $B/ss3m_* $B/ss3r_*; rm -rf %s/__pycache__; '
                     'echo "CLEARED $N"' % (REMOTE, REMOTE), timeout=120, quiet=True)
    n = out.strip().replace('CLEARED', '').strip() or '?'
    log('  已清 ss3* 家族 %s 个 + __pycache__' % n)


def wait_health(rm, tries=30):
    for _ in range(tries):
        rc, out = rm.run('curl -s -m 5 http://127.0.0.1:8080/api/health', timeout=30, quiet=True)
        if 'ok' in out:
            log('  服务已就绪：%s' % out.strip()[:80])
            return True
        time.sleep(2)
    log('  ✗ 60s 内未就绪，最近日志：')
    rm.run('journalctl -u %s -n 40 --no-pager' % SERVICE, timeout=60)
    return False


def do_restart(rm):
    log('\n【重启 %s】' % SERVICE)
    rm.run('systemctl restart %s' % SERVICE, timeout=180, quiet=True)
    return wait_health(rm)


def do_rollback(rm, tgz=None):
    log('\n【回滚】')
    if not tgz:
        rc, out = rm.run('ls -1t %s/ss3v4_*.tgz 2>/dev/null | head -1' % BAK_DIR, quiet=True)
        tgz = out.strip()
        if not tgz:
            die('没有可用备份，回滚失败', 3)
    log('  用备份恢复：%s' % tgz)
    rm.run('cd %s && tar -xzf %s && rm -rf __pycache__ && systemctl restart %s'
           % (REMOTE, tgz, SERVICE), timeout=300, quiet=True)
    return wait_health(rm, tries=20)


def do_check(rm):
    log('【只读巡检】%s@%s:%s' % (BE_USER, BE_HOST, REMOTE))
    for label, cmd in [
        ('服务', 'systemctl is-active %s' % SERVICE),
        ('远端 py', 'ls -1 %s/*.py 2>/dev/null | wc -l' % REMOTE),
        ('V4 端点', 'grep -c stockscore_v3_core %s/api.py || true' % REMOTE),
        ('源码 md5', 'md5sum %s/api.py %s/stockscore_v3.py 2>/dev/null | cut -c1-10 | tr "\\n" " "'
         % (REMOTE, REMOTE)),
        ('缓存 ss3*', 'ls -1 %s/data/persist/ss3* 2>/dev/null | wc -l' % REMOTE),
        ('env 键名', "grep -o '^[A-Za-z_]*=' %s/api.env | tr -d '=' | tr '\\n' ' '" % REMOTE),
        ('备份', 'ls -1t %s/ss3v4_*.tgz 2>/dev/null | head -3 | tr "\\n" " "' % BAK_DIR),
        ('磁盘', 'df -h / | tail -1'),
        ('本机 core', 'curl -s -o /dev/null -w "%%{http_code}" -m 30 -X POST '
                      'http://127.0.0.1:8080/api/stockscore_v3_core '
                      '-H "Content-Type: application/json" -d \'{"code":"%s"}\'' % CODE),
    ]:
        rc, out = rm.run(cmd, timeout=90, quiet=True)
        log('  %-9s %s' % (label, (out or '').strip().replace('\n', ' | ')[:150]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只读巡检，不改任何文件')
    ap.add_argument('--dry-run', action='store_true', help='只列计划，不连服务器')
    ap.add_argument('--verify-only', action='store_true', help='只做冒烟验证')
    ap.add_argument('--public', action='store_true', help='验证公网 %s' % SITE)
    ap.add_argument('--rollback', action='store_true', help='用最近备份回滚')
    ap.add_argument('--no-rollback', action='store_true', help='失败时不自动回滚')
    a = ap.parse_args()

    files = collect_sources()

    if a.dry_run:
        log('【dry-run】后端 %s@%s:%s，服务 %s' % (BE_USER, BE_HOST, REMOTE, SERVICE))
        for p in files:
            log('  将上传 %s' % os.path.basename(p))
        log('  冒烟：服务器本机 8080 + 公网 %s（code=%s）' % (SITE, CODE))
        return 0

    if a.verify_only and a.public:
        ok, _rows, fails = smoke(LocalHTTP(), '公网 ' + SITE)
        return 0 if ok else 4

    try:
        rm = Remote(BE_HOST, BE_USER, BE_PWD, BE_KEY)
    except Exception as e:
        die('SSH 连不上 %s@%s：%s' % (BE_USER, BE_HOST, e))
    log('已连接 %s@%s' % (BE_USER, BE_HOST))

    try:
        if a.check:
            do_check(rm)
            return 0

        if a.rollback:
            return 0 if do_rollback(rm) else 3

        if a.verify_only:
            ok, _rows, fails = smoke(rm, '后端本机 8080')
            return 0 if ok else 4

        log('\n【1/6】远端前置检查')
        rc, out = rm.run('test -d %s && test -f %s/api.py && test -x %s/venv/bin/python '
                         '&& systemctl cat %s >/dev/null && echo OK'
                         % (REMOTE, REMOTE, REMOTE, SERVICE), quiet=True)
        if 'OK' not in out:
            die('远端目录/venv/服务不完整（%s / %s）' % (REMOTE, SERVICE))

        log('【2/6】备份线上代码')
        tgz = do_backup(rm)

        log('【3/6】上传源码')
        do_upload(rm, files)

        log('【4/6】语法自检 + 清缓存')
        if not do_compile(rm):
            log('  ✗ py_compile 失败，回滚')
            if not a.no_rollback:
                do_rollback(rm, tgz)
            return 3
        do_clear_cache(rm)

        log('【5/6】重启服务')
        if not do_restart(rm):
            log('  ✗ 服务起不来，回滚')
            if not a.no_rollback:
                do_rollback(rm, tgz)
            return 3

        log('【6/6】验证')
        ok, _rows, fails = smoke(rm, '后端本机 8080')
        if not ok:
            log('\n✗ 冒烟未达标：%s' % '；'.join(fails))
            log('  备份留在 %s，可用 --rollback 手动回滚' % tgz)
            return 4

        ok2, _r, fails2 = smoke(LocalHTTP(), '公网 ' + SITE)
        if not ok2:
            log('\n! 公网未达标（%s）：多半是阿里云 nginx 的 /api/ 反代没指向 45.194.22.118:8080，'
                '或静态站还没同步' % '；'.join(fails2))
        log('\n✓ 后端部署完成（备份 %s）' % tgz)
        return 0
    finally:
        rm.close()


if __name__ == '__main__':
    sys.exit(main())
