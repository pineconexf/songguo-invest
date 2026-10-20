# -*- coding: utf-8 -*-
"""写作层：文章级四段框架 + 双端输出（2026-10-20）

设计要点（对应"如何确保丰满度"）：

1. **槽位化**：框架不是"请写一篇深度分析"，而是十个必答槽位，
   每个槽位有明确的问题和可用事实。模型填空，不是自由发挥。
2. **事实包驱动**：提示词里塞的是带 source 的事实清单，不是原始财报字段。
   模型只能"组织"事实，不能"发明"事实。
3. **缺口显式**：事实包里每个缺口都要求模型在正文中声明，
   闸门会检查是否声明了。宁可说"这项没数据"，不许绕过去。
4. **双端同源**：网页全文和手机摘要从同一次调用的同一份 JSON 派生，
   不是两次生成——避免两端口径打架。
5. **不达标就降级**：闸门判定 degrade 时，只发摘要 + 缺口清单，不发半成品长文。

与旧版 stockscore_narrative 的分工：
  - 旧版：解释分数（verdict/overview/quality/price/momentum）
  - 本版：完整分析（业务结构/空间格局/壁垒/数字检验/估值预期/风险安全）
  两者并存，前端可先出分数解读、后出深度分析。
"""
import json
import os
import re
import threading
import time

import requests

import stockscore_facts as F
import stockscore_gate as G

LLM_MODEL = os.environ.get('STOCKSCORE_LLM_MODEL', 'deepseek-v4-flash')
LLM_URL = 'https://api.deepseek.com/chat/completions'

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'deepdive')
_LOCK = threading.Lock()

# ---------------------------------------------------------------- 框架定义
# 每个 section 对应文章的一节。slots 里的 key 必须与 stockscore_gate.FRAMEWORK_SLOTS 对齐。
SECTIONS = [
    {
        'key': 'business',
        'title': '一、业务结构：钱从哪来，增量在哪',
        'question': '这家公司靠什么赚钱？哪块是基本盘、哪块是增长期权？两块生意的资本特征有何不同？',
        'slots': ['biz_base', 'biz_segment', 'biz_option'],
        'words': '350-500',
    },
    {
        'key': 'space',
        'title': '二、空间与格局：天花板够不够高',
        'question': '市场空间有多大、增速多少？公司份额起点在哪？份额提升能不能支撑增长？竞争格局是集中还是分散？',
        'slots': ['space', 'competition'],
        'words': '300-450',
    },
    {
        'key': 'moat',
        'title': '三、差异化：壁垒有多硬，能硬多久',
        'question': '护城河来自哪一层？每一层的持久性是否相同？谁在攻这堵墙？',
        'slots': ['moat'],
        'words': '250-400',
    },
    {
        'key': 'numbers',
        'title': '四、数字检验：赚的是不是真钱',
        'question': 'ROIC 与 WACC 的关系说明什么？现金流和利润是否匹配？资本开支在扩张还是维持？',
        'slots': ['capital_return', 'cashflow'],
        'words': '300-450',
    },
    {
        'key': 'valuation',
        'title': '五、估值与预期：现在贵不贵，隐含了什么',
        'question': 'PE/PB/PS 处在历史什么分位？当前价格隐含了什么增长假设？什么情况下这个判断会失效？',
        'slots': ['valuation'],
        'words': '280-400',
    },
    {
        'key': 'risk',
        'title': '六、风险与安全：哪些线已经越过',
        'question': '哪些财务指标越过了阈值？哪些接近？哪些不适用？还有哪些风险没有数据？',
        'slots': ['risk'],
        'words': '280-400',
    },
]

SYSTEM_PROMPT = """你是一位做产业研究的分析师，写的是给认真投资者看的个股深度分析。\
你的写作样本是那种"把一家公司拆开揉碎讲清楚"的公众号长文——有具体数字、有结构判断、\
有对市场预期的追问，但没有一句买卖建议。

硬性要求（全部必须遵守）：

1. 【只用给定事实】所有数字必须来自下面的「事实清单」。清单里没有的数字，一律不写。\
如果某个问题清单里没有对应数据，就明确写"这项没有公开数据"或"当前未采集"，绝不推测、绝不编造。\
这是最重要的一条——编一个数字比留一个空白糟糕得多。

2. 【每个小节至少 2 个数字】没有数字支撑的判断不要写。\
不写"公司竞争力较强"，要写"毛利率 53.7%，比同行高 X 个百分点"。

3. 【区分事实与判断】事实直接陈述；判断必须写成"从数据看…""这更可能是…"，\
并说明依据。不要把判断说成事实。

4. 【缺口必须声明】事实清单末尾列出的「缺口」，如果与本节相关，\
必须用一句话说明这项没有数据。不要假装什么都知道。

5. 【绝对不出现】买入、卖出、加仓、减仓、建仓、清仓、目标价、必涨、必跌、稳赚、\
推荐、建议持有、抄底、满仓、翻倍股。不给任何操作建议，不预测涨跌。

6. 【术语要解释】第一次出现时用一句人话说明：\
ROIC=每投 100 块能赚回多少；WACC=资金的机会成本；分位=在历史区间里排第几；\
自由现金流=经营收回的现金减去为维持和扩张花的钱。

7. 【句子短】一段 2-4 句。不用"综上所述""不难看出""值得关注"这类套话。\
不用排比句，不用感叹号。

8. 【口吻】像一个把财报翻烂了的人在跟你讲他看到了什么，不是券商研报，也不是营销文案。

只输出 JSON，不要 markdown 代码块，不要任何多余文字。结构：
{
  "title": "一句话点出这家公司最核心的矛盾，20字以内",
  "lead": "开篇总起，讲清这家公司是做什么的、当前最值得看的是什么，120-180字",
  "sections": [
    {"key": "business", "body": "350-500字"},
    {"key": "space", "body": "300-450字"},
    {"key": "moat", "body": "250-400字"},
    {"key": "numbers", "body": "300-450字"},
    {"key": "valuation", "body": "280-400字"},
    {"key": "risk", "body": "280-400字"}
  ],
  "summary": "手机端摘要，180-260字，只讲结论和最关键的三四个数字，不用小标题",
  "highlights": ["最关键的一条，25字以内", "第二条", "第三条"],
  "gaps": ["未取得的数据项，一句话一项"]
}"""


# ---------------------------------------------------------------- 事实渲染
def render_facts(pack):
    """把事实包渲染成提示词里的「事实清单」。

    按块分组，每条带编号（F1/F2...），方便模型引用，也方便事后核对。
    """
    lines = []
    n = 0
    labels = {
        'cashflow': '现金流画像',
        'capital_return': '资本回报',
        'valuation': '估值分位',
        'risk': '风险指标',
        'segment': '分部结构',
    }
    for block_key in ('segment', 'cashflow', 'capital_return', 'valuation', 'risk'):
        blk = (pack.get('blocks') or {}).get(block_key) or {}
        facts = blk.get('facts') or []
        if not facts:
            continue
        lines.append('【%s】' % labels.get(block_key, block_key))
        for f in facts:
            n += 1
            lines.append('  F%d. %s' % (n, f.get('text')))
    if not n:
        lines.append('（本次没有取得任何可用事实，请如实说明数据不可得）')

    gaps = pack.get('gaps') or []
    if gaps:
        lines.append('')
        lines.append('【缺口——必须在相关小节声明】')
        for g in gaps:
            lines.append('  - %s：%s' % (g.get('label'), g.get('reason')))
    return '\n'.join(lines), n


def render_framework():
    """把框架渲染成提示词里的写作大纲。"""
    out = []
    for s in SECTIONS:
        out.append('%s' % s['title'])
        out.append('  要回答：%s' % s['question'])
        out.append('  字数：%s 字' % s['words'])
    return '\n'.join(out)


# ---------------------------------------------------------------- 缓存
def _key(code, asof):
    return '%s_%s' % (code, str(asof or '')[:10].replace('-', ''))


def _path(code, asof):
    return os.path.join(CACHE_DIR, '%s.json' % _key(code, asof))


def _read(code, asof, max_age=None):
    p = _path(code, asof)
    if not os.path.exists(p):
        return None
    try:
        obj = json.load(open(p, encoding='utf-8'))
    except Exception:
        return None
    if max_age and time.time() - (obj.get('generated_at') or 0) > max_age:
        return None
    return obj


def _write(code, asof, obj):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = _path(code, asof) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, _path(code, asof))


# ---------------------------------------------------------------- 模型调用
def _api_key():
    for k in ('DEEPSEEK_API_KEY', 'STOCKSCORE_LLM_KEY'):
        v = os.environ.get(k)
        if v:
            return v
    # 服务器上的 api.env
    for p in ('/root/stockcheck-api/api.env',
              os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api.env')):
        try:
            for line in open(p, encoding='utf-8'):
                line = line.strip()
                if line.startswith('DEEPSEEK_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
        except Exception:
            continue
    return None


def _call_llm(pack, score_payload, facts_text, n_facts):
    key = _api_key()
    if not key:
        return None, 'no_api_key'

    user = []
    if score_payload:
        user.append('【打分卡结果】')
        user.append('总分 %s / 100，档位「%s」' % (score_payload.get('total'),
                                                  score_payload.get('tier')))
        tag = (score_payload.get('tag') or {}).get('label')
        if tag:
            user.append('标签：%s' % tag)
        for k in ('Q', 'V', 'M'):
            g = (score_payload.get('groups') or {}).get(k) or {}
            if g:
                user.append('  %s %s 分（权重 %s%%）：%s'
                            % (g.get('label'), g.get('score'),
                               g.get('weight'), g.get('question')))
        user.append('')

    user.append('【事实清单（共 %d 条，只能用这些数字）】' % n_facts)
    user.append(facts_text)
    user.append('')
    user.append('【写作大纲】')
    user.append(render_framework())
    user.append('')
    user.append('现在按大纲写，只输出 JSON。')

    body = {
        'model': LLM_MODEL,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': '\n'.join(user)},
        ],
        'temperature': 0.3,
        'max_tokens': 4000,
        'response_format': {'type': 'json_object'},
    }
    try:
        r = requests.post(LLM_URL, json=body, timeout=180,
                          headers={'Authorization': 'Bearer %s' % key,
                                   'Content-Type': 'application/json'})
        if r.status_code != 200:
            return None, 'http_%d: %s' % (r.status_code, r.text[:200])
        js = r.json()
        txt = (js.get('choices') or [{}])[0].get('message', {}).get('content') or ''
        return _parse_json(txt), None
    except Exception as e:
        return None, '%s: %s' % (type(e).__name__, str(e)[:160])


def _parse_json(txt):
    """解析模型输出。中文长文容易被截断成非法 JSON，取最外层花括号兜底。"""
    txt = (txt or '').strip()
    txt = re.sub(r'^```(?:json)?\s*', '', txt)
    txt = re.sub(r'\s*```$', '', txt)
    try:
        return json.loads(txt)
    except Exception:
        pass
    i, j = txt.find('{'), txt.rfind('}')
    if i >= 0 and j > i:
        try:
            return json.loads(txt[i:j + 1])
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- 组装
def _flatten(obj):
    """把 JSON 结构压成一段纯文本，供闸门检验。"""
    if not obj:
        return ''
    parts = [obj.get('title') or '', obj.get('lead') or '']
    for s in obj.get('sections') or []:
        parts.append(s.get('body') or '')
    parts.append(obj.get('summary') or '')
    parts.extend(obj.get('highlights') or [])
    return '\n'.join(p for p in parts if p)


def _rule_fallback(pack, score_payload):
    """模型不可用时的确定性文案：把事实拼成可读段落，不惊艳但一定诚实。"""
    blocks = pack.get('blocks') or {}
    def body_of(keys):
        out = []
        for k in keys:
            for f in (blocks.get(k) or {}).get('facts') or []:
                out.append(f.get('text') or '')
        return '；'.join(out) + '。' if out else ''

    sections = []
    for s in SECTIONS:
        b = body_of(s['slots'])
        if not b:
            b = '这一节需要的数据当前没有取得，暂不展开。'
        sections.append({'key': s['key'], 'body': b})

    gaps = ['%s：%s' % (g.get('label'), g.get('reason'))
            for g in (pack.get('gaps') or [])]
    lead = '以下是按规则自动汇总的事实，未经模型组织成文，仅列出已取得的数据。'
    if score_payload and score_payload.get('total') is not None:
        lead = '总分 %s 分（%s）。%s' % (score_payload.get('total'),
                                     score_payload.get('tier'), lead)
    return {
        'title': '数据汇总（未生成分析）',
        'lead': lead,
        'sections': sections,
        'summary': lead,
        'highlights': [f.get('text') for f in (pack.get('facts') or [])[:3]],
        'gaps': gaps,
    }


def get_or_build(code, asof, score_payload=None, force=False):
    """主入口：返回深度分析 + 闸门判定。

    返回 {
      'ok', 'source': 'llm'|'rule'|'cache',
      'content': {title, lead, sections, summary, highlights, gaps},
      'gate': {...}, 'n_facts', 'n_gaps', 'generated_at'
    }
    """
    if not force:
        c = _read(code, asof)
        if c:
            c = dict(c)
            c['source'] = 'cache'
            return c

    pack = F.build_facts(code, fin=(score_payload or {}).get('fin'),
                         extra=(score_payload or {}).get('extra'))
    facts_text, n_facts = render_facts(pack)

    obj, err = _call_llm(pack, score_payload, facts_text, n_facts)
    source = 'llm'
    if not obj or not obj.get('sections'):
        obj = _rule_fallback(pack, score_payload)
        source = 'rule'

    text = _flatten(obj)
    gate = G.evaluate(text, pack.get('facts') or [], pack.get('gaps') or [],
                      score_payload=score_payload,
                      required_slots=G.FRAMEWORK_SLOTS)

    out = {
        'ok': True,
        'source': source,
        'error': err,
        'code': code,
        'asof': asof,
        'content': obj,
        'gate': gate,
        'n_facts': n_facts,
        'n_gaps': len(pack.get('gaps') or []),
        'generated_at': int(time.time()),
    }
    if source == 'llm':
        _write(code, asof, out)
    return out


def to_mobile(out):
    """手机端视图：只留摘要、要点、缺口，不返回长文正文。

    与网页端同源派生（同一个 content 对象），保证口径一致。
    """
    c = out.get('content') or {}
    return {
        'title': c.get('title'),
        'summary': c.get('summary') or c.get('lead'),
        'highlights': (c.get('highlights') or [])[:4],
        'gaps': (c.get('gaps') or [])[:5],
        'verdict': (out.get('gate') or {}).get('verdict'),
        'source': out.get('source'),
    }
