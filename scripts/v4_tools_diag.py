# -*- coding: utf-8 -*-
"""macro-signal 页诊断 v2：同步收 console 消息"""
import json, subprocess, time, urllib.request
import websocket

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9230
BASE = 'http://127.0.0.1:4322/songguo-invest'

subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1.5)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', f'--remote-debugging-port={PORT}',
     '--remote-allow-origins=*',
     '--user-data-dir=' + r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_diag2', 'about:blank'],
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
console_msgs = []
def cmd(m, p=None):
    global mid
    mid += 1
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('method') in ('Runtime.consoleAPICalled', 'Runtime.exceptionThrown'):
            console_msgs.append(r)
        if r.get('id') == mid:
            return r
def ev(expr):
    r = cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    res = r.get('result', {})
    if 'exceptionDetails' in res:
        return 'JS-ERR: ' + json.dumps(res['exceptionDetails'], ensure_ascii=False)[:300]
    return res.get('result', {}).get('value')

cmd('Page.enable'); cmd('Runtime.enable')
cmd('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
cmd('Page.navigate', {'url': BASE + '/tools/macro-signal/'})
time.sleep(4)
console_msgs.clear()

print('1. chart div:', ev("document.querySelectorAll('.chart').length"))
print('2. data-option len:', ev("document.querySelector('.chart') ? document.querySelector('.chart').dataset.option.length : -1"))
print('3. canvas:', ev("document.querySelectorAll('.chart canvas').length"))
print('4. echarts:', ev("typeof echarts"))
print('5. ALL_WEEKS:', ev("typeof ALL_WEEKS !== 'undefined' ? ALL_WEEKS.length : 'UNDEF'"))
print('6. byWeek:', ev("typeof byWeek !== 'undefined' ? byWeek.size : 'UNDEF'"))
print('7. run btn:', ev("!!document.getElementById('ms-run')"))
print('8. click 查询:')
print('   ', ev("(() => { try { document.getElementById('ms-query').value='2026-W32'; document.getElementById('ms-run').click(); return 'clicked ok'; } catch(e) { return 'ERR: ' + e.message; } })()"))
time.sleep(1)
print('9. result:', str(ev("document.getElementById('ms-result').innerText"))[:150])
print('10. 直接调函数测试:')
print('   ', ev("(() => { const w = byWeek.get('2026-W32'); return w ? JSON.stringify(w) : 'NOT FOUND'; })()"))
print()
print('=== console 消息 ===')
for c in console_msgs[-10:]:
    if c.get('method') == 'Runtime.consoleAPICalled':
        args = c['params'].get('args', [])
        print(' console.' + c['params']['type'] + ':', ' | '.join(json.dumps(a.get('value', a.get('description', '')), ensure_ascii=False)[:120] for a in args))
    else:
        ed = c['params'].get('exceptionDetails', {})
        print(' EXCEPTION:', json.dumps(ed, ensure_ascii=False)[:400])
proc.terminate()
