# -*- coding: utf-8 -*-
"""诊断 badge/fill 样式未生效原因"""
import json, subprocess, time
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9237
URL = 'http://127.0.0.1:4321/tools/stockcheck/'

subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_diag8','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
cmd('Page.navigate', {'url': URL}); time.sleep(4)
ev("""(() => { document.getElementById('sc-code').value = '600729'; document.getElementById('sc-run').click(); return true; })()""")
for i in range(12):
    time.sleep(3)
    if ev("document.getElementById('sc-result').style.display == 'block'"): break
time.sleep(1)

out = ev("""(() => {
  const b = document.getElementById('sc-badge');
  const cs = getComputedStyle(b);
  const root = getComputedStyle(document.documentElement);
  const rules = [];
  for (const sheet of document.styleSheets) {
    try {
      for (const r of sheet.cssRules) {
        if (r.selectorText && r.selectorText.includes('badge-gold')) rules.push((sheet.href ? 'LINK' : 'INLINE') + ':' + r.selectorText);
      }
    } catch(e) {}
  }
  return {
    gold500: root.getPropertyValue('--gold-500').trim(),
    gold400: root.getPropertyValue('--gold-400').trim(),
    badgeBgShort: cs.background,
    badgeBgImage: cs.backgroundImage,
    matchingSheets: rules,
    styleSheetCount: document.styleSheets.length,
  };
})()""")
print(json.dumps(out, ensure_ascii=False, indent=1))
ws.close(); proc.terminate()
