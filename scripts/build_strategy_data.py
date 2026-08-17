#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
松果投资体系网站 · 数据管线
V31/V32 月度回测 CSV → src/data/strategy.json（净值/回撤/年度/月度对比/核心指标）

数据源（定稿归档）：
  V31: D:\pineconeinvestfiles\V31版本归档\V31_资金增强定稿\V31_定稿_月度.csv (含成本)
  V32: D:\pineconeinvestfiles\V32版本归档\V32_定稿_月度.csv (含成本)
  年度: V31_年度明细.csv / V32_年度明细.csv
  HS300: D:\pineconeinvestfiles\V27.2版本归档\hs300_monthly_full20.csv
  月度对比: V31_14年月度对比清单_含HS300.csv (已含超额列)

口径说明：adj_ret 是倍数(1.0+ret)；年度明细是收益率(0.24=24%)；
HS300 close 是点位，净值=close/首月close。
"""
import csv, io, json
from pathlib import Path

BASE = Path(r"D:\pineconeinvestfiles")
OUT = Path(r"D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data")
OUT.mkdir(parents=True, exist_ok=True)

V31_DIR = BASE / "V31版本归档" / "V31_资金增强定稿"
V32_DIR = BASE / "V32版本归档"
HS300_CSV = BASE / "V27.2版本归档" / "hs300_monthly_full20.csv"


def read_csv(path):
    with io.open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def nav_series(rows, key="adj_ret"):
    """倍数收益 → 净值序列(从1.0起)"""
    months = [r["ym"] for r in rows]
    nav = [1.0]
    for r in rows:
        nav.append(nav[-1] * float(r[key]))
    return months, nav[1:]


def calc_metrics(nav):
    """净值序列 → 年化/最大回撤/Calmar/累计/回撤序列"""
    n = len(nav)
    final = nav[-1]
    cumulative = final - 1.0
    annual = final ** (12.0 / n) - 1.0
    peak = nav[0]
    mdd = 0.0
    dd_series = []
    for v in nav:
        peak = max(peak, v)
        dd = v / peak - 1.0
        dd_series.append(round(dd, 6))
        mdd = min(mdd, dd)
    calmar = annual / abs(mdd) if mdd != 0 else None
    return {
        "annual_return": round(annual * 100, 2),   # %
        "mdd": round(mdd * 100, 2),                # %
        "calmar": round(calmar, 3) if calmar else None,
        "cumulative": round(cumulative * 100, 1),  # %
        "months": n,
    }, dd_series


# ---------- 1. 月度净值 ----------
v31_rows = read_csv(V31_DIR / "V31_定稿_月度.csv")
v32_rows = read_csv(V32_DIR / "V32_定稿_月度.csv")
hs_rows = read_csv(HS300_CSV)

v31_months, v31_nav = nav_series(v31_rows)
v32_months, v32_nav = nav_series(v32_rows)
assert v31_months == v32_months, "V31/V32 月份不一致"

# HS300 对齐到策略月份窗口
hs_close = {r["ym"]: float(r["close"]) for r in hs_rows}
first_m = v31_months[0]
hs_nav = []
for m in v31_months:
    if m in hs_close:
        hs_nav.append(round(hs_close[m] / hs_close[first_m], 6))
    else:
        hs_nav.append(None)

v31_metrics, v31_dd = calc_metrics(v31_nav)
v32_metrics, v32_dd = calc_metrics(v32_nav)
hs_masked = [v for v in hs_nav if v is not None]
hs_metrics, _ = calc_metrics(hs_masked)
hs_metrics = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in hs_metrics.items()}

# ---------- 2. 年度明细 ----------
yr31 = read_csv(V31_DIR / "V31_年度明细.csv")
yr32 = read_csv(V32_DIR / "V32_年度明细.csv")
years = [r["year"] for r in yr31]
y31 = {r["year"]: round(float(r["V31含成本"]) * 100, 2) for r in yr31}
y32 = {r["year"]: round(float(r["V32含成本"]) * 100, 2) for r in yr32}
# HS300 年度收益（从月度 close 重算）
hs_yearly = []
for y in years:
    closes = [r["close"] for r in hs_rows if r["ym"].startswith(str(y))]
    if len(closes) >= 2:
        hs_yearly.append(round((float(closes[-1]) / float(closes[0]) - 1) * 100, 2))
    else:
        hs_yearly.append(None)

# ---------- 3. 月度对比（V31 vs HS300，含超额）----------
cmp_rows = read_csv(V31_DIR / "V31_14年月度对比清单_含HS300.csv")
cmp_months = [r["月份"] for r in cmp_rows]
cmp_v31 = [round(float(r["V31含成本"]) * 100, 2) for r in cmp_rows]
cmp_hs = [round(float(r["沪深300"]) * 100, 2) for r in cmp_rows]
cmp_excess = [round(float(r["超额(V31含成本-HS300)"]) * 100, 2) for r in cmp_rows]

# ---------- 4. 输出 ----------
data = {
    "meta": {
        "v31": v31_metrics,
        "v32": v32_metrics,
        "hs300": hs_metrics,
        "note": "数据为14年历史回测（2012.04-2026.07，172个月），含成本口径（佣金万2.5+印花税0.05%）；V32含1.5x融资杠杆。历史回测不代表未来收益。",
        "window": {"start": v31_months[0], "end": v31_months[-1], "months": len(v31_months)},
    },
    "nav": {
        "months": v31_months,
        "v31": [round(v, 4) for v in v31_nav],
        "v32": [round(v, 4) for v in v32_nav],
        "hs300": hs_nav,
    },
    "drawdown": {
        "months": v31_months,
        "v31": v31_dd,
        "v32": v32_dd,
    },
    "yearly": {
        "years": years,
        "v31": [y31.get(y) for y in years],
        "v32": [y32.get(y) for y in years],
        "hs300": hs_yearly,
    },
    "monthly_compare": {
        "months": cmp_months,
        "v31": cmp_v31,
        "hs300": cmp_hs,
        "excess": cmp_excess,
    },
}

out_path = OUT / "strategy.json"
out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"✅ 已输出 {out_path}  ({out_path.stat().st_size/1024:.1f} KB)")

# ---------- 5. 校验（与定稿口径对照）----------
print("\n=== 指标校验 ===")
print(f"V31 年化 {v31_metrics['annual_return']}% / MDD {v31_metrics['mdd']}% / Calmar {v31_metrics['calmar']}  (定稿: 24.30% / -22.61% / 1.126)")
print(f"V32 年化 {v32_metrics['annual_return']}% / MDD {v32_metrics['mdd']}% / Calmar {v32_metrics['calmar']}  (定稿: 34.71% / -33.65% / 1.032)")
print(f"HS300 同期 年化 {hs_metrics['annual_return']}% / MDD {hs_metrics['mdd']}%")
print(f"月份数 V31={len(v31_nav)} V32={len(v32_nav)} HS300对齐={len(hs_nav)} (None={hs_nav.count(None)})")
print(f"年度 V31 2026: {y31['2026']}% (定稿 -27.47%) | V32 2026: {y32['2026']}% (定稿 -39.49%)")
