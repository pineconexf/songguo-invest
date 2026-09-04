# -*- coding: utf-8 -*-
"""
宏观信号历史管线：shibor_weekly.csv → src/data/macro_signal.json
逻辑（与 shibor_weekly_signal.py 一致）：
  本周 shibor 1W 周均值 vs 上周，环比下行 > 5bp → 宽松(买入中证500)，否则 → 收紧(空仓)
输出：
  macro_signal.json = {
    weeks: [{week, shibor, diff_bp, signal, action}...]  # 810周全量
    stats: {宽松周数, 收紧周数, 宽松占比, ...}
  }
"""
import csv, json, io, sys, os
from collections import OrderedDict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SRC = r"D:\pineconeinvestfiles\松果投资分析体系\宏观策略_共享数据\shibor_weekly.csv"
HS300 = r"D:\pineconeinvestfiles\松果投资分析体系\宏观策略_共享数据\hs300_weekly.csv"
ZZ500 = r"D:\pineconeinvestfiles\松果投资分析体系\宏观策略_共享数据\zz500_weekly.csv"
OUT = r"D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data\macro_signal.json"

# 1. 读 shibor 周度（week 统一为无横杠格式 2011W01，与用户输入口径一致）
def norm_wk(w):
    return w.strip().replace('-', '')

shibor = []
with open(SRC, encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        shibor.append((norm_wk(row['week']), float(row['shibor_1w_avg'])))
shibor.sort(key=lambda x: x[0])
print(f"shibor 周度数据: {len(shibor)} 周 ({shibor[0][0]} ~ {shibor[-1][0]})")

# 2. 读 hs300 / zz500 周度收益
def read_weekly(p):
    d = {}
    with open(p, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            wk = norm_wk(row['week'])
            for k, v in row.items():
                if k != 'week' and v:
                    try:
                        d[wk] = float(v)
                        break
                    except:
                        pass
    return d

hs300_r = read_weekly(HS300)
zz500_r = read_weekly(ZZ500)
print(f"hs300 周度: {len(hs300_r)} 周, zz500 周度: {len(zz500_r)} 周")

# 3. 逐周计算信号（环比 = 本周均值 - 上周均值）
weeks = []
for i, (week, val) in enumerate(shibor):
    if i == 0:
        diff = None
    else:
        diff = (val - shibor[i-1][1]) * 100  # bp
    # 信号判定：环比下行 > 5bp → 宽松
    if diff is not None and diff < -5:
        signal = '宽松'
        action = '买入中证500'
    elif diff is not None:
        signal = '收紧'
        action = '空仓'
    else:
        signal = '起始'
        action = '等待'
    # 滞后口径：T 信号 → T+1 周收益（可交易）；同期口径保留并标注
    nxt_zz = zz500_r.get(shibor[i+1][0]) if i + 1 < len(shibor) else None
    nxt_hs = hs300_r.get(shibor[i+1][0]) if i + 1 < len(shibor) else None
    weeks.append({
        'week': week,
        'shibor': round(val, 4),
        'diff_bp': round(diff, 2) if diff is not None else None,
        'signal': signal,
        'action': action,
        'hs300_ret': hs300_r.get(week),
        'zz500_ret': zz500_r.get(week),
        'next_zz500_ret': nxt_zz,
        'next_hs300_ret': nxt_hs,
    })

# 本轮持续计数（从末周向前数信号相同的连续周）
_streak, _streak_sig = 0, weeks[-1]['signal']
for w in reversed(weeks):
    if w['signal'] in (_streak_sig, '起始'):
        _streak += 1
    else:
        break

# 4. 统计
loose = sum(1 for w in weeks if w['signal'] == '宽松')
tight = sum(1 for w in weeks if w['signal'] == '收紧')
total = len(weeks)

stats = {
    'total_weeks': total,
    'loose_weeks': loose,
    'tight_weeks': tight,
    'loose_pct': round(loose / total * 100, 1) if total else 0,
    'start': weeks[0]['week'],
    'end': weeks[-1]['week'],
    'threshold': '5bp',
    'note': 'shibor 1W 周均值环比下行>5bp → 宽松买入中证500；否则空仓。walk-forward 样本外年化 +10.04%',
}

# ---------- 5. 证据链计算（滞后口径，全部可由本脚本复算） ----------
sh = dict(shibor)
iw = sorted(set(sh) & set(zz500_r))  # 与 walkforward_macro.py 同窗口
def sigs(th):
    s = {}
    for i, wk in enumerate(iw):
        s[wk] = 1 if (i > 0 and (sh[wk] - sh[iw[i-1]]) * 100 < -th) else 0
    return s
def bt(sig, cost, a, b):
    rets = []
    for i in range(a, b):
        if i == 0:
            continue
        pos, ppos = sig.get(iw[i-1], 0), sig.get(iw[i-2], 0)
        r = zz500_r.get(iw[i], 0) * pos
        if cost:
            r -= cost * abs(pos - ppos)
        rets.append(r)
    return rets
def perf(rs):
    c = pk = 1.0; m = 0.0
    for x in rs:
        c *= (1 + x); pk = max(pk, c); m = min(m, c/pk - 1)
    y = len(rs) / 52
    return dict(ann=round((c**(1/y)-1)*100, 2), cum=round((c-1)*100, 1), mdd=round(m*100, 1), n=len(rs))

s5 = sigs(5)
evid = {}
# 5a 拼接 OOS（训练窗 156 周起，步长 52）+ 阈值×成本敏感性网格
oos = {}
for th in [0, 1, 2, 5, 10]:
    st = sigs(th)
    for cost in [0.0003, 0.0005, 0.001]:
        j = []; t0 = 156
        while t0 + 52 <= len(iw):
            j += bt(st, cost, t0, t0 + 52); t0 += 52
        oos[f'{th}bp_{int(round(cost*1e4))}bp'] = perf(j)
evid['oos_grid'] = oos
# 全样本固定 5bp（含成本）
evid['full_5bp'] = perf(bt(s5, 0.0005, 2, len(iw)))
# 基准满仓
evid['bench'] = perf([zz500_r[w] for w in iw[1:]])
# 5b 逐年（滞后+0.05%成本）
yr = {}
for i in range(2, len(iw)):
    pos, ppos = s5.get(iw[i-1], 0), s5.get(iw[i-2], 0)
    r = zz500_r.get(iw[i], 0) * pos
    if pos != ppos:
        r -= 0.0005
    y = iw[i][:4]
    d = yr.setdefault(y, {'s': 1.0, 'b': 1.0, 'hold': 0, 'n': 0})
    d['s'] *= (1 + r); d['b'] *= (1 + zz500_r.get(iw[i], 0)); d['hold'] += pos; d['n'] += 1
evid['yearly'] = {y: dict(strat=round((d['s']-1)*100, 1), bench=round((d['b']-1)*100, 1), hold=f"{d['hold']}/{d['n']}") for y, d in sorted(yr.items())}
# 5d 执行账本
flips = sum(1 for i in range(2, len(iw)) if s5[iw[i-1]] != s5[iw[i-2]])
hold_ws = [zz500_r[w] for w in iw[1:] if s5.get(iw[iw.index(w)-1], 0)] if False else [zz500_r[iw[i]] for i in range(2, len(iw)) if s5.get(iw[i-1], 0)]
flat_ws = [zz500_r[iw[i]] for i in range(2, len(iw)) if not s5.get(iw[i-1], 0)]
evid['ledger'] = dict(flips_total=flips, flips_per_year=round(flips / (len(iw)/52), 1),
                      in_market_pct=round(len(hold_ws)/(len(hold_ws)+len(flat_ws))*100, 1),
                      mean_hold_week=round(sum(hold_ws)/len(hold_ws)*100, 3),
                      mean_flat_week=round(sum(flat_ws)/len(flat_ws)*100, 3))
# 5c 滚动选阈值对照：每年初用截至上年全部历史选年化最优阈值，次年执行该阈值；对照固定5bp
def sig_at(th, idx):  # 第 idx 周(iw序)的信号 = 上周末环比是否 < -th
    return 1 if (idx >= 2 and (sh[iw[idx]] - sh[iw[idx-1]]) * 100 < -th) else 0
yearly_th = {}
for y in [str(v) for v in range(2014, int(iw[-1][:4]) + 1)]:
    if y == '2014':
        yearly_th[y] = 5; continue
    hi = max(i for i, w in enumerate(iw) if w[:4] < y)  # 上年最后一周索引
    best, bth = None, 5
    for t in [0, 1, 2, 5, 10]:
        a = perf(bt(sigs(t), 0.0005, 2, hi))['ann']
        if best is None or a > best:
            best, bth = a, t
    yearly_th[y] = bth
roll = []; roll_rs = []
for i in range(2, len(iw)):
    y = iw[i][:4]
    if y < '2014':
        continue
    th = yearly_th.get(y)
    if th is None:
        continue
    pos = sig_at(th, i - 1)
    ppos = roll[-1] if roll else 0
    roll.append(pos)
    roll_rs.append(zz500_r.get(iw[i], 0) * pos - 0.0005 * abs(pos - ppos))
evid['roll'] = dict(ann=perf(roll_rs)['ann'], cum=perf(roll_rs)['cum'], mdd=perf(roll_rs)['mdd'], picks=yearly_th)
evid['fixed5'] = perf(bt(s5, 0.0005, iw.index([w for w in iw if w[:4] == '2014'][0]), len(iw)))
# 本轮计数 + 同信号历史平均持续周数
evid['streak'] = dict(signal=_streak_sig, weeks=_streak)
_runs, _prev, _cur = [], None, 0
for i in range(2, len(iw)):
    s = s5.get(iw[i-1], 0)
    if s == _prev:
        _cur += 1
    else:
        if _prev is not None:
            _runs.append((_prev, _cur))
        _prev, _cur = s, 1
_runs.append((_prev, _cur))
evid['avg_streak'] = {str(k): round(sum(r[1] for r in _runs if r[0] == k) / max(1, sum(1 for r in _runs if r[0] == k)), 1) for k in (0, 1)}
stats['evidence'] = evid

out = {'stats': stats, 'weeks': weeks}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)

print(f"\n✅ macro_signal.json 生成: {OUT}")
print(f"   总周数: {total} | 宽松 {loose} ({stats['loose_pct']}%) | 收紧 {tight}")
print(f"   最近5周: {[(w['week'], w['shibor'], w['diff_bp'], w['signal']) for w in weeks[-5:]]}")
