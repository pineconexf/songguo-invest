# -*- coding: utf-8 -*-
"""基金体检卡 v2 CDP 实测（2026-08-30）：填代码→体检→读三卡"""
import json, subprocess, time, urllib.request, sys
import websocket

EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
PORT = 9229
PAGE = 'http://127.0.0.1:4321/songguo-invest/tools/fund-scorecard/'

subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe'], capture_output=True)
time.sleep(1.5)
proc = subprocess.Popen(
    [EDGE, '--headless=new', '--disable-gpu', f'--remote-debugging-port={PORT}',
     '--remote-allow-origins=*',
     '--user-data-dir=' + r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\screenshots\v4\_profile_fund', 'about:blank'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(30):
    try:
        urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/version', timeout=2); break
    except Exception:
        time.sleep(0.5)
targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list').read())
ws_url = next(t['webSocketDebuggerUrl'] for t in targets if t.get('type') == 'page')
ws = websocket.create_connection(ws_url, timeout=90)
mid = 0
def cmd(m, p=None):
    global mid
    mid += 1
    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get('id') == mid:
            return r
def ev(expr, await_promise=False):
    r = cmd('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True if await_promise else False})
    v = r.get('result', {}).get('result', {}).get('value')
    if v is None and 'exceptionDetails' in r.get('result', {}):
        return 'JS-ERR: ' + json.dumps(r['result']['exceptionDetails'], ensure_ascii=False)[:200]
    return v

cmd('Page.enable'); cmd('Runtime.enable')
cmd('Emulation.setDeviceMetricsOverride', {'width': 1440, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})

results = []
def check(name, ok, detail=''):
    results.append((name, ok, detail))
    print(('  GOOD ' if ok else '  BAD  '), name, detail)

print('=== fund-scorecard v2 三卡体检 ===')
cmd('Page.navigate', {'url': PAGE})
time.sleep(3)
check('页面标题', '基金体检卡' in str(ev("document.title")), str(ev("document.title")))
check('输入框 + 按钮存在', bool(ev("!!document.getElementById('fs-code')")) and bool(ev("!!document.getElementById('fs-run')")))

ev("(() => { document.getElementById('fs-code').value='002351'; document.getElementById('fs-run').click(); return true; })()")
time.sleep(12)  # pingzhongdata + jjcc 两个跨域 script

status = str(ev("document.getElementById('fs-status').textContent"))
check('状态提示', '体检完成' in status or '失败' in status, status)
nav_vis = str(ev("document.getElementById('card-nav').style.display"))
pos_vis = str(ev("document.getElementById('card-position').style.display"))
role_vis = str(ev("document.getElementById('card-role').style.display"))
xval_vis = str(ev("document.getElementById('card-xval').style.display"))
check('三卡+互验全部显现', nav_vis == '' and pos_vis == '' and role_vis == '' and xval_vis == '',
      f'nav={nav_vis} pos={pos_vis} role={role_vis} xval={xval_vis}')

base = str(ev("document.getElementById('fs-base').innerText"))
check('基础行含名称与经理', '易方达裕祥' in base and '经理' in base, base[:100])

s1m, s3m, s6m, s1y = (str(ev(f"document.getElementById('fs-{k}').textContent")) for k in ['s1m', 's3m', 's6m', 's1y'])
check('四档收益率渲染', '—' not in s1y and '%' in s1y, f'1m={s1m} 3m={s3m} 6m={s6m} 1y={s1y}')

dd1, vol1, sharpe1 = (str(ev(f"document.getElementById('fs-{k}').textContent")) for k in ['dd1', 'vol1', 'sharpe1'])
check('风险指标（回撤/波动/夏普）', '—' not in dd1 and '%' in dd1 and '—' not in vol1 and '—' not in sharpe1,
      f'MDD={dd1} VOL={vol1} SHARPE={sharpe1}')

rank = str(ev("document.getElementById('fs-rank1').textContent"))
check('同类排名分位', '同类前' in rank, rank)

star = str(ev("document.querySelector('#fs-star .slogan')?.textContent"))
score = str(ev("document.querySelector('#fs-star .value')?.textContent"))
check('松果五标准星级', star in ('可入池', '候选', '谨慎', '不达标') and score != '--', f'{score} / {star}')

alloc = str(ev("document.getElementById('fs-alloc').innerText"))
check('资产配置（股债现）', '股票占净比' in alloc and '债券占净比' in alloc, alloc[:110])

rows = ev("document.querySelectorAll('#fs-holdings tr').length")
check('前十大重仓表', rows is not None and rows >= 4, f'rows={rows}')
# 诊断：apidata 是否存在 + 页面容错提示
diag_apidata = str(ev("typeof window.apidata"))
diag_holdings = str(ev("document.getElementById('fs-holdings').innerText.slice(0,80)"))
print('  [diag] apidata type:', diag_apidata)
print('  [diag] holdings box:', diag_holdings)
# mobapi fetch 诊断
diag_fetch = str(ev('''(async () => { try { const r = await fetch("https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition?FCODE=002351&deviceid=web&plat=Wap&product=EFund&version=2.0.8"); const j = await r.json(); return "OK status=" + r.status + " datas=" + (j.Datas ? JSON.stringify(j.Datas).slice(0,120) : "null"); } catch (e) { return "FETCH-ERR: " + e.message + " | name=" + e.name; } })()''', True))
print('  [diag] mobapi fetch:', diag_fetch)

role = str(ev("document.querySelector('#fs-role .card')?.innerText"))
check('组合角色卡', '角色' in role and '权重参考' in role, role[:120])

xval = str(ev("document.getElementById('fs-xval').innerText"))
check('互验区', '互验' in xval or '匹配' in xval or '仓位' in xval, xval[:90])

# 错误代码容错
ev("(() => { document.getElementById('fs-code').value='999999'; document.getElementById('fs-run').click(); return true; })()")
time.sleep(5)
err = str(ev("document.getElementById('fs-status').textContent"))
check('错误代码容错', '失败' in err or '无效' in err, err[:80])

ws.close(); proc.terminate()
fails = [r for r in results if not r[1]]
print()
print(f'===== 汇总：{len(results)} 项，通过 {len(results)-len(fails)}，失败 {len(fails)} =====')
for f in fails:
    print('  BAD', f[0], f[2])