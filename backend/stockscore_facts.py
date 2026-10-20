# -*- coding: utf-8 -*-
"""事实层扩展采集（2026-10-20）

目标：把个股分析的内容密度提升到"微信深度文章"级别。核心判断——
**丰满度是采集问题，不是提示词问题**。文章里的信息密度
（分部收入占比 69.7%、预付款项 0.43→1.23 亿、ROIC 9.00% vs WACC 8.46%）
来自数据源本身，提示词补不上。

本模块提供四组带溯源的事实：
  1. 现金流画像：经营现金流 / 资本开支 / FCF / 折旧摊销 / 预付款项异动
     （对应文章"预付款项激增→经营现金流下降64%但不是恶化"这类论证）
  2. 资本回报：ROIC vs WACC、净现金占比、剔除净现金后经营性 ROIC
     （对应文章第四节"数字检验"）
  3. 历史估值分位：PE/PB/PS/PCF 的 3/5/10 年分位
     （对应元宝《股票估值技能模块》第三节）
  4. 风险画像：偿债 / 盈利质量 / 资产质量 / 集中度 / 流动性
     （对应元宝《系统化选股风控框架》六大模块中的可量化部分）

铁律：
  - 每个事实条目必须带 source（接口名），供写作层挂 source_id 做溯源
  - 缺失就是缺失，绝不填 0、绝不臆造；缺失项带 na_reason
  - WACC 用简化 CAPM，只作横向参照，不宣称是精确折现率
"""
import math
import time
import threading

from stockscore import dc_all, _shift_days, secu


def _num(v, nd=2):
    """数值转可读字符串（与 stockscore._num 不同：那个是转 float）。"""
    if v is None:
        return '无'
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = ('%.' + str(nd) + 'f') % f
    return s.rstrip('0').rstrip('.') if '.' in s else s

# ------------------------------------------------------------------ 字段集

CASHFLOW_COLS = (
    'SECUCODE,REPORT_DATE,REPORT_DATE_NAME,NOTICE_DATE,'
    'NETCASH_OPERATE,NETCASH_OPERATE_YOY,NETCASH_INVEST,NETCASH_FINANCE,'
    'CONSTRUCT_LONG_ASSET,FA_IR_DEPR,IA_AMORTIZE,FINANCE_EXPENSE'
)

BALANCE_COLS = (
    'SECUCODE,REPORT_DATE,REPORT_DATE_NAME,'
    'MONETARYFUNDS,PREPAYMENT,GOODWILL,INVENTORY,ACCOUNTS_RECE,'
    'FIXED_ASSET,TOTAL_EQUITY,TOTAL_ASSETS,TOTAL_LIABILITIES,'
    'SHORT_LOAN,LONG_LOAN,BOND_PAYABLE,NOTE_ACCOUNTS_RECE,'
    'TOTAL_PARENT_EQUITY'
)

# 现金流量表里 D&A 字段名不完全统一，按优先级取
DA_CANDIDATES = ('DEPR_AMORTIZATION', 'FA_IR_DEPR', 'IA_AMORTIZE', 'LPE_AMORTIZE')

VAL_SERIES_COLS = (
    'TRADE_DATE,PE_TTM,PB_MRQ,PS_TTM,PCF_OCF_TTM,PCF_OCF_LAR,PEG_CAR,'
    'TOTAL_MARKET_CAP,CLOSE_PRICE'
)

# 行业景气与板块（概念20日涨幅位次）由 collect_board_snapshot 提供
# 风险模块里的市场风险 Beta / 波动率 / MDD 由行情序列自算

_MD_CACHE = {}
_MD_LOCK = threading.Lock()
_LAST_QUOTE = {}      # code -> 最新交易日行情行（TOTAL_MARKET_CAP / PE_TTM / CLOSE_PRICE）


# ------------------------------------------------------------------ 基础取数
def cashflow(code, n=8):
    """现金流量表（最近 n 期）。

    先按精确列名取；任一列不存在会整表返回空，此时回退到 ALL 再本地挑列。
    """
    rows = dc_all('RPT_F10_FINANCE_GCASHFLOW', f'(SECUCODE="{secu(code)}")',
                  CASHFLOW_COLS, sort_col='REPORT_DATE', sort_dir=-1,
                  source='HSF10', max_pages=1)[:n]
    if rows:
        return rows
    try:
        rows = dc_all('RPT_F10_FINANCE_GCASHFLOW', f'(SECUCODE="{secu(code)}")',
                      'ALL', sort_col='REPORT_DATE', sort_dir=-1,
                      source='HSF10', max_pages=1)[:n]
    except Exception:
        return []
    keep = set(CASHFLOW_COLS.split(','))
    return [{k: v for k, v in r.items() if k in keep} for r in rows]


def balance(code, n=8):
    """资产负债表（最近 n 期）。"""
    return dc_all('RPT_F10_FINANCE_GBALANCE', f'(SECUCODE="{secu(code)}")',
                  BALANCE_COLS, sort_col='REPORT_DATE', sort_dir=-1,
                  source='HSF10', max_pages=1)[:n]


def income_statement(code, n=8):
    """利润表。RPT_F10_FINANCE_GINCOMEC 在部分代码上返回空，失败降级为空列表。"""
    try:
        return dc_all('RPT_F10_FINANCE_GINCOMEC', f'(SECUCODE="{secu(code)}")',
                      'SECUCODE,REPORT_DATE,REPORT_DATE_NAME,TOTAL_OPERATE_INCOME,'
                      'OPERATE_COST,OPERATE_PROFIT,OPERATE_PROFIT_BEFORE_TAX,'
                      'INCOME_TAX,INCOME_TAX_EXPENSE,TOTAL_PROFIT',
                      sort_col='REPORT_DATE', sort_dir=-1,
                      source='HSF10', max_pages=1)[:n]
    except Exception:
        return []


def main_business_detail(code, periods=2):
    """主营构成（按产品/按地区），多期以看结构变化。

    与 stockscore_v3.main_business 的差别：这里保留多期且不裁剪，
    供写作层描述"某个分部占比从 X 升到 Y"这类动态表述。
    """
    try:
        rows = dc_all('RPT_F10_FN_MAINOP', f'(SECUCODE="{secu(code)}")',
                      'SECUCODE,REPORT_DATE,MAINOP_TYPE,ITEM_NAME,'
                      'MAIN_BUSINESS_INCOME,MBI_RATIO,GROSS_RPOFIT_RATIO',
                      sort_col='REPORT_DATE', sort_dir=-1,
                      source='HSF10', max_pages=1)
    except Exception:
        rows = []
    if not rows:
        return []
    rows.sort(key=lambda r: str(r.get('REPORT_DATE') or ''), reverse=True)
    dates = []
    for r in rows:
        d = str(r.get('REPORT_DATE') or '')[:10]
        if d and d not in dates:
            dates.append(d)
    keep = set(dates[:periods])
    return [r for r in rows if str(r.get('REPORT_DATE') or '')[:10] in keep]


# 财务主表（MAINFINADATA）：ROIC / 杠杆 / 利息覆盖 / 扣非利润等
# 2026-10-20 起 build_facts 自取，不再依赖调用方传 fin=
# （之前 api.py / stockscore_deep.py 都是 build_facts(code) 不传 fin，
#  导致 ROIC、资产负债率、利息保障倍数全落在 gaps 里，写作层看不到）
MAINFIN_COLS = (
    'SECUCODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_DATE_NAME,'
    'ROIC,ZCFZL,INTSTCOVRATE,QYCS,NETCASH_OPERATE_PK,NCO_NETPROFIT,'
    'KCFJCXSYJLR,KCFJCXSYJLRTZ,PARENTNETPROFIT,PARENTNETPROFITTZ,'
    'DJD_DEDUCTDPNP_YOY,DJD_TOI_YOY,TOTALOPERATEREVE,XSMLL,'
    'ROEKCJQ,INTEREST_DEBT_RATIO,LD,SD'
)


def mainfin(code, n=13):
    """财务主表（最近 n 期）。字段缺失时回退 ALL 再本地挑列。"""
    rows = dc_all('RPT_F10_FINANCE_MAINFINADATA', f'(SECUCODE="{secu(code)}")',
                  MAINFIN_COLS, sort_col='REPORT_DATE', sort_dir=-1,
                  source='HSF10', max_pages=1)[:n]
    if rows:
        return rows
    try:
        return dc_all('RPT_F10_FINANCE_MAINFINADATA', f'(SECUCODE="{secu(code)}")',
                      'ALL', sort_col='REPORT_DATE', sort_dir=-1,
                      source='HSF10', max_pages=1)[:n]
    except Exception:
        return []


def _period_key(name):
    """'2026三季报' -> ('2026', '三季报')；'2025年报' -> ('2025', '年报')。"""
    name = (name or '').replace(' ', '')
    for tail in ('年报', '三季报', '中报', '一季报', '年报预告'):
        if name.endswith(tail):
            return name[:len(name) - len(tail)], tail
    return None, None


def _ttm_from_cumulative(rows, field):
    """从「报告期累计值」序列还原 TTM。

    KCFJCXSYJLR 等字段是年内累计（一季报=1季，中报=2季，三季报=3季，年报=4季），
    所以 TTM(截至最新期) = 上一年度年报 + 本期累计 - 去年同期累计。
    688508 实测（2026三季报）：55873849.1 + 11345358.92 - 72052074.81 = -4832866.79，
    即扣非口径 TTM 归母净利为负 —— 表观 PE 88 倍的分母全部来自非经常性损益。
    """
    if not rows:
        return None
    latest = rows[0]
    lyear, ltail = _period_key(latest.get('REPORT_DATE_NAME'))
    if not lyear:
        return None
    if ltail == '年报':
        return _f(latest.get(field))
    ann = None
    for r in rows:
        y, t = _period_key(r.get('REPORT_DATE_NAME'))
        if t == '年报' and y and y < lyear:
            ann = r
            break
    same = None
    for r in rows:
        y, t = _period_key(r.get('REPORT_DATE_NAME'))
        if y == str(int(lyear) - 1) and t == ltail:
            same = r
            break
    if ann is None or same is None:
        return None
    a = _f(ann.get(field))
    c = _f(latest.get(field))
    s = _f(same.get(field))
    if a is None or c is None or s is None:
        return None
    return a + c - s


def val_series(code, years=5):
    """历史估值日频序列（含 PE/PB/PS/PCF/PEG/总市值）。"""
    d0 = _shift_days(years * 365 + 5)
    return dc_all('RPT_VALUEANALYSIS_DET',
                  f"(SECURITY_CODE=\"{code}\")(TRADE_DATE>='{d0}')",
                  VAL_SERIES_COLS, sort_col='TRADE_DATE', sort_dir=-1,
                  max_pages=3)


# ------------------------------------------------------------------ 计算
def _f(v):
    try:
        if v is None or v == '' or v == '-':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _pct(v):
    """比例字段归一化成百分数。

    东财不同报表的比例口径不一致：MBI_RATIO=0.838 表示 83.8%，
    但 ZCFZL=18.5 表示 18.5%。规则：绝对值 <= 1.5 视为小数口径，×100。
    """
    f = _f(v)
    if f is None:
        return None
    if abs(f) <= 1.5:
        return f * 100
    return f


def _pct_rank(series, value):
    """value 在 series 中的百分位（0-100），series 需为可比数值列表。"""
    vals = [x for x in series if x is not None and x > 0]
    if not vals or value is None or value <= 0:
        return None
    below = sum(1 for x in vals if x < value)
    return round(below / len(vals) * 100, 1)


def _period(rows, idx=0):
    """取第 idx 期（0=最新）。"""
    if not rows or idx >= len(rows):
        return {}
    return rows[idx]


def _da_of(row):
    for k in DA_CANDIDATES:
        v = _f(row.get(k))
        if v is not None:
            return v
    return None


# ------------------------------------------------------------------ 估值分位
def valuation_percentile(code, years_list=(3, 5, 10)):
    """历史估值分位：PE/PB/PS/PCF 在 3/5/10 年区间的百分位。

    返回 {metric: {window_years: {'pctl':, 'value':, 'min':, 'max':,
                                    'median':, 'n':}}}
    周期股 PE 会失真（顶部低 PE），因此对 PE 一并给出 PB 分位作为交叉参照。
    """
    out = {}
    series = val_series(code, years=max(years_list))
    if not series:
        return out
    # 顺手缓存最新一行（series 按 TRADE_DATE 倒序，series[0] 即最新交易日）：
    # 扣非口径 PE 需要总市值，单独再拉一次日频序列太贵，这里复用
    try:
        _LAST_QUOTE[code] = series[0]
    except Exception:
        pass
    metrics = ('PE_TTM', 'PB_MRQ', 'PS_TTM', 'PCF_OCF_TTM')
    for m in metrics:
        pts = []
        for r in series:
            d = str(r.get('TRADE_DATE') or '')[:10]
            v = _f(r.get(m))
            if d and v is not None and v > 0:
                pts.append((d, v))
        if not pts:
            continue
        pts.sort()
        out[m] = {}
        for w in years_list:
            cutoff = _shift_days(w * 365)
            sub = [v for d, v in pts if d >= cutoff]
            if len(sub) < 60:
                continue
            cur = pts[-1][1]
            out[m][str(w)] = {
                'pctl': _pct_rank(sub, cur),
                'value': round(cur, 2),
                'min': round(min(sub), 2),
                'max': round(max(sub), 2),
                'median': round(sorted(sub)[len(sub) // 2], 2),
                'n': len(sub),
            }
    return out


def _is_distorted_multiple(metric, value):
    """倍数是否因分母趋零而失真（PCF 分母是经营现金流）。

    2026-10-20 实测：芯朋微 PCF 显示 4723.69、99.9 分位，看着像"极度高估"，
    实际是 TTM 经营现金流接近 0 导致的分母失真。分位再准，倍数本身不可信。
    """
    lim = {'PCF_OCF_TTM': 500.0, 'PE_TTM': 2000.0}.get(metric)
    if lim is None:
        return False
    try:
        v = abs(float(value))
    except (TypeError, ValueError):
        return False
    return v == 0 or v > lim


def valuation_zone(pctl):
    """分位 → 温度区间标签（元宝口径）。

    0-20 低估区 / 20-50 合理偏低 / 50-80 合理偏高 / 80-100 高估区
    >95 或 <5 记为极端值。
    """
    if pctl is None:
        return None
    if pctl >= 95:
        return '极端高估'
    if pctl >= 80:
        return '高估区'
    if pctl >= 50:
        return '合理偏高'
    if pctl > 20:
        return '合理偏低'
    if pctl > 5:
        return '低估区'
    return '极端低估'


# ------------------------------------------------------------------ 资本回报
def _simplified_wacc(code, fin=None):
    """简化 WACC：Rf 2.0% + β×ERP 5.0%，按有息负债/总资本加权后税。

    只作横向参照口径，不宣称精确折现率。β 用 60 日相对沪深300 回归，
    取不到则用 1.0（等价于市场平均），并标注 beta_source。
    """
    r_f, erp = 0.020, 0.050
    beta, beta_src = _beta(code)
    ke = r_f + beta * erp
    debt_ratio = 0.0
    if fin:
        d, e = fin.get('interest_debt'), fin.get('total_equity')
        if d is not None and e is not None and (d + e) > 0:
            debt_ratio = d / (d + e)
    kd_after_tax = 0.035 * (1 - 0.25)
    wacc = ke * (1 - debt_ratio) + kd_after_tax * debt_ratio
    return {
        'wacc': round(wacc * 100, 2),
        'ke': round(ke * 100, 2),
        'rf': r_f * 100, 'erp': erp * 100,
        'beta': round(beta, 2), 'beta_source': beta_src,
        'debt_ratio': round(debt_ratio * 100, 1),
        'note': '简化 CAPM，仅供横向参照',
    }


def _beta(code, days=120):
    """Beta 回归。

    主窗口 120 日（60 日噪声过大：实测同只票 60 日 0.41 / 120 日 2.12），
    并用 250 日长窗口做稳健性参照，取两者中位数。
    样本不足或计算失败时返回 (1.0, 'default')。
    """
    vals = []
    srcs = []
    for w in (120, 250):
        b, s = _beta_window(code, w)
        if s != 'default':
            vals.append(b)
            srcs.append('%dd' % w)
    if not vals:
        return 1.0, 'default'
    vals.sort()
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[0] + vals[1]) / 2
    return round(med, 2), 'regression_' + '+'.join(srcs)


def _beta_window(code, days):
    """单个窗口的回归 beta。取不到返回 (1.0, 'default')。"""
    try:
        hist = _index_hist('000300', days)
        own = _stock_hist(code, days)
        if not hist or not own:
            return 1.0, 'default'
        common = sorted(set(hist) & set(own))
        if len(common) < 40:
            return 1.0, 'default'
        base_s, base_m = own[common[0]], hist[common[0]]
        if base_s <= 0 or base_m <= 0:
            return 1.0, 'default'
        rs = [own[d] / base_s for d in common]
        rm = [hist[d] / base_m for d in common]
        ms, mm = sum(rs) / len(rs), sum(rm) / len(rm)
        var = sum((x - mm) ** 2 for x in rm)
        if var <= 1e-9:
            return 1.0, 'default'
        cov = sum((rs[i] - ms) * (rm[i] - mm) for i in range(len(common)))
        return round(cov / var, 2), 'regression'
    except Exception:
        return 1.0, 'default'


_HIST_CACHE = {}


def _index_hist(code, days):
    """腾讯 qt.gtimg.cn 日K（近 days 日）。返回 {date: close}。"""
    key = 'idx_%s_%d' % (code, days)
    if key in _HIST_CACHE:
        return _HIST_CACHE[key]
    try:
        import requests
        url = ('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
               '?param=sh%s,day,,,%d,qfq' % (code, days + 5))
        r = requests.get(url, timeout=12,
                         headers={'User-Agent': 'Mozilla/5.0'})
        js = r.json()
        node = js.get('data', {}).get('sh%s' % code, {})
        arr = node.get('qfqday') or node.get('day') or []
        out = {}
        for row in arr:
            if len(row) >= 3:
                out[str(row[0])] = float(row[2])
        _HIST_CACHE[key] = out
        return out
    except Exception:
        _HIST_CACHE[key] = {}
        return {}


def _stock_hist(code, days):
    key = 'stk_%s_%d' % (code, days)
    if key in _HIST_CACHE:
        return _HIST_CACHE[key]
    try:
        import requests
        mkt = 'sh' if code.startswith(('6', '9')) else 'sz'
        url = ('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
               '?param=%s%s,day,,,%d,qfq' % (mkt, code, days + 5))
        r = requests.get(url, timeout=12,
                         headers={'User-Agent': 'Mozilla/5.0'})
        js = r.json()
        node = js.get('data', {}).get('%s%s' % (mkt, code), {})
        arr = node.get('qfqday') or node.get('day') or []
        out = {}
        for row in arr:
            if len(row) >= 3:
                out[str(row[0])] = float(row[2])
        _HIST_CACHE[key] = out
        return out
    except Exception:
        _HIST_CACHE[key] = {}
        return {}


def market_risk(code, days=250):
    """市场风险：Beta、年化波动率、最大回撤。"""
    hist = _stock_hist(code, days)
    if len(hist) < 60:
        return {'available': False, 'na_reason': '行情历史不足60个交易日'}
    dates = sorted(hist)
    closes = [hist[d] for d in dates]
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            rets.append(closes[i] / closes[i - 1] - 1)
    if len(rets) < 30:
        return {'available': False, 'na_reason': '收益率样本不足'}
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
    vol = math.sqrt(var) * math.sqrt(244) * 100
    peak = closes[0]
    mdd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        if peak > 0:
            mdd = min(mdd, c / peak - 1)
    beta, bsrc = _beta(code)
    return {
        'available': True,
        'beta': beta, 'beta_source': bsrc,
        'volatility_ann': round(vol, 1),
        'max_drawdown': round(mdd * 100, 1),
        'days': len(closes),
    }


# ------------------------------------------------------------------ 主入口
def build_facts(code, fin=None, extra=None):
    """汇总事实包。返回 {facts: [...], gaps: [...], blocks: {...}}

    facts 里每条 = {'key', 'label', 'value', 'text', 'source'}
    gaps 里每条 = {'key', 'label', 'reason'}  —— 写作层必须显式声明这些缺口
    """
    facts, gaps = [], []
    blocks = {}

    # 金融业（银行/保险/券商）报表口径不同：现金流量表常整表不披露，
    # 资本开支、预付款项、ROIC 也不适用。识别出来后缺口说明改为"行业不适用"，
    # 避免把结构性差异误报成数据缺陷。
    fin_like = _is_financial(code, fin)

    # ---------- 现金流画像 ----------
    cf = cashflow(code)
    bal = balance(code)
    mf = mainfin(code)          # 财务主表：ROIC / 杠杆 / 扣非利润
    mf0 = _period(mf, 0) if mf else {}
    cf0 = _period(cf, 0)
    cf1 = _period(cf, 1)
    b0 = _period(bal, 0)
    b1 = _period(bal, 1)

    nco = _f(cf0.get('NETCASH_OPERATE'))
    nco_yoy = _f(cf0.get('NETCASH_OPERATE_YOY'))
    capex = _f(cf0.get('CONSTRUCT_LONG_ASSET'))
    da = _da_of(cf0)
    prepay = _f(b0.get('PREPAYMENT'))
    prepay_prev = _f(b1.get('PREPAYMENT'))
    cfo = _f(cf0.get('FINANCE_EXPENSE'))

    if nco is not None:
        facts.append({'key': 'cfo', 'label': '经营现金流', 'value': nco,
                      'text': '报告期经营活动现金流净额 %s 亿元' % _num(nco / 1e8, 2),
                      'source': 'RPT_F10_FINANCE_GCASHFLOW'})
        if nco_yoy is not None:
            facts.append({'key': 'cfo_yoy', 'label': '经营现金流同比',
                          'value': nco_yoy,
                          'text': '同比%s %s%%' % ('增长' if nco_yoy >= 0 else '下降',
                                               _num(abs(nco_yoy), 1)),
                          'source': 'RPT_F10_FINANCE_GCASHFLOW'})
    else:
        gaps.append({'key': 'cfo', 'label': '经营现金流',
                     'reason': _na_reason(fin_like, '现金流量表未返回该期数据')})

    if capex is not None:
        facts.append({'key': 'capex', 'label': '资本开支', 'value': capex,
                      'text': '购建固定资产等支出 %s 亿元' % _num(capex / 1e8, 2),
                      'source': 'RPT_F10_FINANCE_GCASHFLOW'})
    else:
        gaps.append({'key': 'capex', 'label': '资本开支',
                     'reason': _na_reason(fin_like, '现金流量表未返回该期数据')})

    if nco is not None and capex is not None:
        fcf = nco - capex
        facts.append({'key': 'fcf', 'label': '自由现金流(简化)', 'value': fcf,
                      'text': '自由现金流（经营现金流-资本开支）%s 亿元'
                              % _num(fcf / 1e8, 2),
                      'source': 'RPT_F10_FINANCE_GCASHFLOW'})
        if da is not None and da > 0:
            facts.append({'key': 'capex_vs_da', 'label': '资本开支/折旧摊销',
                          'value': round(capex / da, 1),
                          'text': '资本开支是折旧摊销的 %s 倍' % _num(capex / da, 1),
                          'source': 'RPT_F10_FINANCE_GCASHFLOW'})
    else:
        gaps.append({'key': 'fcf', 'label': '自由现金流',
                     'reason': '经营现金流或资本开支缺失，无法计算'})

    if prepay is not None:
        txt = '预付款项 %s 亿元' % _num(prepay / 1e8, 2)
        if prepay_prev is not None and prepay_prev > 0:
            txt += '，上期 %s 亿元' % _num(prepay_prev / 1e8, 2)
        facts.append({'key': 'prepay', 'label': '预付款项', 'value': prepay,
                      'text': txt, 'source': 'RPT_F10_FINANCE_GBALANCE'})
    else:
        gaps.append({'key': 'prepay', 'label': '预付款项',
                     'reason': '资产负债表未返回该期数据'})

    blocks['cashflow'] = {'facts': facts, 'gaps': gaps}

    # ---------- 资本回报 ----------
    roic = _f((fin or {}).get('roic'))
    if roic is None:
        roic = _f((fin or {}).get('ROIC'))
    if roic is None:
        roic = _f(mf0.get('ROIC'))       # 2026-10-20：主表自取，别再只靠调用方传 fin
    cash = _f(b0.get('MONETARYFUNDS'))
    equity = _f(b0.get('TOTAL_EQUITY'))
    mcap = (extra or {}).get('total_market_cap')
    if mcap is None and extra:
        mcap = _f(extra.get('TOTAL_MARKET_CAP'))

    wacc_info = _simplified_wacc(code, {
        'interest_debt': _interest_debt(b0),
        'total_equity': equity,
    })

    cr_facts, cr_gaps = [], []
    if roic is not None:
        cr_facts.append({'key': 'roic', 'label': 'ROIC', 'value': roic,
                          'text': 'ROIC %s%%' % _num(roic, 2),
                          'source': 'RPT_F10_FINANCE_MAINFINADATA'})
    else:
        cr_gaps.append({'key': 'roic', 'label': 'ROIC',
                        'reason': '财务主表未返回 ROIC（多为亏损或数据缺失）'})

    cr_facts.append({
        'key': 'wacc', 'label': 'WACC(简化)', 'value': wacc_info['wacc'],
        'text': '简化 WACC 约 %s%%（β=%s，来源 %s）'
                % (_num(wacc_info['wacc'], 2), wacc_info['beta'],
                   '回归计算' if wacc_info['beta_source'] == 'regression_60d'
                   else '默认1.0'),
        'source': '计算:简化CAPM'})

    if roic is not None:
        spread = roic - wacc_info['wacc']
        cr_facts.append({
            'key': 'roic_wacc_spread', 'label': 'ROIC-WACC 差', 'value': round(spread, 2),
            'text': 'ROIC 与 WACC 相差 %s 个百分点，%s'
                    % (_num(abs(spread), 2),
                       '高于' if spread >= 0 else '低于'),
            'source': '计算'})

    net_cash = None
    if cash is not None and equity is not None:
        net_cash = cash - (_interest_debt(b0) or 0)
        cr_facts.append({
            'key': 'net_cash', 'label': '净现金', 'value': net_cash,
            'text': '货币资金减有息负债后约 %s 亿元' % _num(net_cash / 1e8, 2),
            'source': 'RPT_F10_FINANCE_GBALANCE'})
        if mcap and mcap > 0:
            cr_facts.append({
                'key': 'net_cash_to_mcap', 'label': '净现金/市值',
                'value': round(net_cash / mcap * 100, 1),
                'text': '净现金约占总市值 %s%%' % _num(net_cash / mcap * 100, 1),
                'source': '计算'})

    blocks['capital_return'] = {'facts': cr_facts, 'gaps': cr_gaps,
                                'wacc_detail': wacc_info}

    # ---------- 估值分位 ----------
    vp = valuation_percentile(code)
    val_facts, val_gaps = [], []
    if vp:
        for metric, label in (('PE_TTM', 'PE(TTM)'), ('PB_MRQ', 'PB'),
                              ('PS_TTM', 'PS(TTM)'), ('PCF_OCF_TTM', 'PCF(经营现金流)')):
            if metric not in vp:
                continue
            w5 = vp[metric].get('5') or vp[metric].get('3')
            if not w5:
                continue
            yr = '5' if '5' in vp[metric] else '3'
            # 失真护栏：分母趋零的倍数（PCF 靠经营现金流做分母），
            # 分位再准，倍数本身不可信 —— 2026-10-20 芯朋微 PCF 4723.69 就是这种
            if _is_distorted_multiple(metric, w5.get('value')):
                val_gaps.append({
                    'key': 'pctl_%s_distorted' % metric,
                    'label': '%s %s年分位' % (label, yr),
                    'reason': '%s 当前 %s，因分母趋零导致倍数失真，'
                              '其历史分位不构成有效刻度，已剔除'
                              % (label, _num(w5['value'], 2))})
                continue
            zone = valuation_zone(w5['pctl'])
            val_facts.append({
                'key': 'pctl_%s' % metric, 'label': '%s %s年分位' % (label, yr),
                'value': w5['pctl'],
                'text': '%s 当前 %s，处在近 %s 年 %s 分位（区间 %s~%s，中位 %s），属%s'
                        % (label, _num(w5['value'], 2), yr, _num(w5['pctl'], 1),
                           _num(w5['min'], 2), _num(w5['max'], 2),
                           _num(w5['median'], 2), zone),
                'source': 'RPT_VALUEANALYSIS_DET'})
    else:
        val_gaps.append({'key': 'val_percentile', 'label': '历史估值分位',
                         'reason': '估值日频序列不可得（可能长期亏损或上市时间短）'})

    blocks['valuation'] = {'facts': val_facts, 'gaps': val_gaps,
                           'percentile': vp}

    # ---------- 盈利质量：扣非口径 ----------
    # 这是 2026-10-20 补的最要紧的一块：PE_TTM 的分母是 TTM 归母净利，
    # 里面含公允价值变动等非经常性损益。688508 实例：
    # 表观 PE 88.1 倍看着「只是偏高」，但 TTM 扣非归母净利 = -483 万（亏损），
    # 扣非口径下 PE 根本不成立。不把扣非摆出来，写到「PE 属高估区」就是误导。
    pq_facts, pq_gaps = [], []
    ded_cum = _f(mf0.get('KCFJCXSYJLR'))
    ded_ttm = _ttm_from_cumulative(mf, 'KCFJCXSYJLR')
    # 扣非同比用 KCFJCXSYJLRTZ（报告期累计口径），
    # 不用 DJD_DEDUCTDPNP_YOY（单季度口径）：688508 三季报累计扣非 0.11 亿 vs 去年 0.72 亿
    # → 累计同比 -84.3%；单季度口径算出 -671%，基数效应把数字放大到失真。
    ded_yoy = _f(mf0.get('KCFJCXSYJLRTZ'))
    if ded_yoy is None:
        ded_yoy = _f(mf0.get('DJD_DEDUCTDPNP_YOY'))
    np_parent = _f(mf0.get('PARENTNETPROFIT'))
    quote = _LAST_QUOTE.get(code) or {}
    mcap_q = _f(quote.get('TOTAL_MARKET_CAP'))
    pe_q = _f(quote.get('PE_TTM'))

    if ded_cum is not None:
        pq_facts.append({
            'key': 'deducted_profit', 'label': '扣非归母净利（报告期）', 'value': ded_cum,
            'text': '报告期扣除非经常性损益后的归母净利 %s 亿元%s'
                    % (_num(ded_cum / 1e8, 2),
                       ('，同比%s %s%%' % ('增长' if ded_yoy >= 0 else '下降', _num(abs(ded_yoy), 1)))
                       if ded_yoy is not None else ''),
            'source': 'RPT_F10_FINANCE_MAINFINADATA'})
    else:
        pq_gaps.append({'key': 'deducted_profit', 'label': '扣非归母净利（报告期）',
                        'reason': '财务主表未返回 KCFJCXSYJLR（该期无扣非数据或为金融业口径）'})

    if np_parent is not None:
        pq_facts.append({
            'key': 'parent_net_profit', 'label': '归母净利润（报告期）', 'value': np_parent,
            'text': '报告期归母净利润 %s 亿元%s'
                    % (_num(np_parent / 1e8, 2),
                       ('，其中扣非 %s 亿元，非经常性损益约 %s 亿元'
                        % (_num(ded_cum / 1e8, 2), _num((np_parent - ded_cum) / 1e8, 2)))
                       if ded_cum is not None else ''),
            'source': 'RPT_F10_FINANCE_MAINFINADATA'})

    if ded_ttm is not None:
        pq_facts.append({
            'key': 'deducted_ttm_profit', 'label': '扣非归母净利(TTM)', 'value': ded_ttm,
            'text': 'TTM 扣非归母净利 %s 亿元%s'
                    % (_num(ded_ttm / 1e8, 2),
                       '（扣非口径已亏损）' if ded_ttm <= 0 else ''),
            'source': '计算:年报+本期累计-去年同期累计'})

    # 扣非口径 PE
    if ded_ttm is not None and mcap_q is not None:
        if ded_ttm > 0:
            ded_pe = mcap_q / ded_ttm
            pq_facts.append({
                'key': 'pe_deducted_ttm', 'label': 'PE(扣非TTM)', 'value': round(ded_pe, 2),
                'text': '按 TTM 扣非归母净利 %s 亿元计，扣非口径 PE 约 %s 倍'
                        % (_num(ded_ttm / 1e8, 2), _num(ded_pe, 1)),
                'source': '计算:总市值/TTM扣非归母净利'})
            if pe_q and pe_q > 0 and ded_pe > pe_q * 1.5:
                pq_facts.append({
                    'key': 'pe_gap_explained', 'label': 'PE 口径差',
                    'value': round(ded_pe / pe_q, 2),
                    'text': '表观 PE(TTM) %s 倍，扣非口径 PE %s 倍，'
                            '差值来自非经常性损益，估值判断应以扣非口径为准'
                            % (_num(pe_q, 1), _num(ded_pe, 1)),
                    'source': '计算'})
        else:
            pq_facts.append({
                'key': 'pe_deducted_ttm', 'label': 'PE(扣非TTM)', 'value': None,
                'text': 'TTM 扣非归母净利为 %s 亿元（亏损），扣非口径 PE 不成立；'
                        '表观 PE(TTM) %s 倍的盈利分母含非经常性损益，不能当作可持续盈利的估值'
                        % (_num(ded_ttm / 1e8, 2), _num(pe_q, 1) if pe_q else 'N/A'),
                'source': '计算:总市值/TTM扣非归母净利'})
    elif ded_ttm is not None:
        pq_gaps.append({'key': 'pe_deducted_ttm', 'label': 'PE(扣非TTM)',
                        'reason': '总市值不可得，无法计算扣非口径 PE'})

    # 主表补齐的杠杆/质量指标（之前全部落在 gaps，写作层看不到）
    for fld, key, label, fmt, note in (
            ('ZCFZL', 'debt_ratio', '资产负债率', '%s%%', '来自财务主表'),
            ('INTSTCOVRATE', 'interest_cover', '利息保障倍数', '%s 倍', '来自财务主表'),
            ('QYCS', 'cash_short_debt', '现金短债比', '%s', '来自财务主表'),
            # 踩过的坑：主表里 NETCASH_OPERATE_PK 是「经营活动现金流净额（元）」不是比率，
            # 真正比率字段是 NCO_NETPROFIT（净现比 = 经营现金流 / 归母净利）。
            ('NCO_NETPROFIT', 'ocf_np', '净现比(经营现金流/归母净利)', '%s', '来自财务主表')):
        v = _f(mf0.get(fld))
        if v is not None:
            pq_facts.append({'key': key, 'label': label, 'value': v,
                             'text': '%s %s' % (label, fmt % _num(v, 2)),
                             'source': 'RPT_F10_FINANCE_MAINFINADATA'})
        else:
            pq_gaps.append({'key': key, 'label': label,
                            'reason': '财务主表未返回 %s（该期缺失或口径不适用）' % fld})

    blocks['profit_quality'] = {'facts': pq_facts, 'gaps': pq_gaps}

    # 2026-10-20 修：PE 分位与扣非口径的内在矛盾。
    # PE_TTM 的分母是 TTM 归母净利（含非经常性损益），当扣非口径已经亏损时，
    # PE 这个指标本身失效，它的「历史分位 81.8% 属高估区」就成了误导性结论。
    # LLM 会同时写「扣非 PE 不成立」和「PE 处在高估区」——critic 判为 high 级逻辑矛盾。
    # 治法在 facts 层：把限定条件直接写进这条 fact 的文本里，让写作层没有误用空间。
    if ded_ttm is not None and ded_ttm <= 0:
        for _fct in blocks['valuation']['facts']:
            if _fct.get('key') == 'pctl_PE_TTM':
                _fct['text'] += ('；但该 PE 的分母为 TTM 归母净利、含非经常性损益，'
                                 '扣非口径下 PE 已不成立，因此本分位不可用于高估/低估判断，'
                                 '仅作历史位置参考')

    # ---------- 风险画像 ----------
    rs_facts, rs_gaps = [], []
    mr = market_risk(code)
    if mr.get('available'):
        rs_facts.append({
            'key': 'beta', 'label': 'Beta', 'value': mr['beta'],
            'text': 'Beta 约 %s（%s），%s'
                    % (_num(mr['beta'], 2), mr['beta_source'],
                       '弹性高于大盘' if mr['beta'] > 1.1 else
                       ('弹性低于大盘' if mr['beta'] < 0.9 else '与大盘接近')),
            'source': '计算:60日回归沪深300'})
        rs_facts.append({
            'key': 'vol', 'label': '年化波动率', 'value': mr['volatility_ann'],
            'text': '近 %d 个交易日年化波动率 %s%%' % (mr['days'], _num(mr['volatility_ann'], 1)),
            'source': '计算:qt.gtimg.cn'})
        rs_facts.append({
            'key': 'mdd', 'label': '最大回撤', 'value': mr['max_drawdown'],
            'text': '区间最大回撤 %s%%' % _num(abs(mr['max_drawdown']), 1),
            'source': '计算:qt.gtimg.cn'})
    else:
        rs_gaps.append({'key': 'market_risk', 'label': '市场风险',
                        'reason': mr.get('na_reason') or '行情数据不足'})

    if fin:
        dbt = _f(fin.get('ZCFZL'))
        cov = _f(fin.get('INTSTCOVRATE'))
        qy = _f(fin.get('QYCS'))
        cfo_np = _f(fin.get('NETCASH_OPERATE_PK'))
        for k, label, fmt, src in (
                ('ZCFZL', '资产负债率', '%s%%', 'RPT_F10_FINANCE_MAINFINADATA'),
                ('INTSTCOVRATE', '利息保障倍数', '%s 倍', 'RPT_F10_FINANCE_MAINFINADATA'),
                ('QYCS', '现金短债比', '%s', 'RPT_F10_FINANCE_MAINFINADATA'),
                ('NETCASH_OPERATE_PK', '经营现金流/净利润', '%s', 'RPT_F10_FINANCE_MAINFINADATA')):
            v = _f(fin.get(k))
            if v is not None:
                rs_facts.append({'key': k, 'label': label, 'value': v,
                                 'text': '%s %s' % (label, fmt % _num(v, 2)),
                                 'source': src})
            else:
                rs_gaps.append({'key': k, 'label': label,
                                'reason': '财务主表未返回该字段'})

    goodwill = _f(b0.get('GOODWILL'))
    if goodwill is not None and equity:
        rs_facts.append({
            'key': 'goodwill_ratio', 'label': '商誉/净资产',
            'value': round(goodwill / equity * 100, 1),
            'text': '商誉占净资产 %s%%' % _num(goodwill / equity * 100, 1),
            'source': 'RPT_F10_FINANCE_GBALANCE'})

    blocks['risk'] = {'facts': rs_facts, 'gaps': rs_gaps}

    # ---------- 分部结构 ----------
    seg = _segment_blocks(code)
    blocks['segment'] = seg

    all_facts = (blocks['cashflow']['facts'] + blocks['capital_return']['facts']
                 + blocks['valuation']['facts'] + blocks['risk']['facts']
                 + blocks['profit_quality']['facts']
                 + seg.get('facts', []))
    all_gaps = (blocks['cashflow']['gaps'] + blocks['capital_return']['gaps']
                + blocks['valuation']['gaps'] + blocks['risk']['gaps']
                + blocks['profit_quality']['gaps']
                + seg.get('gaps', []))
    return {'facts': all_facts, 'gaps': all_gaps, 'blocks': blocks}


def _is_financial(code, fin=None):
    """是否金融业。金融业报表口径与实业不同，部分指标不适用。"""
    try:
        from stockscore import FIN_INDUSTRY_RE, stock_basic
        b = stock_basic(code) or {}
        name = ' '.join(str(b.get(k) or '') for k in
                        ('CSRC_INDUSTRY_NAME', 'BOARD_NAME_1LEVEL',
                         'BOARD_NAME_2LEVEL', 'BOARD_NAME_3LEVEL'))
        if name and FIN_INDUSTRY_RE and FIN_INDUSTRY_RE.search(name):
            return True
    except Exception:
        pass
    # 兜底：银行/保险/证券按代码段粗判（601398 等）
    try:
        b = (fin or {}).get('industry') or ''
        if b and FIN_INDUSTRY_RE and FIN_INDUSTRY_RE.search(str(b)):
            return True
    except Exception:
        pass
    return False


def _na_reason(fin_like, default):
    return '金融业报表口径不含此项' if fin_like else default


def _interest_debt(bal):
    """有息负债 = 短期借款 + 长期借款 + 应付债券。"""
    if not bal:
        return None
    tot = 0.0
    got = False
    for k in ('SHORT_LOAN', 'LONG_LOAN', 'BOND_PAYABLE'):
        v = _f(bal.get(k))
        if v is not None:
            tot += v
            got = True
    return tot if got else None


def _segment_blocks(code, periods=8):
    """分部结构块：把主营构成整理成可写的句子 + 同期增速对比。

    periods 默认 8 期——需要足够回溯才能找到"去年同期"做同口径对比
    （半年报必须比半年报，不能比年报）。
    """
    rows = main_business_detail(code, periods=periods)
    facts, gaps = [], []
    if not rows:
        gaps.append({'key': 'segment', 'label': '分部结构',
                     'reason': '主营构成数据不可得（未按产品/地区披露）'})
        return {'facts': facts, 'gaps': gaps, 'items': []}

    by_date = {}
    for r in rows:
        d = str(r.get('REPORT_DATE') or '')[:10]
        typ = r.get('MAINOP_TYPE')
        by_date.setdefault((d, typ), []).append(r)

    items = []
    for (d, typ), rs in sorted(by_date.items(), key=lambda x: (x[0][0], str(x[0][1])), reverse=True):
        for r in rs:
            inc = _f(r.get('MAIN_BUSINESS_INCOME'))
            ratio = _pct(r.get('MBI_RATIO'))
            gp = _pct(r.get('GROSS_RPOFIT_RATIO'))
            if inc is None and ratio is None:
                continue
            items.append({
                'date': d, 'type': typ, 'name': r.get('ITEM_NAME'),
                'income': inc, 'ratio': ratio, 'gross_margin': gp,
            })

    # MAINOP_TYPE 语义（实测 688279）：1=按行业 2=按产品 3=按地区。
    # 优先按产品（最能解释"一体两翼"式结构），没有则退到按地区。
    types_present = {i['type'] for i in items}
    if '2' in types_present:
        seg_type = '2'
    elif '3' in types_present:
        seg_type = '3'
    else:
        seg_type = '1'
    items = [i for i in items if i['type'] == seg_type]

    # 取最新一期金额最大的 4 个分部（排除"其他(补充)"噪声项之外照常排序）
    latest = max((i['date'] for i in items), default='')
    cur = sorted([i for i in items if i['date'] == latest],
                 key=lambda x: -(x['income'] or 0))[:4]
    for it in cur:
        if it['income'] is None:
            continue
        parts = ['%s收入 %s 亿元' % (it['name'], _num(it['income'] / 1e8, 2))]
        if it['ratio'] is not None:
            parts.append('占比 %s%%' % _num(it['ratio'], 1))
        if it['gross_margin'] is not None:
            parts.append('毛利率 %s%%' % _num(it['gross_margin'], 1))
        facts.append({
            'key': 'seg_%s_%s' % (it['date'], it['name']),
            'label': '分部 %s' % it['name'], 'value': it['income'],
            'text': '（%s）%s' % (latest, '，'.join(parts)),
            'source': 'RPT_F10_FN_MAINOP'})

    # 同期比较：必须拿"去年同期"比，不能拿上一期（半年报 vs 年报口径不同，
    # 否则会写出"从 4.82 亿增至 3.91 亿，同比下降"这种自相矛盾的句子）。
    yoy = _same_period_last_year(latest)
    if yoy:
        prev_map = {i['name']: i for i in items if i['date'] == yoy}
        for it in cur:
            p = prev_map.get(it['name'])
            if not p or it['income'] is None or not p.get('income'):
                continue
            growth = (it['income'] / p['income'] - 1) * 100
            if abs(growth) < 10:
                continue
            verb = '增至' if growth >= 0 else '降至'
            facts.append({
                'key': 'seg_growth_%s' % it['name'],
                'label': '分部 %s 同比' % it['name'], 'value': round(growth, 1),
                'text': '分部 %s 收入%s %s 亿元（去年同期 %s 亿元），同比%s %s%%'
                        % (it['name'], verb, _num(it['income'] / 1e8, 2),
                           _num(p['income'] / 1e8, 2),
                           '增长' if growth >= 0 else '下降',
                           _num(abs(growth), 1)),
                'source': 'RPT_F10_FN_MAINOP'})
    else:
        gaps.append({'key': 'segment_yoy', 'label': '分部同比',
                     'reason': '未取得去年同期同口径分部数据'})

    return {'facts': facts, 'gaps': gaps, 'items': items,
            'period': latest, 'seg_type': seg_type}


def _same_period_last_year(date_str):
    """'2026-06-30' -> '2025-06-30'。用于同期对比。"""
    if not date_str or len(date_str) < 4:
        return None
    try:
        y = int(date_str[:4]) - 1
        return '%04d%s' % (y, date_str[4:])
    except (TypeError, ValueError):
        return None
