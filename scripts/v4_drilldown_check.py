# -*- coding: utf-8 -*-
"""strategies + monthly 页数据渲染验证"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9244

def check(url, js_exprs):
    subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
    proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_dd','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try: urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=2); break
        except Exception: time.sleep(0.5)
    targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list').read())
    ws = websocket.create_connection(next(t['webSocketDebuggerUrl'] for t in targets if t.get('type')=='page'), timeout=90)
    mid = 0
    def cmd(m, p=None):
        nonlocal mid; mid += 1
        ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
        while True:
            r = json.loads(ws.recv())
            if r.get('id') == mid: return r
    def ev(e):
        r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True})
        return r.get('result',{}).get('result',{}).get('value')
    cmd('Page.enable'); cmd('Runtime.enable')
    cmd('Emulation.setDeviceMetricsOverride', {'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
    cmd('Page.navigate', {'url': url}); time.sleep(4)
    out = {}
    for name, expr in js_exprs.items():
        out[name] = ev(expr)
    shot = cmd('Page.captureScreenshot', {'format':'png'})
    path = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\\' + js_exprs.get('__shot', 'dd_check.png')
    if '__shot' in js_exprs: open(path,'wb').write(base64.b64decode(shot['result']['data']))
    ws.close(); proc.terminate(); time.sleep(1)
    return out

BASE = 'http://127.0.0.1:4322/songguo-invest'

# strategies 页：三版本关键数值
r1 = check(BASE + '/strategies/', {
    'std_etf': "document.body.innerText.includes('10.41')",
    'std_fund': "document.body.innerText.includes('9.65')",
    'std_stock': "document.body.innerText.includes('20.52')",
    'std_index': "document.body.innerText.includes('6.71')",
    'pro_reco': "document.body.innerText.includes('14.39') && document.body.innerText.includes('-9.44')",
    'pro_corr': "document.body.innerText.includes('0.95')",
    'frontier_rows': "document.querySelectorAll('#pro tbody tr').length",
    'max_rows': "document.querySelectorAll('#max tbody tr').length",
    'max_finding': "document.body.innerText.includes('Calmar 不升反降')",
    'overflow': "document.documentElement.scrollWidth > window.innerWidth",
})
print('strategies 页:', json.dumps(r1, ensure_ascii=False))

# monthly 页：tab 切换 + 表格
r2 = check(BASE + '/strategies/monthly/', {
    'rows_default': "document.querySelectorAll('#drill-body tr').length",
    'first_row': "document.querySelector('#drill-body tr')?.innerText.slice(0, 60)",
    'has_worst': "document.body.innerText.includes('最深回撤')",
    'tabs': "document.querySelectorAll('.drill-tab').length",
    'yearly_rows': "document.querySelectorAll('table.data-table tbody tr').length",
    'overflow': "document.documentElement.scrollWidth > window.innerWidth",
    '__shot': 'monthly_dd.png',
})
print('monthly 页:', json.dumps(r2, ensure_ascii=False))
