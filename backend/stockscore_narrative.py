# -*- coding: utf-8 -*-
"""打分卡白话解读层（2026-10-19）

打分本身是确定性的（规则 + 公开数据），但普通股民看不懂「65.9 分」意味着什么。
本模块在分数算完之后，用 DeepSeek 把同一批数字翻译成大白话：

  verdict   这个总分说明什么（分数刻度锚定，解决"60 多分跟我有啥关系"）
  overview  整体为什么是这个分
  quality   质地这栏在说什么
  price     价格这栏在说什么
  momentum  势能这栏在说什么

设计原则：
  1. 分数永不由模型产生——模型只解释，不计算，避免不可复现。
  2. 模型挂了/超时/触发禁词 → 用规则文案兜底，页面永远有话说。
  3. 结果按 (code, data_asof) 落盘缓存，同一天同一只票只花一次 token。
  4. 禁词扫描沿用 stockscore.BANNED_RE：命中整句丢弃，绝不让"买入/目标价"漏到页面。
"""
import json
import os
import re
import threading
import time

import requests

from stockscore import BANNED_RE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, 'data', 'narrative')
CACHE_KEEP = 400                      # 最多保留的缓存文件数
LLM_URL = 'https://api.deepseek.com/chat/completions'
LLM_MODEL = 'deepseek-v4-flash'
TIMEOUT = 90

_lock = threading.Lock()
_mem = {}                             # (code, asof) -> payload

SCALE = ('分数刻度：80 分以上算优秀，65–79 是良，45–64 是中，45 以下待观察。'
         '这不是考试分数，是「和全市场同类公司比，站在什么位置」。')


# ---------------------------------------------------------------- 事实压缩
def _num(v, nd=1):
    if v is None:
        return '无'
    if isinstance(v, (int, float)):
        s = f'{v:.{nd}f}'
        return s.rstrip('0').rstrip('.') if '.' in s else s
    return str(v)


def _facts(p):
    """把 payload 压成模型看得懂、又不至于太长的事实清单。"""
    g = p.get('groups') or {}
    lines = [
        f"公司：{p.get('name')}（{p.get('code')}），行业：{p.get('industry') or '未分类'}",
        f"数据日期：{p.get('data_asof')}",
        f"总分 {_num(p.get('total'))} / 100，档位「{p.get('tier')}」，裸分 {_num(p.get('total_raw'))}",
        f"标签：{p.get('tag', {}).get('label')}——{p.get('tag', {}).get('desc')}",
    ]
    if p.get('tier_note'):
        lines.append(f"调档说明：{p['tier_note']}")
    lines.append('三组：')
    for k in ('Q', 'V', 'M'):
        gg = g.get(k) or {}
        lines.append(f"  - {gg.get('label')} {_num(gg.get('score'))} 分（权重 {gg.get('weight')}%）："
                     f"{gg.get('question')}")
    lines.append('八维：')
    for d in p.get('dims') or []:
        if not d.get('available'):
            lines.append(f"  - {d.get('label')}：N/A（{d.get('na_reason') or '数据不可用'}）")
            continue
        ms = sorted(d.get('metrics') or [], key=lambda m: -(m.get('weight') or 0))[:2]
        m_txt = '；'.join(
            f"{m.get('name')} {_num(m.get('value'))}{m.get('unit') or ''}"
            + (f"（同行分位 {_num(m.get('pctl'), 0)}）" if m.get('pctl') is not None else '')
            for m in ms)
        lines.append(f"  - {d.get('label')} {_num(d.get('score'))} 分"
                     f"（维内权重 {int(round((d.get('weight') or 0) * 100))}%）：{m_txt}")
    gate = p.get('gate') or {}
    lines.append(f"闸门：红旗 {len(gate.get('red') or [])} 条，黄旗 {len(gate.get('yellow') or [])} 条")
    for r in (gate.get('red') or [])[:3]:
        lines.append(f"  · 红旗：{r}")
    for y in (gate.get('yellow') or [])[:3]:
        lines.append(f"  · 黄旗：{y}")
    checks = p.get('investable_checks') or {}
    if checks:
        ok = [k for k, v in checks.items() if v]
        no = [k for k, v in checks.items() if not v]
        lines.append(f"可投性检查：{len(ok)}/{len(checks)} 项通过"
                     + (f"；未过：{'、'.join(no)}" if no else ''))
    return '\n'.join(lines)


SYSTEM_PROMPT = """你是一位专门帮普通股民读懂研报的分析师。你的读者没学过财务，也没时间看财报，\
他们只想知道一件事：这个分数到底说明什么。

写作要求（必须全部遵守）：
1. 绝对不出现这些词：买入、卖出、加仓、减仓、建仓、清仓、目标价、必涨、稳赚、推荐、持有、抄底、逃顶。
2. 不预测涨跌，不给操作建议，不说"该买/该卖/值得买"。只解释公司现在的状态。
3. 少用术语。必须用时立刻跟一句人话解释，例如：
   - 分位 → 在同行里排第几
   - ROIC → 每投 100 块钱能赚回多少
   - 现金流 → 账上真金白银收回来多少
   - 估值 → 市场愿意为它现在的赚钱能力付多少钱
4. 句子短，一段 2–4 句。不要排比句，不要"综上所述""不难看出"这类套话。
5. 必须让读者对分数有感觉：80 以上算优秀，65–79 是良，45–64 是中，45 以下待观察；\
这不是考试分数，是跟全市场同类公司比站在什么位置。
6. 说清"为什么是这个分"：至少点名一个把分拉高的维度、一个把分拖低的维度，用具体数字支撑。
7. 某一维显示 N/A 时，用一句话说明缺什么，绝不编数字。
8. 语气像一个懂行的朋友在解释，不是券商研报。
9. 指标名照抄事实清单里的叫法，不要自己换算成别的指标，更不要把两个指标混着说\
（例如 ROIC 和 ROE 是两回事，净占用天数为负是占用上下游资金、不是坏事）。

只输出 JSON，不要 markdown 代码块，不要多余文字。字段与字数：
{"verdict":"这个总分意味着什么，80-120字","overview":"整体为什么是这个分，好在哪差在哪，80-140字",\
"quality":"质地这栏在说什么，70-120字","price":"价格这栏在说什么，70-120字",\
"momentum":"势能这栏在说什么，70-120字"}"""


# ---------------------------------------------------------------- 规则兜底
def _scale_hint(total):
    t = total or 0
    if t >= 80:
        return '放在全市场里属于优秀那一档。'
    if t >= 65:
        return '放在全市场里属于良这一档——比多数公司好，但还没到最顶尖。'
    if t >= 45:
        return '放在全市场里属于中等水平，有明显长处也有明显短板。'
    return '放在全市场里偏弱，短板比较集中。'


def _fallback(p):
    """模型不可用时的确定性文案：不惊艳，但一定读得懂、一定合规。"""
    total = p.get('total')
    tier = p.get('tier') or ''
    tag = (p.get('tag') or {}).get('desc') or ''
    dims = [d for d in (p.get('dims') or []) if d.get('available') and d.get('score') is not None]
    dims.sort(key=lambda d: d['score'], reverse=True)
    best = dims[0] if dims else None
    worst = dims[-1] if dims else None

    verdict = f"总分 {_num(total)} 分，档位「{tier}」。{_scale_hint(total)}"
    if tag:
        verdict += f"标签是「{tag}」。"
    verdict += '这个分数只描述公司现在的状态，不代表接下来会涨还是会跌。'

    ov = ''
    if best:
        ov += f"拉高分数的主要是{best['label']}（{_num(best['score'])} 分），"
    if worst and worst is not best:
        ov += f"拖后腿的是{worst['label']}（{_num(worst['score'])} 分）。"
    pages = p.get('pages') or {}
    for b in ((pages.get('overview') or {}).get('blocks') or [])[:2]:
        ov += (b.get('t') or '') + ' '

    out = {'verdict': verdict.strip(), 'overview': ov.strip()}
    for key, page in (('quality', 'quality'), ('price', 'price'), ('momentum', 'momentum')):
        pg = pages.get(page) or {}
        txt = ''
        for b in (pg.get('blocks') or [])[:2]:
            txt += (b.get('t') or '') + ' '
        out[key] = txt.strip() or '这一栏本次没有足够数据可讲。'
    return out


def _guard(text):
    """命中禁词整句丢弃；丢光了返回空串，由调用方换兜底文案。"""
    if not text:
        return ''
    parts = re.split(r'(?<=[。！？!?])', str(text))
    keep = [s for s in parts if s.strip() and not BANNED_RE.search(s)]
    return ''.join(keep).strip()


# ---------------------------------------------------------------- 缓存
def _cache_path(code, asof):
    safe = re.sub(r'[^\w.-]', '_', f'{code}_{asof or "na"}')
    return os.path.join(CACHE_DIR, safe + '.json')


def _read_cache(code, asof):
    k = (code, asof)
    with _lock:
        if k in _mem:
            return _mem[k]
    try:
        with open(_cache_path(code, asof), encoding='utf-8') as f:
            obj = json.load(f)
        with _lock:
            _mem[k] = obj
        return obj
    except (OSError, ValueError):
        return None


def _write_cache(code, asof, obj):
    with _lock:
        _mem[(code, asof)] = obj
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = _cache_path(code, asof) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)
        os.replace(tmp, _cache_path(code, asof))
        _prune()
    except OSError:
        pass


def _prune():
    try:
        files = [os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR) if f.endswith('.json')]
        if len(files) <= CACHE_KEEP:
            return
        files.sort(key=lambda p: os.path.getmtime(p))
        for p in files[:len(files) - CACHE_KEEP]:
            os.remove(p)
    except OSError:
        pass


# ---------------------------------------------------------------- 生成
def _call_llm(facts, key):
    body = {
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': facts},
        ],
        'temperature': 0.5,
        'max_tokens': 1400,
        'response_format': {'type': 'json_object'},
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.post(LLM_URL, json=body, timeout=TIMEOUT,
                              headers={'Authorization': f'Bearer {key}',
                                       'Content-Type': 'application/json'})
            if r.status_code != 200:
                last = f'HTTP {r.status_code} {r.text[:120]}'
                time.sleep(2 + attempt * 3)
                continue
            raw = r.json()['choices'][0]['message']['content'].strip()
            raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.M).strip()
            return json.loads(raw)
        except Exception as e:                      # noqa: BLE001
            last = f'{type(e).__name__}: {e}'
            time.sleep(2 + attempt * 3)
    raise RuntimeError(last or 'LLM 调用失败')


FIELDS = ('verdict', 'overview', 'quality', 'price', 'momentum')


def get_or_build(payload, key):
    """返回 {'verdict','overview','quality','price','momentum','source','generated_at'}。

    source: 'llm' 模型生成 / 'rule' 规则兜底（模型不可用或全部触发禁词）。
    """
    code = str(payload.get('code') or '')
    asof = str(payload.get('data_asof') or '')
    hit = _read_cache(code, asof)
    if hit:
        return hit

    base = {'source': 'rule', 'generated_at': int(time.time()), 'model': LLM_MODEL}
    if not key:
        out = dict(base, **_fallback(payload))
        _write_cache(code, asof, out)
        return out

    try:
        raw = _call_llm(_facts(payload), key)
    except Exception:                                # noqa: BLE001
        out = dict(base, **_fallback(payload))
        _write_cache(code, asof, out)                # 兜底也缓存，避免反复打模型
        return out

    cleaned = {}
    for f in FIELDS:
        cleaned[f] = _guard(raw.get(f) or '')
    missing = [f for f in FIELDS if not cleaned[f]]
    if missing:
        fb = _fallback(payload)
        for f in missing:
            cleaned[f] = fb.get(f) or ''
        src = 'rule' if len(missing) == len(FIELDS) else 'llm'
    else:
        src = 'llm'

    out = dict(base, source=src, **cleaned)
    _write_cache(code, asof, out)
    return out


if __name__ == '__main__':
    import sys
    p = json.load(open(sys.argv[1], encoding='utf-8'))
    print(_facts(p))
    print('--- fallback ---')
    print(json.dumps(_fallback(p), ensure_ascii=False, indent=1))
