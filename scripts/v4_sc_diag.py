# -*- coding: utf-8 -*-
"""诊断：徽章/评分条的 DOM 计算样式"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9233
URL = 'http://127.0.0.1:4321/tools/stockcheck/'

subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_diag5','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
time.sleep(1.5)  # 等动画完成

print('=== 徽章 ===')
print('textContent:', repr(ev("document.getElementById('sc-badge').textContent")))
print('badge display:', ev("getComputedStyle(document.getElementById('sc-badge')).display"))
print('badge 尺寸:', str(ev("document.getElementById('sc-badge').offsetWidth")) + 'x' + str(ev("document.getElementById('sc-badge').offsetHeight")))
print('badge 背景:', ev("getComputedStyle(document.getElementById('sc-badge')).backgroundImage").slice(0, 60))
print('badge 颜色:', ev("getComputedStyle(document.getElementById('sc-badge')).color"))
print('=== 评分条（第一条）===')
print('track 宽:', ev("document.querySelector('.sc-bar .track').offsetWidth"))
print('fill 宽:', ev("document.querySelector('.sc-bar .fill').offsetWidth"), '/ track', ev("document.querySelector('.sc-bar .track').offsetWidth"))
print('fill 背景:', ev("getComputedStyle(document.querySelector('.sc-bar .fill')).backgroundImage").slice(0, 60))
print('fill 高度:', ev("getComputedStyle(document.querySelector('.sc-bar .fill')).height"))
print('=== 评分条总数/有fill的 ===')
print('sc-bar 总数:', ev("document.querySelectorAll('.sc-bar').length"))
print('fill 有宽度条数:', ev("Array.from(document.querySelectorAll('.sc-bar .fill')).filter(f => f.offsetWidth > 0).length"))
# 截图（滚动到结果区）
ev("document.getElementById('sc-result').scrollIntoView({behavior:'instant', block:'start'})"); time.sleep(1)
shot = cmd('Page.captureScreenshot', {'format':'png'})
open(r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\stockcheck_diag.png','wb').write(base64.b64decode(shot['result']['data']))
print('截图已存: stockcheck_diag.png')
ws.close(); proc.terminate()
