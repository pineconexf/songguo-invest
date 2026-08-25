# -*- coding: utf-8 -*-
"""线上页面真实渲染验证：CDP 加载 github.io + 检查样式 + 截图"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9227
OUT = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4'

subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1.5)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', f'--remote-debugging-port={PORT}',
     '--remote-allow-origins=*',
     '--user-data-dir=' + OUT + r'\_profile_live', 'about:blank'],
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
cmd('Page.navigate', {'url': 'https://pineconexf.github.io/songguo-invest/'})
time.sleep(6)

print('标题:', ev('document.title'))
print('CSS 加载数:', ev("Array.from(document.styleSheets).length"))
nav_color = ev("getComputedStyle(document.querySelector('.nav-link')).color")
print('nav-link 颜色:', nav_color, '| 下划线:', ev("getComputedStyle(document.querySelector('.nav-link')).textDecorationLine"))
print('品牌颜色:', ev("getComputedStyle(document.querySelector('.brand')).color"))
print('按钮1背景:', ev("getComputedStyle(document.querySelector('.hero-actions a')).backgroundColor"), '| 颜色:', ev("getComputedStyle(document.querySelector('.hero-actions a')).color"))
print('sigil 数字:', ev("document.querySelector('.sigil-num').textContent"))
print('页面总高:', ev('document.documentElement.scrollHeight'))
r = cmd('Page.captureScreenshot', {'format': 'png'})
data = base64.b64decode(r['result']['data'])
with open(OUT + r'\live_desktop_top.png', 'wb') as f:
    f.write(data)
print('live_desktop_top.png', len(data)//1024, 'KB')

# 移动端
cmd('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True})
cmd('Page.reload', {'ignoreCache': True})
time.sleep(5)
print('移动端 innerWidth:', ev('innerWidth'))
print('移动端 nav-links 溢出:', ev("document.querySelector('.nav-links').scrollWidth"), '>', ev("document.querySelector('.nav-links').clientWidth"))
print('移动端 横向溢出:', ev('document.documentElement.scrollWidth > innerWidth'))
btn_bg = ev("getComputedStyle(document.querySelector('.hero-actions a')).backgroundColor")
print('移动端 按钮背景:', btn_bg)
r = cmd('Page.captureScreenshot', {'format': 'png'})
data = base64.b64decode(r['result']['data'])
with open(OUT + r'\live_mobile_top.png', 'wb') as f:
    f.write(data)
print('live_mobile_top.png', len(data)//1024, 'KB')
ws.close(); proc.terminate()
