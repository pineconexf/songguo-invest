# -*- coding: utf-8 -*-
"""首页 V5 重构截图验证（版本选择区 + 三资产 + 净值四线）"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9246
URL = 'http://127.0.0.1:4322/songguo-invest/'

subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_home','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
cmd('Emulation.setDeviceMetricsOverride', {'width':1440,'height':900,'deviceScaleFactor':1,'mobile':False})
cmd('Page.navigate', {'url': URL}); time.sleep(4.5)
# 检查版本选择区
info = ev("""(() => {
  const btns = document.querySelectorAll('#versions .link-card');
  const metrics = document.querySelectorAll('#evidence .metric-card');
  const canvas = document.querySelectorAll('canvas').length;
  return {
    versionCards: btns.length,
    versionTitles: Array.from(btns).map(b => b.querySelector('h3')?.textContent.trim()),
    evidenceCards: metrics.length,
    evidenceVals: Array.from(metrics).map(m => m.querySelector('.value')?.textContent.trim()),
    canvases: canvas,
    overflow: document.documentElement.scrollWidth > window.innerWidth
  };
})()""")
print('首页检查:', json.dumps(info, ensure_ascii=False))
# 截图：首屏
shot = cmd('Page.captureScreenshot', {'format':'png'})
open(r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\home_v5_top.png','wb').write(base64.b64decode(shot['result']['data']))
# 滚动到版本选择区
ev("document.getElementById('versions')?.scrollIntoView({block:'start'})")
time.sleep(2)
shot = cmd('Page.captureScreenshot', {'format':'png'})
open(r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\home_v5_versions.png','wb').write(base64.b64decode(shot['result']['data']))
# 滚动到证据区
ev("document.getElementById('evidence')?.scrollIntoView({block:'start'})")
time.sleep(2)
shot = cmd('Page.captureScreenshot', {'format':'png'})
open(r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\home_v5_evidence.png','wb').write(base64.b64decode(shot['result']['data']))
ws.close(); proc.terminate()
print('截图完成')
