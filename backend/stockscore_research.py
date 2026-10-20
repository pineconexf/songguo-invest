# -*- coding: utf-8 -*-
"""研报深度数据补漏模块（2026-10-20）

## 为什么有这个模块

个股打分卡要写到"微信深度文章"水平（峰岹科技那篇），需要三类数据：

  A. 公司自身财务与分部数据  → facts 层已有（东财 F10）
  B. 行业空间 / 竞争格局 / 市占率 / 关键风险  → **没有任何结构化接口**
  C. 一致预期与预期修正  → 东财研报中心 API 有

B 类是文章级内容与打分卡内容差距最大的一块。它在现实里靠研究员手工调研
（翻研报正文、翻行业报告、算 CR5），人工无法复制。

本模块的解法：**把研报正文当作数据源**。

  研报正文（东财 data.eastmoney.com/report/info/{infoCode}.html）
    → 剥标签取正文
    → LLM 按固定 schema 抽取结构化要点，每条**必须带原文逐字引用**
    → 引用做程序化回验（quote 必须能在原文中找到）
    → 回验不通过的条目直接丢弃
    → 结果落盘缓存（code + asof）

这样得到的是「可溯源、可回验、零人工」的行业与竞争数据。

实测（2026-10-20）：6 只票 18 篇研报正文抓取成功率 18/18。

## 铁律

1. **quote 回验是硬闸**：抽取的每条要点必须携带原文逐字片段；
   程序化检查该片段确实出现在研报原文中，否则整条丢弃。
   这是本模块唯一能防止模型编造行业数据的机制。
2. **不生成数字**：模型只能复述原文里有的数字。抽取结果里出现的数字，
   会在写回验时逐一检查是否在原文出现。
3. **不写结论**：本模块只做「研报说了什么」的事实摘录，
   不做主观判断。判断由写作层在拿到这些事实后自行完成。
4. **失败降级**：研报抓不到 / LLM 不可用 → 返回空 blocks，
   写作层按"外部深度数据不可得"降级，绝不用常识补数。
5. **缓存**：同一 code + asof 只跑一次。缓存保留 300 份。
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'data', 'research')
CACHE_KEEP = 300

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

REPORT_LIST_URL = 'https://reportapi.eastmoney.com/report/list'
REPORT_INFO_URL = 'https://data.eastmoney.com/report/info/{infoCode}.html'

LLM_URL = 'https://api.deepseek.com/chat/completions'
LLM_MODEL = 'deepseek-v4-flash'
LLM_TIMEOUT = 120

_lock = threading.Lock()
_mem = {}

# 研报正文里常见的噪声段，抓完先砍掉，减少 token 与误抽取
_NOISE = re.compile(
    r'(今日最新研究报告|郑重声明|东方财富发布此内容|建议用户在阅读研报|'
    r'最新宏观研究报告|更多\s*点击查看全部|最新研报|data recommendation|'
    r'数据推荐|查看PDF原文.*?公司\s*$)')


# ================================================================== 抓取层
def _report_list(code, days=180, page_size=50):
    """研报列表。返回 [{date, org, rating, title, eps_this, eps_next, infoCode, industry}]"""
    end = time.time()
    params = {
        'cb': '', 'industryCode': '*', 'pageSize': page_size, 'industry': '*',
        'rating': '', 'ratingChange': '',
        'beginTime': time.strftime('%Y-%m-%d', time.localtime(end - days * 86400)),
        'endTime': time.strftime('%Y-%m-%d', time.localtime(end)),
        'pageNo': 1, 'fields': '', 'qType': 0, 'orgCode': '',
        'code': code, 'rcode': '', 'p': 1, 'pageNum': 1,
    }
    try:
        r = requests.get(REPORT_LIST_URL, params=params, headers=UA, timeout=25)
        t = r.text.strip()
        if t.startswith('('):
            t = t[1:-1]
        data = json.loads(t).get('data') or []
    except Exception:
        return []
    out = []
    for x in data:
        if not x.get('infoCode'):
            continue
        out.append({
            'date': str(x.get('publishDate') or '')[:10],
            'org': x.get('orgSName') or '',
            'rating': x.get('emRatingName') or x.get('sRatingName') or '',
            'title': (x.get('title') or '').strip(),
            'eps_this': _f(x.get('predictThisYearEps')),
            'eps_next': _f(x.get('predictNextYearEps')),
            'infoCode': x.get('infoCode'),
            'industry': x.get('indvInduName') or '',
        })
    out.sort(key=lambda r: r['date'], reverse=True)
    return out


def _report_body(info_code):
    """研报正文纯文本。返回 str（空串=抓不到）。"""
    try:
        r = requests.get(REPORT_INFO_URL.format(infoCode=info_code),
                         headers=UA, timeout=30)
        h = r.text
    except Exception:
        return ''
    i = h.find('zw-content')
    if i < 0:
        return ''
    seg = h[i:i + 30000]
    # 先断掉尾部噪声区
    for marker in ('今日最新研究报告', '郑重声明', '数据推荐'):
        j = seg.find(marker)
        if j > 2000:
            seg = seg[:j]
    seg = re.sub(r'<script.*?</script>', ' ', seg, flags=re.S)
    seg = re.sub(r'<style.*?</style>', ' ', seg, flags=re.S)
    seg = re.sub(r'<[^>]+>', ' ', seg)
    seg = seg.replace('&nbsp;', ' ').replace('&amp;', '&')
    seg = re.sub(r'[ \t　]+', ' ', seg)
    seg = re.sub(r'\n\s*\n+', '\n', seg)
    return seg.strip()


def _f(v):
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ================================================================== 抽取层
EXTRACT_SYSTEM = """你是卖方研报的资深信息抽取员。你的任务是从一篇中文券商研报正文里，抽取结构化要点。

铁律：
1. 只抽取**原文中确实写明**的内容。原文没写的不许推测、不许用常识补。
2. 每一条要点必须带 `quote` 字段：原文中的**逐字片段**（15–60 字），用于程序化回验。
   quote 必须是你从原文中原样复制的，不许改写、不许拼接两处。
3. 数字必须与原文一致，不许换算、不许四舍五入、不许自己算。
4. 不写你自己的判断、评价、结论。只写"研报说了什么"。
5. 某一项原文没有，就不要给这个键（或给空数组）。

要抽取的字段：
- business_model: 业务结构描述（公司靠什么赚钱、有哪些业务板块、各自地位）
- segments: [{name, revenue_share, growth, quote}]  分部/产品/地区结构与增速
- market_space: [{scope, size, cagr, quote}]  市场规模与增速。scope 写"全球"/"中国"/"国内"等
- market_share: [{metric, value, note, quote}]  公司市占率、份额排名、CR5 等
- competition: [{point, durability, quote}]  竞争格局与壁垒。durability 只能填"强"/"中"/"弱"
- growth_drivers: [{driver, evidence, timing, quote}]  增长驱动与催化
- capital_notes: [{point, quote}]  资本开支/产能/供应链/客户/存货/应收等资本与经营特征
- risks: [{risk, trigger, quote}]  研报明示的风险（要写明触发条件或观察指标）
- expectations: [{item, value, quote}]  研报给出的盈利预测、市值空间、增速假设等量化预期
- valuation_view: [{point, quote}]  研报对估值/股价空间的判断（只记录研报观点，不加自己的）

输出严格 JSON，不要 markdown 代码块，不要多余文字。"""

EXTRACT_FIELDS = ('business_model', 'segments', 'market_space', 'market_share',
                   'competition', 'growth_drivers', 'capital_notes', 'risks',
                   'expectations', 'valuation_view')


def _call_llm(body_text, key):
    body = {
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': EXTRACT_SYSTEM},
            {'role': 'user', 'content': '研报正文：\n\n' + body_text[:16000]},
        ],
        'temperature': 0.1,
        'max_tokens': 4000,
        'response_format': {'type': 'json_object'},
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.post(LLM_URL, json=body, timeout=LLM_TIMEOUT,
                              headers={'Authorization': 'Bearer ' + key,
                                       'Content-Type': 'application/json'})
            if r.status_code != 200:
                last = 'HTTP %d %s' % (r.status_code, r.text[:120])
                time.sleep(2 + attempt * 3)
                continue
            raw = r.json()['choices'][0]['message']['content'].strip()
            raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.M).strip()
            i, j = raw.find('{'), raw.rfind('}')
            if i >= 0 and j > i:
                raw = raw[i:j + 1]
            return json.loads(raw)
        except Exception as e:                       # noqa: BLE001
            last = '%s: %s' % (type(e).__name__, e)
            time.sleep(2 + attempt * 3)
    raise RuntimeError(last or '研报抽取 LLM 调用失败')


# ================================================================== 回验层
_NUM_RE = re.compile(r'-?\d+(?:\.\d+)?%?')


def _norm(s):
    """归一化用于 quote 比对：去掉所有空白与全角符号差异。"""
    s = re.sub(r'\s+', '', s or '')
    return (s.replace('（', '(').replace('）', ')')
             .replace('，', ',').replace('：', ':').replace('“', '"')
             .replace('”', '"').replace('、', ',').replace('；', ';'))


def _verify_quote(item, haystack_norm):
    """quote 必须在原文中逐字出现（归一化后子串匹配）。"""
    q = _norm(item.get('quote') or '')
    if len(q) < 8:
        return False
    return q in haystack_norm


def _verify_numbers(item, haystack):
    """条目中出现的每个数字都必须在原文里出现（允许千分位/百分号差异）。"""
    for m in _NUM_RE.findall(json.dumps(item, ensure_ascii=False)):
        num = m.rstrip('%')
        if not num or num in ('1', '2', '3', '4', '5'):
            continue
        cands = {num, num + '%', num.lstrip('0') or num}
        try:
            fv = float(num)
            cands.add(('%g' % fv))
            cands.add(('%f' % fv).rstrip('0').rstrip('.'))
            if fv == int(fv):
                cands.add(str(int(fv)))
        except ValueError:
            pass
        if not any(c and c in haystack for c in cands):
            return False
    return True


def _verify_block(blocks, body):
    """对每个数组字段逐条回验。返回 (kept_blocks, dropped_count)。"""
    hay = body
    hay_norm = _norm(body)
    dropped = 0
    out = {}
    for k in EXTRACT_FIELDS:
        v = blocks.get(k)
        if k == 'business_model':
            # 自由文本：检查里面提到的数字是否在原文（不要求逐字 quote）
            if isinstance(v, str) and v:
                out[k] = v if _verify_numbers({'t': v}, hay) else None
                if out[k] is None:
                    dropped += 1
            else:
                out[k] = None
            continue
        if not isinstance(v, list):
            out[k] = []
            continue
        kept = []
        for item in v:
            if not isinstance(item, dict):
                continue
            if not _verify_quote(item, hay_norm):
                dropped += 1
                continue
            if not _verify_numbers(item, hay):
                dropped += 1
                continue
            kept.append(item)
        out[k] = kept
    return out, dropped


# ================================================================== 组装层
def _collect_expectations(reports, extracted):
    """一致预期与预期修正：从研报列表的 EPS 预测聚合（可程序化，不依赖 LLM）。"""
    cur = [r for r in reports if r.get('eps_this') is not None]
    nxt = [r for r in reports if r.get('eps_next') is not None]
    out = {}
    if cur:
        vals = [r['eps_this'] for r in cur]
        out['eps_this'] = {
            'mean': round(sum(vals) / len(vals), 3),
            'min': round(min(vals), 3), 'max': round(max(vals), 3),
            'n': len(vals), 'asof': cur[0]['date'],
            'orgs': sorted({r['org'] for r in cur if r.get('org')}),
        }
    if nxt:
        vals = [r['eps_next'] for r in nxt]
        out['eps_next'] = {
            'mean': round(sum(vals) / len(vals), 3),
            'min': round(min(vals), 3), 'max': round(max(vals), 3),
            'n': len(vals), 'asof': nxt[0]['date'],
            'orgs': sorted({r['org'] for r in nxt if r.get('org')}),
        }
    if 'eps_this' in out and 'eps_next' in out:
        a, b = out['eps_this']['mean'], out['eps_next']['mean']
        if a:
            out['implied_growth'] = round((b / a - 1) * 100, 2)
    ratings = [r.get('rating') for r in reports if r.get('rating')]
    if ratings:
        cnt = {}
        for x in ratings:
            cnt[x] = cnt.get(x, 0) + 1
        out['rating_dist'] = dict(sorted(cnt.items(), key=lambda kv: -kv[1]))
        out['coverage'] = len(reports)
    return out


def _build(code, asof, key, max_reports=3, days=180):
    """采集 + 抽取 + 回验。返回完整 research block。"""
    reports = _report_list(code, days=days)
    result = {
        'code': code, 'asof': asof,
        'report_count': len(reports),
        'reports': reports[:12],
        'expectations': _collect_expectations(reports, {}),
        'extracted': {},
        'dropped_items': 0,
        'used_reports': 0,
        'source': 'none',
        'note': '',
    }
    if not reports:
        result['note'] = '近%d天无券商研报覆盖，外部深度数据不可得' % days
        return result

    bodies = []
    for rep in reports[:max_reports]:
        b = _report_body(rep['infoCode'])
        if len(b) > 800:
            bodies.append((rep, b))
    if not bodies:
        result['note'] = '研报列表可取但正文抓取失败，外部深度数据不可得'
        return result

    merged = {k: [] for k in EXTRACT_FIELDS}
    dropped = 0
    notes = []

    def _one(rep, body):
        """单篇抽取 + 回验。返回 (blocks, dropped, err)。"""
        try:
            raw = _call_llm(body, key)
        except Exception as e:                       # noqa: BLE001
            return None, 0, str(e)[:80]
        blk, dr = _verify_block(raw, body)
        return blk, dr, None

    # 多篇研报并行抽取（每篇独立，失败不影响其他）
    with ThreadPoolExecutor(max_workers=min(len(bodies), 4)) as ex:
        futs = [(rep, body, ex.submit(_one, rep, body)) for rep, body in bodies]
        for rep, body, fu in futs:
            blk, dr, err = fu.result()
            if err:
                notes.append('抽取失败：%s' % err)
                continue
            dropped += dr
            for k in EXTRACT_FIELDS:
                v = (blk or {}).get(k)
                if isinstance(v, list):
                    for it in v:
                        it = dict(it)
                        it['_src'] = {'org': rep.get('org'), 'date': rep.get('date'),
                                      'title': rep.get('title')}
                        merged[k].append(it)
                elif isinstance(v, str) and v and not merged.get(k):
                    merged[k] = v
                    merged[k + '_src'] = {'org': rep.get('org'), 'date': rep.get('date')}
    if notes:
        result['note'] = '；'.join(notes)

    result['extracted'] = {k: v for k, v in merged.items() if v}
    result['dropped_items'] = dropped
    result['used_reports'] = len(bodies)
    result['source'] = 'eastmoney_research'
    if not result['extracted']:
        result['note'] = '研报正文抽取后无可回验条目，外部深度数据不可得'
    else:
        result['note'] = ('研报正文抽取，%d 篇可回验，丢弃 %d 条未通过回验的要点'
                          % (len(bodies), dropped))
    return result


# ================================================================== 缓存
def _cache_path(code, asof):
    return os.path.join(CACHE_DIR, '%s_%s.json' % (code, asof))


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
        _prune()
    except Exception:
        pass


def _prune():
    try:
        files = [os.path.join(CACHE_DIR, x) for x in os.listdir(CACHE_DIR)
                 if x.endswith('.json')]
        if len(files) <= CACHE_KEEP:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[:len(files) - CACHE_KEEP]:
            try:
                os.remove(p)
            except Exception:
                pass
    except Exception:
        pass


# ================================================================== 对外
def get_research(code, asof, key, force=False):
    """返回 research block。key 为空时仍会抓研报列表（预期数据可程序化聚合）。"""
    with _lock:
        k = (code, asof)
        if k in _mem and not force:
            return _mem[k]
    hit = None if force else _read_cache(code, asof)
    if hit is None:
        try:
            hit = _build(code, asof, key)
        except Exception as e:                       # noqa: BLE001
            hit = {'code': code, 'asof': asof, 'report_count': 0, 'reports': [],
                   'expectations': {}, 'extracted': {}, 'dropped_items': 0,
                   'used_reports': 0, 'source': 'error',
                   'note': '研报采集异常：%s' % (str(e)[:80],)}
        _write_cache(code, asof, hit)
    with _lock:
        _mem[(code, asof)] = hit
    return hit


def coverage_level(research, industry=None):
    """外部深度数据完备度 → A/B/C 级。

    A：有行业空间 + 竞争格局 + 风险 + 预期，够写五段式深度分析
    B：有部分，够写三段
    C：几乎没有，写作层必须短而实

    2026-10-20 新增 industry 参数（外部深度数据补漏机制）：
    研报通道（research）天生拿不到行业集中度和公司行业份额——
    券商不写、口径也不可核。但行业结构数据层（stockscore_industry）
    能自己从申万成分股实算出来。所以：
      - 研报里有「市场空间」或行业层有「集中度」→ 都算 has_space
      - 研报里有「市占率」或行业层有「目标公司行业份额」→ 都算 has_share
    这样 B/C 级票能靠行业层自动补上这两个维度，
    而不是整段空着（实测 688508 的 market 段 chars=0）。

    注意：行业层只能补「结构类」维度（空间/集中度/份额/景气），
    不能补「风险」和「预期」——那两个只能来自研报或基本面，
    不许拿行业集中度去顶替。
    """
    ex = (research or {}).get('extracted') or {}
    exp = (research or {}).get('expectations') or {}
    ind = (industry or {}).get('industry') or {}
    conc = (industry or {}).get('concentration') or {}
    growth = (industry or {}).get('growth') or {}
    idx = (industry or {}).get('industry_index') or {}

    has_space = bool(ex.get('market_space')) or bool(conc) or bool(growth)
    has_share = bool(ex.get('market_share')) or (
        conc.get('target_mv_share_pct') is not None)
    has_comp = bool(ex.get('competition')) or bool(conc)
    has_risk = bool(ex.get('risks'))
    has_exp = bool(exp.get('eps_this'))
    has_growth = bool(ex.get('growth_drivers')) or bool(idx)
    score = sum([has_space, has_comp, has_risk, has_exp, has_growth, has_share])
    if score >= 4:
        return 'A'
    if score >= 2:
        return 'B'
    return 'C'


def facts_for_writer(research):
    """把 research block 压成写作层可直接引用的事实条目。

    每条 = {'label', 'text', 'source'}，source 写明机构与日期，便于页面溯源。
    """
    ex = (research or {}).get('extracted') or {}
    out = []
    bm = ex.get('business_model')
    if bm:
        out.append({'label': '业务结构（研报口径）', 'text': bm,
                    'source': '券商研报正文'})
    for k, lbl in (('segments', '分部结构'), ('market_space', '市场空间'),
                   ('market_share', '市占率与集中度'), ('competition', '竞争格局'),
                   ('growth_drivers', '增长驱动'), ('capital_notes', '资本与经营特征'),
                   ('risks', '研报明示风险'), ('expectations', '研报量化预期'),
                   ('valuation_view', '研报估值观点')):
        for it in (ex.get(k) or []):
            if not isinstance(it, dict):
                continue
            parts = []
            for f in ('name', 'scope', 'metric', 'driver', 'point', 'risk',
                      'item', 'revenue_share', 'growth', 'size', 'cagr',
                      'value', 'evidence', 'timing', 'trigger', 'durability', 'note'):
                if it.get(f):
                    parts.append('%s: %s' % (f, it[f]))
            if not parts:
                continue
            src = it.get('_src') or {}
            srcs = ' / '.join(x for x in (src.get('org'), src.get('date')) if x)
            out.append({'label': lbl, 'text': '；'.join(parts),
                        'source': ('券商研报（%s）' % srcs) if srcs else '券商研报正文'})
    exp = (research or {}).get('expectations') or {}
    if exp.get('eps_this'):
        e = exp['eps_this']
        out.append({'label': '一致预期 EPS（当年）',
                    'text': '覆盖 %d 家机构，均值 %s（区间 %s–%s），截至 %s'
                            % (e['n'], e['mean'], e['min'], e['max'], e['asof']),
                    'source': '东财研报中心'})
    if exp.get('eps_next') and exp.get('eps_this'):
        e = exp['eps_next']
        out.append({'label': '一致预期 EPS（次年）',
                    'text': '覆盖 %d 家机构，均值 %s（区间 %s–%s），隐含增速 %s%%'
                            % (e['n'], e['mean'], e['min'], e['max'],
                               exp.get('implied_growth')),
                    'source': '东财研报中心'})
    if exp.get('rating_dist'):
        out.append({'label': '机构评级分布',
                    'text': '；'.join('%s %d 篇' % (k, v)
                                      for k, v in exp['rating_dist'].items()),
                    'source': '东财研报中心'})
    return out


if __name__ == '__main__':
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else '688508'
    key = ''
    try:
        import api as _api
        key = _api.DS_KEY
    except Exception:
        pass
    r = get_research(code, '20261020', key, force=True)
    print(json.dumps(r, ensure_ascii=False, indent=1)[:4000])
    print('--- coverage', coverage_level(r))
