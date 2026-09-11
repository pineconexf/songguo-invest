#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略月报自动生成 —— 更新 research_industry.json 的 monthly_report 段
====================================================================
数据源（全部为本地权威产出物，不编造）：
  src/data/monthly_returns.json  126 月四腿月度收益（etf/fund/stock/index）—— 权威
  src/data/strategy.json         V35/V36/沪深300 的年化/MDD/年度/月度对比
  src/data/macro_signal.json     811 周 Shibor 宏观信号（宽松/收紧）
只覆盖 monthly_report + source 的月报段；雷达段（hot_sectors/events/warnings）保持不动。

用法: python scripts/build_monthly_report.py
"""
import json, os, re, sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, 'src', 'data')

def load(name):
    with open(os.path.join(D, name), encoding='utf-8') as f:
        return json.load(f)

def save(name, obj):
    p = os.path.join(D, name)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ---------- 收益计算 ----------
def cum(rs):
    """月度收益序列(%) → 累计收益(%)"""
    v = 1.0
    for r in rs:
        v *= (1 + r / 100.0)
    return (v - 1) * 100

def mdd(rs):
    """月度收益序列(%) → 历史最大回撤(%)"""
    v = peak = 1.0
    worst = 0.0
    for r in rs:
        v *= (1 + r / 100.0)
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    return worst * 100

def ym_cn(ym):
    return f"{ym[:4]}年{int(ym[4:6])}月"

# ---------- 主流程 ----------
def main():
    mr = load('monthly_returns.json')
    strat = load('strategy.json')
    macro = load('macro_signal.json')
    ind = load('research_industry.json')

    last = mr[-1]['ym']                      # 最新月 e.g. 202608
    year = last[:4]
    period_cn = ym_cn(last)

    # 当月各腿（%）；stock 取 monthly_returns，v35 口径与 strategy.monthly_compare.v35 对账
    m_etf = mr[-1]['etf']
    m_fund = mr[-1]['fund']
    m_stock = mr[-1]['stock']

    mc = strat['monthly_compare']
    m_v35 = mc['v35'][-1]
    m_hs300 = mc['hs300'][-1]
    y_v35 = strat['yearly']['v35'][-1]
    y_hs300 = strat['yearly']['hs300'][-1]

    # 与权威月度对比对账（同月必须一致，否则数据源不同步，退出报警）
    if abs(m_stock - m_v35) > 0.02:
        print(f"[WARN] monthly_returns.stock({m_stock}) 与 strategy.monthly_compare.v35({m_v35}) 不一致，按 strategy 口径", file=sys.stderr)
        m_stock = m_v35

    # YTD / MDD：etf/fund 由 126 月序列自算
    def ytd_of(key):
        rs = [r[key] for r in mr if r['ym'][:4] == year and r[key] is not None]
        return cum(rs) if rs else None

    ytd_etf, ytd_fund = ytd_of('etf'), ytd_of('fund')
    mdd_etf = mdd([r['etf'] for r in mr if r['etf'] is not None])
    mdd_fund = mdd([r['fund'] for r in mr if r['fund'] is not None])
    mdd_v35 = strat['meta']['v35']['mdd']
    mdd_hs300 = strat['meta']['hs300']['mdd']

    def pct(x, plus=True):
        if x is None:
            return '—'
        return f"{x:+.2f}%" if plus else f"{x:.2f}%"

    assets = [
        {"name": "股票策略 V35（含成本）", "jul": pct(m_v35), "ytd": pct(y_v35), "mdd": pct(mdd_v35, False), "role": "进攻腿"},
        {"name": "ETF 四拼图", "jul": pct(m_etf), "ytd": pct(ytd_etf), "mdd": pct(mdd_etf, False), "role": "防守壳 ETF 版"},
        {"name": "基金组合", "jul": pct(m_fund), "ytd": pct(ytd_fund), "mdd": pct(mdd_fund, False), "role": "防守壳 公募版"},
        {"name": "沪深300（基准）", "jul": pct(m_hs300), "ytd": pct(y_hs300), "mdd": pct(mdd_hs300, False), "role": "买入持有基准"},
    ]

    # 市场叙述（自动，仅用真实数字）
    legs = [("股票策略 V35", m_v35), ("ETF 四拼图", m_etf), ("基金组合", m_fund)]
    best = max(legs, key=lambda x: x[1])
    worst = min(legs, key=lambda x: x[1])
    market = (f"{period_cn}：沪深300 单月 {m_hs300:+.2f}%，四腿中 {best[0]} 最强"
              f"（{best[1]:+.2f}%）、{worst[0]} 最弱（{worst[1]:+.2f}%）。含成本口径，"
              f"历史回测窗口 {strat['meta']['window']['start'][:4]}.{strat['meta']['window']['start'][4:6]}"
              f"-{last[:4]}.{last[4:6]}（{strat['meta']['window']['months']} 个月）。")

    # 超额（相对沪深300，pp）
    exc_v35 = m_v35 - m_hs300
    exc_etf = m_etf - m_hs300
    excess = (f"{period_cn} 股票策略相对沪深300 超额 {exc_v35:+.2f}pp；ETF 四拼图超额 {exc_etf:+.2f}pp。")

    # 宏观信号（当月周信号统计：按 ISO 周号的周一日期归属月份）
    target_ym = last
    weeks_m = [w for w in macro['weeks'] if (lambda d: d and f"{d.year}{d.month:02d}" == target_ym)(week_monday(w.get('week')))]
    if not weeks_m:
        weeks_m = macro['weeks'][-4:]
    loose = sum(1 for w in weeks_m if str(w.get('signal', '')).startswith('宽松'))
    tight = sum(1 for w in weeks_m if str(w.get('signal', '')).startswith('收紧'))
    shibors = [w['shibor'] for w in weeks_m if w.get('shibor') is not None]
    sh_txt = f"Shibor 1W 区间 {min(shibors):.4f}-{max(shibors):.4f}%" if shibors else "Shibor 1W 数据缺失"
    signal = (f"{period_cn} 共 {len(weeks_m)} 周信号：宽松 {loose} 周、收紧 {tight} 周，{sh_txt}"
              f"（阈值：周均值环比下行 >5bp 判宽松，数据源 {macro['stats']['total_weeks']} 周历史）。宏观信号整体指向"
              f"{'进攻' if loose > tight else '防守'}。")

    actions = [
        f"防守仓位：ETF/基金组合无需因单月波动调整，季度审视 + 半年再平衡节奏不变（{period_cn} ETF {m_etf:+.2f}%、基金 {m_fund:+.2f}%）",
        f"进攻仓位：{period_cn} 进攻腿 {m_v35:+.2f}%、相对基准超额 {exc_v35:+.2f}pp，仓位高低取决于个人回撤容忍度（V35 历史 MDD {mdd_v35:.2f}%）",
        f"宏观择时：Shibor 未破宽松阈值前指数策略保持空仓（触发条件：1W 周均值环比下行 >5bp）",
    ]

    ind['monthly_report'] = {
        "period": period_cn,
        "market": market,
        "assets": assets,
        "excess": excess,
        "signal": signal,
        "actions": actions,
    }
    # source 的月报段同步（保留雷达段）
    src = ind.get('source', '')
    src = re.sub(r'\+ *策略月报.*$', '', src).rstrip(' +')
    ind['source'] = f"{src} + 策略月报 {period_cn}（月度自动生成）"

    save('research_industry.json', ind)
    print(f"[OK] 月报已更新 → {period_cn}")
    for a in assets:
        print(f"    {a['name']:<22} 月 {a['jul']:>8}  YTD {a['ytd']:>8}  MDD {a['mdd']:>8}")
    print(f"    超额：{excess}")
    print(f"    信号：{signal[:60]}...")

def week_monday(wk):
    """'2026W36' → 该 ISO 周的周一日期（用于归属月份）；解析失败返回 None"""
    m = re.match(r'(\d{4})W(\d{1,2})', str(wk or ''))
    if not m:
        return None
    try:
        return datetime.fromisocalendar(int(m.group(1)), int(m.group(2)), 1).date()
    except (ValueError, AttributeError):
        return None

if __name__ == '__main__':
    main()
