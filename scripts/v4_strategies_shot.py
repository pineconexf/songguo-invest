# -*- coding: utf-8 -*-
"""策略总览 + ETF 详情页截图验证（桌面+移动）"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9239

def shot(url, out, w=1440, h=900, mobile=False, scroll_sel=None):
    subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
    proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_str','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    cmd('Emulation.setDeviceMetricsOverride', {'width':w,'height':h,'deviceScaleFactor':2 if mobile else 1,'mobile':mobile})
    cmd('Page.navigate', {'url': url}); time.sleep(4)
    if scroll_sel:
        ev(f"(() => {{ const el = document.querySelector({json.dumps(scroll_sel)}); if (el) el.scrollIntoView({{block:'start'}}); return !!el; }})()")
        time.sleep(2)
    info = ev("""(() => ({
        charts: document.querySelectorAll('.chart canvas').length,
        overflow: document.documentElement.scrollWidth > window.innerWidth,
        dw: document.documentElement.scrollWidth, vw: window.innerWidth,
    }))()""")
    shot = cmd('Page.captureScreenshot', {'format':'png'})
    path = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\\' + out
    open(path,'wb').write(base64.b64decode(shot['result']['data']))
    print(f'{out}: {json.dumps(info, ensure_ascii=False)}')
    ws.close(); proc.terminate(); time.sleep(1)

BASE = 'http://127.0.0.1:4322/songguo-invest'
shot(BASE + '/strategies/', 'strategies_desktop.png', 1440, 900, False)
shot(BASE + '/strategies/etf/', 'strategies_etf.png', 1440, 900, False, '.chart')
shot(BASE + '/strategies/', 'strategies_mobile.png', 390, 844, True, 'h2.section-title')
