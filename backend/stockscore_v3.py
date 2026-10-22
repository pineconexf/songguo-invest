# -*- coding: utf-8 -*-
"""个股打分卡 V3 引擎（2026-10-18）

V1 六维 → V3 八维 · 3 组：
  Q 质地 52 = 盈利质量16 + 核心竞争力16 + 成长质量12 + 财务健康8
  V 价格 26 = 估值与安全边际26
  M 势能 22 = 产业链景气8 + 预期修正8 + 资金动能6
总分 = 0.52Q + 0.26V + 0.22M，再过闸门（🔴封顶59 / 🟡≥2降一档 / 🟡=1标注）

相对 V1 的四处改动（对应峰哥六条意见）：
  1) 护城河 → 核心竞争力：纵(链条位置/议价力) 6 + 横(同行地位/技术) 6 + 己(壁垒/持续性) 4
  2) 资金动能：A/B/C 可靠性分级 + 主窗口 20 日（V1 用 60/5 日，与月度调仓不同频）
  3) 产业链景气：东财行业+概念板块快照，非 LLM 生成
  4) 预期修正：研报 EPS 预测漂移 + 单季扣非同比（与 V35 H3/A+ 同源）

数据层完全复用 stockscore.py（东财 datacenter + 新浪资金流 + 腾讯行情），
不引入 tushare——保持与线上 V1 同一套取数通道，避免双源口径打架。

口径铁律（沿用 V1）：
  - 缺失子项不进分母，维内权重重归一；整维缺失 available=false，严禁填 0
  - 每个分数带置信度；<0.6 进低置信清单
  - 亏损股估值维整维 N/A；金融业 PE/PEG 不计分只用 PB
"""
import json
import math
import time
import threading

import requests

from stockscore import (
    universe, dc_get, dc_all, tx_quote, sina_moneyflow, pct_rank, conf_for,
    _num, secu, _shift_days, _today, stock_finance, stock_val_series,
    stock_rzrq, stock_basic, stock_predict_recent, industry_pe_history,
    load_board_returns, tier_of, FIN_INDUSTRY_RE, PHARMA_SEMI_RE,
)
import chain_structure
import stockscore_persist as _sspersist

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      'Referer': 'https://data.eastmoney.com/'}

# ---------------------------------------------------------------- 权重（V3）
W = {
    'profit_quality':    0.16,
    'core_competence':   0.16,
    'growth':            0.12,
    'financial_health':  0.08,
    'valuation':         0.26,
    'chain_prosperity':  0.08,
    'earnings_revision': 0.08,
    'capital_momentum':  0.06,
}
GROUP_OF = {
    'Q': ['profit_quality', 'core_competence', 'growth', 'financial_health'],
    'V': ['valuation'],
    'M': ['chain_prosperity', 'earnings_revision', 'capital_momentum'],
}
GROUP_META = {
    'Q': {'label': '质地', 'question': '是不是好公司？'},
    'V': {'label': '价格', 'question': '现在贵不贵？'},
    'M': {'label': '势能', 'question': '现在有没有风？'},
}

# 卡点环节白名单（规则判定，非 LLM）
CHOKEPOINT_RE = None
try:
    import re
    CHOKEPOINT_RE = re.compile(
        r'半导体|芯片|集成电路|设备|材料|零部件|电子元件|光模块|光学|军工|航空装备|'
        r'精密|机床|工业母机|EDA|传感器|连接器|功率器件|被动元件|锂电材料|稀土|'
        r'特种化工|电子化学|高端制造|仪器仪表|生物制品|疫苗|创新药')
except Exception:
    pass

_EPS_CACHE = {}
_EPS_LOCK = threading.Lock()

# V3 需要、但 V1 的 FINANCE_COLS 没取的一组字段（核心竞争力 / FCF / 商誉分母）
FIN_COLS_V3 = ('SECUCODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_DATE_NAME,NOTICE_DATE,'
               'ROEKCJQ,ROIC,NCO_NETPROFIT,XSMLL,XSJLL,ZZCJLL,TOTAL_ROI,TOAZZL,CQBL,QYCS,ZCFZL,'
               'INTEREST_DEBT_RATIO,INTSTCOVRATE,LD,SD,NETCASH_OPERATE_PK,LIABILITY,'
               'TOTALOPERATEREVE,KCFJCXSYJLR,DJD_TOI_YOY,DJD_DEDUCTDPNP_YOY,'
               'YSZKZZTS,PAYABLE_TDAYS,CHZZTS,OPERATE_CYCLE,RDEXPEND,FCFF_FORWARD,FCFF_BACK')

_V3X = {'ts': 0.0, 'data': {}}
_V3X_LOCK = threading.Lock()


def stock_finance_v3(code):
    """个股财务（V3 超集字段），13 期足够算同比与 3 年 CAGR。"""
    return dc_all('RPT_F10_FINANCE_MAINFINADATA', f'(SECUCODE="{secu(code)}")',
                  FIN_COLS_V3, sort_col='REPORT_DATE', sort_dir=-1,
                  source='HSF10', max_pages=1)[:13]


def v3_cross(period):
    """最新报告期的全市场扩展横截面（周转天数/研发/营业周期），1 小时缓存。
    只用于给 V1 的 mid 补列，不改变 V1 任何取数行为。

    2026-10-22：加磁盘层。实测该查询 17.6s（拉全市场 13465 行），
    进程重启后内存缓存丢失 → compute_v3 从 0.4s 涨到 29s，
    卡在深度正文生成之前，首段可见时间被推到 40s。
    横截面按报告期唯一，天然日级稳定，落盘安全。
    """
    if not period:
        return {}
    with _V3X_LOCK:
        if _V3X['data'] and time.time() - _V3X['ts'] < 3600:
            return _V3X['data']
    disk_key = 'v3cross_' + str(period).replace('-', '')
    out = _sspersist.get(disk_key)
    if not out:
        cols = ('SECUCODE,YSZKZZTS,PAYABLE_TDAYS,CHZZTS,OPERATE_CYCLE,RDEXPEND,'
                'TOTALOPERATEREVE,FCFF_FORWARD')
        out = {}
        try:
            for r in dc_all('RPT_F10_FINANCE_MAINFINADATA', f"(REPORT_DATE='{period}')",
                            cols, source='HSF10'):
                sc = r.get('SECUCODE')
                if sc and len(str(sc)) > 6 and str(sc)[6] == '.':
                    out[sc] = r
        except Exception:
            out = {}
        _sspersist.put(disk_key, out)
    with _V3X_LOCK:
        _V3X.update(ts=time.time(), data=out)
    return out


# ================================================================ 新增取数
def main_business(code, periods=1):
    """主营业务构成（按产品/按地区）。东财 F10 MAINOP。"""
    rows = dc_all('RPT_F10_FN_MAINOP', f'(SECUCODE="{secu(code)}")',
                  'SECUCODE,REPORT_DATE,MAINOP_TYPE,ITEM_NAME,MAIN_BUSINESS_INCOME,'
                  'MBI_RATIO,GROSS_RPOFIT_RATIO', sort_col='REPORT_DATE', sort_dir=-1,
                  source='HSF10', max_pages=1)
    if not rows:
        return []
    rows.sort(key=lambda r: str(r.get('REPORT_DATE') or ''), reverse=True)
    latest = str(rows[0].get('REPORT_DATE') or '')[:10]
    return [r for r in rows if str(r.get('REPORT_DATE') or '')[:10] == latest]


def balance_sheet(code, n=4):
    """资产负债表（商誉等）。"""
    return dc_all('RPT_F10_FINANCE_GBALANCE', f'(SECUCODE="{secu(code)}")',
                  'SECUCODE,REPORT_DATE,GOODWILL,TOTAL_EQUITY,TOTAL_ASSETS',
                  sort_col='REPORT_DATE', sort_dir=-1, source='HSF10', max_pages=1)[:n]


def billboard_net(code, days=20):
    """龙虎榜净买入（A 级：交易所披露真实席位）。"""
    d0 = _shift_days(days + 5)
    rows = dc_all('RPT_DAILYBILLBOARD_DETAILS',
                  f'(SECURITY_CODE="{code}")(TRADE_DATE>=\'{d0}\')',
                  'SECURITY_CODE,TRADE_DATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,'
                  'BILLBOARD_SELL_AMT,EXPLANATION')
    if not rows:
        return None, 0
    rows = [r for r in rows if str(r.get('TRADE_DATE') or '')[:10] >= d0]
    if not rows:
        return None, 0
    tot = sum(_num(r.get('BILLBOARD_NET_AMT')) or 0.0 for r in rows)
    return tot, len(rows)


def research_reports(code, days=120):
    """东财研报中心：机构评级 + 当年/次年 EPS 预测。用于「预期修正」。"""
    key = (code, days)
    with _EPS_LOCK:
        if key in _EPS_CACHE and time.time() - _EPS_CACHE[key][0] < 3600:
            return _EPS_CACHE[key][1]
    end = time.time()
    p = {'cb': '', 'industryCode': '*', 'pageSize': 60, 'industry': '*',
         'rating': '', 'ratingChange': '',
         'beginTime': time.strftime('%Y-%m-%d', time.localtime(end - days * 86400)),
         'endTime': time.strftime('%Y-%m-%d', time.localtime(end)),
         'pageNo': 1, 'fields': '', 'qType': 0, 'orgCode': '', 'code': code,
         'rcode': '', 'p': 1, 'pageNum': 1}
    out = []
    try:
        r = requests.get('https://reportapi.eastmoney.com/report/list',
                         params=p, headers=UA, timeout=20)
        t = r.text.strip()
        if t.startswith('('):
            t = t[1:-1]
        d = json.loads(t)
        for x in (d.get('data') or []):
            out.append({
                'date': str(x.get('publishDate') or '')[:10],
                'org': x.get('orgSName'),
                'rating': x.get('emRatingName') or x.get('sRatingName'),
                'eps_this': _num(x.get('predictThisYearEps')),
                'eps_next': _num(x.get('predictNextYearEps')),
            })
    except Exception:
        out = []
    with _EPS_LOCK:
        _EPS_CACHE[key] = (time.time(), out)
    return out


# ================================================================ 维内工具
def _m(name, value, unit, pctl, weight, direction='high', n_samples=None,
       coarse=False, note=None, reliability=None):
    if value is None or pctl is None:
        return None
    contrib = pctl if direction == 'high' else 100.0 - pctl
    d = {'name': name, 'value': round(value, 4) if isinstance(value, float) else value,
         'unit': unit, 'pctl': round(pctl, 1), 'weight': round(weight, 4),
         'contrib': contrib, 'confidence': conf_for(pctl, n_samples, coarse),
         'note': note}
    if reliability:
        d['reliability'] = reliability
    return d


def _abs(value, points):
    """绝对刻度 → 0–100（无全市场宇宙时的粗档替代，必须在 note 里标明「粗档」）。
    points 必须按 x 升序，线性插值，两端截断。"""
    if value is None or not points:
        return None
    if value <= points[0][0]:
        return float(points[0][1])
    if value >= points[-1][0]:
        return float(points[-1][1])
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        if x0 <= value <= x1:
            if x1 == x0:
                return float(y1)
            return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return None


def _dim(key, label, weight, metrics, flags, extras=None):
    ms = [m for m in metrics if m]
    if not ms:
        return {'key': key, 'label': label, 'weight': weight, 'score': None,
                'weighted_score': None, 'available': False, 'confidence': None,
                'metrics': [], 'flags': flags,
                'na_reason': (extras or {}).get('na_reason', '该维全部字段缺失')}
    wsum = sum(m['weight'] for m in ms)
    raw = sum(m['weight'] * m['contrib'] for m in ms) / wsum
    for m in ms:
        m['weight'] = round(m['weight'] / wsum, 8)
    conf = sum(m['weight'] * m['confidence'] for m in ms)
    d = {'key': key, 'label': label, 'weight': weight, 'score': raw, 'available': True,
         'confidence': round(conf, 2),
         # 2026-10-22：保留 contrib（该指标实际贡献的分）。
         # 原来被剥掉了，导致后端无法判断"哪个指标是短板"——
         # 只有 contrib 能把 direction 的方向折算吸收掉（pctl 做不到）。
         'metrics': [dict(m) for m in ms],
         'flags': flags}
    if extras:
        d.update({k: v for k, v in extras.items() if k != 'na_reason'})
    return d


def _peers_xsmll(uni, board_code):
    """同行业（东财二级）毛利率样本。"""
    out = []
    for sc, r in (uni.get('mid') or {}).items():
        vr = (uni.get('valmap') or {}).get((sc or '').split('.')[0]) or {}
        if board_code and vr.get('BOARD_CODE') == board_code:
            v = _num(r.get('XSMLL'))
            if v is not None:
                out.append(v)
    return out


def _peers_mv(uni, board_code):
    out = []
    for code, vr in (uni.get('valmap') or {}).items():
        if vr.get('BOARD_CODE') == board_code:
            v = _num(vr.get('TOTAL_MARKET_CAP'))
            if v:
                out.append(v)
    return out


def _median(vs):
    if not vs:
        return None
    s = sorted(vs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# 行业景气横截面缓存（30 分钟）：板块级聚合比逐股取数便宜，但遍历 5500 只仍不宜每请求重算
_BP = {'ts': 0.0, 'data': {}}
_BP_LOCK = threading.Lock()


def board_prosperity(uni):
    """行业景气横截面（东财二级行业口径，全部走 datacenter-web 固定通道）。

    对每个板块算三件事：
      rev_med  成分股「单季营收同比」中位数 —— 需求景气
      dnp_med  成分股「单季扣非净利同比」中位数 —— 盈利景气
      loss_pct 板块亏损家数占比 —— 景气的地板（低=好）
    再对全市场每只股票算 alpha：个股营收同比 − 所属板块中位数 = 链内相对景气（份额变化）。

    返回 {'boards': {bk: {...}}, 'alpha_pool': [...], 'rev_pool': [...], ...}
    """
    with _BP_LOCK:
        if _BP['data'] and time.time() - _BP['ts'] < 1800:
            return _BP['data']
    mid = uni.get('mid') or {}
    vm = uni.get('valmap') or {}
    if not mid or not vm:
        return {}
    rev, dnp = {}, {}
    for code, vr in vm.items():
        bk = vr.get('BOARD_CODE')
        if not bk:
            continue
        m = mid.get(vr.get('SECUCODE') or secu(code)) or {}
        rv = _num(m.get('DJD_TOI_YOY'))
        dv = _num(m.get('DJD_DEDUCTDPNP_YOY'))
        if rv is not None:
            rev.setdefault(bk, []).append(rv)
        if dv is not None:
            dnp.setdefault(bk, []).append(dv)
    loss = {}
    for r in (uni.get('industry_today') or []):
        bk = r.get('BOARD_CODE')
        n, l = _num(r.get('NUM')), _num(r.get('LOSS_COUNT'))
        if bk and n and n > 0 and l is not None:
            loss[bk] = l / n * 100.0
    boards = {}
    for bk in set(rev) | set(dnp) | set(loss):
        r_, d_ = rev.get(bk) or [], dnp.get(bk) or []
        boards[bk] = {
            'rev_med': _median(r_) if len(r_) >= 5 else None,
            'dnp_med': _median(d_) if len(d_) >= 5 else None,
            'loss_pct': loss.get(bk),
            'n': len(r_),
        }
    # 全市场 alpha 池：每只股票相对自己板块的超额营收增速
    alpha_pool = []
    names = {}
    for code, vr in vm.items():
        bk = vr.get('BOARD_CODE')
        if not bk:
            continue
        if vr.get('BOARD_NAME'):
            names[bk] = vr['BOARD_NAME']
        b = boards.get(bk) or {}
        if b.get('rev_med') is None:
            continue
        m = mid.get(vr.get('SECUCODE') or secu(code)) or {}
        rv = _num(m.get('DJD_TOI_YOY'))
        if rv is not None:
            alpha_pool.append(rv - b['rev_med'])
    out = {
        'boards': boards,
        'names': names,
        'alpha_pool': alpha_pool,
        'rev_pool': [b['rev_med'] for b in boards.values() if b.get('rev_med') is not None],
        'dnp_pool': [b['dnp_med'] for b in boards.values() if b.get('dnp_med') is not None],
        'loss_pool': [b['loss_pct'] for b in boards.values() if b.get('loss_pct') is not None],
    }
    with _BP_LOCK:
        _BP.update(ts=time.time(), data=out)
    return out


# ================================================================ 主流程
def compute_v3(code):
    uni = universe()
    # 给横截面补上 V3 需要的周转/研发列（不改变 V1 取数）
    _xc = v3_cross(uni.get('latest_period'))
    if _xc:
        merged = {}
        for sc, r in (uni.get('mid') or {}).items():
            m = dict(r)
            m.update(_xc.get(sc) or {})
            merged[sc] = m
        uni = dict(uni)
        uni['mid'] = merged
    src_errors = list(uni.get('errors') or [])

    fin = stock_finance_v3(code)
    if not fin:
        src_errors.append('个股财务序列为空（字段名不匹配或接口异常）——'
                          '盈利质量/成长/财务健康将整维 N/A，请先排查取数')
    vs = stock_val_series(code)
    q = tx_quote(code)
    basic = stock_basic(code)
    sc = secu(code)
    ind_row = (uni.get('valmap') or {}).get(code) or {}
    name = ((fin[0].get('SECURITY_NAME_ABBR') if fin else None)
            or ind_row.get('SECURITY_NAME_ABBR')
            or (basic or {}).get('SECURITY_NAME_ABBR') or code)
    if not fin and not vs and not q:
        return None, 404

    board_name = ind_row.get('BOARD_NAME') or (basic or {}).get('BOARD_NAME_2LEVEL') or ''
    board_code = ind_row.get('BOARD_CODE') or ''
    is_fin = bool(FIN_INDUSTRY_RE.search(board_name))
    ann = [r for r in fin if str(r.get('REPORT_DATE', ''))[5:10] == '12-31'][:3]

    def latest(key):
        for r in fin:
            v = _num(r.get(key))
            if v is not None:
                return v
        return None

    def yoy_change(key):
        """最新期 vs 上年同期（同报告期）。"""
        if len(fin) < 5:
            return None
        cur, prev = _num(fin[0].get(key)), _num(fin[4].get(key))
        if cur is None or prev in (None, 0):
            return None
        return (cur - prev) / abs(prev) * 100.0

    mv = _num((q or {}).get('mv_yi')) or (_num(ind_row.get('TOTAL_MARKET_CAP')) or 0) / 1e8
    mv_abs = _num(ind_row.get('TOTAL_MARKET_CAP')) or (mv * 1e8 if mv else None)

    # ============================================ ① 盈利质量 16
    f1, m1 = [], []
    roe3 = [v for v in (_num(r.get('ROEKCJQ')) for r in ann) if v is not None]
    roe3min = min(roe3) if roe3 else None
    m1.append(_m('扣非ROE近3年最低', roe3min, '%',
                 pct_rank((uni.get('univ_roe3min') or {}).values(), roe3min), 0.25,
                 'high', n_samples=len(roe3)))
    roic = _num((fin[0] or {}).get('ROIC')) if fin else None
    m1.append(_m('ROIC', roic, '%',
                 pct_rank([_num(r.get('ROIC')) for r in (uni.get('mid') or {}).values()], roic),
                 0.20, 'high'))
    nco_vals = [v for v in (_num(r.get('NCO_NETPROFIT')) for r in ann) if v is not None]
    nco_mean = sum(nco_vals) / len(nco_vals) if nco_vals else None
    m1.append(_m('经营现金流÷净利润(近3年均值)', nco_mean, '倍',
                 pct_rank([_num(r.get('NCO_NETPROFIT')) for r in (uni.get('mid') or {}).values()],
                          nco_mean), 0.30, 'high', n_samples=len(nco_vals)))
    gm = [v for v in (_num(r.get('XSMLL')) for r in ann) if v is not None]
    gm_std = None
    if len(gm) >= 2:
        g0 = sum(gm) / len(gm)
        gm_std = math.sqrt(sum((v - g0) ** 2 for v in gm) / len(gm))
    m1.append(_m('毛利率稳定性(近3年σ，低为好)', gm_std, 'pct',
                 pct_rank((uni.get('univ_gm_std') or {}).values(), gm_std), 0.15, 'low',
                 n_samples=len(gm)))
    combo = None
    if nco_mean is not None and roe3min is not None:
        a, b = nco_mean >= 1.2, roe3min >= 10
        combo = 100.0 if (a and b) else 50.0 if (a or b) else 0.0
    m1.append(_m('现金流×ROE双高组合', combo, '分', combo, 0.10, 'high',
                 note='cfo≥1.2 且 ROE≥10 记 100；单项 50；皆不达 0'))
    d1 = _dim('profit_quality', '盈利质量', W['profit_quality'], m1, f1,
              extras={'thresh': 'P2 现金保险丝：3年均值<0.7→封顶60',
                      'dupont': {'margin': _num((fin[0] or {}).get('XSJLL')) if fin else None,
                                 'turnover': _num((fin[0] or {}).get('TOAZZL')) if fin else None,
                                 'equity_mult': latest('QYCS')}})
    if d1['available'] and nco_mean is not None and nco_mean < 0.7:
        f1.append(f'现金流保险丝：近3年 CFO/净利均值 {nco_mean:.2f} < 0.7，该维封顶 60 分')
        d1['score'] = min(d1['score'], 60.0)
        d1['confidence'] = min(d1['confidence'], 0.55)

    # ============================================ ② 核心竞争力 16（纵6/横6/己4）
    f2, m2 = [], []
    uni_mid = uni.get('mid') or {}
    peer_gm = _peers_xsmll(uni, board_code)
    gm_now = _num((fin[0] or {}).get('XSMLL')) if fin else None
    gm_med = (sorted(peer_gm)[len(peer_gm) // 2] if len(peer_gm) >= 5 else None)

    # —— 纵向：链条位置与议价力
    ar_days = latest('YSZKZZTS')
    ap_days = latest('PAYABLE_TDAYS')
    net_days = (ar_days - ap_days) if (ar_days is not None and ap_days is not None) else None
    uni_net_days = []
    for r in uni_mid.values():
        a, b = _num(r.get('YSZKZZTS')), _num(r.get('PAYABLE_TDAYS'))
        if a is not None and b is not None:
            uni_net_days.append(a - b)
    m2.append(_m('净占用天数(应收−应付周转，低=占用他人资金)', net_days, '天',
                 pct_rank(uni_net_days, net_days), 2.5, 'low',
                 note='负值=用别人的钱做生意（议价力强）'))
    op_cycle = latest('OPERATE_CYCLE')
    m2.append(_m('营业周期', op_cycle, '天',
                 pct_rank([_num(r.get('OPERATE_CYCLE')) for r in uni_mid.values()], op_cycle),
                 1.5, 'low'))
    ch_days = latest('CHZZTS')
    m2.append(_m('存货周转天数', ch_days, '天',
                 pct_rank([_num(r.get('CHZZTS')) for r in uni_mid.values()], ch_days),
                 1.0, 'low'))
    choke = None
    if CHOKEPOINT_RE and board_name:
        choke = 100.0 if CHOKEPOINT_RE.search(board_name) else 50.0
        m2.append(_m('环节卡点度(规则命中白名单)', choke, '分', choke, 1.0, 'high',
                     note='命中「设备/材料/零部件/芯片/精密/军工」等白名单→100，否则中性 50'))

    # —— 横向：同行地位与技术
    peer_mv = _peers_mv(uni, board_code)
    # 2026-10-22：单位纠正 + 精简到亿元。
    # 坑：valmap 里的 TOTAL_MARKET_CAP 单位是**元**（688508 = 8,020,700,357 元 = 80.21 亿元），
    # 跟 tushare daily_basic 的 total_mv（万元）只差字母，千万别混用。
    # 原来这里 unit 标成 '元'，前端会渲染出 "8,020,700,357.22 元" 这种长到没法读的数字。
    # 改成亿元口径（元 / 1e8），peer_mv 同步换算保持同一量纲。
    mv_abs_yuan = _num(ind_row.get('TOTAL_MARKET_CAP'))
    mv_abs_yi = (mv_abs_yuan / 1e8) if mv_abs_yuan else (mv if mv else None)
    peer_mv_yi = [(v / 1e8) for v in peer_mv]
    m2.append(_m('规模位次(市值行业内分位)', mv_abs_yi, '亿元',
                 pct_rank(peer_mv_yi, mv_abs_yi) if mv_abs_yi is not None else None,
                 1.5, 'high', n_samples=len(peer_mv_yi)))
    premium = (gm_now - gm_med) if (gm_now is not None and gm_med is not None) else None
    uni_prem = []
    for r in uni_mid.values():
        v = _num(r.get('XSMLL'))
        if v is not None:
            uni_prem.append(v)
    m2.append(_m('毛利溢价(本票毛利率−行业中位)', premium, 'pct',
                 pct_rank(uni_prem, gm_now) if premium is not None else None,
                 2.0, 'high', note=f'行业中位 {round(gm_med,2)}%' if gm_med else None))
    rd = latest('RDEXPEND')
    rev = latest('TOTALOPERATEREVE')
    rd_int = (rd / rev * 100.0) if (rd and rev) else None
    uni_rd = []
    for r in uni_mid.values():
        a, b = _num(r.get('RDEXPEND')), _num(r.get('TOTALOPERATEREVE'))
        if a is not None and b:
            uni_rd.append(a / b * 100.0)
    m2.append(_m('研发强度(研发支出÷营收)', rd_int, '%',
                 pct_rank(uni_rd, rd_int), 1.5, 'high', n_samples=len(uni_rd),
                 note='研发费用未披露时该子项不纳入'))
    m2.append(_m('ROIC 行业位次', roic, '%',
                 pct_rank([_num(uni_mid.get(k, {}).get('ROIC')) for k, vr in
                           (uni.get('valmap') or {}).items()
                           if vr.get('BOARD_CODE') == board_code], roic),
                 1.0, 'high'))

    # —— 自身：壁垒类型与持续性
    roic_ann = [v for v in (_num(r.get('ROIC')) for r in ann) if v is not None]
    yrs8 = sum(1 for v in roic_ann if v > 8) if roic_ann else None
    m2.append(_m('ROIC>8% 年数(近3年报)', yrs8, '年',
                 (yrs8 / 3.0 * 100.0) if yrs8 is not None else None, 1.5, 'high',
                 note='3 年全过=100；2 年=67；1 年=33；0 年=0'))
    m2.append(_m('毛利率波动(σ，低=壁垒稳)', gm_std, 'pct',
                 pct_rank((uni.get('univ_gm_std') or {}).values(), gm_std), 1.5, 'low'))
    fcff = latest('FCFF_FORWARD')
    fcf_yield = (fcff / mv_abs * 100.0) if (fcff and mv_abs) else None
    m2.append(_m('自由现金流收益率(FCFF÷市值，松果FCF/EV代理)', fcf_yield, '%',
                 _abs(fcf_yield, [(-5, 0), (0, 40), (3, 65), (8, 90), (15, 100)]),
                 1.0, 'high', coarse=True,
                 note='粗档绝对刻度；代理口径（分母仅市值，未扣净债）'))
    d2 = _dim('core_competence', '核心竞争力', W['core_competence'], m2, f2,
              extras={'sub': {'vertical': 6, 'horizontal': 6, 'self': 4},
                      'thresh': '纵向=链条位置/议价力；横向=同行地位/技术；自身=壁垒/持续性。'
                                '技术代差、毛利溢价为代理指标，非真护城河判定'})
    if d2['available']:
        f2.append('技术代差/毛利溢价为代理指标：真正的护城河（转换成本、网络效应、心智占领）'
                  '拿不到结构化数据，本维只算其影子')

    # ============================================ ③ 成长质量 12
    f3, m3 = [], []
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

    rev_cagr, dnp_cagr = cagr_stock('TOTALOPERATEREVE'), cagr_stock('KCFJCXSYJLR')
    m3.append(_m('营收3年复合增速', rev_cagr, '%',
                 pct_rank((uni.get('univ_rev_cagr') or {}).values(), rev_cagr), 0.20,
                 'high', n_samples=len(ann)))
    m3.append(_m('扣非净利3年复合增速', dnp_cagr, '%',
                 pct_rank((uni.get('univ_dnp_cagr') or {}).values(), dnp_cagr), 0.20,
                 'high', n_samples=len(ann)))
    toi_yoy = _num((fin[0] or {}).get('DJD_TOI_YOY')) if fin else None
    dnp_yoy = _num((fin[0] or {}).get('DJD_DEDUCTDPNP_YOY')) if fin else None
    m3.append(_m('单季营收同比', toi_yoy, '%',
                 pct_rank([_num(r.get('DJD_TOI_YOY')) for r in uni_mid.values()], toi_yoy),
                 0.15, 'high'))
    m3.append(_m('单季扣非净利同比', dnp_yoy, '%',
                 pct_rank([_num(r.get('DJD_DEDUCTDPNP_YOY')) for r in uni_mid.values()], dnp_yoy),
                 0.15, 'high'))
    diverg = (toi_yoy - dnp_yoy) if (toi_yoy is not None and dnp_yoy is not None) else None
    m3.append(_m('增收不增利背离度(低为好)', diverg, 'pct',
                 pct_rank([(_num(r.get('DJD_TOI_YOY')) - _num(r.get('DJD_DEDUCTDPNP_YOY')))
                           if r.get('DJD_TOI_YOY') is not None and r.get('DJD_DEDUCTDPNP_YOY') is not None
                           else None for r in uni_mid.values()], diverg), 0.20, 'low'))
    ar_chg = yoy_change('YSZKZZTS')
    m3.append(_m('应收周转天数同比变化(低=回款未恶化)', ar_chg, '%',
                 _abs(ar_chg, [(-20, 100), (0, 70), (30, 30), (60, 0)]),
                 0.10, 'high', coarse=True,
                 note='粗档绝对刻度（逐股算全市场同比宇宙成本过高）；应收增速快于营收时该值上升'))
    d3 = _dim('growth', '成长质量', W['growth'], m3, f3,
              extras={'thresh': '扣非口径强制；背离>30pct 记入闸门 🟡'})

    # ============================================ ④ 财务健康 8
    f4, m4 = [], []
    coarse4 = is_fin
    if coarse4:
        f4.append('金融业不适用通用阈值表，按全市场粗档（置信度×0.6）')
    m4.append(_m('资产负债率(低为好)', latest('ZCFZL'), '%',
                 pct_rank([_num(r.get('ZCFZL')) for r in uni_mid.values()], latest('ZCFZL')),
                 0.25, 'low', coarse=coarse4))
    m4.append(_m('有息负债率(低为好)', latest('INTEREST_DEBT_RATIO'), '%',
                 pct_rank([_num(r.get('INTEREST_DEBT_RATIO')) for r in uni_mid.values()],
                          latest('INTEREST_DEBT_RATIO')), 0.20, 'low', coarse=coarse4))
    m4.append(_m('利息保障倍数', latest('INTSTCOVRATE'), '倍',
                 pct_rank([_num(r.get('INTSTCOVRATE')) for r in uni_mid.values()],
                          latest('INTSTCOVRATE')), 0.20, 'high', coarse=coarse4))
    ld, sd = latest('LD'), latest('SD')
    p_ld = pct_rank([_num(r.get('LD')) for r in uni_mid.values()], ld)
    p_sd = pct_rank([_num(r.get('SD')) for r in uni_mid.values()], sd)
    if p_ld is not None and p_sd is not None:
        m4.append(_m('流动/速动比综合', (ld + sd) / 2.0, '倍', (p_ld + p_sd) / 2.0,
                     0.15, 'high', coarse=coarse4))
    nco_pk, lia = latest('NETCASH_OPERATE_PK'), latest('LIABILITY')
    cover = (nco_pk / lia) if (nco_pk is not None and lia) else None
    m4.append(_m('经营现金流覆盖总负债', cover, '倍',
                 pct_rank([(_num(r.get('NETCASH_OPERATE_PK')) / _num(r.get('LIABILITY')))
                           if (_num(r.get('NETCASH_OPERATE_PK')) is not None and _num(r.get('LIABILITY')))
                           else None for r in uni_mid.values()], cover), 0.10, 'high',
                 coarse=coarse4))
    # 商誉 / 净资产
    bs = balance_sheet(code, 1)
    gw = _num((bs[0] or {}).get('GOODWILL')) if bs else None
    eq = _num((bs[0] or {}).get('TOTAL_EQUITY')) if bs else None
    gw_ratio = (gw / eq * 100.0) if (gw is not None and eq) else None
    if gw is not None:
        m4.append(_m('商誉÷净资产(低为好)', gw_ratio, '%',
                     _abs(gw_ratio, [(0, 100), (10, 80), (30, 40), (50, 10), (80, 0)]),
                     0.10, 'high', coarse=True,
                     note='粗档绝对刻度（无全市场商誉宇宙）'))
    d4 = _dim('financial_health', '财务健康', W['financial_health'], m4, f4,
              extras={'thresh': '排雷主项在闸门，本维只作水位读数，避免双重计分'})
    if d4['available']:
        d4['grade'] = '稳健' if d4['score'] >= 70 else '中性' if d4['score'] >= 40 else '承压'

    # ============================================ ⑤ 估值与安全边际 26
    f5, m5 = [], []
    pe_now = _num((vs[0].get('PE_TTM') if vs else None)) or _num(ind_row.get('PE_TTM'))
    pb_now = _num((vs[0].get('PB_MRQ') if vs else None)) or _num(ind_row.get('PB_MRQ'))
    if pe_now is not None and pe_now <= 0:
        f5.append('盈利为负 → PE 无定义，估值维整维 N/A（严禁填 0/100）')
        d5 = _dim('valuation', '估值与安全边际', W['valuation'], [], f5,
                  extras={'na_reason': '盈利为负（PE_TTM≤0），估值维 N/A'})
    elif not vs and pe_now is None:
        d5 = _dim('valuation', '估值与安全边际', W['valuation'], [], f5,
                  extras={'na_reason': '个股估值日频序列缺失'})
    else:
        use_pe = not is_fin
        if is_fin:
            f5.append(f'金融业（{board_name}）：PE/PEG 不计分，只用 PB')
        pe_s = [_num(r.get('PE_TTM')) for r in vs]
        pb_s = [_num(r.get('PB_MRQ')) for r in vs]
        if use_pe:
            m5.append(_m('PE 自身3年分位(低=高分)', pe_now, '倍', pct_rank(pe_s, pe_now),
                         0.22, 'low', n_samples=len(vs)))
        m5.append(_m('PB 自身3年分位(低=高分)', pb_now, '倍', pct_rank(pb_s, pb_now),
                     0.18 if use_pe else 0.45, 'low', n_samples=len(vs)))
        peg = _num((vs[0] or {}).get('PEG_CAR')) if vs else None
        peg_pos = [v for v in (_num(r.get('PEG_CAR')) for r in vs) if v is not None and v > 0]
        if use_pe and peg and peg > 0:
            m5.append(_m('PEG 自身3年分位(低=高分)', peg, '倍',
                         pct_rank(peg_pos, peg), 0.12, 'low', n_samples=len(peg_pos)))
        # 股息率
        dps = (uni.get('bonus_ps') or {}).get(sc)
        price = (q or {}).get('price') or _num((vs[0] or {}).get('CLOSE_PRICE')) if vs else (q or {}).get('price')
        dy = (dps / price * 100.0) if (dps and price) else (0.0 if price else None)
        uni_dy = []
        for r in (uni.get('valmap') or {}).values():
            d_ = (uni.get('bonus_ps') or {}).get(r.get('SECUCODE') or '')
            mc, ts = _num(r.get('TOTAL_MARKET_CAP')), _num(r.get('TOTAL_SHARES'))
            if d_ and mc and ts:
                uni_dy.append(d_ * ts / mc * 100.0)
        if dy is not None:
            m5.append(_m('股息率(TTM)', dy, '%', pct_rank(uni_dy, dy),
                         0.10 if use_pe else 0.25, 'high', n_samples=len(uni_dy)))
        peers_pe = [_num((uni.get('valmap').get(k) or {}).get('PE_TTM' if use_pe else 'PB_MRQ'))
                    for k, vr in (uni.get('valmap') or {}).items()
                    if vr.get('BOARD_CODE') == board_code] if board_code else []
        peers_pe = [v for v in peers_pe if v is not None]
        cur = pe_now if use_pe else pb_now
        if len(peers_pe) >= 5:
            m5.append(_m('行业中位分位(低=高分)', cur, '倍', pct_rank(peers_pe, cur),
                         0.12 if use_pe else 0.30, 'low', n_samples=len(peers_pe)))
        # 松果 FCF 收益率（粗档绝对刻度：无全市场 FCFF 宇宙，且 1/市值 是规模因子不是收益率）
        if fcf_yield is not None:
            m5.append(_m('松果FCF收益率(FCFF÷市值)', fcf_yield, '%',
                         _abs(fcf_yield, [(-5, 0), (0, 40), (3, 65), (8, 90), (15, 100)]),
                         0.26, 'high', coarse=True,
                         note='松果 FCF/EV 的代理口径（分母仅市值，未扣净债；粗档绝对刻度）'))
        d5 = _dim('valuation', '估值与安全边际', W['valuation'], m5, f5,
                  extras={'thresh': '低分位=高分；金融只PB；亏损整维N/A；'
                                    '松果FCF收益率权重最高（26%）'})

    # ============================================ ⑥ 产业链景气 8
    f6, m6 = [], []
    board_ret = load_board_returns()
    bl = [c for c in str((basic or {}).get('BLGAINIAN_CODE') or '').split(',') if c]
    if board_ret and bl:
        own = [board_ret[c] for c in bl if c in board_ret]
        if own:
            own_s = sorted(own)
            n = len(own_s)
            med = own_s[n // 2] if n % 2 else (own_s[n // 2 - 1] + own_s[n // 2]) / 2.0
            m6.append(_m('所属概念20日涨幅中位数·位次', med, '%',
                         pct_rank([v for v in board_ret.values() if v is not None], med),
                         0.12, 'high', n_samples=len(board_ret),
                         note=f'{len(own)}/{len(bl)} 个概念有连续快照'))
    else:
        f6.append('板块每日快照不足 20 个交易日（采集脚本积累中），概念位次子项不纳入')

    # 6.1–6.3 行业基本面景气（东财二级行业横截面，全部 datacenter-web 固定通道）
    bp = board_prosperity(uni)
    bk_row = (bp.get('boards') or {}).get(board_code) or {}
    bk_name = board_name or board_code or '未分类行业'
    if bk_row.get('rev_med') is not None and len(bp.get('rev_pool') or []) >= 30:
        m6.append(_m('所属行业营收增速中位数', bk_row['rev_med'], '%',
                     pct_rank(bp['rev_pool'], bk_row['rev_med']), 0.26, 'high',
                     n_samples=len(bp['rev_pool']),
                     note=f'{bk_name} 板块内 {bk_row.get("n")} 只成分股单季营收同比中位数，'
                          f'跨 {len(bp["rev_pool"])} 个二级行业排位（需求景气）'))
    else:
        f6.append('行业营收增速中位数不可用（板块成分股不足 5 只或横截面为空）')
    if bk_row.get('dnp_med') is not None and len(bp.get('dnp_pool') or []) >= 30:
        m6.append(_m('所属行业扣非净利增速中位数', bk_row['dnp_med'], '%',
                     pct_rank(bp['dnp_pool'], bk_row['dnp_med']), 0.20, 'high',
                     n_samples=len(bp['dnp_pool']),
                     note='板块内单季扣非净利同比中位数（盈利景气，剔除非经常性损益）'))
    if bk_row.get('loss_pct') is not None and len(bp.get('loss_pool') or []) >= 30:
        m6.append(_m('所属行业亏损家数占比', bk_row['loss_pct'], '%',
                     pct_rank(bp['loss_pool'], bk_row['loss_pct']), 0.14, 'low',
                     n_samples=len(bp['loss_pool']),
                     note='板块内亏损公司占比（低=好），景气的地板而非天花板'))

    # 6.4 链内相对景气：个股单季营收同比 − 所属行业营收增速中位数（份额变化，α）
    own_rev = _num((((uni.get('mid') or {}).get(sc) or {})).get('DJD_TOI_YOY'))
    if own_rev is not None and bk_row.get('rev_med') is not None \
            and len(bp.get('alpha_pool') or []) >= 200:
        alpha = own_rev - bk_row['rev_med']
        m6.append(_m('链内相对景气(营收超额)', alpha, 'pp',
                     pct_rank(bp['alpha_pool'], alpha), 0.28, 'high',
                     n_samples=len(bp['alpha_pool']),
                     note=f'本股营收同比 {own_rev:.2f}% − 行业 {bk_row["rev_med"]:.2f}% = '
                          f'{alpha:+.2f}pp；衡量在链条内抢份额还是在丢份额，'
                          f'与「成长质量」的绝对增速不重复计分'))

    # 6.5 行业 20 日相对强度（市值变动代理，粗档；push2his 通道不稳，权重压到最低）
    rel20 = None
    if board_code:
        hist = industry_pe_history(board_code)
        mcs = [v for v in (_num(r.get('TOTAL_MARKET_CAP')) for r in hist) if v]
        if len(mcs) >= 21:
            rel20 = (mcs[-1] / mcs[-21] - 1.0) * 100.0
            m6.append(_m('所属行业20日市值变动', rel20, '%',
                         _abs(rel20, [(-20, 0), (-5, 30), (0, 50), (10, 78), (30, 100)]),
                         0.12, 'high', coarse=True,
                         note='行业总市值20日变动，非价格收益率口径（push2his 通道高危）；粗档绝对刻度'))
    d6 = _dim('chain_prosperity', '产业链景气', W['chain_prosperity'], m6, f6,
              extras={'thresh': '只读「这条链现在好不好」，与核心竞争力的「纵向位置」严格分工：'
                                '位置慢变归 Q，景气快变归 M；'
                                '行业层(β)与链内层(α)分开算，同一行业内不同公司不再同分',
                      'industry': bk_name,
                      'industry_peers': bk_row.get('n')})
    if d6['available']:
        f6.append('本维是景气读数，不是质地评价；投入产出表（153 部门结构层）'
                  '尚未接入——数据源 WAF 拦截，暂以申万/东财二级行业横截面替代，'
                  '结构层缺失只影响「上下游是谁」的解说，不影响景气打分')

    # 产业链结构层（路线 2）：申万三级归属 + 主营构成 + 链条图 + 上下游当前景气
    # 只影响势能页解说，不进权重——等 P3 验证「结构信息是否有增量」后再决定是否计分
    try:
        _mb_rows = main_business(code, periods=1)
    except Exception as _e:
        _mb_rows = []
        src_errors.append(f'主营构成取数失败：{type(_e).__name__}')
    chain = chain_structure.build(code, basic, bp, _mb_rows, own_rev=own_rev)

    # ============================================ ⑦ 预期修正 8
    f7, m7 = [], []
    reps = research_reports(code, days=120)
    n_rep = len(reps)
    if n_rep >= 3:
        m7.append(_m('研报覆盖数(近120日)', n_rep, '篇',
                     _abs(n_rep, [(0, 0), (3, 30), (10, 60), (30, 85), (60, 100)]),
                     0.25, 'high', coarse=True,
                     note='粗档绝对刻度（无全市场研报覆盖度宇宙）'))
        dated = sorted([r for r in reps if r.get('eps_this')], key=lambda x: x['date'])
        if len(dated) >= 4:
            half = max(2, len(dated) // 2)
            early = sum(r['eps_this'] for r in dated[:half]) / half
            late = sum(r['eps_this'] for r in dated[-half:]) / half
            drift = ((late - early) / abs(early) * 100.0) if early else None
            m7.append(_m('当年EPS预测漂移(近期 vs 早期)', drift, '%',
                         _abs(drift, [(-20, 0), (-5, 35), (0, 50), (5, 70), (20, 100)]),
                         0.35, 'high', n_samples=len(dated), coarse=True,
                         note=f'{dated[0]["date"]}→{dated[-1]["date"]}；粗档绝对刻度'))
        buy = sum(1 for r in reps if r.get('rating') in ('买入', '增持', '强烈推荐', '推荐'))
        m7.append(_m('买入/增持评级占比', buy / n_rep * 100.0, '%',
                     _abs(buy / n_rep * 100.0, [(0, 0), (50, 50), (80, 80), (100, 100)]),
                     0.20, 'high', n_samples=n_rep, coarse=True,
                     note='粗档绝对刻度'))
    else:
        f7.append('近120日研报覆盖 <3 篇 → 覆盖度与预测漂移子项 N/A（严禁填 0，否则系统性惩罚冷门中小盘）')
    m7.append(_m('单季扣非净利同比', dnp_yoy, '%',
                 pct_rank([_num(r.get('DJD_DEDUCTDPNP_YOY')) for r in uni_mid.values()], dnp_yoy),
                 0.20, 'high'))
    preds = stock_predict_recent(code, days=30)
    pred_dir = None
    if preds:
        kinds = sorted({str(r.get('PREDICT_FINANCE')) for r in preds if r.get('PREDICT_FINANCE')})
        f7.append('业绩预告(近30日)：' + '、'.join(kinds[:3]) + '（仅展示不计分）')
        pred_dir = kinds
    d7 = _dim('earnings_revision', '预期修正', W['earnings_revision'], m7, f7,
              extras={'thresh': '单季扣非同比口径全站统一，不重新定义；'
                                '无研报覆盖 → N/A 不进分母',
                      'forecast': pred_dir})

    # ============================================ ⑧ 资金动能 6（A/B/C 分级 + 20日）
    f8, m8 = [], []
    rz_rows = stock_rzrq(code, n=40)
    uni_rz = []
    for r in (uni.get('rzrq_today') or {}).values():
        a, b, y = _num(r.get('RZMRE5D')), _num(r.get('RZCHE5D')), _num(r.get('RZYE'))
        if a is not None and b is not None and y:
            uni_rz.append((a - b) / y * 100.0)
    rz20 = None
    if len(rz_rows) >= 21:
        r0, r20 = _num(rz_rows[0].get('RZYE')), _num(rz_rows[20].get('RZYE'))
        if r0 is not None and r20:
            rz20 = (r0 - r20) / r20 * 100.0
    elif len(rz_rows) >= 6:
        r0, r5 = _num(rz_rows[0].get('RZYE')), _num(rz_rows[5].get('RZYE'))
        if r0 is not None and r5:
            rz20 = (r0 - r5) / r5 * 100.0
            f8.append('融资余额逐日序列不足 21 日，退化为 5 日口径（已标注）')
    m8.append(_m('融资余额20日变化(A级·真实披露)', rz20, '%', pct_rank(uni_rz, rz20),
                 2.0, 'high', n_samples=len(rz_rows), reliability='A'))
    bb, bb_n = billboard_net(code, 20)
    if bb is not None:
        bb_yi = bb / 1e8
        m8.append(_m('龙虎榜20日净买入(A级·真实席位)', bb_yi, '亿元',
                     _abs(bb_yi, [(-3, 0), (0, 50), (1, 72), (3, 88), (8, 100)]),
                     1.5, 'high', n_samples=bb_n, coarse=True, reliability='A',
                     note=f'近20日上榜 {bb_n} 次；粗档绝对刻度（无全市场龙虎榜宇宙）'))
    else:
        f8.append('近20日未上龙虎榜 → 该子项 N/A（不填 0）')
    mf = sina_moneyflow(code, num=60)
    nets = [x['netamount'] for x in mf if x['netamount'] is not None]
    if len(nets) >= 21:
        net20 = sum(nets[:20])
        roll = [sum(nets[i:i + 20]) for i in range(len(nets) - 19)]
        m8.append(_m('主力净流入20日累计（大单推算，拆单可能失真）', net20 / 1e8, '亿元',
                     pct_rank(roll, net20), 2.5, 'high', n_samples=len(nets),
                     reliability='B',
                     note='按单笔成交金额分档推算，主力可拆单规避 → 只读异动，不读主力意图'))
    else:
        f8.append('新浪资金流序列不足 21 日 → 主力子项不纳入')
    f8.append('北向资金 2024-09-30 起停止实时披露，本维不含北向（C 级，永久剔除）')
    d8 = _dim('capital_momentum', '资金动能', W['capital_momentum'], m8, f8,
              extras={'thresh': '主窗口 20 日；5日/60日只展示不计分；'
                                'A级占3.5分、B级占2.5分——真实性越高权重越高',
                      'reliability': {'A': '融资余额/龙虎榜（真实披露）',
                                      'B': '主力净流入（大单推算，拆单失真）',
                                      'C': '北向（已停更，剔除）'}})

    dims = [d1, d2, d3, d4, d5, d6, d7, d8]

    # ============================================ 分组与总分
    avail = [d for d in dims if d['available']]
    w_eff = sum(d['weight'] for d in avail)
    for d in dims:
        d['weighted_score'] = (round(d['score'], 2) * d['weight'] / w_eff) if d['available'] else None
        if d['available']:
            d['score'] = round(d['score'], 2)
    total_raw = sum(d['weighted_score'] for d in avail)

    groups = {}
    for gk, keys in GROUP_OF.items():
        gd = [d for d in avail if d['key'] in keys]
        gw = sum(d['weight'] for d in gd)
        groups[gk] = {
            'key': gk, 'label': GROUP_META[gk]['label'],
            'question': GROUP_META[gk]['question'],
            'weight': round(sum(W[k] for k in keys) * 100),
            'score': round(sum(d['score'] * d['weight'] for d in gd) / gw, 2) if gw else None,
            'available': bool(gd),
        }

    # ============================================ 闸门
    # 分级原则（2026-10-18 实测修正）：
    #   🔴 = 不可接受的尾部风险（会计/资产/债务层面），一票封顶
    #   🟡 = 业绩与质量信号（H3/A+ 等），降档或标注，不封顶
    # 理由：H3/A+ 在 V35 里是「删票不补位」的持仓规则，不等于「这公司不能碰」。
    #       把它当一票否决，会让业绩下滑期的好公司全被标红旗，失去区分度。
    gate = {'red': [], 'yellow': [], 'not_wired': []}
    neg_years = sum(1 for r in ann if (_num(r.get('KCFJCXSYJLR')) or 0) < 0)
    if neg_years >= 2:
        gate['red'].append(f'近3年报中 {neg_years} 年扣非净利润为负（连续亏损）')
    if gw_ratio is not None and gw_ratio > 50:
        gate['red'].append(f'商誉÷净资产 {gw_ratio:.1f}% > 50%（资产质量尾部风险）')

    h3 = (toi_yoy is not None and dnp_yoy is not None and toi_yoy < 0 and dnp_yoy < 0)
    if h3:
        gate['yellow'].append(
            f'H3 双降：单季营收同比 {toi_yoy:.1f}%、扣非同比 {dnp_yoy:.1f}% 均 <0')
    elif dnp_yoy is not None and dnp_yoy < 0:
        # H3 是 A+ 的超集：H3 命中时不再重复计 A+
        gate['yellow'].append(f'业绩信号：单季扣非净利同比 {dnp_yoy:.1f}%（为负，盈利质量走弱）')
    if nco_mean is not None and nco_mean < 0.5:
        gate['yellow'].append(f'经营现金流÷净利润 3 年均值 {nco_mean:.2f} <0.5')
    ar_c = yoy_change('YSZKZZTS')
    if ar_c is not None and ar_c > 30:
        gate['yellow'].append(f'应收周转天数同比恶化 {ar_c:.1f}%（>30%）')
    ch_c = yoy_change('CHZZTS')
    if ch_c is not None and ch_c > 30:
        gate['yellow'].append(f'存货周转天数同比恶化 {ch_c:.1f}%（>30%）')
    gate['not_wired'] = ['审计意见（接口未接）', '股权质押比例（接口未接）',
                         '大股东减持（接口未接）', '高管异常离职（接口未接）']

    # 闸门应用
    total = total_raw
    gate_hit = 'none'
    if gate['red']:
        total = min(total_raw, 59.0)
        gate_hit = 'red'
    elif len(gate['yellow']) >= 2:
        gate_hit = 'yellow2'
    elif len(gate['yellow']) == 1:
        gate_hit = 'yellow1'

    _TIERS = ['待观察', '中', '良', '优']
    tier = tier_of(total)
    if gate_hit == 'yellow2' and tier in _TIERS:
        tier = _TIERS[max(0, _TIERS.index(tier) - 1)]
    tier_note = None
    if gate_hit == 'yellow2':
        # 坑：档位本来就已是最低档时，降一档的结果还是同一档，
        # 直接套模板会写出"（待观察 → 待观察）"这种没信息量的话。
        _before = tier_of(total)
        # 2026-10-22："黄旗/红旗"是策略内部标记口径，对外改中性表述。
        tier_note = (f'风险提示 {len(gate["yellow"])} 条 → 分档下调一档（{_before} → {tier}）'
                     if _before != tier
                     else f'风险提示 {len(gate["yellow"])} 条 → 已在下限档（{tier}），不再下调')
    elif gate_hit == 'yellow1':
        tier_note = f'风险提示 1 条 → 仅标注，不调档（{tier}）'
    elif gate_hit == 'red':
        tier_note = f'风险提示 {len(gate["red"])} 条 → 总分封顶 59（裸分 {round(total_raw,2)}）'

    # ============================================ 松果可投性（简化 11 步代理）
    checks = {
        '扣非ROE三年最低>3%': (roe3min is not None and roe3min > 3),
        'ROIC>0': (roic is not None and roic > 0),
        '资产负债率≤60%': (latest('ZCFZL') is not None and latest('ZCFZL') <= 60),
        '经营现金流>0': (nco_mean is not None and nco_mean > 0),
        '市值≤300亿': (mv is not None and mv <= 300),
    }
    passed = sum(1 for v in checks.values() if v)
    # 2026-10-22：这里原本输出「域内候选 / 域外优质 / 域外 / 红旗不碰」，
    # 那是选股结论（域内/域外、可投域、优质线、一票否决），
    # 与"面向普通股票的质地查询"定位冲突。
    # 现在只保留客观门槛达成情况，不给可投/不可投的结论。
    tag = {'code': 'basic', 'label': f'基础门槛 {passed}/{len(checks)} 项达成',
           'desc': '仅列示可量化门槛的达成数量，不作可投性判断'}

    # ============================================ 四页内容
    pages = _build_pages(
        name=name, code=code, board_name=board_name, total=total, tier=tier,
        groups=groups, dims=dims, gate=gate, tag=tag, checks=checks,
        mv=mv, pe=pe_now, pb=pb_now, gm=gm_now, gm_med=gm_med, fcf_yield=fcf_yield,
        roic=roic, nco_mean=nco_mean, dnp_yoy=dnp_yoy, toi_yoy=toi_yoy,
        reps=n_rep, rz20=rz20, bb=bb, net20=(sum(nets[:20]) / 1e8 if len(nets) >= 21 else None),
        rel20=rel20, ar_days=ar_days, ap_days=ap_days, net_days=net_days, choke=choke,
        chain=chain,
    )

    excluded = [{'dim': d['label'], 'key': d['key'], 'reason': d.get('na_reason')}
                for d in dims if not d['available']]
    low_conf = []
    for d in dims:
        if not d['available']:
            continue
        weak = [m['name'] for m in d['metrics'] if m['confidence'] < 0.6]
        if (d['confidence'] or 1) < 0.6 or weak:
            low_conf.append({'dim': d['label'], 'dim_confidence': d['confidence'],
                             'metrics_below_0.6': weak})

    payload = {
        'version': 'v3',
        'code': code, 'name': name, 'industry': board_name,
        'data_asof': uni.get('val_date') or _today(),
        'quote': {'price': (q or {}).get('price'), 'pe_ttm': pe_now, 'pb': pb_now,
                  'mv_yi': mv, 'quote_ts': (q or {}).get('ts')},
        'total': round(total, 2), 'total_raw': round(total_raw, 2),
        'tier': tier, 'tier_note': tier_note, 'gate_hit': gate_hit,
        'groups': groups, 'dims': dims, 'gate': gate, 'tag': tag,
        'investable_checks': checks, 'pages': pages, 'chain': chain,
        'excluded': excluded, 'low_confidence': low_conf,
        'source_errors': src_errors,
        'meta': {'weights': {k: round(v * 100) for k, v in W.items()},
                 'weights_sum': round(sum(W.values()), 9),
                 'latest_fin_period': uni.get('latest_period'),
                 'val_cross_date': uni.get('val_date'),
                 'universe_built': uni.get('date')},
    }
    return payload, 200


def _f(v, nd=1):
    """数字格式化：None → N/A，浮点去掉长尾（此前页面上出现过 PE 20.33942726 这种）。"""
    if v is None:
        return 'N/A'
    try:
        return f'{float(v):.{nd}f}'
    except (TypeError, ValueError):
        return str(v)


def _scale(total):
    t = total or 0
    if t >= 80:
        return '属于优秀那一档'
    if t >= 65:
        return '属于良这一档，比多数公司好，但没到最顶尖'
    if t >= 45:
        return '属于中等，有明显长处也有明显短板'
    return '偏弱，短板比较集中'


def _build_pages(**k):
    """四页解说内容（规则生成，非 LLM 自由发挥）。

    2026-10-19：数字统一保留 1 位、句子改口语（原版直接插浮点，
    页面上出现「PE 20.33942726」，普通股民看不懂也没法读）。
    """
    d = {x['key']: x for x in k['dims']}
    g = k['groups']
    # 2026-10-22：小数位 0 → 1。总览 headline 写「质地 53」而深度页写「53.5 分」，
    # 同一个人看两个页面数字对不上，没必要。
    qs = lambda key: _f((g.get(key) or {}).get('score'), 1)  # noqa: E731
    p1 = {
        'title': '总览',
        # 2026-10-22：去掉"按松果口径属于【域内候选/域外优质/红旗不碰】"。
        # 用户明确要求不接入松果投资策略的选股最终影响 ——
        # 这里的 tag 文案就是选股结论，属于策略输出，不该出现在质地查询工具里。
        # 2026-10-22："红旗/黄旗"是策略内部标记口径，改为中性「风险提示」。
        'headline': (f"质地 {qs('Q')} / 价格 {qs('V')} / 势能 {qs('M')}；"
                     f"风险提示 {len(k['gate']['red']) + len(k['gate']['yellow'])} 条"),
        'blocks': [
            {'h': '结论', 't': f"总分 {_f(k['total'])}，{_scale(k['total'])}。"
                               f"这是按打分卡算出的质地水平，不构成买卖建议。"},
            {'h': '闸门', 't': ('没有触发封顶的风险项' if not k['gate']['red']
                                else '；'.join(k['gate']['red'])) +
                               ('；关注：' + '；'.join(k['gate']['yellow']) if k['gate']['yellow'] else '')},
            {'h': '未接入项', 't': '、'.join(k['gate']['not_wired']) + '（如实标注，不填 0）'},
        ],
    }
    q = d.get('profit_quality') or {}
    cc = d.get('core_competence') or {}
    gr = d.get('growth') or {}
    fh = d.get('financial_health') or {}
    roic_txt = (f"每投 100 块钱一年能赚回 {_f(k['roic'])} 块" if k.get('roic') is not None
                else 'ROIC 暂缺')
    gm_txt = (f"毛利率 {_f(k['gm'])}%，比同行中位数{'高' if (k.get('gm') or 0) >= (k.get('gm_med') or 0) else '低'} "
              f"{_f(abs((k.get('gm') or 0) - (k.get('gm_med') or 0)))} 个百分点"
              if k.get('gm') is not None and k.get('gm_med') is not None else '毛利率数据暂缺')
    p2 = {
        'title': '质地', 'score': g['Q']['score'],
        'headline': f"Q {_f(g['Q']['score'])}｜盈利质量 {_f(q.get('score'))} · 核心竞争力 {_f(cc.get('score'))} · "
                    f"成长质量 {_f(gr.get('score'))} · 财务健康 {_f(fh.get('score'))}",
        'blocks': [
            {'h': '强在哪', 't': f"盈利质量 {_f(q.get('score'))} 分：{roic_txt}；{gm_txt}。"},
            {'h': '弱在哪', 't': (f"成长质量 {_f(gr.get('score'))} 分：最近一个季度扣非利润同比 "
                                f"{_f(k['dnp_yoy'])}%，增长{'在放缓' if (k.get('dnp_yoy') or 0) < 0 else '还算稳'}。"
                                if k.get('dnp_yoy') is not None else
                                f"成长质量 {_f(gr.get('score'))} 分：单季同比数据暂缺。")},
            {'h': '纵-横-己', 't': f"应收 {_f(k['ar_days'], 0)} 天、应付 {_f(k['ap_days'], 0)} 天，"
                               f"净占用上下游资金 {_f(k['net_days'], 1)} 天（负数=占用别人的钱）；"
                               f"卡点判定 {k['choke'] if k['choke'] is not None else '未判定'}。"},
        ],
    }
    v = d.get('valuation') or {}
    p3 = {
        'title': '价格', 'score': g['V']['score'],
        'headline': (f"V {_f(g['V']['score'])}｜PE {_f(k['pe'])} 倍 · PB {_f(k['pb'])} 倍 · "
                     f"FCF 收益率 {_f(k['fcf_yield'])}%" if g['V']['available']
                     else f"V N/A｜{v.get('na_reason', '估值维不可用')}"),
        'blocks': [
            {'h': '估值位置', 't': (f"市盈率 {_f(k['pe'])} 倍、市净率 {_f(k['pb'])} 倍。"
                                f"通俗说，市场愿意为它每 1 块钱的年利润付 {_f(k['pe'])} 块钱。"
                                if k.get('pe') is not None else
                                '亏损或数据缺失，PE 无定义，这一维按 N/A 处理。')},
            {'h': '松果安全边际', 't': f"FCF 收益率 {_f(k['fcf_yield'])}%：按松果口径，它每年能自由支配的现金"
                                  f"大约相当于市值的 {_f(k['fcf_yield'])}%，这个数越高说明越便宜"
                                  f"（FCFF÷市值代理口径，未扣净债）。"},
        ],
    }
    cp = d.get('chain_prosperity') or {}
    er = d.get('earnings_revision') or {}
    cm = d.get('capital_momentum') or {}
    ch = k.get('chain') or {}
    chain_blocks = list(ch.get('narration') or [])
    p4 = {
        'title': '势能', 'score': g['M']['score'],
        'headline': f"M {_f(g['M']['score'])}｜产业链景气 {_f(cp.get('score'))} · "
                    f"预期修正 {_f(er.get('score'))} · 资金动能 {_f(cm.get('score'))}",
        'blocks': chain_blocks + [
            {'h': '风从哪来', 't': f"所在行业近 20 个交易日市值变动 {_f(k['rel20'])}%。"},
            {'h': '预期', 't': f"近 120 天有 {k['reps'] if k.get('reps') is not None else 'N/A'} 篇研报覆盖；"
                            f"单季扣非同比 {_f(k['dnp_yoy'])}%。"},
            {'h': '资金（带可靠性）', 't': f"融资余额近 20 日 {_f(k['rz20'])}%（A 级·真实披露）· "
                                    f"龙虎榜净买入 {_f((k['bb'] or 0) / 1e8, 2) if k.get('bb') else 'N/A'} 亿（A 级）· "
                                    f"主力净流入 20 日 {_f(k['net20'], 2)} 亿元（大单推算口径，拆单可能失真）"},
        ],
    }
    return {'overview': p1, 'quality': p2, 'price': p3, 'momentum': p4}


if __name__ == '__main__':
    import sys
    import os
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dump_json = '--json' in sys.argv
    codes = args or ['600519']
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_v3_out')
    if dump_json:
        os.makedirs(outdir, exist_ok=True)
    for c in codes:
        t0 = time.time()
        payload, st = compute_v3(c)
        print('=' * 70)
        if not payload:
            print(c, 'status', st); continue
        print(f"{payload['name']}（{c}） {payload['industry']}  用时 {time.time()-t0:.1f}s")
        print(f"总分 {payload['total']}（{payload['tier']}） 裸分 {payload['total_raw']} "
              f"闸门 {payload['gate_hit']} 标签 {payload['tag']['label']}")
        for gk in ('Q', 'V', 'M'):
            gg = payload['groups'][gk]
            print(f"  {gk} {gg['label']} {gg['score']}  (权重{gg['weight']})")
        for dd in payload['dims']:
            print(f"    - {dd['label']:<8} {str(dd['score']):>7}  w={int(dd['weight']*100)}%  "
                  f"conf={dd['confidence']}  {'' if dd['available'] else 'N/A: '+str(dd.get('na_reason'))}")
        print('  闸门红:', payload['gate']['red'])
        print('  闸门黄:', payload['gate']['yellow'])
        print('  四页 headline:')
        for pk in ('overview', 'quality', 'price', 'momentum'):
            print(f"    [{payload['pages'][pk]['title']}] {payload['pages'][pk]['headline']}")
        if dump_json:
            fp = os.path.join(outdir, f'{c}.json')
            with open(fp, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=1, default=str)
            print('  JSON ->', fp)
