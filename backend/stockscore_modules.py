# -*- coding: utf-8 -*-
"""估值与预期模块 + 风险与安全模块的确定性计算层（2026-10-20）

两个模块共用 facts 层的取数，但计算逻辑完全独立于写作层：
所有数字在这里算好并带 source，写作层只负责组织语言。

设计原则（对应 skill=stock-valuation-module / stock-risk-safety-module）：

1. **分位是刻度，估值方法是锚**。本层输出 PE/PB/PS/PCF 的 3/5/10 年分位，
   并按 stock-valuation-module 的五档区间给出 zone 标签。
2. **绝对估值给区间不给点值**。DCF 假设做 ±20% 敏感性，输出三档。
3. **预期反推**：从市值和一致预期 EPS 反推市场隐含增速，再与实际增速对比。
4. **风险只报命中的红旗**，不命中的不写"无风险"。
5. **接不到就写"数据不可得"**，绝不用常识补数。
6. **本层不产生买卖结论**。只输出读数、阈值对比、判读。

对外：
  build_valuation_block(code, ...) -> 估值与预期 facts 块
  build_risk_block(code, ...)       -> 风险与安全 facts 块
"""
import math

import stockscore_facts as F
import stockscore_research as RS
import tushare_client as T
from stockscore import dc_all, secu, _num as _snum

# ================================================================== 工具
def _f(v):
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _n(v, d=2):
    if v is None:
        return '—'
    try:
        return ('%.' + str(d) + 'f') % float(v)
    except (TypeError, ValueError):
        return '—'


def _ts(code):
    return code + ('.SH' if code.startswith('6') else '.SZ')


# ================================================================== 一、估值与预期
def _dcf(cash, growth, wacc, years=10, terminal_g=0.03):
    """简化 DCF：两阶段 FCFF 折现。
    cash: 当期自由现金流（年化，元）
    growth: 前 years 年增长率
    wacc: 折现率
    返回每股内在价值不可得（缺股本），这里返回企业价值。
    """
    if not cash or not wacc or wacc <= 0:
        return None
    g = terminal_g
    if g >= wacc:
        return None
    pv = 0.0
    fcff = cash
    for t in range(1, years + 1):
        fcff = cash * ((1 + growth) ** t)
        pv += fcff / ((1 + wacc) ** t)
    tv = fcff * (1 + g) / (wacc - g)
    pv += tv / ((1 + wacc) ** years)
    return pv


def _valuation_zone(pctl):
    if pctl is None:
        return '数据不可得'
    if pctl < 20:
        return '低估区'
    if pctl < 50:
        return '合理偏低'
    if pctl < 80:
        return '合理偏高'
    return '高估区'


# 失真倍数护栏：分母趋零时倍数本身没有意义（PCF 靠 OCF 做分母）
# 2026-10-20 实测：芯朋微 PCF 显示 4723.69、99.9 分位，看着像"极度高估"，
# 实际是 TTM 经营现金流接近 0 导致的分母失真。分位再准，倍数本身不可信。
_DISTORTED_MULTIPLES = {'PCF_OCF_TTM': 500.0, 'PE_TTM': 2000.0, 'PEG_CAR': 500.0}


def _is_distorted(metric, value):
    """倍数是否因分母趋零而失真。"""
    lim = _DISTORTED_MULTIPLES.get(metric)
    if lim is None:
        return False
    try:
        v = abs(float(value))
    except (TypeError, ValueError):
        return False
    if v == 0:
        return True
    return v > lim


def build_valuation_block(code, research=None, extra=None, vp=None):
    """估值与预期模块。返回 {'facts': [...], 'gaps': [...], 'detail': {...}}"""
    facts, gaps = [], []
    detail = {}

    # ---------- 1. 历史估值分位（刻度） ----------
    vp = vp if vp is not None else F.valuation_percentile(code)
    detail['percentile'] = vp
    if vp:
        for metric, label in (('PE_TTM', 'PE(TTM)'), ('PB_MRQ', 'PB'),
                              ('PS_TTM', 'PS(TTM)'), ('PCF_OCF_TTM', 'PCF(经营现金流)'),
                              ('PEG_CAR', 'PEG')):
            m = vp.get(metric)
            if not m:
                continue
            win, w = None, None
            for yr in ('10', '5', '3'):
                if m.get(yr):
                    win, w = yr, m[yr]
                    break
            if not w:
                continue
            p = w.get('pctl')
            # 失真护栏：分母趋零导致的极端倍数，分位不可信，直接标为不可用
            if _is_distorted(metric, w.get('value')):
                gaps.append({
                    'key': 'pctl_%s_distorted' % metric,
                    'label': '%s 分位' % label,
                    'reason': '%s 当前值 %s，因分母趋零导致倍数失真，'
                              '其历史分位不构成有效刻度，已剔除'
                              % (label, _n(w.get('value'), 2))})
                continue
            zone = _valuation_zone(p)
            facts.append({
                'key': 'pctl_%s_%s' % (metric, win),
                'label': '%s %s年分位' % (label, win),
                'value': p,
                'text': '%s 当前 %s，近 %s 年 %s 分位（区间 %s~%s，中位 %s），处于%s'
                        % (label, _n(w.get('value'), 2), win, _n(p, 1),
                           _n(w.get('min'), 2), _n(w.get('max'), 2),
                           _n(w.get('median'), 2), zone),
                'zone': zone,
                'source': 'RPT_VALUEANALYSIS_DET'})
    else:
        gaps.append({'key': 'val_percentile', 'label': '历史估值分位',
                     'reason': '估值日频序列不可得（可能长期亏损或上市时间短）'})

    # ---------- 2. 相对估值倍数（锚） ----------
    db = T._call('daily_basic', {'ts_code': _ts(code), 'trade_date': _latest_trade_day()},
                 'ts_code,trade_date,pe_ttm,pb,ps_ttm,total_mv,circ_mv,dv_ttm,turnover_rate')
    dbi = db[0] if db else {}
    detail['daily_basic'] = dbi
    mcap = _f(dbi.get('total_mv'))          # 万元
    circ_mv = _f(dbi.get('circ_mv'))
    if mcap:
        detail['mcap_yi'] = round(mcap / 1e4, 2)
        facts.append({'key': 'mcap', 'label': '总市值', 'value': round(mcap / 1e4, 2),
                      'text': '总市值约 %s 亿元（流通市值 %s 亿元）'
                              % (_n(mcap / 1e4, 2),
                                 _n(circ_mv / 1e4, 2) if circ_mv else '—'),
                      'source': 'tushare daily_basic'})
        if circ_mv and mcap:
            facts.append({'key': 'float_ratio', 'label': '流通市值占比',
                          'value': round(circ_mv / mcap * 100, 1),
                          'text': '流通市值占总市值 %s%%' % _n(circ_mv / mcap * 100, 1),
                          'source': '计算'})

    # 股息率 → DDM 适用性
    dv = _f(dbi.get('dv_ttm'))
    detail['dv_ttm'] = dv
    if dv is not None:
        ddm_ok = dv >= 1.5
        facts.append({'key': 'dv_ttm', 'label': '股息率(TTM)', 'value': dv,
                      'text': '股息率(TTM) %s%%，%s'
                              % (_n(dv, 2),
                                 '满足 DDM 适用条件（稳定分红>1.5%）' if ddm_ok
                                 else '不满足 DDM 适用条件（分红过低，DDM 不适用）'),
                      'source': 'tushare daily_basic'})

    # EV/EBITDA（用 tushare fina_indicator）
    fi_rows = T._call('fina_indicator', {'ts_code': _ts(code)},
                       'ts_code,ann_date,end_date,ebit,ebitda,netdebt,interestdebt,'
                       'debt_to_assets,ocf_to_or,grossprofit_margin')
    fi = fi_rows[0] if fi_rows else {}
    detail['fina_indicator'] = fi
    ebitda = _f(fi.get('ebitda'))
    netdebt = _f(fi.get('netdebt'))
    if ebitda and mcap:
        # tushare: total_mv 万元 → 元；netdebt 元
        ev = (mcap * 1e4) + (netdebt or 0)
        ev_ebitda = ev / ebitda
        detail['ev_ebitda'] = round(ev_ebitda, 2)
        facts.append({'key': 'ev_ebitda', 'label': 'EV/EBITDA', 'value': round(ev_ebitda, 2),
                      'text': 'EV/EBITDA 约 %s 倍（EV = 总市值 %s 亿 %s 净债务 %s 亿）'
                              % (_n(ev_ebitda, 2), _n(mcap / 1e4, 2),
                                 '+' if (netdebt or 0) >= 0 else '−',
                                 _n(abs(netdebt or 0) / 1e8, 2)),
                      'source': '计算:tushare fina_indicator + daily_basic'})
    else:
        gaps.append({'key': 'ev_ebitda', 'label': 'EV/EBITDA',
                     'reason': 'EBITDA 或市值不可得（可能取数权限或当期数据缺失）'})

    # ---------- 3. 一致预期与隐含增速（预期反推） ----------
    research = research or {}
    exp = research.get('expectations') or {}
    detail['expectations'] = exp
    if exp.get('eps_this') and exp.get('eps_next'):
        e1, e2 = exp['eps_this'], exp['eps_next']
        g = exp.get('implied_growth')
        facts.append({'key': 'consensus_eps', 'label': '一致预期 EPS',
                      'value': e1.get('mean'),
                      'text': '当年 EPS 一致预期均值 %s（%d 家机构，区间 %s~%s，%s）；'
                              '次年均值 %s，隐含增速 %s%%'
                              % (_n(e1.get('mean'), 3), e1.get('n', 0),
                                 _n(e1.get('min'), 3), _n(e1.get('max'), 3),
                                 e1.get('asof'), _n(e2.get('mean'), 3), _n(g, 1)),
                      'source': '东财研报中心'})
        # 市场隐含增速反推：用 PE 与 PEG
        peg = None
        for m in (vp or {}).get('PEG_CAR', {}).values():
            if m and m.get('value') is not None:
                peg = m['value']
                break
        if peg and peg > 0:
            implied_g = 100.0 / peg
            facts.append({'key': 'implied_growth', 'label': '市场隐含增速(PEG反推)',
                          'value': round(implied_g, 1),
                          'text': '当前 PEG %s，对应市场隐含增速约 %s%%；'
                                  '与一致预期隐含增速 %s%% %s'
                                  % (_n(peg, 2), _n(implied_g, 1), _n(g, 1),
                                     '基本吻合' if abs(implied_g - (g or 0)) <= 8
                                     else '存在差距'),
                          'source': '计算:RPT_VALUEANALYSIS_DET + 研报预期'})
    else:
        gaps.append({'key': 'consensus', 'label': '一致预期 EPS',
                     'reason': '研报覆盖不足，无可用一致预期数据'})

    # ---------- 4. 绝对估值：DCF 敏感性区间 ----------
    dcf_info = _dcf_block(code, fi, mcap)
    if dcf_info:
        detail['dcf'] = dcf_info
        facts.append({'key': 'dcf_range', 'label': 'DCF 内在价值区间',
                      'value': dcf_info.get('mid'),
                      'text': '简化两阶段 DCF 内在价值区间 %s~%s 亿元（中值 %s 亿），'
                              '对应 %s 倍现价中枢；假设：WACC %s%%、前10年增速 %s%%、'
                              '永续增长 %s%%，敏感性已做 ±20%% 扰动'
                              % (_n(dcf_info.get('low'), 1), _n(dcf_info.get('high'), 1),
                                 _n(dcf_info.get('mid'), 1),
                                 _n(dcf_info.get('mid_to_mcap'), 2),
                                 _n(dcf_info.get('wacc'), 1),
                                 _n(dcf_info.get('growth'), 1),
                                 _n(dcf_info.get('terminal_g'), 1)),
                      'source': '计算:简化两阶段FCFF折现'})
    else:
        gaps.append({'key': 'dcf', 'label': 'DCF 内在价值',
                     'reason': '自由现金流为负或关键参数不可得，DCF 当前不适用（转用 EV/EBITDA + 分位）'})

    # ---------- 5. 估值方法适用性 ----------
    facts.append({'key': 'method_fit', 'label': '估值方法适用性',
                  'value': None,
                  'text': _method_fit(code, dv, ebitda, fi, vp),
                  'source': '判定'})

    return {'facts': facts, 'gaps': gaps, 'detail': detail}


def _method_fit(code, dv, ebitda, fi, vp):
    """按公司类型给出方法适用性组合。"""
    seg = ''
    try:
        mb = F.main_business_detail(code, 1)
        if mb:
            seg = str(mb[0].get('MAINOP_TYPE') or '')
    except Exception:
        pass
    is_bank = '银行' in code_names(code)
    parts = []
    if is_bank:
        parts.append('银行/金融：首选 P/B、股息率、DDM；PEG 不适用')
    else:
        parts.append('绝对估值：DDM %s；DCF %s'
                     % ('适用（股息率>1.5%）' if (dv or 0) >= 1.5 else '不适用（分红过低）',
                        '可用' if ebitda else '受限（EBITDA/FCF 不可得）'))
        if vp and vp.get('PE_TTM'):
            parts.append('相对估值：PE/PB/PS 分位 + PEG')
        parts.append('交叉验证：EV/EBITDA %s'
                     % ('可用' if ebitda else '不可得'))
    return '；'.join(parts)


_CODE_NAMES = {}


def code_names(code):
    global _CODE_NAMES
    if not _CODE_NAMES:
        try:
            rows = dc_all('RPT_VALUEANALYSIS_DET', '(TRADE_DATE=\'%s\')' % _latest_trade_day(),
                          'SECURITY_CODE,SECURITY_NAME_ABBR', max_pages=3)
            for r in rows:
                _CODE_NAMES[r.get('SECURITY_CODE')] = r.get('SECURITY_NAME_ABBR') or ''
        except Exception:
            pass
    return _CODE_NAMES.get(code, '')


def _dcf_block(code, fi, mcap):
    """简化两阶段 DCF。缺 FCF 则返回 None。"""
    cf_rows = F.cashflow(code, 4)
    ocf = capex = None
    for r in cf_rows:
        o = _f(r.get('NETCASH_OPERATE') or r.get('NETCASH_OPERATE_TTM'))
        c = _f(r.get('CONSTRUCT_LONG_ASSET') or r.get('CONSTRUCT_LONG_ASSET_TTM'))
        if o is not None:
            ocf = o
            if c is not None:
                capex = c
            break
    if not ocf or ocf <= 0:
        return None
    fcf = ocf - (capex or 0)
    if fcf <= 0:
        return None
    wacc_info = F._simplified_wacc(code, {})
    wacc = wacc_info.get('wacc') or 10.0
    wacc = max(wacc, 6.0) / 100.0
    # 增长：用 ROE/ROIC 保守取 6%
    growth = 0.06
    g = 0.03
    out = {}
    for tag, gw, ww in (('low', growth * 0.8, wacc * 1.2),
                        ('mid', growth, wacc),
                        ('high', growth * 1.2, wacc * 0.8)):
        ev = _dcf(fcf, gw, ww)
        if ev:
            out[tag] = round(ev / 1e8, 1)
    if 'mid' not in out:
        return None
    if mcap:
        out['mid_to_mcap'] = round(out['mid'] / (mcap / 1e4), 2)
    out['wacc'] = round(wacc * 100, 2)
    out['growth'] = round(growth * 100, 1)
    out['terminal_g'] = round(g * 100, 1)
    out['fcf_yi'] = round(fcf / 1e8, 2)
    out['low'] = out.get('low', out['mid'])
    out['high'] = out.get('high', out['mid'])
    return out


def _latest_trade_day():
    import time
    d = time.strftime('%Y%m%d')
    # 往前找，最多 10 天
    for i in range(0, 12):
        t = time.localtime(time.time() - i * 86400)
        ds = time.strftime('%Y%m%d', t)
        if time.strftime('%w', t) in ('1', '2', '3', '4', '5'):
            return ds
    return d


# ================================================================== 二、风险与安全
RED_FLAGS = [
    # (key, label, 计算键, 阈值, 比较方向, 说明, 单位)
    # 单位列是 2026-10-20 补的：这些指标量纲不统一（% / 倍 / 个百分点），
    # 以前正文不写单位 → 页面出现「商誉占比 0.60，未触发阈值 30.00」这种看着量纲错位的文本，
    # critic 还把它当成真 bug 报了（误报）。现在按指标逐个标单位。
    ('ocf_np', '盈利质量', 'ocf_np', 0.6, 'lt', '经营现金流/净利润低于 0.6，利润含金量不足', '倍'),
    ('goodwill_ratio', '商誉占比', 'goodwill_ratio', 30, 'gt', '商誉/净资产超过 30%，减值敞口大', '%'),
    ('debt_ratio', '杠杆水平', 'debt_ratio', 60, 'gt', '资产负债率超过 60%', '%'),
    ('interest_cover', '利息覆盖', 'interest_cover', 3, 'lt', '利息保障倍数低于 3 倍', '倍'),
    ('cash_short_debt', '短债覆盖', 'cash_short_debt', 0.5, 'lt', '货币资金/一年内到期有息负债低于 0.5', '倍'),
    ('recv_gap', '应收堆积', 'recv_gap', 20, 'gt', '应收增速超出营收增速 20 个百分点以上', '个百分点'),
    ('inv_gap', '存货堆积', 'inv_gap', 20, 'gt', '存货增速超出营收增速 20 个百分点以上', '个百分点'),
    ('gross_margin_drop', '毛利率承压', 'gross_margin_drop', -3, 'lt', '单期毛利率同比下滑超过 3 个百分点', '个百分点'),
    ('capex_ratio', '资本开支失控', 'capex_ratio', 10, 'gt', '资本开支/营收超过 10%', '%'),
    ('fcf_negative', '自由现金流为负', 'fcf_negative', 1, 'eq', '经营现金流为负', ''),
]


def build_risk_block(code, research=None, extra=None, fin=None, mr=None):
    """风险与安全模块。返回 {'facts': [...], 'flags': [...], 'gaps': [...], 'detail': {...}}"""
    facts, gaps, flags = [], [], []
    detail = {}

    # ---------- 1. 市场与宏观风险 ----------
    mr = mr if mr is not None else F.market_risk(code)
    detail['market_risk'] = mr
    if mr.get('available'):
        beta = mr.get('beta')
        facts.append({'key': 'beta', 'label': 'Beta', 'value': beta,
                      'text': 'Beta 约 %s（%s），%s'
                              % (_n(beta, 2), mr.get('beta_source'),
                                 '下跌时放大系统风险' if (beta or 1) > 1.1 else
                                 ('波动低于大盘' if (beta or 1) < 0.9 else '与大盘接近')),
                      'source': '计算:60日回归沪深300'})
        facts.append({'key': 'mdd', 'label': '区间最大回撤', 'value': mr.get('max_drawdown'),
                      'text': '近 %d 个交易日最大回撤 %s%%，年化波动率 %s%%'
                              % (mr.get('days', 0), _n(abs(mr.get('max_drawdown') or 0), 1),
                                 _n(mr.get('volatility_ann'), 1)),
                      'source': '计算:qt.gtimg.cn'})
    else:
        gaps.append({'key': 'market_risk', 'label': '市场风险',
                     'reason': mr.get('na_reason') or '行情数据不足'})

    # ---------- 2. 财务红旗扫描 ----------
    bal = F.balance(code, 4)
    cfl = F.cashflow(code, 4)
    fin = fin or {}
    if not fin:
        # 2026-10-20 修：之前调用方（api.py / __main__）都不传 fin，
        # 于是 盈利质量/杠杆/利息覆盖/短债覆盖 4 条 RED_FLAGS 的读数全是 None，
        # 红旗扫描里这 4 条从来没生效过（页面看不出来，因为是 None 不是 0）。
        # 现在自己取财务主表，取不到就当没有（不补数）。
        try:
            fin = F.mainfin(code)
            fin = fin[0] if fin else {}
        except Exception:
            fin = {}
    metrics = _risk_metrics(code, bal, cfl, fin)
    detail['metrics'] = metrics

    for key, label, ck, thr, direction, desc, unit in RED_FLAGS:
        v = metrics.get(ck)
        if v is None:
            continue
        hit = (v < thr) if direction == 'lt' else (v > thr) if direction == 'gt' else (v == thr)
        u = unit or ''
        if ck == 'ocf_np':
            # 净现比 = 经营现金流 / 归母净利。归母净利为负时这个比值的符号没有意义
            # （亏损公司现金流为正反而是好事），不能拿来判「利润含金量不足」。
            npp = metrics.get('parent_net_profit')
            if npp is not None and npp <= 0:
                gaps.append({'key': 'ocf_np', 'label': '盈利质量',
                             'reason': '报告期归母净利为 %s 亿元，净现比在亏损状态下无意义，'
                                       '不据此判定利润含金量' % _n(npp / 1e8, 2)})
                continue
        if hit:
            if ck == 'fcf_negative':
                # 哨兵值 1 没有信息量，正文不能写「当前 1.00（阈值 1.00）」→ 改写真实经营现金流
                ocf_v = metrics.get('ocf')
                real = ('最近一期经营活动现金流净额 %s 亿元（为负），自由现金流随之为负'
                        % _n(ocf_v / 1e8, 2)) if ocf_v is not None else '最近一期经营活动现金流净额为负'
                flags.append({'key': key, 'label': label, 'value': ocf_v, 'threshold': thr,
                              'direction': direction, 'status': '已兑现',
                              'text': '%s：%s' % (label, real)})
                continue
            flags.append({'key': key, 'label': label, 'value': v, 'threshold': thr,
                          'direction': direction, 'status': '已兑现',
                          'text': '%s：当前 %s%s（阈值 %s%s，%s）'
                                  % (label, _n(v, 2), u, _n(thr, 2), u, desc)})
        else:
            facts.append({'key': 'ok_%s' % key, 'label': '%s（正常）' % label, 'value': v,
                          'text': '%s %s%s，未触发阈值 %s%s' % (label, _n(v, 2), u, _n(thr, 2), u),
                          'source': '计算'})

    # ---------- 3. 安全边际量化 ----------
    mcap = (_f((extra or {}).get('total_market_cap')) or 0)
    if not mcap:
        db = T._call('daily_basic', {'ts_code': _ts(code), 'trade_date': _latest_trade_day()},
                     'ts_code,total_mv')
        mcap = (_f(db[0].get('total_mv')) or 0) * 1e4 if db else 0
    cash = metrics.get('cash')
    ibd = metrics.get('interest_debt')
    netcash = (cash - ibd) if (cash is not None and ibd is not None) else None
    if netcash is not None and mcap > 0:
        ratio = netcash / mcap * 100
        detail['net_cash_to_mcap'] = round(ratio, 1)
        facts.append({'key': 'net_cash_ratio', 'label': '净现金/市值', 'value': round(ratio, 1),
                      'text': '净现金 %s 亿元，占总市值 %s%%，%s'
                              % (_n(netcash / 1e8, 2), _n(ratio, 1),
                                 '缓冲较厚（>20%）' if ratio > 20 else
                                 ('中等（5%~20%）' if ratio > 5 else '缓冲有限（<5%）')),
                      'source': '计算:资产负债表 + daily_basic'})

    # 历史分位下行空间
    vp = F.valuation_percentile(code)
    m5 = ((vp or {}).get('PE_TTM') or {}).get('5') or ((vp or {}).get('PE_TTM') or {}).get('3')
    if m5 and m5.get('value') and m5.get('min'):
        cur, lo = m5['value'], m5['min']
        if cur > 0 and lo > 0:
            down = (1 - lo / cur) * 100
            detail['downside_to_min'] = round(down, 1)
            facts.append({'key': 'downside', 'label': '下行空间(至历史最低分位)',
                          'value': round(down, 1),
                          'text': 'PE(TTM) 当前 %s，历史区间最低 %s，'
                                  '若回到历史最低位对应下行空间约 %s%%'
                                  % (_n(cur, 2), _n(lo, 2), _n(down, 1)),
                          'source': '计算:RPT_VALUEANALYSIS_DET'})
        med = m5.get('median')
        if med and cur > 0:
            facts.append({'key': 'to_median', 'label': '回归中位空间', 'value': round((1 - med / cur) * 100, 1),
                          'text': 'PE(TTM) 历史中位 %s，回到中位对应 %s%% 空间'
                                  % (_n(med, 2), _n((1 - med / cur) * 100, 1)),
                          'source': '计算:RPT_VALUEANALYSIS_DET'})

    # ---------- 4. 流动性与拥挤 ----------
    db = T._call('daily_basic', {'ts_code': _ts(code), 'trade_date': _latest_trade_day()},
                 'ts_code,trade_date,turnover_rate,volume_ratio,total_mv,circ_mv')
    dbi = db[0] if db else {}
    tr = _f(dbi.get('turnover_rate'))
    detail['turnover_rate'] = tr
    if tr is not None:
        facts.append({'key': 'turnover', 'label': '换手率', 'value': tr,
                      'text': '最新换手率 %s%%，%s'
                              % (_n(tr, 2),
                                 '流动性充足' if tr >= 1 else '流动性偏弱，注意冲击成本'),
                      'source': 'tushare daily_basic'})
    drows = T._call('daily', {'ts_code': _ts(code), 'trade_date': _latest_trade_day()},
                    'ts_code,amount')
    amt = _f(drows[0].get('amount')) if drows else None   # 千元
    if amt:
        detail['amount_yi'] = round(amt / 1e5, 2)
        facts.append({'key': 'amount', 'label': '日成交额', 'value': round(amt / 1e5, 2),
                      'text': '最新交易日成交额约 %s 亿元' % _n(amt / 1e5, 2),
                      'source': 'tushare daily'})

    # ---------- 5. 治理与解禁 ----------
    sf = T._call('share_float', {'ts_code': _ts(code)}, 'ts_code,float_date,float_share,ratio')
    upcoming = [x for x in (sf or [])
                if str(x.get('float_date') or '') >= _latest_trade_day()[:4]]
    upcoming.sort(key=lambda x: str(x.get('float_date')))
    if upcoming:
        nxt = upcoming[0]
        detail['next_unlock'] = nxt
        facts.append({'key': 'unlock', 'label': '限售解禁', 'value': str(nxt.get('float_date')),
                      'text': '最近一次限售解禁日 %s，解禁股数 %s 万股'
                              % (str(nxt.get('float_date'))[:10], _n(nxt.get('float_share'), 0)),
                      'source': 'tushare share_float'})

    # ---------- 6. 行业与竞争风险（外部深度数据） ----------
    research = research or {}
    ex = research.get('extracted') or {}
    detail['research_coverage'] = RS.coverage_level(research)
    if ex.get('risks'):
        for i, it in enumerate(ex.get('risks')[:6]):
            facts.append({'key': 'res_risk_%d' % i, 'label': '研报明示风险', 'value': None,
                          'text': it.get('risk') or '', 'source': '券商研报正文'})
    if ex.get('competition'):
        for i, it in enumerate(ex.get('competition')[:4]):
            facts.append({'key': 'res_comp_%d' % i, 'label': '竞争格局要点', 'value': None,
                          'text': it.get('point') or '', 'source': '券商研报正文'})
    if not ex.get('risks') and not ex.get('competition'):
        gaps.append({'key': 'industry_risk', 'label': '行业与竞争风险',
                     'reason': '研报正文未提供可回验的竞争格局/风险条目'})

    # ---------- 7. 估值与预期风险 ----------
    if ex.get('valuation_view'):
        for i, it in enumerate(ex.get('valuation_view')[:3]):
            facts.append({'key': 'res_val_%d' % i, 'label': '研报估值观点', 'value': None,
                          'text': it.get('point') or '', 'source': '券商研报正文'})

    return {'facts': facts, 'flags': flags, 'gaps': gaps, 'detail': detail}


def _risk_metrics(code, bal, cfl, fin):
    """算出红旗扫描需要的全部读数。取不到就是 None（不补数）。"""
    m = {}
    b0 = bal[0] if bal else {}
    b1 = bal[1] if len(bal) > 1 else {}
    c0 = cfl[0] if cfl else {}

    m['debt_ratio'] = _f(fin.get('ZCFZL'))
    m['interest_cover'] = _f(fin.get('INTSTCOVRATE'))
    m['cash_short_debt'] = _f(fin.get('QYCS'))
    # 踩过的坑：主表 NETCASH_OPERATE_PK 是「经营活动现金流净额（元）」，
    # 当成比率去比 0.6 阈值会把「-9200 万」当成「-9200 倍」。比率字段是 NCO_NETPROFIT。
    m['ocf_np'] = _f(fin.get('NCO_NETPROFIT'))
    m['parent_net_profit'] = _f(fin.get('PARENTNETPROFIT'))
    m['gross_margin_drop'] = _f(fin.get('MLL'))

    cash = _f(b0.get('MONETARYFUNDS'))
    m['cash'] = cash
    m['interest_debt'] = F._interest_debt(b0)
    m['net_cash'] = (cash - m['interest_debt']) if cash is not None and m['interest_debt'] is not None else None

    equity = _f(b0.get('TOTAL_EQUITY'))
    gw = _f(b0.get('GOODWILL'))
    if gw is not None and equity and equity > 0:
        m['goodwill_ratio'] = gw / equity * 100

    ocf = _f(c0.get('NETCASH_OPERATE') or c0.get('NETCASH_OPERATE_TTM'))
    m['fcf_negative'] = 1 if (ocf is not None and ocf < 0) else None
    m['ocf'] = ocf

    capex = _f(c0.get('CONSTRUCT_LONG_ASSET') or c0.get('CONSTRUCT_LONG_ASSET_TTM'))
    rev = _f(fin.get('TOTALOPERATEREVE'))
    if capex and rev and rev > 0:
        m['capex_ratio'] = capex / rev * 100

    # 应收/存货增速 vs 营收增速
    recv0, recv1 = _f(b0.get('ACCOUNTS_RECE')), _f(b1.get('ACCOUNTS_RECE'))
    inv0, inv1 = _f(b0.get('INVENTORY')), _f(b1.get('INVENTORY'))
    rev_yoy = _f(fin.get('TOTALOPERATEREVE_YOY'))
    if recv0 and recv1 and rev_yoy is not None:
        m['recv_gap'] = ((recv0 / recv1 - 1) * 100) - rev_yoy
    if inv0 and inv1 and rev_yoy is not None:
        m['inv_gap'] = ((inv0 / inv1 - 1) * 100) - rev_yoy

    return m


if __name__ == '__main__':
    import sys
    import json
    sys.path.insert(0, '.')
    code = sys.argv[1] if len(sys.argv) > 1 else '688508'
    import api as _api
    r = RS.get_research(code, '20261020', _api.DS_KEY)
    v = build_valuation_block(code, research=r)
    k = build_risk_block(code, research=r, fin=None)
    print('=== 估值与预期 ===')
    for f in v['facts']:
        print(' -', f['label'], '|', f['text'])
    for g in v['gaps']:
        print(' ! GAP', g['label'], g['reason'])
    print('=== 风险与安全 ===')
    for f in k['flags']:
        print(' ! FLAG', f['text'])
    for f in k['facts'][:14]:
        print(' -', f['label'], '|', f['text'])
    for g in k['gaps']:
        print(' ! GAP', g['label'], g['reason'])
