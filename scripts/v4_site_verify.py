# -*- coding: utf-8 -*-
"""全站链接验证 + 工具功能测试（CDP 加载线上，爬内链逐个检查 + 估值计算器输入测试）"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9229
SITE = 'https://pineconexf.github.io/songguo-invest'

subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1.5)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', f'--remote-debugging-port={PORT}',
     '--remote-allow-origins=*',
     '--user-data-dir=' + r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_links', 'about:blank'],
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

# 1) 首页：Slogan + 样式
cmd('Page.navigate', {'url': SITE + '/'})
time.sleep(5)
print('=== 首页 ===')
print('Slogan 渲染:', ev("document.querySelector('.slogan') ? document.querySelector('.slogan').textContent : 'MISSING'"))
print('nav 颜色:', ev("getComputedStyle(document.querySelector('.nav-link')).color"))
print('CSS rules:', ev("document.styleSheets[0] ? document.styleSheets[0].cssRules.length : 0"))

# 2) 爬全站内链（href 是 /songguo-invest/ 开头的路径形式）
print('=== 全站内链检查 ===')
links = ev(f"""Array.from(new Set(Array.from(document.querySelectorAll('a[href^="/songguo-invest/"]')).map(a => a.getAttribute('href'))))""") or []
# 逐页收集更多链接：访问每个主页面再爬
pages = ['/', '/philosophy/', '/methodology/', '/macro/', '/backtest/', '/portfolio/', '/ranking/', '/tools/', '/archive/', '/about/']
all_links = set(links)
for pg in pages:
    cmd('Page.navigate', {'url': SITE + pg})
    time.sleep(2.5)
    more = ev("""Array.from(document.querySelectorAll('a[href^="/songguo-invest/"]')).map(a => a.getAttribute('href'))""") or []
    all_links.update(more)
print(f'共 {len(all_links)} 个内链，逐页 HTTP 检查...')
bad = []
for link in sorted(all_links):
    url = 'https://pineconexf.github.io' + link  # link 已含 /songguo-invest/ 前缀
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        r = urllib.request.urlopen(req, timeout=15)
        code = r.status
    except Exception as e:
        code = getattr(e, 'code', 'ERR')
    status = 'OK' if code == 200 else 'BAD'
    if code != 200:
        bad.append((link, code))
    print(f'  {status} {link} ({code})')
print(f'=== 结果: {"全部通过 ✅" if not bad else "失败: " + str(bad)} ===')

# 3) 估值计算器功能测试
print('=== 估值计算器功能测试 ===')
cmd('Page.navigate', {'url': SITE + '/tools/valuator/'})
time.sleep(4)
ev("""(() => {
  const set = (id, v) => { const el = document.getElementById(id); el.value = v; el.dispatchEvent(new Event('input')); };
  set('v-pe', 12); set('v-pb', 1.2); set('v-roe', 18); set('v-dy', 3.5);
  document.getElementById('v-run').click();
  return true;
})()""")
time.sleep(1)
print('评分:', ev("document.getElementById('v-score').textContent"))
print('档位:', ev("document.getElementById('v-grade').textContent"))
print('一句话:', ev("document.getElementById('v-oneword').textContent"))
print('结果可见:', ev("document.getElementById('v-result').style.display != 'none'"))

# 4) 复利计算器
print('=== 复利计算器功能测试 ===')
cmd('Page.navigate', {'url': SITE + '/tools/compound/'})
time.sleep(4)
ev("""(() => {
  document.getElementById('c-principal').value = 100000;
  document.getElementById('c-rate').value = 24.3;
  document.getElementById('c-years').value = 14;
  document.getElementById('c-run').click();
  return true;
})()""")
time.sleep(1)
print('期末总资产:', ev("document.getElementById('c-final').textContent"), '| 明细:', ev("document.getElementById('c-meta').textContent"))
ws.close(); proc.terminate()
