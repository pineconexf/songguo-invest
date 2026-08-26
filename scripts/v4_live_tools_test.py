# -*- coding: utf-8 -*-
"""线上实测 4 个新工具页（CDP 交互断言 + 控制台错误）"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9250
BASE = 'https://pineconexf.github.io/songguo-invest'

subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_live','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(30):
    try: urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=2); break
    except Exception: time.sleep(0.5)
targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list').read())
ws = websocket.create_connection(next(t['webSocketDebuggerUrl'] for t in targets if t.get('type')=='page'), timeout=120)
mid = 0
errors = []
def cmd(m, p=None):
    global mid; mid += 1
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid: return r
        if r.get('method') == 'Runtime.exceptionThrown':
            errors.append(str(r['params']['exceptionDetails'].get('text', ''))[:200])
def ev(e):
    r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True})
    return r.get('result',{}).get('result',{}).get('value')
cmd('Page.enable'); cmd('Runtime.enable')
def load(url, wait=5):
    errors.clear()
    cmd('Page.navigate', {'url': url}); time.sleep(wait)
    # 收集加载期间累积的页面异常
    js_errors = list(errors)
    errors.clear()
    return js_errors

results = {}

# 1. 宏观信号查询
url = f'{BASE}/tools/macro-signal/?v=live'
js_errors = load(url)
results['macro-signal'] = {
    'title': ev("document.title"),
    '当前信号': ev("document.querySelector('.metric-card .value')?.textContent.trim()"),
    '统计卡': ev("document.querySelectorAll('.metric-card').length"),
    '信号表行数': ev("document.querySelectorAll('tbody tr').length"),
    '图表canvas': ev("document.querySelectorAll('canvas').length"),
    'js_errors': js_errors,
}

# 2. ETF 组合配置
url = f'{BASE}/tools/etf-allocator/?v=live'
js_errors = load(url)
results['etf-allocator'] = {
    'title': ev("document.title"),
    '输入框': ev("document.querySelectorAll('input').length"),
    '结果表': ev("document.querySelectorAll('.data-table tbody tr, table tbody tr').length"),
    'js_errors': js_errors,
}

# 3. 基金打分卡
url = f'{BASE}/tools/fund-scorecard/?v=live'
js_errors = load(url)
results['fund-scorecard'] = {
    'title': ev("document.title"),
    '输入框': ev("document.querySelectorAll('input').length"),
    '五维条': ev("document.querySelectorAll('.bar, [class*=bar]').length"),
    'js_errors': js_errors,
}

# 4. 回测对比
url = f'{BASE}/tools/backtest-compare/?v=live'
js_errors = load(url)
results['backtest-compare'] = {
    'title': ev("document.title"),
    '输入框': ev("document.querySelectorAll('input').length"),
    '对比表': ev("document.querySelectorAll('tbody tr').length"),
    'js_errors': js_errors,
}

print(json.dumps(results, ensure_ascii=False, indent=1))
ws.close(); proc.terminate()
