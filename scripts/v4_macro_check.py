# -*- coding: utf-8 -*-
"""macro 页移动端截图验证（390px）"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9238
URL = 'http://127.0.0.1:4322/songguo-invest/macro/'

subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_macro','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(30):
    try: urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=2); break
    except Exception: time.sleep(0.5)
targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list').read())
ws = websocket.create_connection(next(t['webSocketDebuggerUrl'] for t in targets if t.get('type')=='page'), timeout=90)
mid = 0
def cmd(m, p=None):
    global mid; mid += 1
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid: return r
def ev(e):
    r = cmd('Runtime.evaluate', {'expression': e, 'returnByValue': True})
    return r.get('result',{}).get('result',{}).get('value')
cmd('Page.enable'); cmd('Runtime.enable')
cmd('Emulation.setDeviceMetricsOverride', {'width':390,'height':844,'deviceScaleFactor':3,'mobile':True})
cmd('Page.navigate', {'url': URL}); time.sleep(5)

# 滚动到 V1 常规版区域
ev("""(() => {
  const h = Array.from(document.querySelectorAll('h2.section-title')).find(x => x.textContent.includes('V1 常规版'));
  if (h) h.scrollIntoView({block:'start'});
  return !!h;
})()""")
time.sleep(2)

info = ev("""(() => {
  const cards = Array.from(document.querySelectorAll('.metric-card'));
  const c = document.querySelectorAll('.callout');
  return {
    metricCards: cards.length,
    callouts: c.length,
    warnCallouts: document.querySelectorAll('.callout.warn').length,
    labels: cards.map(x => x.querySelector('.label')?.textContent),
    // 检查是否有横向溢出
    docWidth: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
    overflow: document.documentElement.scrollWidth > window.innerWidth,
  };
})()""")
print('结构检查:', json.dumps(info, ensure_ascii=False))
shot = cmd('Page.captureScreenshot', {'format':'png'})
open(r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\macro_v1_mobile.png','wb').write(base64.b64decode(shot['result']['data']))
print('截图已存: screenshots/v4/macro_v1_mobile.png')
ws.close(); proc.terminate()
