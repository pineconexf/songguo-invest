# -*- coding: utf-8 -*-
"""Tushare 取数模块（个股打分卡 v2.1 专用）

**为什么需要它**：v1.1 引擎全部走东财，但 Q1/Q4 必需 Tushare 的两个能力，东财做不到：
  1. `fina_indicator.ann_date` = 真实披露日 → PIT 根基
     （东财 `NOTICE_DATE` 实测为当前重述快照：2024 年报恒为 2026-09-30，不是历史披露日）
  2. `ebit` / `netdebt` → Q4 Greenblatt 两指标的分子与净债务项（东财无对应字段）

**Q2/Q3 仍走东财**（行情天然 PIT，估值分位已校准，不动）。

三条 PIT 铁律（在 build_fin_pool.py 实测踩坑后固化，勿删）：
  1. 只取 ann_date <= 基准日的记录
  2. ann_date < end_date 的记录是预告/快报 → 剔除
  3. 退市股按退市日截断（78.2% 退市股存在退市后披露，不截断等于用退市后信息回测退市前）

量纲铁律（同源）：
  fina_indicator.ebit / netdebt  单位 = 元
  daily_basic.total_mv            单位 = 万元
  balancesheet.total_*            单位 = 元
  → 跨接口比值前必须统一到「元」，未统一会让 EY 算出 33996%（茅台真实 4.03%）
"""
import os
import json
import time
import threading

import requests

TOKEN = (os.environ.get('TUSHARE_API_KEY') or '').strip()
BASE_URL = (os.environ.get('TUSHARE_BASE_URL') or 'https://api.tushare.pro').strip()

_session = requests.Session()
_lock = threading.Lock()
_last_call = [0.0]

# 官方频控：fina_indicator 约 200 次/分钟；留余量串行限速
MIN_INTERVAL = 0.35

FIELDS = ('ts_code,ann_date,end_date,roe,or_yoy,netprofit_yoy,ocf_to_or,'
          'grossprofit_margin,netprofit_margin,debt_to_assets,ebit,ebitda,netdebt,interestdebt')
BS_FIELDS = 'ts_code,ann_date,end_date,total_assets,total_cur_assets,total_cur_liab,total_liab'

_cache = {}
_cache_lock = threading.Lock()


def _throttled():
    with _lock:
        dt = time.time() - _last_call[0]
        if dt < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - dt)
        _last_call[0] = time.time()


def _call(api, params, fields='', retries=3):
    """调 Tushare。失败返回 []，不抛异常——上层据此降级，绝不编数。"""
    if not TOKEN:
        return []
    key = (api, json.dumps(params, sort_keys=True, ensure_ascii=False), fields)
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    out = []
    for attempt in range(retries):
        _throttled()
        try:
            r = _session.post(BASE_URL,
                              data=json.dumps({'api_name': api, 'token': TOKEN,
                                               'params': params, 'fields': fields}),
                              headers={'Content-Type': 'application/json'}, timeout=30)
            j = r.json()
            if j.get('code') == 0 and j.get('data'):
                fl = j['data'].get('fields') or fields.split(',')
                out = [dict(zip(fl, it)) for it in j['data'].get('items', [])]
                break
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))          # 退避后重试，≤3 次（死循环铁律）
    with _cache_lock:
        _cache[key] = out
    return out


def _pit(rows, cutoff, delist_date=None):
    """三条 PIT 铁律的唯一实现点。返回按 ann_date 升序的记录。"""
    out = []
    for r in rows:
        a, e = r.get('ann_date'), r.get('end_date')
        if not a or not e:
            continue
        if a > cutoff:                    # 铁律1：尚未披露
            continue
        if a < e:                         # 铁律2：预告/快报 → 未来函数
            continue
        if delist_date and a > delist_date:   # 铁律3：退市后披露
            continue
        out.append(r)
    out.sort(key=lambda x: x['ann_date'])
    return out


def _normalize(code):
    """Tushare 退市老代码带 T 前缀（T600018.SH），还原为 600018.SH。"""
    c = (code or '').strip().upper()
    return ('T' + c[1:]) if c.startswith('T') else c


def latest(rows, cutoff):
    """取 cutoff 时点上已披露的最新一期记录。"""
    pit = _pit(rows, cutoff)
    return pit[-1] if pit else None


def history(rows, cutoff, n=None):
    pit = _pit(rows, cutoff)
    return pit[-n:] if n else pit


def fina_indicator(code, cutoff, delist_date=None, n=None):
    """Q1 财务特征 + Q4 的 EBIT/净债务。返回 PIT 升序记录列表。"""
    code = _normalize(code)
    rows = _call('fina_indicator', {'ts_code': code, 'ann_date': '19700101'}, FIELDS)
    return _pit(rows, cutoff, delist_date)[-n:] if n else _pit(rows, cutoff, delist_date)


def balancesheet(code, cutoff, delist_date=None, n=None):
    """Q4 投入资本 = total_assets - total_cur_liab。"""
    code = _normalize(code)
    rows = _call('balancesheet', {'ts_code': code, 'ann_date': '19700101'}, BS_FIELDS)
    pit = _pit(rows, cutoff, delist_date)
    return pit[-n:] if n else pit


def daily_basic(code, cutoff, delist_date=None):
    """估值序列（Q3 用东财，此处备用）。返回 {trade_date: row}。"""
    code = _normalize(code)
    rows = _call('daily_basic', {'ts_code': code, 'trade_date': '19700101'},
                 'ts_code,trade_date,pe_ttm,pb,ps_ttm,dv_ttm,total_mv')
    return {r['trade_date']: r for r in rows
            if r.get('trade_date') and r['trade_date'] <= cutoff
            and not (delist_date and r['trade_date'] > delist_date)}


def delist_date_of(code):
    """查退市日；非退市返回 None。"""
    code = _normalize(code)
    rows = _call('stock_basic', {'ts_code': code},
                 'ts_code,name,list_date,delist_date')
    for r in rows:
        if _normalize(r.get('ts_code')) == code:
            return r.get('delist_date') or None
    return None


def health():
    """自检：凭据是否就位、端点是否通。页面诊断用，不泄露 token。"""
    if not TOKEN:
        return {'ok': False, 'reason': 'TUSHARE_API_KEY 未配置'}
    rows = _call('stock_basic', {'list_status': 'D'}, 'ts_code,name,delist_date', retries=1)
    return {'ok': len(rows) > 0, 'delisted': len(rows),
            'endpoint': BASE_URL, 'token_len': len(TOKEN)}