# -*- coding: utf-8 -*-
"""
14年历史选股档案批量生成：每月 Top5 名单 + 投前投后对比
数据源：pick_monthly.py 相同逻辑（复用 audit_rerun_p1.py 数据基础）
输出：src/data/history_records.json
  {
    months: [{
      ym: '201204',
      picks: [{ts_code, name, industry, fcf_ev, vc}...],
      prev_ret: [投前月收益...],   # 选股时点的前月收益（止损过滤依据）
      next_ret: [投后月收益...],   # 持仓月的实际收益
    }...]
  }
"""
import sys, io, json, os
import pandas as pd
import numpy as np
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

OUT_DIR = Path(r"D:\pineconeinvestfiles\V24校验")
exec(open(OUT_DIR / "audit_rerun_p1.py", encoding="utf-8").read().split("# ---------- 5. 执行 ----------")[0])

sys.path.insert(0, r"D:\pineconeinvestfiles\松果纯多头策略")
from pick_monthly import pick_month  # 复用选股逻辑

# 目标：2012-04 ~ 2026-07 每月
months = []
# 用全局的季度数据构建可用的持仓月列表
valid_months = []
for q in ALL_QUARTERS:
    merged = load_quarter(q)
    if merged is None:
        continue
    for col in merged.columns:
        if col.startswith('投资回报率_') and len(col) == 14 and col[6:].isdigit():
            m = col[6:]  # 完整月末日期 20160430
            ym = m[:6]
            if 201204 <= int(ym) <= 202607:
                valid_months.append(m)
valid_months = sorted(set(valid_months))
print(f"可回算的持仓月: {len(valid_months)} 个 ({valid_months[0]} ~ {valid_months[-1]})")

records = []
for m in valid_months:
    ym = m[:6]
    # 找报告期
    qe = None
    for q in ALL_QUARTERS:
        merged = load_quarter(q)
        if merged is None:
            continue
        if f"投资回报率_{m}" in merged.columns:
            qe = q
            break
    if qe is None:
        continue
    merged = load_quarter(qe)
    try:
        picks, n = pick_month(qe, merged, m)
    except Exception as e:
        print(f"  {ym}: 失败 {e}")
        continue
    rec = {'ym': ym, 'report_qe': qe, 'candidate_count': n, 'picks': []}
    m_prev = pick_month.__globals__['prev_month_end'](m) if 'prev_month_end' in pick_month.__globals__ else None
    for _, r in picks.iterrows():
        p = {
            'ts_code': r['ts_code'],
            'industry': r.get('industry'),
            'fcf_ev': round(float(r.get('score', np.nan)), 4) if pd.notna(r.get('score')) else None,
        }
        # VC 值
        for vc_col in [f"估值系数_{m_prev}", f"估值系数_{m}"]:
            if vc_col in merged.columns and pd.notna(r.get(vc_col)):
                p['vc'] = round(float(r[vc_col]), 3)
                break
        # 投后月收益（持仓月实际收益）
        ret_col = f"投资回报率_{m}"
        if ret_col in merged.columns and pd.notna(r.get(ret_col)):
            p['next_ret'] = round((float(r[ret_col]) - 1) * 100, 2)
        # 投前月收益
        if m_prev and f"投资回报率_{m_prev}" in merged.columns and pd.notna(r.get(f"投资回报率_{m_prev}")):
            p['prev_ret'] = round((float(r[f"投资回报率_{m_prev}"]) - 1) * 100, 2)
        rec['picks'].append(p)
    records.append(rec)
    if len(records) % 12 == 0:
        print(f"  ...已处理 {len(records)} 个月")

print(f"\n完成: {len(records)} 个月份的选股档案")
print(f"样本: {records[0]['ym']} -> {records[-1]['ym']}")

# 写 JSON
OUT = r"D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data\history_records.json"
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'count': len(records), 'months': records}, f, ensure_ascii=False)
print(f"✅ history_records.json 生成: {OUT}")
