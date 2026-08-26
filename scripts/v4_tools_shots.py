# -*- coding: utf-8 -*-
"""4 个新工具页截图存档（首屏 + 结果态）"""
import json, subprocess, time, urllib.request, os
import websocket

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9231
BASE = 'http://127.0.0.1:4322/songguo-invest'
OUT = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\tools_20260826'
os.makedirs(OUT, exist_ok=True)

subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1.5)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', f'--remote-debugging-port={PORT}',
     '--remote-allow-origins=*',
     '--user-data-dir=' + r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_shot', 'about:blank'],
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
    return r.get('result', {}).get('result', {}).get('value')

cmd('Page.enable'); cmd('Runtime.enable')
cmd('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})

def shot(name, url, prep=None):
    cmd('Page.navigate', {'url': url})
    time.sleep(3)
    if prep:
        ev(prep); time.sleep(1)
    shot = cmd('Page.captureScreenshot', {'format': 'png'})
    p = os.path.join(OUT, name + '.png')
    open(p, 'wb').write(base64.b64decode(shot['result']['data']))
    print('saved', p)

import base64
shot('1_macro_signal', BASE + '/tools/macro-signal/')
shot('2_etf_allocator_result', BASE + '/tools/etf-allocator/',
     "document.getElementById('ea-amount').value='200000'; document.getElementById('ea-run').click(); true")
shot('3_fund_scorecard_result', BASE + '/tools/fund-scorecard/',
     """(() => { document.getElementById('fs-ret').value='12.5'; document.getElementById('fs-mdd').value='6'; document.getElementById('fs-fee').value='0.8'; document.getElementById('fs-size').value='85'; document.getElementById('fs-mgr').value='6'; document.getElementById('fs-run').click(); return true; })()""")
shot('4_backtest_compare_result', BASE + '/tools/backtest-compare/',
     """(() => { document.getElementById('bc-ar-a').value='15'; document.getElementById('bc-mdd-a').value='8'; document.getElementById('bc-year-a').value='10'; document.getElementById('bc-ar-b').value='24.3'; document.getElementById('bc-mdd-b').value='22.66'; document.getElementById('bc-year-b').value='14'; document.getElementById('bc-run').click(); return true; })()""")
shot('5_tools_overview', BASE + '/tools/')
ws.close(); proc.terminate()
print('DONE')
