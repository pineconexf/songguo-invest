#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
松果基金五维排名数据构建脚本（V2 批量版）
==========================================
数据源：Tushare Pro（token 在 ~/AppData/Local/hermes/.env 的 TUSHARE_API_KEY）
通道：http://api.tushare.pro/dataapi/<api>（实测 https 被墙，http 通）
策略：全量接口按交易日批量拉（fund_nav 10500只/次、fund_share 2000只/次、fund_manager 5000条/次）
      —— 从逐只 65000 次调用压缩到约 300 次，几分钟完成

口径（与 fund-scorecard.astro 页面 scoreFive() 完全一致）：
  收益 30 分：近1年 0%→20% 线性
  回撤 25 分：近1年最大回撤 5%→15% 反向线性（≤5% 满分）
  费率 15 分：管理费+托管费 0.1%→0.6% 反向线性（近似，页面注明）
  规模 20 分：20-300 亿满分；>300 每5亿扣1分；<20 按比例
  经理 10 分：现任经理最长任职 3→7 年线性

分类（合同类型近似）：偏股=股票型、固收+=混合型、纯债=债券型
过滤：场外(market=O)、成立满1年、规模≥1亿、排除 ETF 联接

输出：D:/pineconeinvestfiles/松果投资体系网站/01_网站开发/src/data/fund_ranking.json
"""
import os
import json
import re
import time
import math
import datetime as dt
import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser('~/AppData/Local/hermes/.env'))
TOKEN = os.environ.get('TUSHARE_API_KEY', '')
API = 'http://api.tushare.pro/dataapi/'
OUT_FILE = r'D:/pineconeinvestfiles/松果投资体系网站/01_网站开发/src/data/fund_ranking.json'

CALLS = 0


def q(api, params, fields=''):
    """tushare 直连查询（http 通道），每次调用后 sleep 0.3s 保 200/min 限速"""
    global CALLS
    CALLS += 1
    r = requests.post(API + api, json={'api_name': api, 'token': TOKEN, 'params': params, 'fields': fields}, timeout=30)
    b = r.json()
    if b.get('code') != 0:
        raise RuntimeError(f'{api} 失败: {b.get("msg")}')
    d = b['data']
    time.sleep(0.3)
    return [dict(zip(d['fields'], item)) for item in d['items']]


def q_all(api, params, fields='', page_size=5000):
    """分页全量拉取"""
    rows, offset = [], 0
    while True:
        p = dict(params)
        p['offset'] = offset
        p['limit'] = page_size
        batch = q(api, p, fields)
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < page_size:
            break
        time.sleep(0.1)
    return rows


def linear(v, lo, hi, direction=1):
    """与页面 linear() 一致：None/NaN→0 分"""
    if v is None or isinstance(v, str) or math.isnan(v):
        return 0.0
    v = float(v)
    if direction == 1:
        if v >= hi: return 100.0
        if v <= lo: return 0.0
        return (v - lo) / (hi - lo) * 100
    else:
        if v <= lo: return 100.0
        if v >= hi: return 0.0
        return (hi - v) / (hi - lo) * 100


def score_five(r1y, mdd1y, fee_pct, size_y, mgr_years):
    """与页面 scoreFive() 完全一致"""
    s_ret = linear(r1y, 0, 20, 1)
    s_mdd = linear(mdd1y, 5, 15, -1)
    s_fee = linear(fee_pct, 0.1, 0.6, -1)
    if size_y is None or math.isnan(size_y):
        s_size = 0.0
    elif 20 <= size_y <= 300:
        s_size = 100.0
    elif size_y > 300:
        s_size = max(0.0, 100 - (size_y - 300) / 5)
    else:
        s_size = max(0.0, size_y / 20 * 100)
    s_mgr = linear(mgr_years, 3, 7, 1)
    total = s_ret * 0.3 + s_mdd * 0.25 + s_fee * 0.15 + s_size * 0.2 + s_mgr * 0.1
    grade = '可入池' if total >= 75 else '候选' if total >= 60 else '谨慎' if total >= 45 else '不达标'
    return round(total, 1), grade, round(s_ret), round(s_mdd), round(s_fee), round(s_size), round(s_mgr)


def main():
    t0 = time.time()

    # ---------- ① fund_basic 全量 ----------
    print('① fund_basic 全量列表...')
    funds = q_all('fund_basic', {}, 'ts_code,name,fund_type,m_fee,c_fee,found_date,status,market')
    print(f'   全市场 {len(funds)} 只')

    # 分类过滤：场外 + 三类 + L 状态 + 成立满1年 + 排除 ETF 联接
    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=365)).strftime('%Y%m%d')
    cats = {'偏股榜': '股票型', '固收+榜': '混合型', '纯债榜': '债券型'}
    candidates = {}
    for cname, ftype in cats.items():
        picks = [f for f in funds
                 if f.get('fund_type') == ftype
                 and f.get('market') == 'O'
                 and f.get('status') == 'L'
                 and (f.get('found_date') or '99999999') <= cutoff
                 and not re.search(r'ETF联接', f.get('name', '') or '')]
        candidates[cname] = picks
        print(f'   {cname}（{ftype}）: {len(picks)} 只')

    # ---------- ② fund_nav 按交易日批量拉近一年 ----------
    print('② fund_nav 批量拉近一年交易日净值...')
    # 先拿交易日列表：用 fund_nav 最后一个交易日 + 往前 370 天每个交易日
    # 简化：直接用 fund_nav 的 nav_date 参数从最近交易日逐日向前
    nav_by_code = {}  # ts_code -> [(date, adj_nav), ...] 最新在前
    # 从今天往前枚举日期，逐日拉（只拉工作日，拿到 10500 只全量）
    d = today
    days_fetched = 0
    while days_fetched < 240:  # 约一年交易日（250 左右）
        date_s = d.strftime('%Y%m%d')
        try:
            rows = q('fund_nav', {'nav_date': date_s, 'market': 'O'}, 'ts_code,adj_nav,unit_nav')
            if rows:
                for r in rows:
                    ts = r['ts_code']
                    try:
                        adj = float(r['adj_nav'])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if adj > 0:
                        nav_by_code.setdefault(ts, []).append((date_s, adj))
                days_fetched += 1
                if days_fetched % 20 == 0:
                    print(f'   已拉 {days_fetched} 个交易日，覆盖 {len(nav_by_code)} 只基金')
        except Exception as e:
            pass  # 非交易日/接口波动，跳过
        d -= dt.timedelta(days=1)
        if (dt.date.today() - d).days > 400:
            print('   超 400 天兜底，停止')
            break
    print(f'   完成: {days_fetched} 个交易日, {len(nav_by_code)} 只基金有净值')

    # ---------- ③ fund_share 按季末批量 ----------
    print('③ fund_share 批量拉最近两个季末份额...')
    share_rows = []
    for qdate in ['20260630', '20260331']:
        try:
            batch = q_all('fund_share', {'trade_date': qdate, 'market': 'O'}, 'ts_code,fd_share', page_size=2000)
            share_rows.extend(batch)
            print(f'   {qdate}: {len(batch)} 条')
        except Exception as e:
            print(f'   {qdate} 失败: {e}')
    share_by_code = {r['ts_code']: (qdate, float(r['fd_share'])) for r in share_rows if r.get('fd_share')}

    # ---------- ④ fund_manager 全量（分页） ----------
    print('④ fund_manager 全量拉取...')
    mgr_rows = q_all('fund_manager', {}, 'ts_code,name,begin_date,end_date', page_size=5000)
    print(f'   经理记录: {len(mgr_rows)} 条')
    # 现任（end_date 空格）按基金取最长任职
    mgr_by_code = {}
    for m in mgr_rows:
        if str(m.get('end_date') or '').strip():
            continue  # 已离任
        ts = m.get('ts_code', '')
        began = m.get('begin_date') or ''
        if not ts or not began or len(began) != 8:
            continue
        try:
            years = max(0, (today - dt.datetime.strptime(began, '%Y%m%d').date()).days / 365.0)
        except ValueError:
            continue
        if ts not in mgr_by_code or years > mgr_by_code[ts]:
            mgr_by_code[ts] = years

    # ---------- ⑤ 每只基金组装五维 + 打分 ----------
    print('⑤ 组装五维打分...')
    results = {}
    n_rej_abnormal = 0  # 复权异常剔除计数
    for cname, picks in candidates.items():
        n_ok = 0
        for f in picks:
            ts = f['ts_code']
            navs = nav_by_code.get(ts)
            if not navs or len(navs) < 60:  # 至少 60 个交易日（约3个月），防止刚成立假数据
                continue
            # 数据质量门控：单日 adj_nav 跳变 >25% ⇒ 复权异常（份额折算/复权因子调整），剔除
            # 例证：20260602 金信民兴债 adj +192.5% / unit 仅 +0.04%（tushare 复权因子批量调整）
            navs.sort(key=lambda x: x[0])  # 升序
            abnormal = False
            for i in range(1, len(navs)):
                d = navs[i][1] / navs[i - 1][1] - 1
                if abs(d) > 0.25:
                    abnormal = True
                    break
            if abnormal:
                n_rej_abnormal += 1  # 复权异常，剔除（不参与排名，口径公开）
                continue
            latest = navs[-1][1]
            # 找一年前的点位
            target = (dt.datetime.strptime(navs[-1][0], '%Y%m%d') - dt.timedelta(days=365)).strftime('%Y%m%d')
            past = None
            for dte, v in navs:
                if dte >= target:
                    past = v
                    break
            if past is None or past <= 0:
                continue
            r1y = (latest / past - 1) * 100
            # 最大回撤
            peak, mdd = navs[0][1], 0.0
            for _, v in navs:
                if v > peak:
                    peak = v
                dd = (peak - v) / peak * 100
                if dd > mdd:
                    mdd = dd
            # 规模：最新季末份额 × 最新净值
            shr = share_by_code.get(ts)
            if not shr:
                continue
            size_y = shr[1] * latest / 10000  # 万份 × 元/份 /10000 = 亿元
            if size_y < 1:
                continue  # 微型基金排除
            # 经理
            mgr_years = mgr_by_code.get(ts)
            if mgr_years is None:
                continue
            fee = float(f.get('m_fee', 0) or 0) + float(f.get('c_fee', 0) or 0)
            total, grade, s_ret, s_mdd, s_fee, s_size, s_mgr = score_five(r1y, mdd, fee, size_y, mgr_years)
            code = ts.replace('.OF', '')
            results[cname + '|' + code] = {
                'code': code, 'name': f['name'], 'type': f.get('fund_type'),
                'r1y': round(r1y, 2), 'mdd': round(mdd, 2),
                'fee': round(fee, 3), 'size': round(size_y, 1), 'mgr': round(mgr_years, 1),
                'total': total, 'grade': grade,
                's_ret': s_ret, 's_mdd': s_mdd, 's_fee': s_fee, 's_size': s_size, 's_mgr': s_mgr,
            }
            n_ok += 1
        print(f'   {cname}: 有效 {n_ok} 只')

    # ---------- ⑥ 排序输出 ----------
    print('⑥ 排序输出 JSON...')
    ranking = {
        'meta': {
            'data_date': today.strftime('%Y-%m-%d'),
            'data_source': 'tushare（http 通道批量拉取）',
            'rule': '松果五标准：收益30/回撤25/费率15/规模20/经理10（与 fund-scorecard 页面一致）',
            'category_note': '分类按合同类型（tushare fund_type）近似：偏股=股票型、固收+=混合型、纯债=债券型',
            'fee_note': '费率维度用管理费+托管费近似（tushare 无申购费字段）',
            'filter': '成立满1年、当前规模≥1亿、至少60个交易日净值',
            'excluded': f'复权异常剔除 {n_rej_abnormal} 只（单日 adj_nav 跳变>25%，通常为份额折算/复权因子批量调整，如 20260602 tushare 批量调整日）',
        },
        'categories': [],
    }
    for cname in cats:
        entries = [r for k, r in results.items() if k.startswith(cname + '|')]
        entries.sort(key=lambda x: (-x['total'], -x['r1y']))
        top = entries[:50]
        slim = [{'code': r['code'], 'name': r['name'], 'r1y': r['r1y'], 'mdd': r['mdd'],
                 'fee': r['fee'], 'size': r['size'], 'mgr': r['mgr'], 'total': r['total'], 'grade': r['grade']}
                for r in top]
        ranking['categories'].append({'name': cname, 'count': len(entries), 'top10': slim[:10], 'top50': slim})
        print(f'   {cname}: {len(entries)} 只 | Top1: {top[0]["name"]} {top[0]["total"]}分')

    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(ranking, f, ensure_ascii=False, indent=1)
    print(f'✅ 输出: {OUT_FILE}（总调用 {CALLS} 次，用时 {(time.time() - t0) / 60:.1f} min）')


if __name__ == '__main__':
    main()