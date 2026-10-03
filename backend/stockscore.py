# -*- coding: utf-8 -*-
"""个股打分卡引擎（spec: D:/hermesfiles/松果商业生态/个股打分卡/spec.md v1.0，2026-10-03）

六维权重：盈利质量22 / 成长18 / 估值20 / 财务健康15 / 资金动能13 / 概念景气12
- P1 分位优先：连续指标全部转 0–100 分位（percentile rank = 低于当前值的样本占比，
  两端 5% Winsorize）。仅 spec 明写的硬规则用绝对刻度（现金保险丝封顶60、
  背离>30pct→×0.85、概念命中数分档）。
- P2 现金流保险丝：近3年 NCO_NETPROFIT 均值 <0.7 → 盈利质量维封顶 60 并标低置信。
- P3 缺失维不计分：available=false 进 excluded，剩余权重归一化，严禁填 0 分。

数据分层（接口可用性矩阵报告 2026-10-03 实测）：
  datacenter-web.eastmoney.com（稳定区）：F10 财务/个股估值日频序列/行业估值/两融/分红/预告/映射
  新浪 MoneyFlow.ssl_qsfx_zjlrqs（稳定）：主力资金流（口径锁定，禁东财 fflow）
  腾讯 qt.gtimg.cn（最稳，GBK）：实时价/PE/PB/市值
  push2 clist：高危——本模块**绝不实时调用**，只读每日采集脚本落盘的板块快照

分位宇宙 = 同日全市场横截面（日级缓存 + 启动预热，成本≈20 次稳定区请求/天）。

score 契约（对齐 spec §6/§7 两种读法，见交付报告"spec 疑问"节）：
  dims[i].score         = 维内 0–100 分（spec §6 示例 78.4/权重0.22 的读法）
  dims[i].weighted_score = 归一化后对总分的贡献 = score*weight/Σavailable_weight
  total = Σ weighted_score（同一批 float 精确相加，1e-6 可复算）
  fundamental_score = ①②④ 按自身权重归一；trading_score = ⑤⑥ 按自身权重归一。
"""
import os
import re
import json
import math
import time
import threading

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(BASE_DIR, 'data', 'board_snapshots')   # 采集脚本产物
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
DC = 'https://datacenter-web.eastmoney.com/api/data/v1/get'

FIN_INDUSTRY_RE = re.compile('银行|证券|保险|多元金融')
REALESTATE_RE = re.compile('房地产')
PHARMA_SEMI_RE = re.compile('医药|生物|半导体')
BANNED_RE = re.compile('买入|卖出|加仓|减仓|目标价|必涨|稳赚|推荐|持有|建仓|清仓')


def tier_of(total):
    if total is None:
        return None
    return '优' if total >= 80 else '良' if total >= 65 else '中' if total >= 45 else '待观察'


FUND_DIMS = {'profit_quality', 'growth', 'financial_health'}
MKT_DIMS = {'valuation', 'capital_momentum', 'concept_heat'}   # 市场侧：③⑤⑥（日频）

FINANCE_COLS = ('SECUCODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_DATE_NAME,NOTICE_DATE,'
                'ROEKCJQ,ROIC,NCO_NETPROFIT,XSMLL,XSJLL,ZZCJLL,TOTAL_ROI,TOAZZL,CQBL,QYCS,ZCFZL,'
                'INTEREST_DEBT_RATIO,INTSTCOVRATE,LD,SD,NETCASH_OPERATE_PK,LIABILITY,'
                'TOTALOPERATEREVE,KCFJCXSYJLR,DJD_TOI_YOY,DJD_DEDUCTDPNP_YOY')

_uni_lock = threading.Lock()
_uni = {}
_uni_building = {'flag': False}


# ================================================================ 基础取数
def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def dc_get(report_name, flt, columns='ALL', page=1, size=500, sort_col=None, sort_dir=-1,
           source='WEB', retries=3):
    params = {'reportName': report_name, 'columns': columns, 'filter': flt,
              'pageNumber': page, 'pageSize': size, 'source': source, 'client': 'PC'}
    if sort_col:
        params['sortColumns'] = sort_col
        params['sortTypes'] = sort_dir
    for attempt in range(retries):
        try:
            r = requests.get(DC, params=params, headers=UA, timeout=20)
            d = r.json()
            res = d.get('result') or {}
            if res.get('data'):
                return res['data'], res.get('count', 0), res.get('pages', 1)
            return None, 0, 0
        except Exception:
            time.sleep(1.0 + attempt)
    return None, 0, 0


def dc_all(report_name, flt, columns='ALL', sort_col=None, sort_dir=-1, max_pages=24, source='WEB'):
    out = []
    page = 1
    while page <= max_pages:
        data, count, pages = dc_get(report_name, flt, columns, page, 5000, sort_col, sort_dir, source)
        if data is None:
            break
        out.extend(data)
        if page >= (pages or 1):
            break
        page += 1
        time.sleep(0.35)
    return out


def market_prefix(code):
    if code[0] in ('6', '9') or (code[0] == '5'):
        return 'sh' + code
    if code[0] in ('4', '8'):
        return 'bj' + code
    return 'sz' + code


def secu(code):
    mk = 'SH' if code[0] in ('5', '6', '9') else 'BJ' if code[0] in ('4', '8') else 'SZ'
    return f"{code}.{mk}"


def tx_quote(code):
    url = f"https://qt.gtimg.cn/q={market_prefix(code)}"
    for _ in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=15)
            r.encoding = 'gbk'
            f = r.text.split('"')[1].split('~')
            t = f[30] if len(f) > 30 else ''
            return {'price': _num(f[3]), 'pe_ttm': _num(f[39]), 'pb': _num(f[46]),
                    'mv_yi': _num(f[44]), 'float_mv_yi': _num(f[45]),
                    'ts': (f'{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:14]}'
                           if len(t) >= 14 else '')}
        except Exception:
            time.sleep(1)
    return None


def sina_moneyflow(code, num=80):
    url = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={num}&sort=opendate&asc=0&daima={market_prefix(code)}')
    try:
        r = requests.get(url, headers=UA, timeout=15)
        arr = json.loads(r.text)
        return [{'date': x.get('opendate'), 'netamount': _num(x.get('netamount')),
                 'ratioamount': _num(x.get('ratioamount'))} for x in arr]
    except Exception:
        return []


# ================================================================ 分位（spec §2）
def pct_rank(series, value, winsor=0.05):
    s = sorted(x for x in series if x is not None)
    if value is None or len(s) < 5:
        return None
    lo = s[int(len(s) * winsor)]
    hi = s[min(int(len(s) * (1 - winsor)), len(s) - 1)]
    v = min(max(value, lo), hi)
    return sum(1 for x in s if x < v) / float(len(s)) * 100.0


def conf_for(pctl, n_samples=None, coarse=False):
    c = 1.0
    if n_samples is not None and n_samples < 60:
        c *= 0.7
    if pctl is not None and (pctl < 5 or pctl > 95):
        c *= 0.8
    if coarse:
        c *= 0.6
    return round(c, 2)


# ================================================================ 日级宇宙
def _today():
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() + 28800))


def _build_universe():
    u = {'date': _today(), 'errors': []}
    RPT_FIN = 'RPT_F10_FINANCE_MAINFINADATA'
    RPT_VAL = 'RPT_VALUEANALYSIS_DET'

    # 最新披露期（取"披露家数最多"的最近期，避免财报季只有一只先披露导致宇宙过窄）
    data, _, _ = dc_get(RPT_FIN, f"(REPORT_DATE>='{_shift_days(400)}')", 'REPORT_DATE,SECUCODE',
                        page=1, size=5000, sort_col='REPORT_DATE', sort_dir=-1, source='HSF10')
    latest_period = None
    if data:
        from collections import Counter
        cnt = Counter(str(r['REPORT_DATE'])[:10] for r in data if re.match(r'^\d{6}\.', str(r.get('SECUCODE') or '')))
        if cnt:
            # 候选=最近 4 个期，取其中记录数最大者
            periods = sorted(cnt, reverse=True)[:4]
            latest_period = max(periods, key=lambda d: cnt[d])
    u['latest_period'] = latest_period
    if not latest_period:
        u['errors'].append('最新财报期探测失败——分位宇宙不可用，所有横截面分位降级')
        return u
    y = int(latest_period[:4])
    ann_dates = [f'{k}-12-31' for k in (y - 3, y - 2, y - 1)]

    # 近 3 个完整年报横截面 → ROE3min/毛利σ/3年CAGR 宇宙
    ann = {}
    for d in ann_dates:
        rows = dc_all(RPT_FIN, f"(REPORT_DATE='{d}')",
                      'SECUCODE,ROEKCJQ,XSMLL,TOTALOPERATEREVE,KCFJCXSYJLR', source='HSF10')
        for r in rows:
            sc = r.get('SECUCODE')
            if sc and re.match(r'^\d{6}\.', sc):
                ann.setdefault(sc, {})[d] = r
        time.sleep(0.3)
    u['annual'] = ann

    def _cagr(yrs, key):
        f0 = _num((yrs.get(ann_dates[0]) or {}).get(key))
        f1 = _num((yrs.get(ann_dates[-1]) or {}).get(key))
        if f0 is None or f1 is None or f0 <= 0 or f1 <= 0:
            return None
        return ((f1 / f0) ** (1.0 / 2.0) - 1.0) * 100.0   # 2023→2025 两年跨度=3年窗口

    def _roe3min(yrs):
        vs = [_num((yrs.get(d) or {}).get('ROEKCJQ')) for d in ann_dates]
        vs = [v for v in vs if v is not None]
        return min(vs) if vs else None

    def _gm_std(yrs):
        vs = [_num((yrs.get(d) or {}).get('XSMLL')) for d in ann_dates]
        vs = [v for v in vs if v is not None]
        if len(vs) < 2:
            return None
        m = sum(vs) / len(vs)
        return math.sqrt(sum((v - m) ** 2 for v in vs) / len(vs))

    def _col(fn):
        out = {}
        for sc, yrs in ann.items():
            v = fn(yrs)
            if v is not None:
                out[sc] = v
        return out

    u['univ_roe3min'] = _col(_roe3min)
    u['univ_gm_std'] = _col(_gm_std)
    u['univ_rev_cagr'] = _col(lambda y: _cagr(y, 'TOTALOPERATEREVE'))
    u['univ_dnp_cagr'] = _col(lambda y: _cagr(y, 'KCFJCXSYJLR'))

    # 最新期财务横截面（单季同比/ROIC/现金流/杠杆偿债宇宙）
    MC = ('SECUCODE,ROIC,NCO_NETPROFIT,XSMLL,CQBL,QYCS,ZCFZL,INTEREST_DEBT_RATIO,INTSTCOVRATE,'
          'LD,SD,DJD_TOI_YOY,DJD_DEDUCTDPNP_YOY,NETCASH_OPERATE_PK,LIABILITY,XSJLL')
    mid = {}
    for r in dc_all(RPT_FIN, f"(REPORT_DATE='{latest_period}')", MC, source='HSF10'):
        sc = r.get('SECUCODE')
        if sc and re.match(r'^\d{6}\.', sc):
            mid[sc] = r
    u['mid'] = mid
    if not mid:
        u['errors'].append('最新期财务横截面为空')

    # 估值全市场最新交易日快照（行业映射/市值/总股本/行业位次宇宙）
    data, _, _ = dc_get(RPT_VAL, f"(TRADE_DATE>='{_shift_days(200)}')", 'TRADE_DATE',
                        page=1, size=1, sort_col='TRADE_DATE', sort_dir=-1)
    vdate = str(data[0]['TRADE_DATE'])[:10] if data else None
    u['val_date'] = vdate
    vmap = {}
    if vdate:
        for r in dc_all(RPT_VAL, f"(TRADE_DATE='{vdate}')",
                        'SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,BOARD_CODE,BOARD_NAME,'
                        'PE_TTM,PB_MRQ,TOTAL_MARKET_CAP,TOTAL_SHARES'):
            if r.get('SECURITY_CODE'):
                vmap[r['SECURITY_CODE']] = r
    u['valmap'] = vmap
    if not vmap:
        u['errors'].append('估值全市场快照为空（行业位次/股息率宇宙降级）')

    # 行业当日横截面（127 个二级行业）
    u['industry_today'] = (dc_all('RPT_VALUEINDUSTRY_DET', f"(TRADE_DATE='{vdate}')",
                                  'BOARD_CODE,BOARD_NAME,PE_TTM,PB_MRQ,NUM,LOSS_COUNT')
                           if vdate else [])

    # 两融当日横截面
    rz = {}
    data, _, _ = dc_get('RPTA_WEB_RZRQ_GGMX', f"(DATE>='{_shift_days(200)}')", 'DATE',
                        page=1, size=1, sort_col='DATE', sort_dir=-1)
    u['rzrq_date'] = str(data[0]['DATE'])[:10] if data else None
    if u['rzrq_date']:
        for r in dc_all('RPTA_WEB_RZRQ_GGMX', f"(DATE='{u['rzrq_date']}')",
                        'SCODE,RZYE,RZMRE5D,RZCHE5D,RZYEZB,DATE'):
            if r.get('SCODE'):
                rz[r['SCODE']] = r
    u['rzrq_today'] = rz

    # 近一年实施分红 → 每股股息(TTM) 宇宙
    d0 = _shift_days(366)
    bonus = {}
    rows = dc_all('RPT_SHAREBONUS_DET',
                  f"(EX_DIVIDEND_DATE>='{d0}')(EX_DIVIDEND_DATE<='{_today()}')"
                  f'(ASSIGN_PROGRESS="实施分配")',
                  'SECUCODE,PRETAX_BONUS_RMB', source='HSF10')
    for r in rows:
        sc = r.get('SECUCODE')
        v = _num(r.get('PRETAX_BONUS_RMB'))
        if sc and v:
            bonus[sc] = bonus.get(sc, 0.0) + v / 10.0
    u['bonus_ps'] = bonus
    if not rows:
        u['errors'].append('分红横截面为空（股息率子项降级）')
    return u


def _shift_days(n):
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() + 28800 - n * 86400))


def universe(force=False):
    with _uni_lock:
        if force or _uni.get('date') != _today() or not _uni.get('mid'):
            if _uni_building['flag'] and not force:
                return _uni            # 别的线程在重建：先用旧宇宙（stale 可接受，标注日期）
            _uni_building['flag'] = True
            try:
                fresh = _build_universe()
                _uni.clear()
                _uni.update(fresh)
            finally:
                _uni_building['flag'] = False
        return _uni


def warmup_async():
    def _run():
        try:
            universe(force=True)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()


# ================================================================ 个股级取数
def stock_finance(code):
    return dc_all('RPT_F10_FINANCE_MAINFINADATA', f'(SECUCODE="{secu(code)}")',
                  FINANCE_COLS, sort_col='REPORT_DATE', sort_dir=-1,
                  source='HSF10', max_pages=1)[:13]


def stock_val_series(code, years=3):
    d0 = _shift_days(years * 365 + 3)
    return dc_all('RPT_VALUEANALYSIS_DET', f"(SECURITY_CODE=\"{code}\")(TRADE_DATE>='{d0}')",
                  'TRADE_DATE,PE_TTM,PB_MRQ,PEG_CAR,TOTAL_MARKET_CAP,CLOSE_PRICE',
                  sort_col='TRADE_DATE', sort_dir=-1, max_pages=2)


def stock_rzrq(code, n=40):
    rows = dc_all('RPTA_WEB_RZRQ_GGMX', f'(SCODE="{code}")', 'DATE,RZYE,RZMRE5D,RZCHE5D,RZYEZB',
                  sort_col='DATE', sort_dir=-1, max_pages=1)
    return rows[:n]


def stock_basic(code):
    data, _, _ = dc_get('RPT_F10_ORG_BASICINFO', f'(SECUCODE="{secu(code)}")',
                        'BLGAINIAN,BLGAINIAN_CODE,BOARD_CODE_BK_1LEVEL,BOARD_CODE_BK_2LEVEL,'
                        'BOARD_NAME_1LEVEL,BOARD_NAME_2LEVEL,BOARD_NAME_3LEVEL,CSRC_INDUSTRY_NAME,'
                        'SECURITY_NAME_ABBR', page=1, size=1, source='HSF10')
    return (data or [None])[0]


def stock_predict_recent(code, days=30):
    d0 = _shift_days(days)
    return dc_all('RPT_PUBLIC_OP_NEWPREDICT',
                  f"(SECURITY_CODE=\"{code}\")(NOTICE_DATE>='{d0}')",
                  'NOTICE_DATE,REPORT_DATE,PREDICT_FINANCE,ADD_AMP_LOWER,ADD_AMP_UPPER',
                  sort_col='NOTICE_DATE', sort_dir=-1, max_pages=1)


def industry_pe_history(board_code, years=3):
    d0 = _shift_days(years * 365 + 5)
    return dc_all('RPT_VALUEINDUSTRY_DET',
                  f"(BOARD_CODE=\"{board_code}\")(TRADE_DATE>='{d0}')",
                  'TRADE_DATE,PE_TTM,PB_MRQ,TOTAL_MARKET_CAP,NUM,LOSS_COUNT',
                  sort_col='TRADE_DATE', sort_dir=-1, max_pages=2)


# ================================================================ 板块快照
def load_board_returns(min_days=20):
    try:
        files = sorted(f for f in os.listdir(SNAP_DIR)
                       if f.endswith('.json') and f.startswith('boards_'))
    except FileNotFoundError:
        return None
    if len(files) < min_days + 1:
        return None
    snaps = []
    for fn in files[-(min_days + 1):]:
        try:
            with open(os.path.join(SNAP_DIR, fn), encoding='utf-8') as f:
                snaps.append(json.load(f))
        except Exception:
            continue
    if len(snaps) < min_days + 1:
        return None
    first, last = snaps[0], snaps[-1]
    out = {}
    for bk, chg in last.items():
        if bk in first and isinstance(chg, (int, float)):
            cum, ok = 1.0, True
            for s in snaps[1:]:
                v = s.get(bk)
                if v is None:
                    ok = False
                    break
                cum *= (1.0 + v / 100.0)
            if ok:
                out[bk] = (cum - 1.0) * 100.0
    return out if len(out) >= 100 else None


# ================================================================ 维内工具
def _metric(name, value, unit, pctl, weight, direction='high', n_samples=None,
            coarse=False, note=None):
    """direction=high：分位越高分越高；low：分位越低分越高（PE/负债率等）。"""
    if value is None or pctl is None:
        return None
    contrib = pctl if direction == 'high' else 100.0 - pctl
    return {'name': name, 'value': round(value, 4) if isinstance(value, float) else value,
            'unit': unit, 'pctl': round(pctl, 1), 'weight': round(weight, 4),
            'contrib': contrib, 'confidence': conf_for(pctl, n_samples, coarse), 'note': note}


def _dim(key, label, weight, metrics, flags, extras=None):
    ms = [m for m in metrics if m]
    if not ms:
        d = {'key': key, 'label': label, 'weight': weight, 'score': None,
             'weighted_score': None, 'available': False, 'confidence': None,
             'metrics': [], 'flags': flags,
             'na_reason': (extras or {}).get('na_reason', '该维全部字段缺失')}
        return d
    wsum = sum(m['weight'] for m in ms)
    raw = sum(m['weight'] * m['contrib'] for m in ms) / wsum
    for m in ms:
        m['weight'] = round(m['weight'] / wsum, 8)   # 8 位舍入：Σ仍==1（verify 容差 1e-6），JSON 可读
    conf = sum(m['weight'] * m['confidence'] for m in ms)
    d = {'key': key, 'label': label, 'weight': weight,
         'score': raw, 'available': True,
         'confidence': round(conf, 2),
         'metrics': [{k: v for k, v in m.items() if k != 'contrib'} for m in ms],
         'flags': flags}
    if extras:
        d.update({k: v for k, v in extras.items() if k != 'na_reason'})
    return d


# ================================================================ 主流程
def compute_stock_score(code):
    """→ (payload, status)。payload 严格按 spec §6；status 404=无此票。"""
    uni = universe()
    src_errors = list(uni.get('errors') or [])

    fin_rows = stock_finance(code)
    vs = stock_val_series(code)
    q = tx_quote(code)
    basic = stock_basic(code)
    sc = secu(code)
    ind_row = (uni['valmap'] or {}).get(code) or {}
    name = ((fin_rows[0].get('SECURITY_NAME_ABBR') if fin_rows else None)
            or ind_row.get('SECURITY_NAME_ABBR') or (basic or {}).get('SECURITY_NAME_ABBR') or code)
    if not fin_rows and not vs and not q:
        return None, 404

    board_name = ind_row.get('BOARD_NAME') or (basic or {}).get('BOARD_NAME_2LEVEL') or ''
    board_code_e = ind_row.get('BOARD_CODE') or ''
    is_fin = bool(FIN_INDUSTRY_RE.search(board_name))
    is_re = bool(REALESTATE_RE.search(board_name))

    def latest(key):
        for r in fin_rows:
            v = _num(r.get(key))
            if v is not None:
                return v
        return None

    ann = [r for r in fin_rows if str(r.get('REPORT_DATE', ''))[5:10] == '12-31'][:3]

    # ------------------------------------------------ ① 盈利质量 (22)
    f1, m1 = [], []
    roe3 = [v for v in (_num(r.get('ROEKCJQ')) for r in ann) if v is not None]
    roe3min = min(roe3) if roe3 else None
    m1.append(_metric('扣非ROE近3年最低', roe3min, '%',
                      pct_rank((uni['univ_roe3min'] or {}).values(), roe3min),
                      0.25, 'high', n_samples=len(roe3)))
    roic = _num((fin_rows[0] or {}).get('ROIC')) if fin_rows else None
    m1.append(_metric('ROIC', roic, '%',
                      pct_rank([_num(r.get('ROIC')) for r in (uni['mid'] or {}).values()], roic),
                      0.20, 'high'))
    nco_vals = [v for v in (_num(r.get('NCO_NETPROFIT')) for r in ann) if v is not None]
    nco_mean = sum(nco_vals) / len(nco_vals) if nco_vals else None
    m1.append(_metric('经营现金流÷净利润(近3年均值)', nco_mean, '倍',
                      pct_rank([_num(r.get('NCO_NETPROFIT')) for r in (uni['mid'] or {}).values()],
                               nco_mean), 0.30, 'high', n_samples=len(nco_vals)))
    gm = [v for v in (_num(r.get('XSMLL')) for r in ann) if v is not None]
    gm_std = None
    if len(gm) >= 2:
        g0 = sum(gm) / len(gm)
        gm_std = math.sqrt(sum((v - g0) ** 2 for v in gm) / len(gm))
    m1.append(_metric('毛利率稳定性(近3年σ，低为好)', gm_std, 'pct',
                      pct_rank((uni['univ_gm_std'] or {}).values(), gm_std),
                      0.15, 'low', n_samples=len(gm)))
    combo = None
    if nco_mean is not None and roe3min is not None:
        a, b = nco_mean >= 1.2, roe3min >= 10
        combo = 100.0 if (a and b) else 50.0 if (a or b) else 0.0
    m1.append(_metric('现金流×扣非ROE双高组合(cfo≥1.2且ROE≥10)', combo, '分', combo,
                      0.10, 'high',
                      note='1.0双达标/0.5单项/0皆不达标' if combo is not None else None))
    cap1 = None
    if nco_mean is not None and nco_mean < 0.7:
        cap1 = 60.0
        f1.append(f'现金流保险丝触发：近3年经营现金流÷净利均值 {nco_mean:.2f} <0.7，该维封顶60分并标低置信')
    margin = _num((fin_rows[0] or {}).get('XSJLL')) if fin_rows else None
    # 杜邦：周转率腿必须是 TOAZZL（总资产周转率，次/年）。
    # 审计 B2 实测：ZZCJLL 是「总资产净利率」(=净利率×周转率)，用它会让
    # 净利率腿与周转率腿伪独立、恒等式塌成两条腿（茅台实测 8.99% vs ROE 16.75%）。
    turnover = None
    dupont_note = '权益乘数取 QYCS（=总资产/净资产）；CQBL 为产权比率（=乘数−1），非权益乘数'
    if fin_rows:
        turnover = _num(fin_rows[0].get('TOAZZL'))
        dupont_note += '；周转率腿取 TOAZZL（总资产周转率，次/年，季报为累计未年化口径）'
    qycs = latest('QYCS')
    mult1 = None
    if is_fin and qycs is not None:
        peer = [_num((uni['mid'].get(k) or {}).get('QYCS'))
                for k, vr in (uni['valmap'] or {}).items()
                if FIN_INDUSTRY_RE.search(vr.get('BOARD_NAME') or '')]
        peer = [v for v in peer if v is not None]
        if peer:
            med = sorted(peer)[len(peer) // 2]
            if med > 0 and qycs > 2 * med:
                mult1 = 0.85
                f1.append(f'高杠杆驱动 ROE：权益乘数 {qycs:.2f} > 同行业中位 {med:.2f}×2，该维×0.85（维基杜邦词条）')
    d1 = _dim('profit_quality', '盈利质量', 0.22, m1, f1,
              extras={'dupont': {'margin': margin, 'turnover': turnover,
                                 'equity_mult': qycs, 'note': dupont_note},
                      'thresh': 'P2 现金保险丝：3年均值<0.7→封顶60；金融高杠杆→×0.85'})
    if d1['available']:
        if cap1 is not None and d1['score'] > cap1:
            d1['score'] = cap1
            d1['confidence'] = min(d1['confidence'], 0.55)
        if mult1 is not None:
            d1['score'] *= mult1

    # ------------------------------------------------ ② 成长能力 (18)
    f2, m2 = [], []
    ann_dates = sorted(str(r['REPORT_DATE'])[:10] for r in ann)

    def cagr_stock(key):
        if len(ann_dates) < 2:
            return None
        f0 = _num((next(r for r in ann if str(r['REPORT_DATE'])[:10] == ann_dates[0])).get(key))
        f1_ = _num((next(r for r in ann if str(r['REPORT_DATE'])[:10] == ann_dates[-1])).get(key))
        if f0 is None or f1_ is None or f0 <= 0 or f1_ <= 0:
            return None
        n = int(ann_dates[-1][:4]) - int(ann_dates[0][:4])
        return ((f1_ / f0) ** (1.0 / n) - 1.0) * 100.0 if n > 0 else None

    neg_years = sum(1 for r in ann if (_num(r.get('KCFJCXSYJLR')) or 0) < 0)
    if neg_years:
        f2.append(f'近3年报中 {neg_years} 年扣非净利润为负：复合增速要求基期与末期均盈利，否则该子项不纳入（不填0）')
    rev_cagr = cagr_stock('TOTALOPERATEREVE')
    dnp_cagr = cagr_stock('KCFJCXSYJLR')
    m2.append(_metric('营收3年复合增速', rev_cagr, '%',
                      pct_rank((uni['univ_rev_cagr'] or {}).values(), rev_cagr),
                      0.25, 'high', n_samples=len(ann)))
    m2.append(_metric('扣非净利3年复合增速', dnp_cagr, '%',
                      pct_rank((uni['univ_dnp_cagr'] or {}).values(), dnp_cagr),
                      0.25, 'high', n_samples=len(ann)))
    toi_yoy = _num((fin_rows[0] or {}).get('DJD_TOI_YOY')) if fin_rows else None
    dnp_yoy = _num((fin_rows[0] or {}).get('DJD_DEDUCTDPNP_YOY')) if fin_rows else None
    m2.append(_metric('单季营收同比', toi_yoy, '%',
                      pct_rank([_num(r.get('DJD_TOI_YOY')) for r in (uni['mid'] or {}).values()],
                               toi_yoy), 0.15, 'high'))
    m2.append(_metric('单季扣非净利同比', dnp_yoy, '%',
                      pct_rank([_num(r.get('DJD_DEDUCTDPNP_YOY')) for r in (uni['mid'] or {}).values()],
                               dnp_yoy), 0.20, 'high'))
    divergence = (toi_yoy - dnp_yoy) if (toi_yoy is not None and dnp_yoy is not None) else None
    m2.append(_metric('营收−扣非净利增速背离度(低为好)', divergence, 'pct',
                      pct_rank([(_num(r.get('DJD_TOI_YOY')) - _num(r.get('DJD_DEDUCTDPNP_YOY')))
                                if r.get('DJD_TOI_YOY') is not None and r.get('DJD_DEDUCTDPNP_YOY') is not None
                                else None for r in (uni['mid'] or {}).values()], divergence),
                      0.15, 'low'))
    mult2 = None
    if divergence is not None and divergence > 30:
        mult2 = 0.85
        f2.append(f'增收不增利：营收同比−扣非净利同比 = {divergence:.1f}pct >30，该维×0.85')
    d2 = _dim('growth', '成长能力', 0.18, m2, f2,
              extras={'thresh': '扣非口径强制；背离>30pct→×0.85'})
    if d2['available'] and mult2 is not None:
        d2['score'] *= mult2

    # ------------------------------------------------ ③ 估值水平 (20)
    f3, m3 = [], []
    pe_now = _num((vs[0].get('PE_TTM') if vs else None))
    if pe_now is None:
        pe_now = _num(ind_row.get('PE_TTM'))
    pb_now = _num((vs[0].get('PB_MRQ') if vs else None))
    if pb_now is None:
        pb_now = _num(ind_row.get('PB_MRQ'))
    if not vs and (pe_now is None or pe_now <= 0):
        d3 = _dim('valuation', '估值水平', 0.20, [], f3,
                  extras={'na_reason': '个股估值日频序列缺失（RPT_VALUEANALYSIS_DET 无返回）'})
    elif pe_now is not None and pe_now <= 0:
        f3.append('盈利为负 → PE 无定义，估值维整体不计分（维基PE词条：亏损公司PE无意义；严禁填0/100）')
        d3 = _dim('valuation', '估值水平', 0.20, [], f3,
                  extras={'na_reason': '盈利为负（PE_TTM≤0），估值维 N/A'})
    else:
        if PHARMA_SEMI_RE.search(board_name):
            f3.append('医药/半导体行业：亏损期本维应整维不计分；当前 PE 为正，按口径正常计分')
        use_pe = not is_fin
        if is_fin:
            f3.append(f'金融业（{board_name}）：PE/PEG 不计分，只用 PB 口径（维基PB词条）')
        n_series = len(vs)
        pe_s = [_num(r.get('PE_TTM')) for r in vs]
        pb_s = [_num(r.get('PB_MRQ')) for r in vs]
        if use_pe:
            m3.append(_metric('PE_TTM 自身3年分位(低=高分)', pe_now, '倍',
                              pct_rank(pe_s, pe_now), 0.30, 'low', n_samples=n_series))
        m3.append(_metric('PB_MRQ 自身3年分位(低=高分)', pb_now, '倍',
                          pct_rank(pb_s, pb_now), 0.25 if use_pe else 0.60, 'low',
                          n_samples=n_series))
        peg_now = _num((vs[0] or {}).get('PEG_CAR')) if vs else None
        peg_pos = [v for v in (_num(r.get('PEG_CAR')) for r in vs) if v is not None and v > 0]
        if use_pe and peg_now is not None and peg_now > 0:
            m3.append(_metric('PEG_CAR 自身3年分位(低=高分)', peg_now, '倍',
                              pct_rank(peg_pos, peg_now), 0.20, 'low', n_samples=len(peg_pos)))
        elif use_pe:
            f3.append('PEG 无有效正值（净利增速为负/口径为负），子项不纳入')
        dps = (uni['bonus_ps'] or {}).get(sc)
        price = (q or {}).get('price')
        if not price and vs:
            price = _num((vs[0] or {}).get('CLOSE_PRICE'))
        dy = (dps / price * 100.0) if (dps and price) else (0.0 if (price and sc not in (uni['bonus_ps'] or {})) else None)
        if dy is None and not (uni['bonus_ps'] or {}).get(sc):
            f3.append('近一年无实施分红记录 → 股息率按 0 计入宇宙分位')
        univ_y = []
        for r in (uni['valmap'] or {}).values():
            d2v = (uni['bonus_ps'] or {}).get(r.get('SECUCODE') or '')
            mc, ts = _num(r.get('TOTAL_MARKET_CAP')), _num(r.get('TOTAL_SHARES'))
            if d2v and mc and ts:
                univ_y.append(d2v * ts / mc * 100.0)
        if dy is not None:
            m3.append(_metric('股息率(TTM)', dy, '%', pct_rank(univ_y, dy),
                              0.10 if use_pe else 0.20, 'high', n_samples=len(univ_y)))
        peers = [_num((uni['valmap'].get(k) or {}).get('PE_TTM' if use_pe else 'PB_MRQ'))
                 for k, vr in (uni['valmap'] or {}).items()
                 if vr.get('BOARD_CODE') == board_code_e] if board_code_e else []
        cur = pb_now if not use_pe else pe_now
        if len([v for v in peers if v is not None]) >= 5:
            m3.append(_metric('行业中位分位(本票在同花顺/东财二级行业成分内，低=高分)', cur, '倍',
                              pct_rank(peers, cur),
                              0.15 if use_pe else 0.20, 'low',
                              n_samples=len([v for v in peers if v is not None]),
                              coarse=is_re,
                              note=('房地产开发：PE、PB 同时降权至50%（账面历史成本+预售口径争议，'
                                    'A阶段标注为推论）' if is_re else None)))
        d3 = _dim('valuation', '估值水平', 0.20, m3, f3,
                  extras={'thresh': '低分位=高分；金融只PB；地产降权；亏损整维N/A'})
        if is_re and d3['available']:
            d3['score'] = 50.0 + (d3['score'] - 50.0) * 0.5
            d3['confidence'] = min(d3['confidence'], 0.6)

    # ------------------------------------------------ ④ 财务健康 (15)
    f4, m4 = [], []
    coarse4 = is_fin or is_re
    if coarse4:
        f4.append('行业阈值缺失：金融/地产不适用通用阈值表，按全市场粗档（置信度×0.6）并明示')
    zcfzl = latest('ZCFZL')
    m4.append(_metric('资产负债率(低为好)', zcfzl, '%',
                      pct_rank([_num(r.get('ZCFZL')) for r in (uni['mid'] or {}).values()], zcfzl),
                      0.25, 'low', coarse=coarse4))
    qycs2 = latest('QYCS')
    m4.append(_metric('权益乘数(低为好)', qycs2, '倍',
                      pct_rank([_num(r.get('QYCS')) for r in (uni['mid'] or {}).values()], qycs2),
                      0.15, 'low', coarse=coarse4))
    idr = latest('INTEREST_DEBT_RATIO')
    m4.append(_metric('有息负债率(低为好)', idr, '%',
                      pct_rank([_num(r.get('INTEREST_DEBT_RATIO')) for r in (uni['mid'] or {}).values()], idr),
                      0.20, 'low', coarse=coarse4))
    icr = latest('INTSTCOVRATE')
    m4.append(_metric('利息保障倍数', icr, '倍',
                      pct_rank([_num(r.get('INTSTCOVRATE')) for r in (uni['mid'] or {}).values()], icr),
                      0.20, 'high', coarse=coarse4))
    ld, sd = latest('LD'), latest('SD')
    p_ld = pct_rank([_num(r.get('LD')) for r in (uni['mid'] or {}).values()], ld)
    p_sd = pct_rank([_num(r.get('SD')) for r in (uni['mid'] or {}).values()], sd)
    if p_ld is not None and p_sd is not None:
        m4.append(_metric('流动/速动比综合', (ld + sd) / 2.0, '倍', (p_ld + p_sd) / 2.0,
                          0.10, 'high', coarse=coarse4))
    elif p_ld is not None:
        m4.append(_metric('流动比率', ld, '倍', p_ld, 0.10, 'high', coarse=coarse4))
    elif p_sd is not None:
        m4.append(_metric('速动比率', sd, '倍', p_sd, 0.10, 'high', coarse=coarse4))
    nco_pk, lia = latest('NETCASH_OPERATE_PK'), latest('LIABILITY')
    cover = (nco_pk / lia) if (nco_pk is not None and lia) else None
    m4.append(_metric('经营现金流覆盖总负债', cover, '倍',
                      pct_rank([(_num(r.get('NETCASH_OPERATE_PK')) / _num(r.get('LIABILITY')))
                                if (_num(r.get('NETCASH_OPERATE_PK')) is not None and _num(r.get('LIABILITY')))
                                else None for r in (uni['mid'] or {}).values()], cover),
                      0.10, 'high', coarse=coarse4))
    d4 = _dim('financial_health', '财务健康', 0.15, m4, f4,
              extras={'grade': None, 'thresh': '只输出等级不给精确分（Altman Z 两年期准确率仅72%、漏报6%）；'
                                               '精确分仅参与总分加权'})
    if d4['available']:
        d4['grade'] = '稳健' if d4['score'] >= 70 else '中性' if d4['score'] >= 40 else '承压'

    # ------------------------------------------------ ⑤ 资金动能 (13)
    f5, m5 = [], []
    rz_rows = stock_rzrq(code)
    rz_today = (uni['rzrq_today'] or {}).get(code)
    univ_net = []
    for r in (uni['rzrq_today'] or {}).values():
        a, b, y = _num(r.get('RZMRE5D')), _num(r.get('RZCHE5D')), _num(r.get('RZYE'))
        if a is not None and b is not None and y:
            univ_net.append((a - b) / y * 100.0)
    d5v = None
    if len(rz_rows) >= 6:
        r0, r5 = _num(rz_rows[0].get('RZYE')), _num(rz_rows[5].get('RZYE'))
        if r0 is not None and r5:
            d5v = (r0 - r5) / r5 * 100.0
    if d5v is None and rz_today:
        a, b, y = _num(rz_today.get('RZMRE5D')), _num(rz_today.get('RZCHE5D')), _num(rz_today.get('RZYE'))
        if a is not None and b is not None and y:
            d5v = (a - b) / y * 100.0
            f5.append('融资余额逐日序列不足，5日变动改用两融当日截面净买入强度口径（同表同源）')
    m5.append(_metric('融资余额5日变动', d5v, '%', pct_rank(univ_net, d5v), 0.35, 'high',
                      n_samples=len(rz_rows)))
    rzye_zb = (_num(rz_rows[0].get('RZYEZB')) if rz_rows else None)
    if rzye_zb is None and rz_today:
        rzye_zb = _num(rz_today.get('RZYEZB'))
    m5.append(_metric('融资余额占流通市值比(低为好,高=拥挤)', rzye_zb, '%',
                      pct_rank([_num(r.get('RZYEZB')) for r in (uni['rzrq_today'] or {}).values()],
                               rzye_zb), 0.20, 'low',
                      n_samples=len(uni['rzrq_today'] or {}),
                      note='高占比=杠杆拥挤，反向计分' if rzye_zb is not None else None))
    mf = sina_moneyflow(code)
    nets = [x['netamount'] for x in mf if x['netamount'] is not None]
    ratios = [x['ratioamount'] for x in mf if x['ratioamount'] is not None]
    if len(nets) >= 10:
        net5 = sum(nets[:5])
        roll5 = [sum(nets[i:i + 5]) for i in range(len(nets) - 4)]
        m5.append(_metric('主力净额5日累计(新浪口径)', net5 / 1e8, '亿元',
                          pct_rank(roll5, net5), 0.30, 'high', n_samples=len(nets)))
        if len(ratios) >= 10:
            r5 = sum(ratios[:5]) / 5.0 * 100.0
            rollr = [sum(ratios[i:i + 5]) / 5.0 * 100.0 for i in range(len(ratios) - 4)]
            m5.append(_metric('主力净占比5日均值', r5, '%', pct_rank(rollr, r5), 0.15, 'high',
                              n_samples=len(ratios)))
    else:
        f5.append('新浪资金流序列不足10日（新股/停牌/接口异常），主力子项不纳入')
    if not rz_rows and not rz_today:
        f5.append('无两融数据（非两融标的或数据缺失），融资子项不纳入')
    f5.append('北向持股 2024-09-30 停更，本维不含北向（spec §1⑤）')
    d5 = _dim('capital_momentum', '资金动能', 0.13, m5, f5,
              extras={'thresh': '主力口径锁定新浪 MoneyFlow.ssl_qsfx_zjlrqs，禁用东财fflow'
                                '（实测同日茅台 5.34亿 vs 7.41亿，混用致环比断裂）'})

    # ------------------------------------------------ ⑥ 概念景气 (12)
    f6, m6 = [], []
    bl_codes = [c for c in str((basic or {}).get('BLGAINIAN_CODE') or '').split(',') if c]
    n_concepts = len(bl_codes)
    board_ret = load_board_returns()
    if board_ret and bl_codes:
        own = [board_ret[c] for c in bl_codes if c in board_ret]
        if own:
            own_s = sorted(own)
            n = len(own_s)
            med = own_s[n // 2] if n % 2 else (own_s[n // 2 - 1] + own_s[n // 2]) / 2.0
            universe_all = [v for v in board_ret.values() if v is not None]
            m6.append(_metric('所属概念20日涨幅中位数·位次', med, '%',
                              pct_rank(universe_all, med), 0.50, 'high',
                              n_samples=len(universe_all),
                              note=f'{len(own)}/{n_concepts} 个概念板块有连续快照；取中位数防单一暴涨概念拉飞'))
    elif not board_ret:
        f6.append('板块每日快照不足20个交易日（采集脚本积累中），概念20日位次子项不纳入')
    preds = stock_predict_recent(code, days=30)
    hits = []
    if preds:
        kinds = sorted({str(r.get('PREDICT_FINANCE')) for r in preds if r.get('PREDICT_FINANCE')})
        hits.append('业绩预告(近30日):' + '、'.join(kinds[:3]))
    nd = str((fin_rows[0] or {}).get('NOTICE_DATE') or '')[:10] if fin_rows else ''
    if nd and nd >= _shift_days(20):
        hits.append(f'定期报告披露:{nd}')
    # 审计 B8 修正：催化事件是「绝对计数→绝对分档」，且在板块快照缺位时会以 40% 维内权重
    # 单独决定整维得分——实测茅台因此把概念维压到 10 分，等于把「数据未积累」当成「表现差」。
    # 处置：催化事件降为纯展示（不计分），概念维在无板块序列时整维 available=false。
    if hits:
        f6.append('催化事件（结构化规则命中，仅展示不计分）：' + '；'.join(hits))
    else:
        f6.append('催化事件（结构化规则命中，仅展示不计分）：近30日无命中')
    f6.append('政策关键词匹配本期未实现（无可验证免费结构化源）；概念数量子项(维内10%)因全市场概念映射'
              '需5572次逐股查询，本期不打分、维内权重按剩余归一——仅展示数量')
    f6.append('板块拥挤度提示（Arnott et al. 2016，维基Factor_investing）：热门因子/概念吸引大量资金流入，'
              '抬高估值并压低未来回报——本维是"当下拥挤"读数，不是质地评价')
    d6 = _dim('concept_heat', '概念景气', 0.12, m6, f6,
              extras={'concepts': {'count': n_concepts,
                                   'names': str((basic or {}).get('BLGAINIAN') or '')[:200]},
                      'thresh': '只允许结构化规则触发；严禁LLM编造催化剂；禁止人格化标签'})

    dims = [d1, d2, d3, d4, d5, d6]

    # ------------------------------------------------ 归一化（spec §2/§3）
    avail = [d for d in dims if d['available']]
    w_eff = sum(d['weight'] for d in avail)
    for d in dims:
        if d['available']:
            d['score'] = round(d['score'], 2)
            # weighted_score 不做二次舍入：total = 同一批 float 相加，verify 可 1e-6 复算
            d['weighted_score'] = d['score'] * d['weight'] / w_eff
        else:
            d['weighted_score'] = None
    total = sum(d['weighted_score'] for d in avail)
    # 小计契约修正（审计 B3）：估值维③的输入是逐日 PE/PB 序列，属日频，原 spec 把③漏在
    # 两个子计之外，导致「日频合计」被低估为 25%（实为 45%），且 verify 的加法恒等式无法成立。
    # 现按数据频率正确二分：基本面=①②④(55%) / 市场=③⑤⑥(45%)。
    fund = [d for d in avail if d['key'] in FUND_DIMS]
    mkt = [d for d in avail if d['key'] in MKT_DIMS]
    fw = sum(d['weight'] for d in fund)
    mw = sum(d['weight'] for d in mkt)
    fundamental_score = sum(d['score'] * d['weight'] for d in fund) / fw if fw else None
    market_score = sum(d['score'] * d['weight'] for d in mkt) / mw if mw else None
    trading_score = market_score   # 向后兼容旧字段名
    excluded = [{'dim': d['label'], 'key': d['key'], 'reason': d.get('na_reason')}
                for d in dims if not d['available']]
    low_conf = []
    for d in dims:
        if not d['available']:
            continue
        weak = [m['name'] for m in d['metrics'] if m['confidence'] < 0.6]
        if (d['confidence'] or 1) < 0.6 or weak:
            low_conf.append({'dim': d['label'], 'key': d['key'],
                             'dim_confidence': d['confidence'],
                             'metrics_below_0.6': weak,
                             'reason': '样本<60→×0.7 / 分位极端区→×0.8 / 粗档→×0.6（spec §3）'})

    # ------------------------------------------------ 行业参考层（不入总分）
    industry = None
    if board_code_e:
        today_row = next((r for r in uni['industry_today'] or []
                          if r.get('BOARD_CODE') == board_code_e), None)
        hist = industry_pe_history(board_code_e) if today_row else []
        pe_pctl = pb_pctl = rel20 = None
        if hist and today_row:
            pe_pctl = pct_rank([_num(r.get('PE_TTM')) for r in hist], _num(today_row.get('PE_TTM')))
            pb_pctl = pct_rank([_num(r.get('PB_MRQ')) for r in hist], _num(today_row.get('PB_MRQ')))
            mcs = [v for v in (_num(r.get('TOTAL_MARKET_CAP')) for r in hist) if v]
            if len(mcs) >= 21:
                rel20 = (mcs[-1] / mcs[-21] - 1.0) * 100.0
        comp_pe = [_num((uni['valmap'].get(k) or {}).get('PE_TTM'))
                   for k, vr in (uni['valmap'] or {}).items()
                   if vr.get('BOARD_CODE') == board_code_e and _num((uni['valmap'].get(k) or {}).get('PE_TTM'))]
        ind_pe = _num((today_row or {}).get('PE_TTM'))
        loss_ratio = None
        if today_row and _num(today_row.get('NUM')):
            loss_ratio = round((_num(today_row.get('LOSS_COUNT')) or 0) / _num(today_row.get('NUM')), 4)
        stock_rank = pct_rank(comp_pe, pe_now)
        industry = {'name': (today_row or {}).get('BOARD_NAME') or board_name,
                    'name3': (basic or {}).get('BOARD_NAME_3LEVEL'),
                    'level': '东财二级',
                    'pe_ttm': ind_pe,
                    'pe_median': round(sorted(comp_pe)[len(comp_pe) // 2], 2) if comp_pe else ind_pe,
                    'pe_pctl': None if pe_pctl is None else round(pe_pctl, 1),
                    'pb_pctl': None if pb_pctl is None else round(pb_pctl, 1),
                    'rank_pct': None if stock_rank is None else round(stock_rank, 1),
                    'n_constituents': len(comp_pe),
                    'loss_ratio': loss_ratio,
                    'rel_strength_20d': None if rel20 is None else round(rel20, 2),
                    'caveat': '行业PE分位=东财二级口径自建序列（申万三级无免费分位源），三级仅作展示标签；'
                              'rank_pct=本票PE在行业成分股内的分位；rel_strength_20d=行业总市值20日变动'
                              '（push2his K线通道高危，用估值表市值代理，非价格收益率口径）'}

    data_asof = uni.get('val_date') or _today()
    payload = {
        'code': code, 'name': name, 'data_asof': data_asof,
        'quote': {'price': (q or {}).get('price'),
                  'pe_ttm': (q or {}).get('pe_ttm') if q else pe_now,
                  'pb': (q or {}).get('pb') if q else pb_now,
                  'mv_yi': (q or {}).get('mv_yi'), 'float_mv_yi': (q or {}).get('float_mv_yi'),
                  'quote_ts': (q or {}).get('ts')},
        'dims': dims,
        'fundamental_score': fundamental_score, 'market_score': market_score,
        'trading_score': trading_score,
        'total': total, 'tier': tier_of(total),
        'industry': industry,
        'low_confidence': low_conf,
        'excluded': excluded,
        'source_errors': src_errors,
        'weights_sum': round(sum(d['weight'] for d in dims), 9),
        'dims_available_n': len(avail),
        'meta': {'latest_fin_period': uni.get('latest_period'),
                 'val_cross_date': uni.get('val_date'),
                 'rzrq_date': uni.get('rzrq_date'),
                 'universe_built': uni.get('date'),
                 'universe_note': '分位宇宙=同日全市场横截面（日级缓存）；'
                                  '估值自身分位=个股3年日频序列；主力分位=个股60日滚动分布'},
    }
    if not q:
        payload['source_errors'].append('腾讯实时行情失败（PE/PB回退东财估值序列）')
    return payload, 200


def llm_report_input(payload):
    """给 LLM 的输入：只有分数与口径，无任何买卖倾向词（spec §6 铁律）。"""
    ind = payload.get('industry') or {}
    lines = [f"股票：{payload['name']}（{payload['code']}） 行业：{ind.get('name', '未知')}"]
    lines.append(f"总分 {round(payload['total'], 1)}，档位 {payload['tier']}；"
                 f"季频基本面小计 {round(payload['fundamental_score'], 1) if payload['fundamental_score'] is not None else 'N/A'}；"
                 f"日频交易小计 {round(payload['trading_score'], 1) if payload['trading_score'] is not None else 'N/A'}")
    for d in payload['dims']:
        if d['available']:
            lines.append(f"维度「{d['label']}」权重{int(d['weight']*100)}% 得分{d['score']}/100 "
                         f"置信度{d['confidence']}；指标: " +
                         '，'.join(f"{m['name']}={m['value']}{m['unit']}(分位{m['pctl']})"
                                   for m in d['metrics']))
            for fl in d['flags']:
                lines.append(f"  标记: {fl}")
        else:
            lines.append(f"维度「{d['label']}」未纳入：{d.get('na_reason')}")
    for e in payload['excluded']:
        lines.append(f"未纳入维度：{e['dim']}（{e['reason']}）")
    return '\n'.join(lines)
