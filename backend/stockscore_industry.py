# -*- coding: utf-8 -*-
"""行业景气与结构数据层（外部深度数据补漏机制 · 核心件）

2026-10-20 落地。

【为什么需要这个】
打分卡 + 研报抽取（stockscore_facts / stockscore_research）拿不到三块东西：
  1) 行业市场规模与增速（研报里偶有，且口径不可核）
  2) 行业集中度（CR5/CR10/HHI）——研报基本不写
  3) 目标公司在行业里的位置（份额、市值占比）
而 deep 层的"市场空间与竞争格局""竞争格局"两段恰恰最需要这些，
拿不到就只能空着（实测 688508：市场段 chars=0）。

【本模块解决什么】
用 tushare 的申万行业成分股数据，自己把行业结构算出来——
每一个数字都可复算、可溯源到具体接口，不依赖任何一家券商的措辞。

数据来源（全部 tushare pro）：
  - index_member_all  申万行业成分股（l1/l2/l3 三级）
  - index_classify    申万行业分类字典
  - daily_basic       全市场估值/市值快照（单次调用取全市场 5000+ 只）
  - fina_indicator    营收/净利同比、ROE（批量逗号调用）
  - index_daily       行业指数行情（涨跌幅 → 行业景气方向）

【设计原则：宁可算错也不猜】
所有聚合值都带 caliber（口径说明）和 method（算法说明），
前端/写作层必须原样带出，不许把"行业中位PE"说成"行业PE"。
样本不足（<8 只有效成分股）一律不给集中度，标 insufficient。
"""
import os
import time
import json
import threading

from tushare_client import _call

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'data', 'industry')
# 2026-10-20 v2：修 CRn 为 None 时渲染出字面量 "None%"；
# 集中度样本阈值 8→6（申万二级存在天然小行业，如「国有大型银行Ⅱ」仅 6 只）。
PIPELINE_VERSION = 2

_lock = threading.Lock()
_mem = {}

# 最近可用交易日回溯窗口（往前找 N 个交易日）
_TRADE_DATE_FALLBACK = 8


# ================================================================== 缓存

def _cache_path(code, asof):
    return os.path.join(CACHE_DIR, '%s_%s_v%d.json' % (code, asof, PIPELINE_VERSION))


def _read_cache(code, asof):
    p = _cache_path(code, asof)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _write_cache(code, asof, obj):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(code, asof), 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    except Exception:
        pass


# ================================================================== 基础件

def _industry_of(code):
    """取目标股票的申万一/二/三级行业。

    优先 index_member_all（能同时给 l1/l2/l3）；
    退路 stock_basic.industry（只有粗分类，且 tushare 的行业名经常带冗余后缀）。
    """
    ts = _with_suffix(code)
    out = {}
    try:
        rows = _call('index_member_all', {'ts_code': ts},
                     'ts_code,l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,in_date')
        if rows:
            r = rows[0]
            out['l1_code'] = r.get('l1_code')
            out['l1_name'] = r.get('l1_name')
            out['l2_code'] = r.get('l2_code')
            out['l2_name'] = r.get('l2_name')
            out['l3_code'] = r.get('l3_code')
            out['l3_name'] = r.get('l3_name')
            out['_src'] = 'index_member_all'
    except Exception:
        pass
    if not out.get('l2_code'):
        try:
            rows = _call('stock_basic', {'ts_code': ts}, 'ts_code,name,industry')
            if rows and rows[0].get('industry'):
                out['fallback_industry'] = rows[0]['industry']
                out['_src'] = 'stock_basic'
        except Exception:
            pass
    return out


def _with_suffix(code):
    c = ''.join(ch for ch in str(code) if ch.isdigit())
    if len(c) != 6:
        return code
    if c.startswith('6'):
        return c + '.SH'
    if c.startswith(('0', '3')):
        return c + '.SZ'
    if c.startswith(('4', '8')):
        return c + '.BJ'
    return c + '.SH'


def _latest_trade_date():
    """最近一个**已发布日频数据**的交易日。

    坑（2026-10-20 实测）：trade_cal 说今天 20261020 是交易日，
    但 daily_basic 今天的快照要收盘后才发布，直接取今天会拿到 0 行，
    后面集中度就整个算不出来。必须逐日回退直到拿到非空快照。
    """
    try:
        rows = _call('trade_cal',
                     {'exchange': 'SSE',
                      'start_date': time.strftime('%Y%m%d', time.localtime(
                          time.time() - 40 * 86400)),
                      'end_date': time.strftime('%Y%m%d')},
                     'cal_date,is_open')
        opens = sorted(r['cal_date'] for r in rows if str(r.get('is_open')) == '1')
    except Exception:
        opens = list(reversed(_recent_dates(10)))
    for d in reversed(opens[-_TRADE_DATE_FALLBACK:]):
        try:
            probe = _call('daily_basic', {'trade_date': d}, 'ts_code')
            if probe:
                return d
        except Exception:
            continue
    return None


def _recent_dates(n):
    out = []
    d = time.time()
    for i in range(n * 3 + 6):
        t = time.localtime(d - i * 86400)
        s = time.strftime('%Y%m%d', t)
        if time.strftime('%w', t) not in ('0', '6'):
            out.append(s)
        if len(out) >= n:
            break
    return out


def _members_of(l2_code, l1_code=None):
    """某申万二级行业（或一级）的当前有效成分股。"""
    kw = {'l2_code': l2_code} if l2_code else {'l1_code': l1_code}
    try:
        rows = _call('index_member_all', kw, 'ts_code,l1_code,l2_code,l3_code,out_date')
    except Exception:
        return []
    return [r['ts_code'] for r in rows if not r.get('out_date')]


# ================================================================== 核心件

def build_industry(code, asof=None, force=False):
    """算出一个票的行业结构全景。返回可直接进 facts 块的 dict。"""
    asof = asof or time.strftime('%Y%m%d')
    with _lock:
        if (code, asof) in _mem and not force:
            return _mem[(code, asof)]
    cached = _read_cache(code, asof)
    if cached and not force:
        with _lock:
            _mem[(code, asof)] = cached
        return cached

    out = {
        'code': code, 'asof': asof,
        'industry': _industry_of(code),
        'concentration': None,
        'peers': None,
        'industry_index': None,
        'growth': None,
        'notes': [],
    }

    ind = out['industry']
    l2 = ind.get('l2_code')
    l1 = ind.get('l1_code')
    if not l2 and not l1:
        out['notes'].append('未能识别申万行业，行业结构数据不可得')
        _save(code, asof, out)
        return out

    # ---- 1) 行业集中度（CR5/CR10/HHI）+ 目标公司行业市值占比
    members = _members_of(l2, l1)
    if members:
        tdate = _latest_trade_date()
        if tdate:
            try:
                # 关键：daily_basic 按 trade_date 一次拿全市场（5000+ 只），0.3 秒。
                # 不要按 ts_code 循环调用（188 只 × 0.35 秒 = 65 秒，太慢）。
                allrows = _call('daily_basic', {'trade_date': tdate},
                                'ts_code,trade_date,total_mv,pe_ttm,pb')
            except Exception as e:
                allrows = []
                out['notes'].append('daily_basic 拉取失败：%s' % (str(e)[:50],))
            mset = set(members)
            rows = [x for x in (allrows or [])
                    if x.get('ts_code') in mset and x.get('total_mv')]
            # 坑（2026-10-20 实测）：申万二级行业里存在**天然小行业**
            # （如「国有大型银行Ⅱ」只有 6 只成分股）。原来硬编码 >=8 只，
            # 导致这类行业整块集中度被丢弃——而 CR3/CR5 对 6 只样本仍然成立。
            # 阈值降到 6：够算 CR3/CR5；CR10/CR20 由 k<=len(rows) 自然跳过。
            if len(rows) >= 6:
                rows.sort(key=lambda x: -x['total_mv'])
                tot = sum(x['total_mv'] for x in rows)
                cr = {}
                for k in (3, 5, 10, 20):
                    if len(rows) >= k:
                        cr['cr%d' % k] = round(
                            sum(x['total_mv'] for x in rows[:k]) / tot * 100, 2)
                hhi = sum((x['total_mv'] / tot * 100) ** 2 for x in rows)
                pes = sorted(x['pe_ttm'] for x in rows if x.get('pe_ttm'))
                pbs = sorted(x['pb'] for x in rows if x.get('pb'))
                tgt = [x for x in rows if x['ts_code'] == _with_suffix(code)]
                out['concentration'] = {
                    'sample_n': len(rows),
                    'trade_date': tdate,
                    'total_mv_wan': round(tot),
                    'cr3': cr.get('cr3'), 'cr5': cr.get('cr5'),
                    'cr10': cr.get('cr10'), 'cr20': cr.get('cr20'),
                    'hhi': round(hhi),
                    'hhi_level': _hhi_level(hhi),
                    'pe_median': round(pes[len(pes) // 2], 2) if pes else None,
                    'pb_median': round(pbs[len(pbs) // 2], 2) if pbs else None,
                    'pe_positive_n': len(pes),
                    'target_mv_wan': round(tgt[0]['total_mv']) if tgt else None,
                    'target_mv_share_pct': round(
                        tgt[0]['total_mv'] / tot * 100, 4) if tgt else None,
                    # 口径纪律（2026-10-20 定）：
                    # 行业块里的 PE 一律用 tushare daily_basic 截面（同行横比必须同源）。
                    # 估值段里的 PE 用东财 VALUEANALYSIS（历史分位必须同源）。
                    # 两个源对同一只票会给出不同的 PE（芯朋微 84.86 vs 88.10，
                    # 因为 daily_basic 财报期滞后在中报），所以正文里绝不能把两个绝对值并排放。
                    # 行业块改为只给「本股 PE 在成分股截面中的百分位」——同源、且比绝对值更有决策价值。
                    'target_pe_ttm': round(tgt[0]['pe_ttm'], 2) if tgt and tgt[0].get('pe_ttm') else None,
                    'target_pe_pctile': None,
                    'target_pb': round(tgt[0]['pb'], 2) if tgt and tgt[0].get('pb') else None,
                    'target_pb': round(tgt[0]['pb'], 2) if tgt and tgt[0].get('pb') else None,
                    'caliber': '申万二级行业成分股总市值口径（%d 只），市值单位万元' % len(rows),
                    'method': 'CRn=前n大成分股市值/行业总市值；HHI=各成分股市值占比平方和',
                }
            else:
                out['notes'].append('有效成分股不足6只（%d），集中度不给' % len(rows))
    else:
        out['notes'].append('申万成分股列表不可得')

    # 本股 PE 在同截面成分股中的百分位（同源横比，替代「本股PE vs 行业PE中位」的跨源绝对值对比）
    try:
        _c = out.get('concentration') or {}
        _tp = _c.get('target_pe_ttm')
        _all = [x.get('pe_ttm') for x in rows if x.get('pe_ttm')]
        if _tp is not None and _all:
            _below = sum(1 for v in _all if v < _tp)
            _c['target_pe_pctile'] = round(_below / len(_all) * 100, 1)
    except Exception:
        pass

    # ---- 2) 行业景气：等权成分股指数区间涨跌幅
    # 坑（2026-10-20 实测）：申万行业指数取不到行情——
    # index_daily 对 801081.SI 返回 0 行，sw_daily / ths_index 同样为空
    # （tushare 的行业指数接口需要更高积分）。
    # 退路且更可核的做法：自己用成分股等权合成一个指数。
    # 口径写清楚"等权合成"，别冒充官方行业指数。
    if members:
        idx = _synth_index(members)
        if idx:
            out['industry_index'] = idx
        else:
            out['notes'].append('行业景气：成分股行情不足以合成指数')

    # ---- 3) 行业增长：成分股营收同比中位数（可比公司口径，非市场规模）
    if members:
        try:
            codes = ','.join(members[:120])   # 120 只一批，够算中位数
            fin = _call('fina_indicator',
                        {'ts_code': codes,
                         'start_date': time.strftime('%Y%m%d', time.localtime(
                             time.time() - 200 * 86400)),
                         'end_date': time.strftime('%Y%m%d')},
                        'ts_code,ann_date,end_date,or_yoy,netprofit_yoy')
            # 取每只最新一期
            latest = {}
            for r in fin or []:
                ts = r.get('ts_code')
                ed = r.get('end_date') or ''
                if ts not in latest or ed > (latest[ts].get('end_date') or ''):
                    latest[ts] = r
            ors = sorted(r['or_yoy'] for r in latest.values()
                         if r.get('or_yoy') is not None)
            nps = sorted(r['netprofit_yoy'] for r in latest.values()
                         if r.get('netprofit_yoy') is not None)
            if len(ors) >= 8:
                out['growth'] = {
                    'sample_n': len(ors),
                    'or_yoy_median_pct': round(ors[len(ors) // 2], 2),
                    'or_yoy_mean_pct': round(sum(ors) / len(ors), 2),
                    'or_yoy_positive_ratio_pct': round(
                        len([x for x in ors if x > 0]) / len(ors) * 100, 1),
                    'netprofit_yoy_median_pct': (round(nps[len(nps) // 2], 2)
                                                 if len(nps) >= 8 else None),
                    'netprofit_positive_ratio_pct': (round(
                        len([x for x in nps if x > 0]) / len(nps) * 100, 1)
                        if len(nps) >= 8 else None),
                    'caliber': '申万二级行业成分股最新一期财报营收同比中位数（可比公司口径）',
                    'method': '逐只取最新报告期 or_yoy 后取中位数，非行业市场规模增速',
                }
        except Exception as e:
            out['notes'].append('行业营收增速聚合失败：%s' % (str(e)[:50],))

    _save(code, asof, out)
    return out


def _synth_index(members):
    """用成分股等权合成行业指数的区间涨跌幅。

    做法：取三个锚点交易日（最近、约20交易日前、约60交易日前）的
    全市场收盘价，算每个成分股在这两个区间的涨跌幅，再取中位数
    —— 中位数比均值抗极端值（个别成分股停牌/暴涨会污染均值）。

    口径必须写"等权合成"，不许说成官方行业指数。
    """
    mset = set(members)
    try:
        cal = _call('trade_cal',
                    {'exchange': 'SSE',
                     'start_date': time.strftime('%Y%m%d', time.localtime(
                         time.time() - 120 * 86400)),
                     'end_date': time.strftime('%Y%m%d')},
                    'cal_date,is_open')
        opens = sorted(r['cal_date'] for r in cal if str(r.get('is_open')) == '1')
    except Exception:
        opens = []
    if len(opens) < 5:
        return None

    def _closes(d):
        try:
            rows = _call('daily', {'trade_date': d}, 'ts_code,close')
        except Exception:
            return {}
        return {r['ts_code']: float(r['close']) for r in (rows or [])
                if r.get('close')}

    # 从后往前找第一个有行情的交易日
    last_d = None
    closes_last = {}
    for d in reversed(opens[-12:]):
        c = _closes(d)
        if c:
            last_d, closes_last = d, c
            break
    if not last_d:
        return None

    def _anchor_back(n):
        # 从 last_d 往前数 n 个交易日
        i = opens.index(last_d) - n
        if i < 0:
            return None
        for d in reversed(opens[max(0, i - 3):i + 1]):
            c = _closes(d)
            if c:
                return d, c
        return None

    res = {'base_date': last_d, 'sample_n': 0}
    for label, n in (('chg_20d_pct', 20), ('chg_60d_pct', 60)):
        a = _anchor_back(n)
        if not a:
            res[label] = None
            continue
        ad, closes_a = a
        rets = []
        for ts in mset:
            if ts in closes_a and ts in closes_last and closes_a[ts] > 0:
                rets.append((closes_last[ts] / closes_a[ts] - 1) * 100)
        if len(rets) >= 8:
            rets.sort()
            res[label] = round(rets[len(rets) // 2], 2)
            res[label + '_n'] = len(rets)
            res[label + '_from'] = ad
        else:
            res[label] = None
    if res.get('chg_20d_pct') is None and res.get('chg_60d_pct') is None:
        return None
    res['caliber'] = '申万二级行业成分股等权合成指数的区间涨跌幅（中位数口径）'
    res['method'] = '各成分股区间涨跌幅取中位数；非官方行业指数'
    return res


def _hhi_level(hhi):
    """HHI 集中度分级（标准口径：<1500 分散，1500-2500 中等，>2500 高度集中）。"""
    if hhi is None:
        return None
    if hhi >= 2500:
        return '高度集中'
    if hhi >= 1500:
        return '中等集中'
    return '分散'


def _save(code, asof, obj):
    with _lock:
        _mem[(code, asof)] = obj
    _write_cache(code, asof, obj)


def get_industry(code, asof=None, force=False):
    return build_industry(code, asof=asof, force=force)


# ================================================================== 出口

def facts_for_writer(ind):
    """把行业结构数据转成写作层能直接用的 facts 块（纯字符串，可核）。"""
    facts = []
    if not ind:
        return facts
    meta = ind.get('industry') or {}
    if meta.get('l2_name'):
        facts.append('公司申万行业分类：一级%s、二级%s、三级%s（分类来源：申万2021行业分类）'
                     % (meta.get('l1_name'), meta.get('l2_name'),
                        meta.get('l3_name') or '未披露'))
    c = ind.get('concentration')
    if c:
        # 坑（2026-10-20 实测）：样本不足 k 只时 cr_k 为 None，
        # 直接 '%s%%' % None 会渲染出字面量 "None%" 混进正文。
        # 必须只拼实际算出来的 CRn，缺哪个就不写哪个。
        cr_parts = []
        for k in (3, 5, 10, 20):
            v = c.get('cr%d' % k)
            if v is not None:
                cr_parts.append('CR%d %s%%' % (k, v))
        facts.append(
            '行业集中度（%s）：%s，'
            'HHI %s（%s）；样本 %d 只申万二级行业成分股，'
            '行业总市值 %s 万元'
            % (c['caliber'], '、'.join(cr_parts),
               c.get('hhi'), c.get('hhi_level'),
               c.get('sample_n'), c.get('total_mv_wan')))
        # 2026-10-20 改：原来这里把「行业 PE 中位」和「公司自身 PE」并排写。
        # 但行业 PE 中位来自 tushare daily_basic 截面，公司自身 PE 若取东财口径，
        # 两者财报期不同（芯朋微 84.86 vs 88.10），并排就是拿两把尺子量同一张桌子。
        # 现在只输出同源截面内的相对位置：本股 PE 在成分股中的百分位。
        _pct = c.get('target_pe_pctile')
        _pe_txt = ('本股 PE(TTM) 在该截面 %d 只成分股中处于第 %s 百分位'
                   % (c.get('sample_n'), _pct)) if _pct is not None else (
                   '本股 PE(TTM) %s' % c.get('target_pe_ttm'))
        facts.append(
            '目标公司行业市值占比 %s%%（自身总市值 %s 万元，交易日 %s；'
            '注意这是市值口径，不等于收入份额，不能直接用来判断公司的规模地位或规模壁垒），'
            '行业 PE(TTM) 中位 %s、PB 中位 %s（申万二级成分股同批截面）；'
            '%s，PB %s'
            % (c.get('target_mv_share_pct'), c.get('target_mv_wan'),
               c.get('trade_date'), c.get('pe_median'), c.get('pb_median'),
               _pe_txt, c.get('target_pb')))
    g = ind.get('growth')
    if g:
        facts.append(
            '行业可比公司增长（%s）：样本 %d 家（申万二级 %s 只成分股中有可比财报数据的子集，'
            '不是全部成分股，口径与全行业不同，不能直接当全行业增速用），'
            '营收同比中位数 %s%%、均值 %s%%，'
            '营收同比增长家数占比 %s%%；净利润同比中位数 %s%%，'
            '净利润同比增长家数占比 %s%%'
            % (g['caliber'], g.get('sample_n'), g.get('member_n') or g.get('sample_n'),
               g.get('or_yoy_median_pct'),
               g.get('or_yoy_mean_pct'), g.get('or_yoy_positive_ratio_pct'),
               g.get('netprofit_yoy_median_pct'),
               g.get('netprofit_positive_ratio_pct')))
    ix = ind.get('industry_index')
    if ix:
        facts.append(
            '行业景气（%s；这是行业整体涨跌背景，用来判断周期位置，'
            '不构成对公司所处市场空间的测算）：近20个交易日 %s%%（样本 %s 只），'
            '近60个交易日 %s%%（样本 %s 只）'
            % (ix['caliber'],
               ix.get('chg_20d_pct'), ix.get('chg_20d_pct_n'),
               ix.get('chg_60d_pct'), ix.get('chg_60d_pct_n')))
    for n in (ind.get('notes') or []):
        facts.append('行业数据缺口：%s' % n)
    return facts


if __name__ == '__main__':
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else '688508'
    r = build_industry(code, force=True)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    print('--- facts ---')
    for f in facts_for_writer(r):
        print(' *', f)
