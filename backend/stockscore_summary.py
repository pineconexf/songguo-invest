# -*- coding: utf-8 -*-
"""元宝总结版：给手机端 / 语音问答用的浓缩摘要（2026-10-20）

## 定位

深度分析是给"坐下来读"的人看的。元宝总结版是给**站在地铁上、只想听结论**的人看的。

硬约束（因为接入方是元宝，答案会直接被朗读）：
  1. 总长 ≤ 1200 字（朗读约 4 分钟）
  2. 纯口语，无 Markdown、无表格、无符号列表
  3. 每个数字都能溯源到 facts
  4. 禁操作建议（跟其他层同一把尺子）
  5. 覆盖度低时不装懂，明说"这块没有数据"

输出格式：纯文本 + 明确的段落切分（用空行），便于语音合成断句。
"""
import json
import os
import re
import threading
import time

import requests

LLM_URL = 'https://api.deepseek.com/chat/completions'
LLM_MODEL = 'deepseek-v4-flash'
LLM_TIMEOUT = 180

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'summary')

# 生成逻辑版本号：prompt/禁词/口径一改就 +1，旧缓存自动失效
# 2026-10-20 v5：coverage 口径统一（研报通道 + 行业结构层），
# 且行业结构事实进 prompt——旧缓存的 coverage 是按旧口径算的，会和页面其它处打架。
PIPELINE_VERSION = 5

# 口播版字数上限（元宝总结版规格：≤1200 字）
MAX_CHARS = 1200

_lock = threading.Lock()
_mem = {}

BANNED_RE = re.compile(
    r'买入|卖出|加仓|减仓|建仓|清仓|目标价|必涨|稳赚|推荐|抄底|逃顶|'
    r'值得买|可以买|该买|该卖|满仓|空仓|操作建议')

# 变相目标价：同 deep 层。2026-10-20 实测口播版出现
# 「市盈率回到历史最低 28.82，对应下行空间约 66%」——用分位倒算涨跌空间，
# 加了「这只是刻度，不是预测」也仍然是价格预测。直接禁掉。
BANNED_PREDICT_RE = re.compile(
    r'对应\s*\d+(\.\d+)?\s*%?\s*(的)?\s*(上涨|下行|上行|涨幅|跌幅|空间)|'
    r'(上涨|下行|上行)\s*空间\s*(约|大概|为)?\s*\d|'
    r'若\s*(市盈率|PE|市净率|PB)\b.{0,20}\s*(回到|涨到|跌到)\s*\d|'
    r'对应\s*(的)?\s*\d+(\.\d+)?\s*%\s*(的)?(上涨|下行|空间)|'
    r'最坏情况下.{0,40}\d+(\.\d+)?\s*%|'
    r'跌到\s*\d|涨到\s*\d')


def _truncate_by_para(text, max_chars):
    """按段落边界裁到 max_chars 以内，不切断句子。"""
    paras = [p for p in re.split(r'\n{2,}', str(text)) if p.strip()]
    out = []
    total = 0
    for p in paras:
        if total + len(p) > max_chars:
            break
        out.append(p)
        total += len(p) + 2
    if not out:
        out = [str(text)[:max_chars]]
    return '\n\n'.join(out)


def _strip_predict(text):
    """删掉变相目标价句子。返回 (文本, 命中数)"""
    if not text:
        return '', 0
    parts = re.split(r'(?<=[。！？!?；;])', str(text))
    keep = [s for s in parts if s.strip() and not BANNED_PREDICT_RE.search(s)]
    return ''.join(keep).strip(), len(parts) - len(keep)


def _call(messages, key, temperature=0.3, max_tokens=2400, retries=2):
    """调用 LLM。

    坑（2026-10-20 实测）：deepseek-v4-flash 会把 max_tokens 花在 reasoning_content 上，
    正文 content 返回空串、finish_reason='length'。修法：content 空且被截断时自动加倍预算重试。
    """
    body = {'model': LLM_MODEL, 'messages': messages,
            'temperature': temperature, 'max_tokens': max_tokens}
    last = None
    budget = max_tokens
    for attempt in range(retries + 1):
        try:
            body['max_tokens'] = budget
            r = requests.post(LLM_URL, json=body, timeout=LLM_TIMEOUT,
                              headers={'Authorization': 'Bearer ' + key,
                                       'Content-Type': 'application/json'})
            if r.status_code != 200:
                last = 'HTTP %d %s' % (r.status_code, r.text[:150])
                if r.status_code in (402, 403):
                    raise RuntimeError(last)
                time.sleep(2 + attempt * 3)
                continue
            j = r.json()
            choice = (j.get('choices') or [{}])[0]
            content = (choice.get('message') or {}).get('content') or ''
            if not content.strip() and choice.get('finish_reason') == 'length' \
                    and budget < 16000:
                budget = min(budget * 2, 16000)
                continue
            if not content.strip():
                budget = min(budget * 2, 16000)
                if attempt < retries:
                    continue
                last = 'LLM 返回空内容 (finish_reason=%s)' % choice.get('finish_reason')
                break
            return content.strip()
        except RuntimeError:
            raise
        except Exception as e:                       # noqa: BLE001
            last = '%s: %s' % (type(e).__name__, e)
            time.sleep(2 + attempt * 3)
    raise RuntimeError(last or 'LLM 调用失败')


# ---------------------------------------------------------------- 兜底（不靠模型）
def _fallback(code, name, payload, vb, kb, coverage):
    """模型不可用时，用确定性数据拼一段能朗读的摘要。"""
    total = (payload or {}).get('total')
    tier = (payload or {}).get('tier') or ''
    tag = ((payload or {}).get('tag') or {}).get('desc') or ''
    lines = ['%s，股票代码%s。' % (name, code)]
    if total is not None:
        lines.append('打分卡总分%s分，档位%s。%s' % (total, tier, tag))
    lines.append('这份评分只描述公司现在的状态，不代表接下来会涨还是会跌。')

    # 估值与预期
    vkeys = {'pctl': '估值分位', 'dv_ttm': '股息率', 'ev_ebitda': 'EV/EBITDA',
             'consensus_eps': '一致预期', 'dcf_range': '内在价值区间',
             'method_fit': '适用估值方法'}
    vlines = []
    for f in (vb.get('facts') or []):
        if f.get('key') in vkeys:
            vlines.append('%s，%s' % (f.get('label'), f.get('text')))
    if vlines:
        lines.append('估值和预期方面，' + '。'.join(vlines[:3]) + '。')

    # 风险
    flags = kb.get('flags') or []
    if flags:
        lines.append('已经触发的风险有%d条：%s。'
                     % (len(flags), '；'.join(f.get('text', '') for f in flags[:3])))
    else:
        lines.append('确定性指标没有触发任何红旗阈值。')

    safe = [f for f in (kb.get('facts') or []) if f.get('key') in ('beta', 'mdd')]
    if safe:
        lines.append('市场层面，' + '，'.join(f.get('text', '') for f in safe) + '。')

    if coverage in ('B', 'C'):
        lines.append('外部深度数据覆盖只有%s级，部分行业和竞争信息没有可核验的公开数据源，'
                     '这一块没有做常识性补写。' % coverage)
    return '\n\n'.join(lines)


# ---------------------------------------------------------------- 主流程
SUMMARY_SYSTEM = """你在给一个语音助手写"这段股票分析的口播稿"。
听众在通勤路上用耳朵听，没有时间看屏幕。

硬性要求：
1. 全文不超过 1000 字。宁可短，不要注水。
2. 纯口语。禁止 Markdown、禁止表格、禁止星号、禁止井号标题、禁止项目符号。
3. 用段落分节，每段之间空一行，方便语音断句。段首用"先说结论""再说估值""风险方面"这类口语过渡。
4. 数字只来自清单里给出的，一个都不许改、不许推算、不许补。
5. 禁止出现：买入、卖出、加仓、减仓、建仓、清仓、目标价、必涨、稳赚、推荐、抄底、逃顶、
   值得买、可以买、该买、该卖、满仓、空仓。
6. 不预测涨跌，不给操作建议。
7. 清单里写了"数据不可得"的，直说这块没有数据，不许用常识编。
8. 说人话。遇到专业词立刻用一句话解释清楚。
9. **绝对不许用历史分位倒算涨跌空间**。不许写"市盈率回到历史最低对应多少空间"、
   "跌到某个位置意味着多少跌幅"这类话。分位只说明"现在在刻度哪一格"，停在刻度上。
10. 结尾必须交代这块分析的数据缺口在哪，缺什么直说。

只输出 JSON：{"text":"口播稿全文"}"""


def build_summary(code, name, payload, vb, kb, research, facts, key,
                  coverage='A', deep=None, industry_facts=None):
    """生成元宝总结版。deep 可选——传了就用深度分析做素材。

    industry_facts：行业结构数据层（申万成分股实算）给的口播素材。
    研报通道拿不到行业集中度/份额，但口播稿需要"它在行业里什么位置"，
    所以这一路必须也进 prompt，否则手机端稿子缺行业维度。
    """
    if not key:
        return {'code': code, 'name': name, 'text': _fallback(code, name, payload, vb, kb, coverage),
                'source': 'rule', 'coverage': coverage, 'chars': 0}

    lines = []
    lines.append('公司：%s（%s）' % (name, code))
    if payload:
        lines.append('打分卡：总分 %s，档位 %s。%s'
                     % (payload.get('total'), payload.get('tier'),
                        (payload.get('tag') or {}).get('desc') or ''))
    lines.append('外部深度数据覆盖度：%s 级' % coverage)

    # 估值与预期要点
    vk = ('pctl_PE_TTM_10', 'pctl_PB_MRQ_10', 'pctl_PS_TTM_10', 'dv_ttm',
          'ev_ebitda', 'consensus_eps', 'dcf_range', 'method_fit', 'implied_growth')
    vl = [f for f in (vb.get('facts') or []) if f.get('key') in vk]
    if vl:
        lines.append('\n【估值与预期】\n'
                     + '\n'.join('- %s：%s' % (f.get('label'), f.get('text')) for f in vl[:10]))

    # 风险与安全要点
    rl = []
    for f in (kb.get('flags') or []):
        rl.append('- [已兑现] %s' % f.get('text'))
    for f in (kb.get('facts') or []):
        if f.get('key') in ('beta', 'mdd', 'net_cash_ratio', 'downside', 'to_median',
                            'turnover', 'unlock', 'gross_margin_drop'):
            rl.append('- %s：%s' % (f.get('label'), f.get('text')))
    if rl:
        lines.append('\n【风险与安全】\n' + '\n'.join(rl[:12]))

    # 深度分析摘要（给口播当主线）
    if deep and deep.get('sections'):
        sec_txt = []
        for s in deep['sections']:
            sec_txt.append('[%s] %s' % (s['title'], s['text']))
        lines.append('\n【深度分析正文（用来提炼主线，可压缩引用）】\n'
                     + '\n\n'.join(sec_txt))

    # 行业结构要点（申万成分股实算）
    if industry_facts:
        lines.append('\n【行业结构数据（申万二级行业成分股实算）】\n'
                     + '\n'.join('- %s' % x for x in industry_facts[:8]))

    # 研报要点
    ex = (research or {}).get('extracted') or {}
    rm = []
    for k, lbl in (('business_model', '业务结构'), ('market_space', '市场空间'),
                   ('market_share', '市占率'), ('competition', '竞争格局'),
                   ('growth_drivers', '增长驱动'), ('risks', '风险'),
                   ('valuation_view', '估值观点')):
        v = ex.get(k)
        if isinstance(v, str) and v:
            rm.append('- %s：%s' % (lbl, v))
        elif isinstance(v, list):
            for it in v[:3]:
                if isinstance(it, dict):
                    t = '；'.join('%s %s' % (kk, it[kk]) for kk in
                                  ('point', 'risk', 'driver', 'name', 'metric', 'evidence')
                                  if it.get(kk))
                    if t:
                        rm.append('- %s：%s' % (lbl, t))
    if rm:
        lines.append('\n【券商研报要点】\n' + '\n'.join(rm[:14]))

    try:
        raw = _call([{'role': 'system', 'content': SUMMARY_SYSTEM},
                     {'role': 'user', 'content': '\n'.join(lines)}], key,
                    temperature=0.35, max_tokens=2400)
        text = _extract(raw)
        text = _guard(text)
        text, n_pred = _strip_predict(text)
        if len(text) < 120:
            raise RuntimeError('口播稿过短，判定生成异常')
        # 长度硬约束：口播版 ≤1200 字（2026-10-20 实测 LLM 常写到 1400+）。
        # 优先让 LLM 自己压缩；还超就按段落边界裁，保留头部结论。
        if len(text) > MAX_CHARS:
            shorter = _call([{'role': 'system', 'content': SUMMARY_SYSTEM},
                             {'role': 'user',
                              'content': '\n'.join(lines) +
                              '\n\n【重要】上一版写到了 %d 字，太长。'
                              '请重新写一份 %d 字以内的版本，'
                              '保留核心判断和关键数字，砍掉次要展开。'
                              % (len(text), MAX_CHARS)}], key,
                            temperature=0.3, max_tokens=2400)
            t2 = _extract(shorter)
            t2 = _guard(t2)
            t2, np2 = _strip_predict(t2)
            if len(t2) >= 120:
                text, n_pred = t2, n_pred + np2
        if len(text) > MAX_CHARS:
            text = _truncate_by_para(text, MAX_CHARS)
        return {'code': code, 'name': name, 'text': text, 'source': 'llm',
                'coverage': coverage, 'chars': len(text),
                'stripped_predict_sentences': n_pred}
    except Exception as e:                           # noqa: BLE001
        fb = _fallback(code, name, payload, vb, kb, coverage)
        return {'code': code, 'name': name, 'text': fb, 'source': 'rule',
                'coverage': coverage, 'chars': len(fb),
                'note': '模型不可用，已用规则版：%s' % (str(e)[:60],)}


def _extract(raw):
    s = (raw or '').strip()
    s = re.sub(r'^```(?:json)?\s*', '', s)
    s = re.sub(r'\s*```$', '', s).strip()
    i, j = s.find('{'), s.rfind('}')
    if i >= 0 and j > i:
        try:
            obj = json.loads(s[i:j + 1])
            if isinstance(obj, dict) and obj.get('text'):
                return str(obj['text']).strip()
        except Exception:
            pass
    m = re.search(r'"text"\s*:\s*"(.*)', s, re.S)
    if m:
        t = m.group(1)
        t = re.sub(r'\\$', '', t)
        t = t.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
        return t.strip().strip('"').strip()
    return s


def _guard(text):
    """去禁词 + 去 Markdown 痕迹。"""
    text = re.sub(r'^```.*$', '', text, flags=re.M)
    text = re.sub(r'[*#]{1,3}\s*', '', text)
    text = re.sub(r'^\s*[-+]\s+', '', text, flags=re.M)
    text = re.sub(r'\*\*|__', '', text)
    parts = re.split(r'(?<=[。！？!?])', text)
    keep = [p for p in parts if p.strip() and not BANNED_RE.search(p)]
    out = ''.join(keep).strip()
    return out


# ---------------------------------------------------------------- 缓存
def _cache_path(code, asof):
    # 带 PIPELINE_VERSION：prompt/规则一改，旧缓存自动失效（见 deep 层同款坑）
    return os.path.join(CACHE_DIR, '%s_%s_v%d.json' % (code, asof, PIPELINE_VERSION))


def get_or_build(code, name, payload, vb, kb, research, facts, key, deep=None,
                 asof=None, force=False, coverage=None, industry_facts=None):
    asof = asof or time.strftime('%Y%m%d')
    with _lock:
        if (code, asof) in _mem and not force:
            return _mem[(code, asof)]
    path = _cache_path(code, asof)
    if not force and os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                obj = json.load(f)
            with _lock:
                _mem[(code, asof)] = obj
            return obj
        except Exception:
            pass
    if coverage is None:
        from stockscore_research import coverage_level
        coverage = coverage_level(research)
    obj = build_summary(code, name, payload, vb, kb, research, facts, key,
                         coverage=coverage, deep=deep,
                         industry_facts=industry_facts)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    except Exception:
        pass
    with _lock:
        _mem[(code, asof)] = obj
    return obj


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '.')
    import api as _api
    import stockscore_v3 as V
    import stockscore_facts as FA
    import stockscore_research as RS
    import stockscore_modules as M
    import stockscore_deep as D

    code = sys.argv[1] if len(sys.argv) > 1 else '688508'
    payload, _ = V.compute_v3(code)
    r = RS.get_research(code, '20261020', _api.DS_KEY)
    fk = FA.build_facts(code)
    vb = M.build_valuation_block(code, research=r)
    kb = M.build_risk_block(code, research=r)
    deep = D.get_or_build(code, payload.get('name', code),
                          [fk.get('facts') or [], vb['facts'], kb['facts']],
                          r, payload=payload, key=_api.DS_KEY, force=True)
    out = get_or_build(code, payload.get('name', code), payload, vb, kb, r,
                       fk.get('facts') or [], _api.DS_KEY, deep=deep, force=True)
    print('source', out['source'], 'chars', out.get('chars'))
    print(out['text'])
