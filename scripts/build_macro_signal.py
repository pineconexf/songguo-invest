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
    weeks.append({
        'week': week,
        'shibor': round(val, 4),
        'diff_bp': round(diff, 2) if diff is not None else None,
        'signal': signal,
        'action': action,
        'hs300_ret': hs300_r.get(week),
        'zz500_ret': zz500_r.get(week),
    })

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

out = {'stats': stats, 'weeks': weeks}

with open(OUT, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False)

print(f"\n✅ macro_signal.json 生成: {OUT}")
print(f"   总周数: {total} | 宽松 {loose} ({stats['loose_pct']}%) | 收紧 {tight}")
print(f"   最近5周: {[(w['week'], w['shibor'], w['diff_bp'], w['signal']) for w in weeks[-5:]]}")
