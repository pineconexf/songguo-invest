# -*- coding: utf-8 -*-
"""
ETF 组合三档回测（2014-01 ~ 2026-08，152 个月，与全ETF版定稿同窗口同口径）
- 数据源：tushare fund_daily（http 80 直连通道），前复权
- 四拼图：511010 国债ETF / 159934 黄金ETF / 510880 红利ETF / 513500 标普500ETF
- 三档权重：保守 [45,25,15,15] / 稳健 [25,30,10,35] / 进取 [10,25,10,55]
- 校验：稳健档应≈定稿 10.10% / -6.15%（全ETF版 152 个月含成本保守口径）
- 输出：src/data/etf_tiers.json（网站用）+ 生活投资策略/工具回测数据/（本地归档）
"""
import os, json, math, csv, sys
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/AppData/Local/hermes/.env'))
TOK = os.environ.get('TUSHARE_API_KEY', '')
if not TOK:
    print('NO TOKEN'); sys.exit(1)

ETFS = [
    ('511010.SH', '国债ETF', 'sh511010'),
    ('159934.SZ', '黄金ETF', 'sz159934'),
    ('510880.SH', '红利ETF', 'sh510880'),
    ('513500.SH', '标普500ETF', 'sh513500'),
]
TIERS = {
    'conservative': {'label': '保守 · 求稳',   'weights': [45, 25, 15, 15], 'color': '#4A7C59'},
    'stable':       {'label': '稳健 · 标准四拼图', 'weights': [25, 30, 10, 35], 'color': '#8B5E3C'},
    'aggressive':   {'label': '进取 · 冲弹性', 'weights': [10, 25, 10, 55], 'color': '#a03a28'},
}
START, END = '20140101', '20260831'


def q(api, params, fields):
    r = requests.post(f'http://api.tushare.pro/dataapi/{api}',
                      json={'api_name': api, 'token': TOK, 'params': params, 'fields': fields}, timeout=15)
    b = r.json()
    if b.get('code') != 0:
        return None, b.get('msg')
    d = b['data']
    if not d.get('items'):
        return [], None
    return [dict(zip(d['fields'], row)) for row in d['items']], None


def fetch_etf_daily(ts_code, sina_sym):
    """拉 ETF 日线（前复权）：
    1) 新浪历史日线 close（2014 起全历史，未复权）
    2) tushare fund_adj 复权因子（2014 起全覆盖）→ close × adj / 最新adj
    """
    url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_sym}&scale=240&ma=no&datalen=3400'
    r = requests.get(url, timeout=20, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'})
    data = json.loads(r.text)
    if not data:
        print(f'  {ts_code} 新浪数据为空'); return None
    closes = {d['day']: float(d['close']) for d in data}
    # tushare 复权因子（分段拉取，避免单次条数截断）
    adj_map = {}
    for a, b in [('20130101', '20171231'), ('20180101', '20221231'), ('20230101', '20261231')]:
        adjs, err = q('fund_adj', {'ts_code': ts_code, 'start_date': a, 'end_date': b},
                      'trade_date,adj_factor')
        if err:
            print(f'  {ts_code} 复权 ERR: {err}'); return None
        for r in adjs:
            adj_map[r['trade_date']] = r['adj_factor']
    if not adj_map:
        print(f'  {ts_code} 复权因子为空'); return None
    last_adj = max(adj_map.values())
    daily = {}
    for d, c in closes.items():
        a = adj_map.get(d.replace('-', ''))
        if a:
            daily[d] = round(c * a / last_adj, 6)
    print(f'  {ts_code} {sina_sym}: 日线 {len(closes)} 天 → 复权 {len(adj_map)} 天 → 合并 {len(daily)} 天')
    return daily


def monthly_returns(daily):
    """日线 → 月度收益。新浪日期格式 'YYYY-MM-DD'，月份键取 [:7]（'YYYY-MM'）。
    首月（如 513500 上市月 2014-01）用月内首日→末日收益（部分月）。"""
    days = sorted(daily.keys())
    mon_last, mon_first = {}, {}
    for d in days:
        mon_last[d[:7]] = daily[d]
        if d[:7] not in mon_first:
            mon_first[d[:7]] = daily[d]
    out, prev_last = {}, None
    for ym in sorted(mon_last.keys()):
        if prev_last is not None:
            out[ym] = mon_last[ym] / prev_last - 1
        else:
            out[ym] = mon_last[ym] / mon_first[ym] - 1  # 首月部分月
        prev_last = mon_last[ym]
    return out


def calc_metrics(returns, weights):
    """组合月收益序列 → 指标（几何年化 / MDD / 夏普 / 卡玛）"""
    n = len(returns)
    if n < 12:
        return None
    nav = 1.0
    navs, peak = [], 1.0
    mdd = 0.0
    for r in returns:
        nav *= (1 + r)
        navs.append(nav)
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    annual = nav ** (12 / n) - 1
    mean_m = sum(returns) / n
    std_m = (sum((r - mean_m) ** 2 for r in returns) / n) ** 0.5
    sharpe = (mean_m * 12 - 0.02) / (std_m * math.sqrt(12)) if std_m > 0 else 0  # 无风险 2%
    calmar = annual / abs(mdd) if mdd < 0 else 0
    return {'annual': annual, 'mdd': mdd, 'sharpe': sharpe, 'calmar': calmar, 'months': n}


def pressure_years(returns, weights):
    """压力年（2015/2018/2022）组合收益"""
    out = {}
    for yr in ['2015', '2018', '2022']:
        r = [v for k, v in returns.items() if k.startswith(yr)]
        if r:
            nav = 1.0
            for x in r:
                nav *= (1 + x)
            out[yr] = nav - 1
    return out


def main():
    print('== 拉取 ETF 日线（前复权）==')
    month_rets = {}  # asset -> {ym: ret}
    for code, name, ssym in ETFS:
        daily = fetch_etf_daily(code, ssym)
        if not daily:
            print(f'  {name} 无数据'); continue
        mr = monthly_returns(daily)
        month_rets[code] = mr
        print(f'  {name} {code}: {len(mr)} 个月 {min(mr)} ~ {max(mr)}')

    # 对齐月份（四资产交集）
    keys = [set(mr.keys()) for mr in month_rets.values()]
    common = set.intersection(*keys)
    common = sorted(common)
    print(f'== 对齐窗口：{len(common)} 个月 {common[0]} ~ {common[-1]} ==')

    result = {}
    for tier, cfg in TIERS.items():
        w = cfg['weights']
        wsum = sum(w)
        combo = {}
        for ym in common:
            combo[ym] = sum((month_rets[c][ym] * wi / wsum) for c, wi in zip(month_rets.keys(), w))
        m = calc_metrics(combo.values(), w)
        py = pressure_years(combo, w)
        result[tier] = {
            'label': cfg['label'], 'color': cfg['color'], 'weights': w,
            'window': {'start': common[0], 'end': common[-1], 'months': len(common)},
            'metrics': m, 'pressure_years': py,
            'monthly': combo,  # 月度序列（本地归档用）
        }
        print(f"\n== {cfg['label']} == 年化 {m['annual']*100:.2f}% / MDD {m['mdd']*100:.2f}% / 夏普 {m['sharpe']:.2f} / 卡玛 {m['calmar']:.2f}")
        print(f"   压力年: " + ', '.join(f"{k} {v*100:+.1f}%" for k, v in py.items()))

    # ==== 输出 1：网站数据（不含月度序列，瘦身） ====
    web = {}
    for t, v in result.items():
        web[t] = {k: (v[k] if k != 'monthly' else None) for k in v}
        del web[t]['monthly']
        web[t]['annual_pct'] = round(v['metrics']['annual'] * 100, 2)
        web[t]['mdd_pct'] = round(v['metrics']['mdd'] * 100, 2)
    site_path = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data\etf_tiers.json'
    with open(site_path, 'w', encoding='utf-8') as f:
        json.dump(web, f, ensure_ascii=False, indent=1)
    print(f'\n== 网站数据已写: {site_path} ==')

    # ==== 输出 2：本地归档（月度明细 + 指标总表 + 说明） ====
    arch = r'D:\pineconeinvestfiles\生活投资策略\工具回测数据'
    os.makedirs(arch, exist_ok=True)
    # 指标总表
    with open(os.path.join(arch, '三档指标总表.json'), 'w', encoding='utf-8') as f:
        json.dump({t: {k: v for k, v in val.items() if k != 'monthly'} for t, val in result.items()},
                  f, ensure_ascii=False, indent=1)
    # 月度明细 CSV（每档一列）
    ym_list = list(result['stable']['monthly'].keys())
    with open(os.path.join(arch, '三档月度收益明细.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        wtr = csv.writer(f)
        wtr.writerow(['ym'] + [f"{v['label']}_ret" for v in result.values()])
        for ym in ym_list:
            wtr.writerow([ym] + [f"{result[t]['monthly'][ym]:.6f}" for t in result])
    print(f'== 本地归档已写: {arch} ==')


if __name__ == '__main__':
    main()
