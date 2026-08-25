# -*- coding: utf-8 -*-
"""首页滚动叙事验收：Edge headless + CDP，桌面 5 个滚动点 + 移动端 2 点 + 横向溢出检查"""
import json, os, subprocess, time, base64, sys

import websocket

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
OUT = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4'
os.makedirs(OUT, exist_ok=True)
PORT = 9223
URL = 'http://127.0.0.1:4321/'

# 清场
subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1.5)

proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', f'--remote-debugging-port={PORT}',
     '--remote-allow-origins=*',
     '--user-data-dir=' + os.path.join(OUT, '_profile'), 'about:blank'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
# 等调试端口
for _ in range(30):
    try:
        import urllib.request
        urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=2)
        break
    except Exception:
        time.sleep(0.5)

ws_url = None
import urllib.request
targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list').read())
for t in targets:
    if t.get('type') == 'page':
        ws_url = t['webSocketDebuggerUrl']
        break
assert ws_url, 'no page target'

ws = websocket.create_connection(ws_url, timeout=30)
msg_id = 0

def cmd(method, params=None):
    global msg_id
    msg_id += 1
    ws.send(json.dumps({'id': msg_id, 'method': method, 'params': params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get('id') == msg_id:
            return resp

def evaluate(expr):
    r = cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
    return r.get('result', {}).get('result', {}).get('value')

def set_viewport(w, h):
    cmd('Emulation.setDeviceMetricsOverride', {'width': w, 'height': h, 'deviceScaleFactor': 1, 'mobile': False})

def shot(name):
    r = cmd('Page.captureScreenshot', {'format': 'png'})
    data = base64.b64decode(r['result']['data'])
    path = os.path.join(OUT, name)
    with open(path, 'wb') as f:
        f.write(data)
    return len(data)

cmd('Page.enable')
cmd('Runtime.enable')

# ---- 桌面 1440x900 ----
set_viewport(1440, 900)
cmd('Page.navigate', {'url': URL})
time.sleep(3.5)  # 等 JS/图表

# 横向溢出检查（桌面）
overflow = evaluate('document.documentElement.scrollWidth > window.innerWidth')
print(f'桌面横向溢出: {overflow}')

# 页面总高 + 5 个滚动点
total_h = evaluate('document.documentElement.scrollHeight')
print(f'桌面页面总高: {total_h}px')
points = [('top', 0), ('q25', 0.25), ('q50', 0.5), ('q75', 0.75), ('bottom', 1.0)]
for name, ratio in points:
    y = int((total_h - 900) * ratio)
    evaluate(f'window.scrollTo(0, {y})')
    time.sleep(1.2)  # 等 reveal/点亮动画
    # 强制触发一次 scroll 检查（防偶发时序未点亮）
    evaluate("window.dispatchEvent(new Event('scroll'))")
    time.sleep(0.8)
    # 检查当前视口内 reveal 是否已点亮
    reveal_missing = evaluate("Array.from(document.querySelectorAll('.reveal')).filter(e => { const r = e.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0 && !e.classList.contains('in'); }).length")
    steps_lit = evaluate("document.querySelectorAll('.steps-step.lit').length")
    steps_total = evaluate("document.querySelectorAll('.steps-step').length")
    shot(f'desktop_{name}.png')
    print(f'  {name} y={y}: 截图OK, 视口内未点亮reveal={reveal_missing}, 审计点亮={steps_lit}/{steps_total}')

# count-up 检查（数据墙数字是否已递增）
sigil = evaluate("document.querySelector('.sigil-num').textContent")
print(f'首屏数字锚点: {sigil}')

# ---- 移动端 390x844 ----
set_viewport(390, 844)
cmd('Page.navigate', {'url': URL})
time.sleep(3.5)
ov_m = evaluate('document.documentElement.scrollWidth > window.innerWidth')
print(f'移动端横向溢出: {ov_m}')
shot('mobile_top.png')
h_m = evaluate('document.documentElement.scrollHeight')
evaluate(f'window.scrollTo(0, {h_m - 844})')
time.sleep(1.5)
shot('mobile_bottom.png')
print(f'移动端: 总高{h_m}px, 首屏+底部截图OK')

ws.close()
proc.terminate()
print('=== 验收截图完成 ===')
