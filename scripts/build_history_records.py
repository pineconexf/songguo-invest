# -*- coding: utf-8 -*-
"""
14年历史选股档案（V30/V31 定稿口径）批量生成 v2
============================================
口径：V30 = V29.1 定稿（2026-08-10）
  - 普通月：Top4（单行业≤2，市值≤300亿，ROE>3%，VC∈[0.90,0.99]，止损0.96，行业tilt）
  - 牛市月（上月HS300>+2%）：keep1add2（保留价值Top1 + 补成长Top2）→ 3只
  - 权重：FCF/EV 排名加权（rank+0.5归一化）——不等权！
  - 空仓保险：上月HS300<-8% → 当月空仓

数据基础：audit_rerun_p1.py（已验证可 exec，含 load_quarter / ALL_QUARTERS / prev_month_end 等）
输出：src/data/history_records.json
"""
import sys, io, json, os
import pandas as pd
import numpy as np
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ===== 数据基础（audit_rerun_p1，同 V27.2 回测链）=====
OUT_DIR = Path(r"D:\pineconeinvestfiles\V24校验")
code = open(OUT_DIR / "audit_rerun_p1.py", encoding="utf-8").read()
exec(code.split("# ---------- 5. 执行 ----------")[0], globals())
print(f"✅ 数据基础已加载: {len(ALL_QUARTERS)} 期")

# ===== V30 定稿参数 =====
TOP_N = 4
KEEP_N = 1
ADD_N = 2
MV_CAP = 3000000       # 300亿（万元）
ROE_MIN = 0.03
TILT_BEST = 1.1
TILT_WORST = 0.9
MAX_IND = 2
FCF_WEIGHT = True      # 不等权！FCF排名加权
STOP_LOSS = 0.96
VC_MIN, VC_MAX = 0.90, 0.99
EMPTY_HS = 1.0 - 0.08  # HS300<-8% 空仓保险

# ===== ROE>3% 面板（step_panel）=====
PANEL_DIR = Path(r"D:\pineconeinvestfiles\V27.2版本归档\step_panel")
roe_panels = {}
if PANEL_DIR.exists():
    for pf in PANEL_DIR.glob("panel_*.parquet"):
        qe = pf.stem.replace("panel_", "")
        try:
            df = pd.read_parquet(pf)
            if "s4_roe3y_min" in df.columns:
                roe_panels[qe] = set(df[df["s4_roe3y_min"] > ROE_MIN]["ts_code"])
        except Exception as e:
            print(f"  ⚠️ panel {qe} 读取失败: {e}")
print(f"✅ ROE 面板: {len(roe_panels)} 期")

# ===== 成长因子面板（牛市增强 q_netprofit_yoy）=====
growth_df = None
GROWTH_PANEL = Path(r"D:\pineconeinvestfiles\V27.2版本归档\growth_factors_panel_full20.parquet")
if GROWTH_PANEL.exists():
    try:
        growth_df = pd.read_parquet(GROWTH_PANEL)
        growth_df = growth_df[growth_df["usable_ym"].notna() & growth_df["q_netprofit_yoy"].notna()]
        print(f"✅ 成长因子面板: {len(growth_df)} 行")
    except Exception as e:
        print(f"  ⚠️ growth 面板读取失败: {e}")

def prev_ym6(ym):
    y, m = int(ym[:4]), int(ym[4:])
    if m == 1:
        return f"{y-1}12"
    return f"{y}{m-1:02d}"

def build_records():
    records = []
    seen_ym = set()

    # 加载 HS300 月度（牛市信号 + 空仓保险）——close 点位转月收益率
    hs_map = {}
    hs_path = Path(r"D:\pineconeinvestfiles\V27.2版本归档\hs300_monthly_full20.csv")
    if hs_path.exists():
        closes = {}
        for line in open(hs_path, encoding="utf-8-sig"):
            line = line.strip()
            if not line or line.startswith("ym"):
                continue
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    closes[parts[0][:6]] = float(parts[1])
                except:
                    pass
        sorted_yms = sorted(closes.keys())
        for i, ym in enumerate(sorted_yms):
            if i == 0:
                hs_map[ym] = 0.0
            else:
                prev_c = closes[sorted_yms[i - 1]]
                hs_map[ym] = closes[ym] / prev_c - 1.0  # 月收益率（-1 到 1 区间）
    print(f"HS300 月度: {len(hs_map)} 月")

    for q in ALL_QUARTERS:
        merged = load_quarter(q)
        if merged is None:
            continue
        ret_cols = sorted([c.replace("投资回报率_", "") for c in merged.columns if c.startswith("投资回报率_")])
        for m in ret_cols:
            ym = m[:6]
            if ym in seen_ym:
                continue
            seen_ym.add(ym)
            ret_col = f"投资回报率_{m}"
            m_prev = prev_month_end(m)
            vc_col = f"估值系数_{m_prev}" if f"估值系数_{m_prev}" in merged.columns else f"估值系数_{m}"
            prev_ret_col = f"投资回报率_{m_prev}"

            # ===== 空仓保险（V30 核心）=====
            py6 = prev_ym6(ym)
            hs_prev = hs_map.get(py6, 0.0)
            is_empty = hs_prev < -0.08  # 上月HS300月收益<-8% → 空仓

            # ===== 池构建 =====
            p = merged[merged[ret_col].notna() & merged[vc_col].notna()
                       & (merged[vc_col] >= VC_MIN) & (merged[vc_col] < VC_MAX) & (merged[vc_col] <= VC_MAX)].copy()
            if len(p) == 0:
                p = merged[merged[ret_col].notna()].copy() if merged[ret_col].notna().sum() > 0 else merged.copy()
            if prev_ret_col in merged.columns and STOP_LOSS is not None:
                p = p[p[prev_ret_col].isna() | (p[prev_ret_col] >= STOP_LOSS)]
            mv_col = f"total_mv_{m_prev}" if f"total_mv_{m_prev}" in p.columns else (f"total_mv_{m}" if f"total_mv_{m}" in p.columns else None)
            if mv_col is not None:
                p = p[p[mv_col].notna() & (p[mv_col] > 0) & (p[mv_col] <= MV_CAP)]
            if q in roe_panels:
                p = p[p["ts_code"].isin(roe_panels[q])]
            p["score_raw"] = p["fcf_ev_q1"]
            p["industry"] = p["ts_code"].map(stock_to_industry)
            p = p.dropna(subset=["industry"])
            if len(p) < TOP_N:
                records.append({"ym": ym, "is_empty": bool(is_empty), "bull_mode": False,
                                "report_qe": q, "candidate_count": len(p), "picks": [], "adj_ret": 1.0})
                continue

            # ===== 行业软调节 tilt =====
            scores = {}
            if 'ind_scores_off' in globals() and q in ind_scores_off:
                scores = ind_scores_off.get(q, {})
            elif 'ind_scores_cache' in globals():
                scores = ind_scores_cache.get(q, {})
            if TILT_BEST != 1.0:
                top3_ind = set(sorted(scores, key=scores.get, reverse=True)[:3]) if scores else set()
                p["tilt_factor"] = p["industry"].apply(lambda x: TILT_BEST if x in top3_ind else TILT_WORST)
            else:
                p["tilt_factor"] = 1.0
            p["score"] = p["score_raw"] * p["tilt_factor"]
            p = p.sort_values("score", ascending=False)

            # ===== Top4 选股 =====
            picks = []
            ind_count = {}
            for _, row in p.iterrows():
                if len(picks) >= TOP_N:
                    break
                ind = row["industry"]
                if ind_count.get(ind, 0) >= MAX_IND:
                    continue
                picks.append(row["ts_code"])
                ind_count[ind] = ind_count.get(ind, 0) + 1

            # ===== 牛市增强 keep1add2 =====
            bull_mode = False
            if not is_empty and hs_prev > 0.02 and len(picks) >= TOP_N and growth_df is not None:
                keep = picks[:KEEP_N]
                # 成长因子：取该月前最新可用 q_netprofit_yoy
                avail = growth_df[growth_df["usable_ym"] <= ym]
                if len(avail) > 0:
                    latest = avail.sort_values("usable_ym").groupby("ts_code").last()
                    growth_map = latest["q_netprofit_yoy"].to_dict()
                    pool2 = p[~p["ts_code"].isin(keep)].copy()
                    pool2["g_score"] = pool2["ts_code"].map(lambda c: growth_map.get(c, float('-inf')))
                    pool2 = pool2.dropna(subset=["g_score"]).sort_values("g_score", ascending=False)
                    ind_count2 = {}
                    for code in keep:
                        ind = p.loc[p["ts_code"] == code, "industry"].iloc[0]
                        ind_count2[ind] = ind_count2.get(ind, 0) + 1
                    add = []
                    for _, row in pool2.iterrows():
                        if len(add) >= ADD_N:
                            break
                        ind = row["industry"]
                        if ind_count2.get(ind, 0) >= MAX_IND:
                            continue
                        add.append(row["ts_code"])
                    if len(add) == ADD_N:
                        picks = keep + add
                        bull_mode = True

            # ===== FCF 排名加权（不等权！）=====
            weights = []
            if len(picks) > 0:
                if FCF_WEIGHT:
                    fcf_vals = np.array([p.loc[p["ts_code"] == c, "score_raw"].iloc[0] for c in picks])
                    w = pd.Series(fcf_vals).rank(pct=True).values + 0.5
                    w = w / w.sum()
                    weights = [round(float(x), 4) for x in w]
                else:
                    weights = [round(1.0 / len(picks), 4)] * len(picks)

            # ===== 个股明细 =====
            pick_list = []
            for i, code in enumerate(picks):
                row = p.loc[p["ts_code"] == code].iloc[0]
                item = {"ts_code": code, "industry": row["industry"],
                        "fcf_ev": round(float(row["score_raw"]), 4),
                        "weight": weights[i] if i < len(weights) else None}
                if vc_col in merged.columns and pd.notna(row.get(vc_col)):
                    item["vc"] = round(float(row[vc_col]), 3)
                if m_prev and f"投资回报率_{m_prev}" in merged.columns and pd.notna(row.get(f"投资回报率_{m_prev}")):
                    item["prev_ret"] = round((float(row[f"投资回报率_{m_prev}"]) - 1) * 100, 2)
                if pd.notna(row.get(ret_col)):
                    item["next_ret"] = round((float(row[ret_col]) - 1) * 100, 2)
                pick_list.append(item)

            # ===== 组合收益（FCF加权）=====
            adj_ret = 1.0
            if not is_empty and len(pick_list) > 0:
                rs = []
                for i, item in enumerate(pick_list):
                    rv = p.loc[p["ts_code"] == item["ts_code"], ret_col].iloc[0]
                    if rv is not None and pd.notna(rv) and rv > 0:
                        rs.append(weights[i] * (rv - 1.0))
                adj_ret = 1.0 + (np.sum(rs) if rs else 0.0)

            records.append({
                "ym": ym, "is_empty": bool(is_empty), "bull_mode": bull_mode,
                "report_qe": q, "candidate_count": len(p),
                "picks": pick_list, "adj_ret": round(float(adj_ret), 6),
            })

    records.sort(key=lambda r: r["ym"])
    return records

records = build_records()
print(f"\n✅ 完成: {len(records)} 个月（V30/V31 定稿口径）")

empty_n = sum(1 for r in records if r["is_empty"])
bull_n = sum(1 for r in records if r["bull_mode"])
total_picks = sum(len(r["picks"]) for r in records)
print(f"   空仓月: {empty_n} | 牛市增强月: {bull_n} | 个股记录: {total_picks}")
print(f"   范围: {records[0]['ym']} ~ {records[-1]['ym']}" if records else "   无数据")

# 抽查
for target in ["202607", "202501", "201506"]:
    sample = [r for r in records if r["ym"] == target]
    if sample:
        r = sample[0]
        print(f"\n=== {target}（bull={r['bull_mode']} empty={r['is_empty']}）===")
        for p in r["picks"]:
            print(f"  {p['ts_code']} | {p['industry']} | FCF={p['fcf_ev']} | 权重={p['weight']*100:.1f}% | 投后={p.get('next_ret')}%")

# 写 JSON
OUT = r"D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data\history_records.json"
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({
        "count": len(records),
        "caliber": "V30/V31 定稿口径（Top4+FCF加权+牛市增强+空仓保险）",
        "months": records,
    }, f, ensure_ascii=False)
print(f"\n✅ history_records.json 已重写: {OUT}")
