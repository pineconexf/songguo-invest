# -*- coding: utf-8 -*-
"""个股体检页面全流程实测：输入代码→查询→报告渲染验证"""
import json, subprocess, time, base64
import websocket, urllib.request

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9232
URL = 'http://127.0.0.1:4322/songguo-invest/tools/stockcheck/'

subprocess.run(['taskkill','/F','/IM','msedge.exe'], capture_output=True); time.sleep(1.5)
proc = subprocess.Popen([EDGE,'--headless=new','--disable-gpu',f'--remote-debugging-port={PORT}','--remote-allow-origins=*','--user-data-dir='+r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_sc','about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

print('页面加载:', ev("document.title"))
print('输入框存在:', ev("!!document.getElementById('sc-code')"))
print('按钮存在:', ev("!!document.getElementById('sc-run')"))

# 输入代码并点击查询
ev("""(() => {
  document.getElementById('sc-code').value = '600729';
  document.getElementById('sc-run').click();
  return true;
})()""")
time.sleep(3)
print('加载态显示:', ev("document.getElementById('sc-loading').style.display != 'none'"))

# 等待 API 返回（LLM 生成约 20 秒）
for i in range(10):
    time.sleep(5)
    done = ev("document.getElementById('sc-result').style.display == 'block'")
    if done:
        break
print('查询完成（等待' + str((i+1)*5) + '秒）:', done)

if done:
    print('股票名:', ev("document.getElementById('sc-name').textContent"))
    print('总分:', ev("document.getElementById('sc-badge').textContent"), ev("document.getElementById('sc-grade').textContent"))
    print('五维条数:', ev("document.querySelectorAll('.sc-bar').length"))
    print('评分条示例:', ev("document.querySelector('.sc-bar') ? document.querySelector('.sc-bar').textContent : 'NONE'"))
    print('报告含AI结论:', ev("document.getElementById('sc-report').textContent.includes('AI 体检结论')"))
    print('优势条数:', ev("document.querySelectorAll('#sc-report li').length"))
    print('免责声明:', ev("document.body.textContent.includes('不构成投资建议')"))
    # 截图
    shot = cmd('Page.captureScreenshot', {'format':'png'})
    open(r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\stockcheck_result.png','wb').write(base64.b64decode(shot['result']['data']))
    print('截图已存: screenshots/v4/stockcheck_result.png')
else:
    err = ev("document.getElementById('sc-error').textContent")
    print('错误:', err)
ws.close(); proc.terminate()
