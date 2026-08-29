# -*- coding: utf-8 -*-
"""4 个新工具页 CDP 交互实测 + 全站本地链接验证（2026-08-26 谷时任务）"""
import json, subprocess, time, urllib.request, os, re, glob
import websocket

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9229
BASE = 'http://127.0.0.1:4322/songguo-invest'
SIM = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\_local_sim\songguo-invest'

subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1.5)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', f'--remote-debugging-port={PORT}',
     '--remote-allow-origins=*',
     '--user-data-dir=' + r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_tools', 'about:blank'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(30):
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=2); break
    except Exception:
        time.sleep(0.5)
targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list').read())
ws_url = next(t['webSocketDebuggerUrl'] for t in targets if t.get('type') == 'page')
ws = websocket.create_connection(ws_url, timeout=60)
mid = 0
def cmd(m, p=None):
    global mid
    mid += 1
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid:
            return r
def ev(expr):
    r = cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    v = r.get('result', {}).get('result', {}).get('value')
    if v is None and 'exceptionDetails' in r.get('result', {}):
        return 'JS-ERR: ' + json.dumps(r['result']['exceptionDetails'], ensure_ascii=False)[:200]
    return v

cmd('Page.enable'); cmd('Runtime.enable')
cmd('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})

results = []
def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('  ✅' if ok else '  ❌'), name, detail)

# ========== 1) 宏观信号查询 ==========
print('=== 1. macro-signal 宏观信号查询 ===')
cmd('Page.navigate', {'url': BASE + '/tools/macro-signal/'})
time.sleep(3)
check('当前信号渲染', '收紧（防守）' in str(ev("document.querySelector('.section-title').textContent")))
check('图表 canvas 渲染', bool(ev("document.querySelectorAll('.chart canvas').length >= 1")))
check('信号表行数=24', ev("document.querySelectorAll('.data-table tbody tr').length") == 24)
# 查询周号
ev("""(() => { const i=document.getElementById('ms-query'); i.value='2026W32'; document.getElementById('ms-run').click(); return true; })()""")
time.sleep(0.8)
q1 = str(ev("document.getElementById('ms-result').innerText"))
check('查询 2026W32', '宽松' in q1 and '2026W32' in q1)
# 查询年份
ev("""(() => { const i=document.getElementById('ms-query'); i.value='2015'; document.getElementById('ms-run').click(); return true; })()""")
time.sleep(0.8)
q2 = str(ev("document.getElementById('ms-result').innerText"))
check('查询 2015 年份', '2015 年信号汇总' in q2 and '周' in q2)

# ========== 2) ETF 组合配置 ==========
print('=== 2. etf-allocator ETF 组合配置 ===')
cmd('Page.navigate', {'url': BASE + '/tools/etf-allocator/'})
time.sleep(3)
ev("""(() => { document.getElementById('ea-amount').value='200000'; document.getElementById('ea-run').click(); return true; })()""")
time.sleep(0.8)
rows = ev("document.querySelectorAll('#ea-rows tr').length")
total = str(ev("document.getElementById('ea-total').textContent"))
hint = str(ev("document.getElementById('ea-hint').textContent"))
check('结果表 4 行', rows == 4, f'rows={rows}')
check('金额显示', '20.0 万' in total, total)
check('权重校验', '权重 100% ✓' in hint, hint)
first = str(ev("document.querySelector('#ea-rows tr td:nth-child(6)').textContent"))
check('份额计算(511010 25%→3手300份)', '300 份（3 手）' in first, first)
# 权重错误提示
ev("""(() => { document.getElementById('ea-w0').value='50'; document.getElementById('ea-run').click(); return true; })()""")
time.sleep(0.5)
hint2 = str(ev("document.getElementById('ea-hint').textContent"))
check('权重≠100% 报错', '≠100%' in hint2, hint2)

# ========== 3) 基金打分卡 ==========
print('=== 3. fund-scorecard 基金打分卡 ===')
cmd('Page.navigate', {'url': BASE + '/tools/fund-scorecard/'})
time.sleep(3)
ev("""(() => {
  document.getElementById('fs-ret').value='12.5'; document.getElementById('fs-mdd').value='6';
  document.getElementById('fs-fee').value='0.8'; document.getElementById('fs-size').value='85';
  document.getElementById('fs-mgr').value='6'; document.getElementById('fs-run').click(); return true;
})()""")
time.sleep(0.8)
score = str(ev("document.getElementById('fs-score').textContent"))
grade = str(ev("document.getElementById('fs-grade').textContent"))
bars = ev("document.querySelectorAll('#fs-bars > div').length")
check('打分结果', score.isdigit(), f'score={score}')
check('档位判定', '优质' in grade or '良好' in grade or '一般' in grade or '不达标' in grade, grade)
check('五维条形 5 条', bars == 5, f'bars={bars}')
# 满分样例：收益20 回撤5 费率0.5 规模50 经理7 → 30+25+15+15+15=100
ev("""(() => {
  document.getElementById('fs-ret').value='20'; document.getElementById('fs-mdd').value='5';
  document.getElementById('fs-fee').value='0.5'; document.getElementById('fs-size').value='50';
  document.getElementById('fs-mgr').value='7'; document.getElementById('fs-run').click(); return true;
})()""")
time.sleep(0.5)
score2 = str(ev("document.getElementById('fs-score').textContent"))
check('满分样例=100', score2 == '100', f'score={score2}')

# ========== 4) 回测对比 ==========
print('=== 4. backtest-compare 回测对比 ===')
cmd('Page.navigate', {'url': BASE + '/tools/backtest-compare/'})
time.sleep(3)
ev("""(() => {
  document.getElementById('bc-name-a').value='我的策略'; document.getElementById('bc-ar-a').value='15';
  document.getElementById('bc-mdd-a').value='8'; document.getElementById('bc-year-a').value='10';
  document.getElementById('bc-vol-a').value='10';
  document.getElementById('bc-name-b').value='松果V31'; document.getElementById('bc-ar-b').value='24.3';
  document.getElementById('bc-mdd-b').value='22.66'; document.getElementById('bc-year-b').value='14';
  document.getElementById('bc-vol-b').value='18'; document.getElementById('bc-run').click(); return true;
})()""")
time.sleep(0.8)
rows = ev("document.querySelectorAll('#bc-rows tr').length")
calmarA = str(ev("document.querySelectorAll('#bc-rows tr')[2].cells[1].textContent"))
calmarB = str(ev("document.querySelectorAll('#bc-rows tr')[2].cells[2].textContent"))
verdict = str(ev("document.getElementById('bc-verdict').textContent"))
check('对比表行数', rows >= 4, f'rows={rows}')
check('Calmar A=1.88', '1.88' in calmarA, calmarA)
check('Calmar B=1.07', '1.07' in calmarB, calmarB)
check('结论含 A 更优', '我的策略' in verdict and '高于' in verdict, verdict[:60])

# ========== 5) 工具页总览 ==========
print('=== 5. tools 总览页 ===')
cmd('Page.navigate', {'url': BASE + '/tools/'})
time.sleep(3)
live = ev("document.querySelectorAll('.tool-status.live').length")
soon = ev("document.querySelectorAll('.tool-status.soon').length")
check('已上线工具数', live == 7, f'live={live}')
check('剩余开发中=3（资讯/行业报告/行业对比）', soon == 3, f'soon={soon}')

ws.close(); proc.terminate()

# ========== 6) 全站本地链接验证（无盲区） ==========
print('=== 6. 全站链接验证（本地模拟目录）===')
def load_links(html):
    return re.findall(r'(?:href|src)="([^"]+)"', html)
bad = []
checked = set()
for f in glob.glob(os.path.join(SIM, '**', '*.html'), recursive=True):
    rel = os.path.relpath(f, SIM).replace('\\', '/')
    html = open(f, encoding='utf-8').read()
    for link in load_links(html):
        if link.startswith(('http://', 'https://', '#', 'mailto:', 'data:', 'javascript:')):
            continue
        if '#' in link:
            link = link.split('#')[0]  # 页面内锚点：只验证文件部分
        if not link:
            continue
        if link.startswith('/'):
            # 站内绝对路径：剥掉 /songguo-invest/ 前缀（若带），映射到 SIM 根
            rel = link.lstrip('/')
            if rel.startswith('songguo-invest/'):
                rel = rel[len('songguo-invest/'):]
            target = os.path.normpath(os.path.join(SIM, rel)).replace('\\', '/')
        else:
            base_dir = os.path.dirname(f)
            target = os.path.normpath(os.path.join(base_dir, link)).replace('\\', '/')
        key = target
        if key in checked: continue
        checked.add(key)
        ok = os.path.exists(target) or os.path.exists(target + '/index.html')
        if not ok:
            bad.append((rel, link))
print(f'共检查 {len(checked)} 个资源引用，坏链 {len(bad)}')
for b in bad[:20]:
    print('  ❌', b[0], '→', b[1])
print('=== 全站链接: ' + ('全部通过 ✅' if not bad else f'失败 {len(bad)}') + ' ===')

print()
print('===== 汇总 =====')
fails = [r for r in results if not r[1]]
print(f'功能断言 {len(results)} 项，通过 {len(results)-len(fails)}，失败 {len(fails)}')
for f_ in fails: print('  ❌', f_[0], f_[2])
