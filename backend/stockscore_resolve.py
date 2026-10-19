# -*- coding: utf-8 -*-
"""股票代码/名称智能解析（2026-10-19）

输入既可以是 6 位代码（600519 / sh600519 / 600519.SH），也可以是名称
（贵州茅台 / 茅台 / 农行 / 隆基绿能 / 锦波生物）。返回 A 股候选列表。

双源降级，任一源可用即可：
  1. 新浪 suggest3 —— 模糊名称匹配最全，支持全称/简称/旧名，覆盖沪深北
  2. 腾讯 smartbox —— 前缀匹配兜底（新浪个别简称在机房 IP 下返回空时接管）
（东财 suggest 对非浏览器请求返回 JSONP + 股吧用户数据，结构不可用，已弃用）

只保留 A 股个股：剔除 ETF/LOF/指数、港股、美股、B 股、新三板。
纯标准库 + requests，无新增依赖。
"""
import re
import unicodedata

import requests

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
TIMEOUT = 8

SINA_URL = 'https://suggest3.sinajs.cn/suggest/type=11&key={}'
SINA_HEADERS = dict(UA, Referer='https://finance.sina.com.cn')
TX_URL = 'https://smartbox.gtimg.cn/s3/?v=2&q={}&t=all'

_MKT = {'sh': '沪A', 'sz': '深A', 'bj': '北交所'}
_UNESC = re.compile(r'\\u([0-9a-fA-F]{4})')

# A 股个股代码段。指数（沪 000xxx / 深 399xxx）、B 股（900/200）、ETF 均在段外，
# 新浪 suggest 对指数也标 type=11，必须按代码段二次过滤，否则「gzmt」会混进绿色煤炭指数。
_SH_CODE = ('600', '601', '603', '605', '688', '689')
_SZ_CODE = ('000', '001', '002', '003', '300', '301')
_BJ_CODE = ('43', '83', '87', '88', '92')


def _is_stock(code, mkt):
    if mkt == '沪A':
        return code.startswith(_SH_CODE)
    if mkt == '深A':
        return code.startswith(_SZ_CODE)
    if mkt == '北交所':
        return code.startswith(_BJ_CODE)
    return code.startswith(_SH_CODE + _SZ_CODE + _BJ_CODE)


def _has_cjk(s):
    return any('\u4e00' <= ch <= '\u9fff' for ch in s)


def _unescape(s):
    """部分源（腾讯/新浪个别响应）把中文返回成 \\uXXXX 转义，统一还原。"""
    return _UNESC.sub(lambda m: chr(int(m.group(1), 16)), s or '')


def _clean(q):
    """归一化：全角转半角、去首尾空白、压缩内部空白。"""
    s = unicodedata.normalize('NFKC', str(q or '')).strip()
    return re.sub(r'\s+', '', s)


def _decode(resp):
    for enc in ('gbk', 'utf-8'):
        try:
            return resp.content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return resp.content.decode('utf-8', 'ignore')


def _mk(code, name, market, alias=''):
    return {'code': code, 'name': _unescape(name).strip(), 'market': market,
            'alias': _unescape(alias).strip()}


def _from_sina(q):
    """var suggestvalue="农业银行,11,601288,sh601288,农业银行,,农业银行,99,1,ESG,,;..." """
    r = requests.get(SINA_URL.format(requests.utils.quote(q)),
                     headers=SINA_HEADERS, timeout=TIMEOUT)
    txt = _decode(r)
    m = re.search(r'suggestvalue="([^"]*)"', txt)
    if not m or not m.group(1):
        return []
    out = []
    for item in m.group(1).split(';'):
        f = item.split(',')
        if len(f) < 5 or f[1] != '11':          # 11 = A 股个股
            continue
        code = f[2].strip()
        if not re.match(r'^\d{6}$', code):
            continue
        full = (f[3] or '').strip()             # sh601288
        mkt = _MKT.get(full[:2].lower(), '')
        if not _is_stock(code, mkt):
            continue
        alias = f[11].strip() if len(f) > 11 else ''
        # 代码查询时 f[0] 是 "sh600519"，f[4] 才是名称；名称查询时两者相同
        name = (f[4] or '').strip() or (f[0] or '').strip()
        out.append(_mk(code, name, mkt, alias))
    return out


def _from_tx(q):
    """v_hint="sh~601012~隆基绿能~ljln~GP-A^sz~002363~隆基机械~ljjx~GP-A" """
    r = requests.get(TX_URL.format(requests.utils.quote(q)),
                     headers=UA, timeout=TIMEOUT)
    txt = _decode(r)
    m = re.search(r'v_hint="([^"]*)"', txt)
    if not m or m.group(1) in ('', 'N'):
        return []
    out = []
    for item in m.group(1).split('^'):
        f = item.split('~')
        if len(f) < 5 or not f[4].startswith('GP-A'):
            continue
        code = f[1].strip()
        if not re.match(r'^\d{6}$', code):
            continue
        mkt = _MKT.get(f[0].lower(), '')
        if not _is_stock(code, mkt):
            continue
        out.append(_mk(code, f[2].strip(), mkt))
    return out


def _rank(cands, q):
    """精确名 > 前缀 > 包含 > 其他；同档保持来源顺序（新浪优先）。"""
    def key(c):
        nm = c['name'] or ''
        if nm == q:
            return 0
        if c.get('alias') and c['alias'] == q:
            return 1
        if nm.startswith(q):
            return 2
        if q in nm:
            return 3
        if c.get('alias') and q in c['alias']:
            return 4
        return 5
    return sorted(cands, key=key)


def resolve(q, limit=8):
    """返回 {'query', 'kind', 'exact', 'candidates': [...]}。

    kind: 'code' = 输入本身是代码；'name' = 按名称解析。
    exact: 第一个候选是否与输入严格对应（前端可直接跳转，不必让用户选）。
    """
    raw = _clean(q)
    if not raw:
        return {'query': '', 'kind': 'empty', 'exact': False, 'candidates': [], 'errors': []}

    errors = []
    digits = re.sub(r'\D', '', raw)
    looks_code = bool(re.match(r'^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$', raw, re.I))

    # ---------- 代码直通 ----------
    if looks_code:
        code = digits[:6]
        m = re.match(r'^(sh|sz|bj)', raw, re.I) or re.search(r'\.(sh|sz|bj)$', raw, re.I)
        want = _MKT.get(m.group(1).lower(), '') if m else ''
        name, mkt = '', want
        for fn in (_from_sina, _from_tx):
            try:
                hits = [c for c in fn(code) if c['code'] == code]
            except Exception as e:
                errors.append(f'{fn.__name__}: {type(e).__name__}')
                continue
            if hits:
                hits.sort(key=lambda c: 0 if c['market'] == want else 1)
                name, mkt = hits[0]['name'], hits[0]['market']
                break
        return {'query': raw, 'kind': 'code', 'exact': True,
                'candidates': [_mk(code, name, mkt)], 'errors': errors}

    # ---------- 名称解析 ----------
    # 纯字母（拼音）不做解析：新浪对拼音的排序不可靠，常把中信银行排在招商银行前，
    # 宁可明确提示「请输入中文名称」，也不给用户一个错的候选。
    if not _has_cjk(raw):
        return {'query': raw, 'kind': 'name', 'exact': False, 'hint': 'latin',
                'candidates': [], 'errors': errors}
    # 逐源降级：新浪覆盖最全（全称/简称/旧名/沪深北），命中即返回；
    # 东财、腾讯只在新浪失败时兜底，避免每查一次打三个外部接口。
    for fn in (_from_sina, _from_tx):
        try:
            got = fn(raw)
        except Exception as e:
            errors.append(f'{fn.__name__}: {type(e).__name__}')
            continue
        if got:
            cands = _rank(got, raw)[:limit]
            exact = cands[0]['name'] == raw or cands[0].get('alias') == raw
            return {'query': raw, 'kind': 'name', 'exact': exact,
                    'candidates': cands, 'errors': errors}

    return {'query': raw, 'kind': 'name', 'exact': False,
            'candidates': [], 'errors': errors}


if __name__ == '__main__':
    import json
    import sys
    for q in (sys.argv[1:] or ['600519', '贵州茅台', '茅台', '农行', '隆基', '锦波生物', '不存在的票']):
        print(q, '->', json.dumps(resolve(q), ensure_ascii=False))
