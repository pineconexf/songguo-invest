# -*- coding: utf-8 -*-
"""档案中心验证：搜索过滤 + 明细表渲染"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9248

def check(url, js_exprs):
    subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
    proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_arch','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    if '__shot' in js_exprs:
        open(r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\\' + js_exprs['__shot'],'wb').write(base64.b64decode(shot['result']['data']))
    ws.close(); proc.terminate(); time.sleep(1)
    return out

BASE = 'http://127.0.0.1:4322/songguo-invest'

# 档案总览：卡片 + 搜索
r1 = check(BASE + '/archive/', {
    'card_count': "document.querySelectorAll('.archive-card').length",
    'groups': "Array.from(document.querySelectorAll('.archive-group .section-kicker')).map(x => x.textContent.trim())",
    '__shot': 'archive_v2.png',
})
print('档案总览:', json.dumps(r1, ensure_ascii=False))

# 搜索过滤测试（输入 etf）
subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1)
# 用第二个检查：搜 ETF
r2 = check(BASE + '/archive/', {
    'search_etf': """(() => {
      const input = document.getElementById('archive-search');
      input.value = 'ETF'; input.dispatchEvent(new Event('input'));
      const visible = Array.from(document.querySelectorAll('.archive-card')).filter(c => c.style.display !== 'none').map(c => c.dataset.title);
      return visible;
    })()""",
})
print('搜索 ETF:', json.dumps(r2, ensure_ascii=False))

# ETF 档案明细
r3 = check(BASE + '/archive/etf/', {
    'rows': "document.querySelectorAll('tbody tr').length",
    'first': "document.querySelector('tbody tr')?.innerText.slice(0, 50)",
    'pieces': "document.querySelectorAll('tbody tr td b').length",
    'overflow': "document.documentElement.scrollWidth > window.innerWidth",
})
print('ETF 档案:', json.dumps(r3, ensure_ascii=False))

# Pro 档案
r4 = check(BASE + '/archive/pro/', {
    'rows': "document.querySelectorAll('tbody tr').length",
    'worst': "document.body.innerText.includes('最深回测')",
    'yearly': "document.querySelectorAll('section:nth-of-type(3) tbody tr, .card table tbody tr').length",
    'overflow': "document.documentElement.scrollWidth > window.innerWidth",
})
print('Pro 档案:', json.dumps(r4, ensure_ascii=False))
