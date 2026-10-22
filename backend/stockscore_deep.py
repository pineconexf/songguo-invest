# -*- coding: utf-8 -*-
"""深度分析层：逐段生成 + 数字回验 + 矛盾清单 + critic（2026-10-20）

## 定位

facts 层给"数字"，research 层给"行业与竞争"，narrative 层给"这个分数啥意思"。
本层给的是**一篇完整的深度分析**，体量对标微信公众号个股深度稿。

## 为什么不能"一次让模型写完"

一次性生成 3000 字必然出现三类问题：
  1. 数字漂移 —— 同一个指标前后不一致，或凭空多出没给过的数字
  2. 段落互相矛盾 —— 前文说壁垒强，后文说现金流差，两段都"对"但合起来自相矛盾
  3. 灌水 —— 外部数据缺失时，模型会靠常识补一段行业描述，看起来像那么回事

本层的解法是**分段生成 + 全局校验**：

  Step 1  切段：按 6 段固定骨架（业务结构/市场空间/竞争壁垒/数字检验/估值与预期/风险与安全）
  Step 2  逐段生成：每段只喂该段需要的 facts，不喂其他段，避免跨段串味
  Step 3  数字回验：全文每个数字都必须能在 facts 清单里找到，否则标为"待核"并重生成该段
  Step 4  矛盾清单：跨段检查同一主体的定性描述是否互斥，输出 contradictions
  Step 5  critic：让模型扮演挑刺的编辑，专门找问题（不是重写，是提意见）
  Step 6  裁决：按 critic 意见 + 矛盾清单决定是否重生成有问题的段

## 分层丰满度

外部数据覆盖度决定体量（对应 research.coverage_level）：
  A 级 → 六段全写，允许 2000–3000 字
  B 级 → 写能写的段（通常 4 段），缺失段落显式声明"该维度无公开数据源"
  C 级 → "短而实"：只写数字检验 + 风险与安全两段，800–1200 字，不注水

铁律：**宁可短，不注水**。缺口必须在正文里显式说出来。
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

LLM_URL = 'https://api.deepseek.com/chat/completions'
LLM_MODEL = 'deepseek-v4-flash'
# 审读模型单独用 deepseek-chat（2026-10-21 实测）：
# v4-flash 25.6s / chat 3.4s（快 7.5 倍），同一份 5250 字六段正文，
# 两者都报出 8 条意见、各含 3 条 high，chat 另抓出「隐含增速易被读成目标价暗示」。
# 审读只要求结构化挑刺，不需要 reasoning，chat 够用且省 22s/轮。
CRITIC_MODEL = 'deepseek-chat'
# 正文字模型（2026-10-21 实测对比，同一 prompt 六段并行）：
#   v4-flash 墙钟 11.7s（各段 5.5-11.7s）
#   chat    墙钟  4.5s（各段 1.8-4.5s）
# 质量对比（同一 critic 审两版）：flash 版 high 2 条 / chat 版 high 0 条，
# chat 版对「数据不可得」的处理更诚实（明说拿不到，不拿常识补），
# 字数也更实（market 段 293 字讲清楚缺口，而非凑数）。
# 代价是注水重复偏多（critic 报 3 条 medium 注水）——这由既有
# critic→重写闭环处理，与模型选择无关。
# 结论：正文改用 chat，速度 2.6 倍且质量不降；重写轮同样用 chat。
SECTION_MODEL = 'deepseek-chat'
LLM_TIMEOUT = 180

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'deep')

# 生成逻辑版本号：任何影响正文的改动都要 +1，让旧缓存自动失效
# 2026-10-20 v8：coverage 改为由调用方统一传入（研报通道 + 行业结构层），
# 避免 deep 页与 modules/口播页报出不同等级。
PIPELINE_VERSION = 28  # v28: 禁词从'换中性说法'改为'整句剔除'——换说法(如目标价→价格预期/上涨空间→上行空间/合理价位→价格中枢)本质仍是涨跌预测,用户已明令禁止变相预测; v27: 策略内部标签中性化(红旗/黄旗/域内域外/可投域/优质线/一票否决/不碰 → 风险项/关注项等)+ 提示层禁止使用这些标签; v26: tier_note 去掉 tag.desc(可投域/域内域外=选股结论),只留分数+档位+调档说明; v25: critic/unresolved/structure_issues 自由文本做内部术语+禁词中性化; v24: 正文 _strip_internal_terms + 金额统一亿元
_lock = threading.Lock()
# 内存缓存键带 PIPELINE_VERSION。
# 坑（2026-10-22）：原来键只有 (code, asof)，版本号升级后进程内
# 仍返回旧对象——磁盘缓存按版本失效了，内存缓存却没失效。
# 结果：改了生成逻辑但 prewarm 返回 "cached"，测的全是旧文本。
_MEM_KEY_VERSION = PIPELINE_VERSION


def _mem_key(code, asof):
    return (code, asof, _MEM_KEY_VERSION)


_mem = {}

# 段落的禁用词（与 narrative 层同一把尺子：不给操作建议）
BANNED_RE = re.compile(
    r'买入|卖出|加仓|减仓|建仓|清仓|目标价|必涨|稳赚|推荐|抄底|逃顶|'
    r'值得买|可以买|该买|该卖|满仓|空仓|加仓点|减仓点|目标价位')

# 变相目标价：2026-10-20 critic 实测抓到的。
# 「PE 回到历史中位 64.19，对应 24.4% 空间」——用分位倒算涨跌空间，
# 哪怕后面加「不是对股价的判断」的免责声明，实质仍然是价格预测。
# 所以这些表达直接禁掉，命中整句丢弃。
BANNED_PREDICT_RE = re.compile(
    r'对应\s*\d+(\.\d+)?\s*%?\s*(的)?\s*(上涨|下行|上行|涨幅|跌幅|空间)|'
    r'(上涨|下行|上行)\s*空间\s*(约|大概|为)?\s*\d|'
    r'若\s*PE\b.{0,20}\s*(回到|涨到|跌到)\s*\d|'
    r'对应\s*(的)?\s*\d+(\.\d+)?\s*%\s*(的)?(上涨|下行|空间)|'
    r'最坏情况下.{0,40}\d+(\.\d+)?\s*%|'
    r'跌到\s*\d|涨到\s*\d')

# 数字提取：含小数、百分号、万亿、倍
NUM_RE = re.compile(r'[-+]?\d+(?:\.\d+)?\s*(?:%|倍|亿|万亿|万|元|个百分点|pp)?')


# ================================================================== 段骨架
SECTIONS = [
    {'key': 'business', 'title': '业务结构',
     'brief': '公司靠什么赚钱，有哪些业务板块，各自占比和增速，商业模式的关键特征是什么',
     'min_chars': 180, 'max_chars': 600},
    {'key': 'market', 'title': '市场空间',
     'brief': '行业市场规模、增速、集中度，公司在其中的位置，需求来自哪里',
     'min_chars': 180, 'max_chars': 600},
    {'key': 'moat', 'title': '差异化壁垒',
     'brief': '公司凭什么赢，壁垒是技术、渠道、规模还是转换成本，护城河能不能守住',
     'min_chars': 180, 'max_chars': 600},
    {'key': 'numbers', 'title': '数字检验',
     'brief': '用财务数字检验前面三段的说法：增长是否真实、盈利质量如何、现金流是否跟上',
     'min_chars': 220, 'max_chars': 700},
    {'key': 'valuation', 'title': '估值与预期',
     'brief': '当前估值处在什么位置，市场预期是什么，与实际经营是否匹配，适用哪种估值方法',
     'min_chars': 200, 'max_chars': 600},
    {'key': 'risk', 'title': '风险与安全',
     'brief': '有哪些已兑现的风险、哪些是待观察的，安全边际有多大，最坏情况是什么',
     'min_chars': 200, 'max_chars': 700},
]

# 哪些段落依赖外部深度数据（research）
RESEARCH_DEPENDENT = {'business', 'market', 'moat'}

# 行业结构数据（stockscore_industry）作为第三个 facts 源。
# 定位：它不是"研报观点"，是自己从 tushare 成分股算出来的结构数据，
# 所以走 facts 通道而不是 research 通道（research 通道会被 coverage 降级裁掉）。
# 注入的段落：market（市场空间与竞争格局）、moat（竞争格局）、business（生意）。
INDUSTRY_FEED_SECTIONS = {'market', 'moat', 'business'}


# ================================================================== LLM
def _call(messages, key, temperature=0.3, max_tokens=3000, retries=2,
          with_meta=False, model=None):
    """调用 LLM。

    坑（2026-10-20 实测）：deepseek-v4-flash 会把 max_tokens 花在 reasoning_content 上，
    正文 content 直接返回空串、finish_reason='length'。段落生成时 max_tokens=1800 就踩过。
    修法：content 为空且 finish_reason='length' 时，**自动加倍预算重试**，
    而不是当作失败直接丢弃这一段。

    with_meta=True 时返回 (content, meta)，meta 含 finish_reason / 是否截断 /
    reasoning 字符数。
    坑（2026-10-20 实测·第二轮）：critic 形同虚设的根因是
    **调用方看不到 finish_reason**——被截断了还以为写完了，
    于是只按残缺 JSON 抢救，17 条意见只救回 1 条。截断信息必须从源头透出来。
    """
    body = {'model': model or LLM_MODEL, 'messages': messages,
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
            reasoning = (choice.get('message') or {}).get('reasoning_content') or ''
            fr = choice.get('finish_reason')
            meta = {'finish_reason': fr, 'truncated': fr == 'length',
                    'reasoning_chars': len(reasoning), 'max_tokens': budget}
            if not content.strip() and fr == 'length' and budget < 16000:
                # 预算被 reasoning 吃光 —— 加倍再试
                budget = min(budget * 2, 16000)
                continue
            if not content.strip():
                # 没被截断却也空：换更保守的提示再试一次
                budget = min(budget * 2, 16000)
                if attempt < retries:
                    continue
                last = 'LLM 返回空内容 (finish_reason=%s)' % fr
                break
            if with_meta:
                return content.strip(), meta
            return content.strip()
        except RuntimeError:
            raise
        except Exception as e:                       # noqa: BLE001
            last = '%s: %s' % (type(e).__name__, e)
            time.sleep(2 + attempt * 3)
    raise RuntimeError(last or 'LLM 调用失败')


# ================================================================== 事实打包
def _num_only(x):
    """把一个值规范化成可匹配的数字串集合。"""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return set()
    out = {'%g' % f}
    if f == int(f):
        out.add(str(int(f)))
    out.add(('%.1f' % f).rstrip('0').rstrip('.'))
    out.add(('%.2f' % f).rstrip('0').rstrip('.'))
    # 千分位/万/亿 变体
    for mul, suf in ((1e8, '亿'), (1e4, '万')):
        v = f * mul
        out.add('%g' % v)
        if v == int(v):
            out.add(str(int(v)))
        out.add(('%g' % v) + suf)
    return out


def build_whitelist(facts_blocks, research_facts, industry_facts=None):
    """建立"允许出现的数字"白名单。

    来自：所有 facts 的 value 字段 + text 里出现的数字 + research 抽取项里的数字
    + 行业结构数据里的数字（2026-10-20 新增）。
    """
    wl = set()
    for blk in (facts_blocks or []):
        for f in (blk if isinstance(blk, list) else blk.get('facts') or []):
            if not isinstance(f, dict):
                continue
            v = f.get('value')
            if isinstance(v, (int, float)):
                wl |= _num_only(v)
            for m in NUM_RE.finditer(str(f.get('text') or '')):
                tok = m.group(0).replace(' ', '')
                num = re.match(r'[-+]?\d+(?:\.\d+)?', tok)
                if num:
                    wl |= _num_only(num.group(0))
    for f in (research_facts or []):
        for m in NUM_RE.finditer(json.dumps(f, ensure_ascii=False)):
            tok = m.group(0).replace(' ', '')
            num = re.match(r'[-+]?\d+(?:\.\d+)?', tok)
            if num:
                wl |= _num_only(num.group(0))
    for t in (industry_facts or []):
        for m in NUM_RE.finditer(str(t)):
            tok = m.group(0).replace(' ', '')
            num = re.match(r'[-+]?\d+(?:\.\d+)?', tok)
            if num:
                wl |= _num_only(num.group(0))
    return wl


# ================================================================== 段落生成
SECTION_SYSTEM = """你是一位资深买方研究员，写个股深度分析。你拿到的是**已经核实过的数字清单**，
现在要把这些数字组织成一段可读的分析。

铁律：
1. **只能用清单里的数字**，一个字都不许改。清单里没有的数字绝对不许出现。
2. 禁止出现：买入、卖出、加仓、减仓、建仓、清仓、目标价、必涨、稳赚、推荐、抄底、逃顶、
   值得买、可以买、该买、该卖、满仓、空仓。
3. 不预测涨跌，不给操作建议。只分析公司现在的状态。
4. 少用术语，必须用时立刻跟一句人话解释。
5. 句子短，一段 3–6 句。不要排比，不要"综上所述""不难看出"这类套话。
6. 指标名照抄清单里的叫法，不要自己换算成别的指标，不要把两个指标混着说。
7. 清单里明确写了"数据不可得"的，就直说这个维度拿不到数据，**不许用常识补**。
8. 如果清单给的信息不足以支撑一个完整判断，就写得短而实，**不许注水凑字数**。
9. **不要重复别的段落已经用过的数字**。本段只讲本段的事，前面段落讲过的核心数字不要再抄一遍。
   除非本段必须引用它做对照（那就一句话带过，不要展开）。
10. 本段尽量引入清单里**别的段落还没用**的数字，让各段信息量不重复。
11. **不要用策略内部标签**（红旗、黄旗、域内、域外、可投域、优质线、一票否决、不碰）。
    要说风险就直说具体是什么风险（如"单季扣非同比 -671%"），不要说"命中红旗"。
11. **绝对不许用历史分位倒算涨跌空间**。不许写"PE 回到历史中位对应多少空间"、
    "跌到某个位置意味着多少跌幅"这类话。分位只能说明"现在的价格在历史什么位置"，
    停在刻度上，不许往前推价格。
12. 如果本段主题的核心数据清单里没有，就**明说"这个维度拿不到数据"**，
    然后写能拿到的部分。**不许用别的段落的数字凑数、不许用常识补、不许注水。**
    宁可本段只有两三句实话。
13. **"数据不可得"和"数据为负"是两回事，不许混用**。
    清单里写了"不可得/缺失"，才是拿不到；清单里给了具体负数，
    就说"是负的"，**不许写成"不可得"**。同理，
    清单里没给 EBITDA 却给了 FCF，就不能说"FCF 不可得"。
    宁可只说清单里有的那个。
14. 引用阈值时必须同时给出阈值的来源口径（哪来的、什么标准），
    清单里没写阈值的就不要提具体百分比。
15. **不许自己算清单里没有的派生数字**。清单给了 6.64 亿元和上年 6.35 亿元，
    你不许自己算出"增长 4.6%"——要写增长就引用清单里已有的同比口径。
    清单给了"同比下降 45.7%"，就不许再用两个绝对值反算出别的幅度。
    派生数字一律不许出现，宁可只说绝对值。
16. **不许把别的段落的数字抄过来充数**。本段主题的数据如果就那么点，
    就把那几个数字讲透（讲清楚它是什么、跟什么比、口径是什么），
    不要靠复述别段已经说过的内容来撑长度。
    如果本段确实没有独有信息，就写清楚"这块没有可核验数据"然后收尾，
    不要写满字数。**宁可短，不注水**。

17. **估值一律以扣非口径为主**。清单里如果给了「扣非归母净利」「扣非归母净利(TTM)」
    「PE(扣非TTM)」，就必须以扣非口径陈述，表观 PE 只能作为一句对照，
    并说明它的分母含非经常性损益。清单说扣非口径 PE 不成立（扣非亏损）时，
    就直说「扣非口径 PE 不成立，PE 这个指标在这里没有意义」，
    **不许把表观 PE 写成估值结论**。不给扣非口径数字时，不许自己拿归母净利减非经常损益凑一个。
18. 归母净利与扣非归母净利差距大时，差距本身就是结论，要讲出来
    （利润里有多少不是主业挣的）。
19. **引述研报数字必须标报告期，并说明与最新财报期的口径差**。
    研报用的是它披露日的报表期（常常是上一期中报），清单里的「报告期」是更新的期次，
    两者数字不一样是正常的口径差。但必须写清楚「研报口径为 X 期，最新财报为 Y 期」，
    不许让读者以为是同一个数的两个版本，更不许用「以清单为准」一句话把差异盖过去。
21. **同一段内不许出现互相矛盾的表述**。每段写完自查一遍：
    前半句说「资产端缓冲还算厚」、后半句说「不构成安全垫」，这就是矛盾，统一成一个结论。
    另外两条硬约束：
    - 市值占比 ≠ 收入份额。**不许**用「占行业市值 0.07%」论证规模壁垒或规模劣势；
      清单里没有收入份额就明说「收入份额数据不可得」。
    - 清单里标了「不成立」「仅供参考」「不构成…判断」的指标，后续推理不许拿它当结论依据。
22. **核心数字不要在多段重复**。同一组数字（扣非净利、经营现金流、自由现金流、
    「扣非 PE 不成立」）只在最能说明问题的那一段展开写，其他段落只引用结论、不复述数字，
    不许三段近乎逐字重复。
23. **不许用「价格位置不高/偏低/处于低估区」这类措辞下结论**。分位数字就写分位数字；
    数据源自带的判定词（合理偏低/低估区）最多引一次，且要说明它基于表观口径、含非经常性损益。
24. **用 TTM 口径下结论时必须说清构成**。比如报告期扣非为正、TTM 扣非为负，
    要说明是哪个季度由盈转亏，或明说季度构成不可得，不许只说「已经亏损」。
25. 引述研报的 EPS / PE 前先做一次自洽检查：研报 EPS × 股本 ≈ 市值。
    与清单总市值对不上，说明研报用的是另一个价格日或另一个股本口径，
    要么写明差异来源，要么不写这个数——不许把两个互斥的数字并排放进正文。

只输出 JSON：{"text":"这段分析"}"""


def _section_prompt(sec, facts_lines, research_lines, name, code, coverage,
                    industry_lines=None):
    parts = []
    parts.append('公司：%s（%s）' % (name, code))
    parts.append('本段任务（%s）：%s' % (sec['title'], sec['brief']))
    parts.append('目标字数：%d–%d 字' % (sec['min_chars'], sec['max_chars']))
    if industry_lines:
        parts.append('\n【行业结构数据（从申万行业成分股实算，可直接引用）】\n'
                     + '\n'.join(industry_lines))
    if research_lines:
        parts.append('\n【券商研报正文抽取的事实（已逐字回验，可直接引用）】\n'
                     + '\n'.join(research_lines))
    else:
        parts.append('\n【券商研报正文抽取的事实】\n（本次没有抓到可回验的研报要点。'
                     '如果本段需要行业空间/竞争格局这类研报信息，你必须直说"该维度无公开数据源"，'
                     '不许用常识或印象编写。）')
    parts.append('\n【可用数字与事实清单（唯一可引用的来源）】\n'
                 + ('\n'.join(facts_lines) if facts_lines else '（本段无数字清单）'))
    if coverage == 'C':
        parts.append('\n【注意】本股外部深度数据覆盖度为 C 级。若清单不足以写满，'
                     '就写短一些并显式说明缺什么，不要注水。')
    return '\n'.join(parts)


def _pick_facts(all_facts, sec_key, max_lines=28, used_idx=None):
    """按段落主题挑相关 facts。

    做法：每个 facts 条目带 label，按关键词打分匹配，取分最高的。
    落选的也保留若干条通用财务条，保证不漏关键数字。

    used_idx：前面段落已经用过的 fact 下标。这些条目**降权但不排除**——
    坑（2026-10-20 实测）：同一组数字在五个板块被反复照抄，
    critic 专门挑出了这条。降权让后续段落优先用没出现过的数字。
    """
    kw = {
        'business': ['业务', '主营', '分部', '构成', '产品', '客户', '收入'],
        'market': ['行业', '市场', '空间', '景气', '份额', '市占', '需求', '规模', '增速'],
        'moat': ['壁垒', '竞争', '毛利', 'ROIC', '研发', '技术', '优势', '护城河', '定价'],
        'numbers': ['现金流', '毛利', '净利', 'ROIC', 'ROE', '应收', '存货', '负债', '增长',
                    '同比', '费用', '周转', '毛利', '净现', '扣非', '非经常', '归母'],
        'valuation': ['估值', 'PE', 'PB', 'PS', '分位', '市值', 'EPS', '预期', 'PEG',
                      '股息', 'DCF', 'EV'],
        # 2026-10-20 修：risk 段原来挑不到「PE(扣非TTM)」这条 fact，
        # 于是 risk 段写「扣非口径的PE清单里没有给」，而 valuation 段写「扣非 PE 不成立」，
        # 两段自相矛盾（688508 实测）。补上 PE/扣非/估值 关键词。
        'risk': ['风险', 'Beta', '回撤', '波动', '商誉', '杠杆', '负债', '质押', '解禁',
                 '换手', '成交', '安全边际', '现金', '覆盖', 'PE', '扣非', '估值', '非经常'],
    }.get(sec_key, [])
    used = used_idx or set()

    scored = []
    for i, f in enumerate(all_facts):
        lab = str(f.get('label') or '')
        txt = str(f.get('text') or '')
        s = sum(2 for k in kw if k in lab) + sum(1 for k in kw if k in txt)
        if i in used:
            s -= 3                      # 前面用过了，降权（不是排除）
        scored.append((s, -i, i, f))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [(f, i) for _, _, i, f in scored[:max_lines]]


def _extract_text(raw):
    """从模型原始输出里稳健地抽出正文。

    三个失败模式都要兜住：
      1. 正常 JSON {"text": "..."}
      2. 包了 ```json 代码块
      3. 被 max_tokens 截断的 JSON —— 丢掉 JSON 外壳，把字符串内容救出来
    """
    if not raw:
        return ''
    s = raw.strip()
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
    # 截断兜底：抓 "text" 后面那段字符串
    m = re.search(r'"text"\s*:\s*"(.*)', s, re.S)
    if m:
        t = m.group(1)
        # 截断在转义中间，先去掉尾部不完整转义
        t = re.sub(r'\\$', '', t)
        t = t.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
        t = re.sub(r'\\u[0-9a-fA-F]{4}', '', t)
        return t.strip().strip('"').strip()
    return s


def _gen_section_from_prompt(sec, user, key, extra_note=''):
    """按已拼好的 prompt 调 LLM 出正文（并行体与重写共用）。

    2026-10-21 新增：把原来 _gen_section 里「拼 prompt」和「调 LLM」拆开。
    并行生成时 prompt 拼装要按原顺序先算完（事实降权依赖顺序），
    LLM 调用本身没有顺序依赖，所以拆成两步。
    """
    if extra_note:
        user = user + '\n\n【重写要求】上一次生成被校验拦下，问题：' + extra_note
    try:
        raw = _call([{'role': 'system', 'content': SECTION_SYSTEM},
                     {'role': 'user', 'content': user}], key,
                    temperature=0.35, max_tokens=2600, model=SECTION_MODEL)
        text = _extract_text(raw)
        # 截断检测（2026-10-20 实测）：critic 抓到过一段
        # "……预期与经营的差距"戛然而止——句子没有谓语也没有结论。
        # 根因是 max_tokens 用完（finish_reason=length），
        # JSON 虽然能解析但正文被砍在半句。检测到就重试一次。
        for _try in range(2):
            if not _looks_truncated(text):
                break
            raw = _call([{'role': 'system', 'content': SECTION_SYSTEM},
                         {'role': 'user', 'content': user +
                          '\n\n【注意】上一版结尾被截断了，'
                          '请把最后一段写完整，说完这句话。'}], key,
                        temperature=0.35, max_tokens=3200, model=SECTION_MODEL)
            text = _extract_text(raw)
        return text, []
    except Exception as e:                           # noqa: BLE001
        return '（本段生成失败：%s）' % (str(e)[:60],), []


def _looks_truncated(text):
    """判断一段文本是否被截断在半句。"""
    t = (text or '').strip()
    if not t:
        return True
    if t[-1] not in '。！？!?）)」”"…':
        return True
    # 末句太短（<8 字）且没有标点 → 典型的半句截断
    last = re.split(r'[。！？!?\n]', t)[-1] if t else ''
    if last and len(last.strip()) < 8 and '，' in t[-30:]:
        return True
    return False


# ================================================================== 数字回验
def verify_numbers(text, whitelist, sec_facts):
    """找出文中不在白名单的数字。返回 {'bad': [...], 'ok': bool}"""
    bad = []
    src = ' '.join(str(f.get('text') or '') for f in sec_facts)
    for m in NUM_RE.finditer(text or ''):
        tok = m.group(0).replace(' ', '')
        num_m = re.match(r'[-+]?\d+(?:\.\d+)?', tok)
        if not num_m:
            continue
        raw = num_m.group(0)
        # 排除年份、序号、常见小整数
        if raw in ('1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '100'):
            continue
        # 排除所有年份（1900-2099）。坑（2026-10-20 实测）：硬编码只排到 2027，
        # 研报里出现"2028 年量产"就被判成未核实数字。
        if len(raw) == 4 and raw.isdigit() and 1900 <= int(raw) <= 2099:
            continue
        if _num_only(raw) & whitelist:
            continue
        # 允许 1.1 倍这种由白名单除出来的？严格起见不算
        if raw in src:
            continue
        bad.append(raw)
    # 去重保序
    seen, uniq = set(), []
    for b in bad:
        if b not in seen:
            seen.add(b)
            uniq.append(b)
    return {'bad': uniq, 'ok': not uniq}


def audit_structure(text):
    """机械结构审计（零 token）：序号断号。
    窄口径，只认列举标记，避免「第三季度」「第一梯队」这类误报。
    起因（2026-10-20）：让 6 段全重写后，business 段生成「商业模式上有两个硬约束。二是投入前置…」，
    「一是」整条丢了；复审靠 LLM 才发现，白烧一轮 token。"""
    probs, t = [], text or ''
    for ch in '二三四五':
        if ('%s是' % ch) in t and '一是' not in t:
            probs.append('列举出现「%s是」但缺「一是」，序号断号' % ch)
            break
    for ch in '二三四五':
        if ('第%s条' % ch) in t and '第一条' not in t:
            probs.append('列举出现「第%s条」但缺「第一条」，序号断号' % ch)
            break
    for ch in '二三四五':
        if ('第%s点' % ch) in t and '第一点' not in t:
            probs.append('列举出现「第%s点」但缺「第一点」，序号断号' % ch)
            break
    if '其次' in t and '首先' not in t:
        probs.append('出现「其次」但缺「首先」，序号断号')
    if '再次' in t and '其次' not in t:
        probs.append('出现「再次」但缺「其次」，序号断号')
    return probs


def audit_numbers(text):
    """机械数字自洽审计（零 token）：只查「市值 ÷ PE 应等于净利」这一个三角。
    起因（2026-10-20）：valuation 段写总市值 83.27 亿、又引研报 PE 56 倍，
    两者隐含净利约 1.49 亿，与文中归母净利差 26%+，没人解释。窄口径换低误报。"""
    probs, t = [], text or ''

    def _f(x):
        try:
            return float(x)
        except Exception:
            return None

    mv = re.search(r'总市值[^0-9\-]{0,10}(-?[\d.]+)\s*亿', t)
    pe = (re.search(r'PE[^0-9\-]{0,14}([\d.]+)\s*倍', t)
          or re.search(r'市盈率[^0-9\-]{0,14}([\d.]+)\s*倍', t))
    npf = re.search(r'(?:归母净利润|净利润)[^0-9\-]{0,14}(-?[\d.]+)\s*亿', t)
    if mv and pe and npf:
        m, p, n = _f(mv.group(1)), _f(pe.group(1)), _f(npf.group(1))
        if m and p and n and m > 0 and p > 0 and n > 0:
            implied = m / p
            gap = abs(implied - n) / n
            if gap > 0.25:
                probs.append(
                    '市值 %.2f 亿 ÷ PE %.1f 倍 = 隐含净利 %.2f 亿，'
                    '与文中净利 %.2f 亿差 %.0f%%，未说明口径'
                    % (m, p, implied, n, gap * 100))
    return probs


def _norm_cn(t):
    """去空白与标点，只留中文/字母/数字，供跨段重复比对。"""
    return re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', t or '')


def cross_section_repeats(sections, min_secs=3, limit=6,
                          skip=('numbers', 'valuation')):
    """跨段重复检测（零 token）：12 字 shingle 同时在 >=3 个「叙述段」出现 → 判注水。
    2 段共享视为正常引用，不报，压低误伤。
    numbers/valuation 不参与判定：这两段的本职就是复核业务段用过的数字，
    把它们算成注水会逼写手删掉检验内容（v20 实测：numbers 段被砍到 197 字，
    三节「数字检验」只剩一句过渡，直接崩）。
    起因（2026-10-20）：business 段「研报口径新品数据」在业务/市场/壁垒三节重复三遍，
    prompt 规则 22 只覆盖「核心数字不跨段重复」，定性描述没人管。
    返回 [(片段, [出现在哪些段...]), ...]，按涉及段数降序。"""
    SH = 12
    use = [s for s in sections if s['key'] not in skip]
    norms = {s['key']: _norm_cn(s['text']) for s in use}
    idx = {}
    for s in use:
        t = norms[s['key']]
        seen = set()
        for i in range(0, len(t) - SH + 1):
            g = t[i:i + SH]
            if g in seen:
                continue
            seen.add(g)
            idx.setdefault(g, []).append(s['key'])
    reps = [(g, ks) for g, ks in idx.items()
            if len(ks) >= min_secs
            # 至少 8 个汉字才算「一句话」；否则命中的是 PowerModule系列 这类产品名，
            # 产品名跨段出现是正常的，报出来只会逼写手删掉必要信息。
            and sum(1 for c in g if '\u4e00' <= c <= '\u9fa5') >= 8]
    reps.sort(key=lambda x: (-len(x[1]), x[0]))
    # 同一句话会切出 12 个相邻 shingle，用 8 字重叠判同源，只报一条
    picked = []
    for g, ks in reps:
        dup = False
        for p, _ in picked:
            if g[:8] in p or p[:8] in g:
                dup = True
                break
            if any(g[i:i + 8] in p for i in range(0, len(g) - 7)):
                dup = True
                break
        if dup:
            continue
        picked.append((g, ks))
        if len(picked) >= limit:
            break
    return picked


# ================================================================== 金额单位统一
# 2026-10-22：用户要求"所有出现的金额数字，精简到亿元单元"。
# 坑：LLM 写正文时会把金额写成"6,400 万元""12.3 亿元""1,234,567,890 元"混着来，
# 有的带千分位、有的不带，单位还随上下文漂移。必须后处理统一，
# 否则同一页会出现三种金额写法，读者得自己换算。
#
# 规则：
#   - "X 万元" → 换算成亿元；不足 1 亿的保留"万元"（换算会写成 0.00 亿元，丢信息）
#   - "X 元"    → 换算成亿元；不足 1 亿的保留"万元"
#   - "X 亿元"  → 保留，只做千分位规范
#   - 已经带"亿"字的数字不动
#   - 百分比、倍数、股数、股价一律不动（这些不是金额）
_AMT_WAN = re.compile(r'([\d][\d,，\.]*)\s*万元')
# 裸"元"：只匹配长整数（>=7 位），因为股价/单价都是小数值，不该被当成金额换算。
# 负向断言排除 亿/万/美/欧/日/港/英/澳/加/瑞（美元、欧元、港元不是人民币金额）。
_AMT_YUAN = re.compile(r'([\d]{1,3}(?:[\d,，]{3,})+|\d{7,})\s*元(?![亿万美欧日港英澳加瑞])')
_AMT_YI = re.compile(r'([\d][\d,，\.]*)\s*亿元')


def _amt_to_yi_str(numtxt):
    """把一个金额数字串统一换成亿元口径的可读字符串。

    用户口径（2026-10-22）：所有金额一律用"亿元"，不因金额小就回落成万元/元。
    小额写成 0.00 亿元会丢信息，所以小于 0.01 亿元时保留 4 位小数。
    """
    t = str(numtxt).replace(',', '').replace('，', '').strip()
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    yi = v / 1e4
    nd = 2 if abs(yi) >= 0.01 else 4
    txt = '{:,.{}f}'.format(yi, nd).rstrip('0').rstrip('.')
    if txt in ('', '-0'):
        txt = '0'
    return txt + ' 亿元'


# 内部生产流程术语 → 中性说法。
# 正文是 LLM 写的，它会描述"这一段经过二审重写""仍有审读意见未解"
# —— 那是我们的流水线内部说法，用户看到只会莫名其妙。
# 在源头（正文生成后）就收口，不依赖前端过滤。
_INTERNAL_TERMS = [
    (r'二审重写', '二次修订'),
    (r'三审重写', '复核修订'),
    (r'二审', '二次修订'),
    (r'三审', '复核'),
    (r'审读意见未解', '待确认项'),
    (r'仍有审读意见未解', '仍有待确认项'),
    (r'审读意见', '复核意见'),
    (r'审读', '复核'),
    (r'审稿', '复核'),
    (r'审校', '复核'),
    (r'内容自检', '质量检查'),
    (r'自检', '检查'),
    (r'未解问题', '待确认项'),
    (r'未解', '待确认'),
    (r'改法', '修订方式'),
    (r'Critic', '复核'),
    (r'critic', '复核'),
    # 2026-10-22：策略内部口径术语 → 中性说法。
    # "红旗/黄旗/域内/域外/可投域/优质线/一票否决/不碰" 都是选股策略
    # 的内部标签，对"普通股票质地查询"的用户没有意义，且会误导成买卖结论。
    (r'红旗', '风险项'),
    (r'黄旗', '关注项'),
    (r'一票否决', '硬性风险'),
    (r'可投域内', '通过基础门槛'),
    (r'可投域外', '未通过基础门槛'),
    (r'可投域', '基础门槛'),
    (r'域内候选', '门槛达成'),
    (r'域外优质', '门槛未达成'),
    (r'优质线', '质地参考线'),
    (r'不碰', '需回避'),
]


# 被禁措辞的剔除：复核意见里可能引用被禁措辞
# （例如"易被读成隐含目标价"）。用户端不能出现这些词本身，
# 也不能出现同义的变相说法（"上行空间""价格中枢""回报预期"本质仍是涨跌预测），
# 所以命中即整句剔除，而不是换个说法保留。
_BANNED_PHRASES = [
    r'目标价', r'上涨空间', r'上行空间', r'下行空间', r'合理价位', r'价格中枢',
    r'估值区间', r'估值带', r'预期回报', r'回归中位空间', r'回归中位幅度',
    r'涨跌空间', r'空间测算',
]
_BANNED_SPLIT = re.compile(r'(?<=[。；;！!？?])')


def _neutralize_banned(text):
    # 剔除含涨跌预测措辞的句子（整句丢弃，保留其余句子）
    if not text:
        return text
    out = str(text)
    kept = [s for s in _BANNED_SPLIT.split(out)
            if not any(re.search(p, s) for p in _BANNED_PHRASES)]
    return ''.join(kept).strip()


def _strip_internal_terms(text):
    if not text:
        return text
    out = text
    # 先整段删掉"（已按审读意见重写）"这类括号标记 ——
    # 光换词会留下"（已按复核意见重写）"，还是流水线口吻。
    out = re.sub(r'[（(][^）)]*(审读|重写|二审|三审|未解|自检)[^）)]*[）)]', '', out)
    for pat, rep in _INTERNAL_TERMS:
        out = re.sub(pat, rep, out)
    return out


def _normalize_money(text):
    """正文金额单位统一到亿元（2026-10-22）。"""
    if not text:
        return text
    s = text
    # 先处理"亿元"，避免后面的"元"正则把"亿元"拆掉
    s = _AMT_YI.sub(lambda m: m.group(1) + ' 亿元', s)
    s = _AMT_WAN.sub(lambda m: (_amt_to_yi_str(m.group(1)) or m.group(0)), s)
    s = _AMT_YUAN.sub(lambda m: (_amt_to_yi_str(m.group(1)) or m.group(0)), s)
    return s


def _guard_banned(text):
    """命中禁词整句丢弃。返回 (清洗后文本, 命中词列表)"""
    hits = BANNED_RE.findall(text or '')
    pred_hits = BANNED_PREDICT_RE.findall(text or '')
    if not hits and not pred_hits:
        return text or '', []
    parts = re.split(r'(?<=[。！？!?；;])', str(text))
    keep = [s for s in parts
            if s.strip() and not BANNED_RE.search(s) and not BANNED_PREDICT_RE.search(s)]
    return ''.join(keep).strip(), sorted(set(hits) | set(p[0] if isinstance(p, tuple) else p
                                                      for p in pred_hits))


# ================================================================== 矛盾检测
# 指标别名 → 极性词。同一个指标出现相反极性词，才算真矛盾。
# 只比"同一指标"，不同指标一升一降是正常现象（收入增、现金流降），不算矛盾。
METRIC_POLARITY = [
    (r'毛利率', ('提升', '上升', '提高', '改善', '回升'), ('下降', '下滑', '回落', '走低', '承压', '减少')),
    (r'净利率|利润率', ('提升', '上升', '提高', '改善'), ('下降', '下滑', '回落', '走低', '承压')),
    (r'ROIC|ROE|投入资本回报|净资产收益', ('提升', '上升', '提高', '改善'), ('下降', '下滑', '回落', '走低')),
    (r'现金流', ('改善', '转正', '回升', '增长'), ('为负', '转负', '恶化', '下滑', '流出')),
    (r'收入|营收|销售额', ('高增长', '高速增长', '快速增长'), ('下滑', '负增长', '萎缩')),
    (r'份额|市占率', ('提升', '上升', '提高'), ('下降', '下滑', '回落', '丢失')),
    (r'负债率|杠杆', ('上升', '提高', '恶化'), ('下降', '回落', '改善')),
    (r'存货周转|应收周转', ('加快', '改善', '提升'), ('变慢', '恶化', '拉长', '下降')),
]

# 明确互斥的定性词对（同一主体才比）
EXCLUSIVE_PAIRS = [
    ('壁垒稳固', '壁垒不牢'),
    ('有壁垒', '无壁垒'),
    ('净现金', '净负债'),
    ('龙头', '出局者'),
    ('低估', '高估'),
]

# 某些词有多义，必须带上下文锚点才算数。
# 坑（2026-10-20 实测）：「市销率已在低估区」vs「只看归母净利润会高估这家公司
# 当期主业赚到的钱」——第二个「高估」说的是利润不是估值，被误判成估值矛盾。
# 修法：命中词所在小句必须同时出现锚点词，否则该命中不算。
PAIR_ANCHORS = {
    '低估': ('估值', '市盈率', '市净率', '市销率', 'PE', 'PB', 'PS',
             '分位', '价格', '股价', '区间', '刻度'),
    '高估': ('估值', '市盈率', '市净率', '市销率', 'PE', 'PB', 'PS',
             '分位', '价格', '股价', '区间', '刻度'),
}


def _sentences(text):
    return [s for s in re.split(r'[。！？!?\n]', text or '') if s.strip()]


def _clauses(sent):
    """把句子按标点切成小句。极性词必须和指标在**同一小句**才算数。

    否则「研发费率同比提高 1.55pct，毛利率同比下降」会被误判成毛利率既升又降。
    """
    parts = re.split(r'[，,、；;：:]', sent)
    return [p for p in parts if p.strip()]


def detect_contradictions(sections):
    """跨段矛盾检测（精确版）。

    规则：同一指标、同一小句里出现相反极性词才算矛盾。
    不同指标一升一降是正常现象（收入增、现金流降），不算。
    """
    out = []
    texts = {s['key']: s.get('text', '') for s in sections}
    titles = {s['key']: s['title'] for s in sections}

    # 1) 同指标极性冲突
    for metric_re, up_words, down_words in METRIC_POLARITY:
        hit_up, hit_down = [], []
        for key, txt in texts.items():
            for sent in _sentences(txt):
                for cl in _clauses(sent):
                    if not re.search(metric_re, cl):
                        continue
                    if any(w in cl for w in up_words):
                        hit_up.append((key, cl))
                    if any(w in cl for w in down_words):
                        hit_down.append((key, cl))
        if hit_up and hit_down:
            ku, su = hit_up[0]
            kd, sd = hit_down[0]
            if ku == kd:
                continue
            out.append({
                'type': 'contradiction',
                'detail': '同一指标「%s」前后表述相反' % metric_re,
                'a': titles.get(ku, ku), 'b': titles.get(kd, kd),
                'a_text': su[:140], 'b_text': sd[:140]})

    # 2) 定性互斥词对
    #    坑（2026-10-20）：「账面上的净现金是负的」和「处于净负债状态」说的是同一件事，
    #    却被判成矛盾。修法：命中词所在小句里若带否定词（负/不是/没有/缺/不足），
    #    该命中视为"被否定的表述"，不算数。
    NEG = ('负', '不是', '没有', '缺', '不足', '低于', '小于', '为零', '没有净')
    for wa, wb in EXCLUSIVE_PAIRS:
        def _hits(word):
            """某词的有效命中：命中词 + 无否定 + 满足锚点要求。"""
            anchors = PAIR_ANCHORS.get(word)
            res = []
            for k, t in texts.items():
                for sent in _sentences(t):
                    for cl in _clauses(sent):
                        if word not in cl:
                            continue
                        if any(n in cl for n in NEG):
                            continue
                        if anchors and not any(a in cl for a in anchors):
                            continue
                        res.append((k, cl))
                        break
            return res

        ka = _hits(wa)
        kb = _hits(wb)
        if ka and kb and ka[0][0] != kb[0][0]:
            out.append({'type': 'contradiction',
                        'detail': '「%s」与「%s」互斥' % (wa, wb),
                        'a': titles.get(ka[0][0], ka[0][0]),
                        'b': titles.get(kb[0][0], kb[0][0]),
                        'a_text': ka[0][1][:140], 'b_text': kb[0][1][:140]})
    # 3) 段内自相矛盾：同一段里先说"方向不一致"又说"方向一致"
    #    坑（2026-10-20 实测）：估值段前半句"三个分位给出的方向并不一致"，
    #    后半句"拉长到10年，三者分位分别是…方向一致"——同一段自己打自己。
    #    这是纯逻辑错误，必须查出来。
    CONSIST = re.compile(r'方向\s*(并)?不?一致|结论\s*(并)?不?一致|不一致')
    CONSIST_REV = re.compile(r'方向\s*一致|结论\s*一致')
    for key, txt in texts.items():
        if not txt:
            continue
        c1 = CONSIST.search(txt)
        c2 = CONSIST_REV.search(txt)
        if c1 and c2:
            # 确认不是同一处文字（"方向不一致"里也含"一致"）
            if c1.start() != c2.start():
                out.append({
                    'type': 'contradiction',
                    'detail': '同一段内先说不一致、又说一致',
                    'a': titles.get(key, key), 'b': titles.get(key, key),
                    'a_text': txt[max(0, c1.start() - 40):c1.start() + 60],
                    'b_text': txt[max(0, c2.start() - 40):c2.start() + 60]})
                break
    return out


# ================================================================== critic
CRITIC_SYSTEM = """你是一位严格到近乎苛刻的证券研究编辑，负责审阅一篇个股深度分析。
你**只提意见，不重写文章**。

你要检查：
1. **数字一致性**：同一指标在文中不同段落出现的数字是否一致？有没有和事实清单矛盾？
2. **逻辑自洽**：前文的判断能不能支撑后文的结论？有没有自相矛盾？
3. **注水**：哪些段落是空话、没有信息量？哪些是常识凑数？
4. **越界**：有没有出现操作建议、目标价、涨跌预测？
5. **缺口**：该说"数据不可得"的地方，是不是用常识糊过去了？

只输出 JSON：
{"issues":[{"type":"数字不一致|逻辑矛盾|注水|越界|缺口掩盖|表述不清",
  "target":"business|market|moat|numbers|valuation|risk",
  "problem":"具体问题",
  "fix":"具体怎么改","severity":"high|medium|low"}],
 "summary":"整体质量判断，一句话"}

【输出长度硬约束】（2026-10-20 实测：不限长度时输出被 max_tokens 截断，
17 条意见只救回 1 条，critic 等于没有）
- 最多 8 条意见，按严重度从高到低排，只报真正影响结论的
- 每条 problem 不超过 30 字，fix 不超过 30 字
- summary 不超过 40 字
- 宁可少报，不可写不完"""


def run_critic(sections, key):
    body = '\n\n'.join('[%s]\n%s' % (s['title'], s['text']) for s in sections
                       if s.get('text'))
    # 坑（2026-10-20 实测·第二轮）：原来这里靠「返回文本里是否含'被截断'字样」
    # 判断要不要重试——但 LLM 正文里根本不会出现这种字样，判断恒为假，
    # 于是被截断的输出被当成完整结果直接用，critic 形同虚设。
    # 正确做法：从 _call 拿 finish_reason 真相（truncated 标志），据此决定重试。
    last = ''
    truncated = False
    attempt = 0
    budgets = [6000, 12000, 12000]
    for attempt in range(3):
        extra = ''
        if attempt >= 1:
            extra = ('\n\n【重试提示】上一次输出超长被截断。'
                     '这次最多 5 条意见，每条不超过 25 字，只报最关键的问题。')
        try:
            raw, meta = _call(
                [{'role': 'system', 'content': CRITIC_SYSTEM},
                 {'role': 'user',
                  'content': '请审阅以下个股深度分析：\n\n' + body + extra}],
                key, temperature=0.2, max_tokens=budgets[attempt], with_meta=True,
                model=CRITIC_MODEL)
        except Exception as e:                       # noqa: BLE001
            return {'issues': [], 'summary': 'critic 不可用：%s' % (str(e)[:60],)}
        last = raw or ''
        truncated = bool(meta.get('truncated'))
        if not truncated:
            break
    out = _parse_critic(last)
    out['truncated'] = truncated
    out['retry_rounds'] = attempt + 1
    return out


def _parse_critic(raw):
    """解析 critic 输出。截断时逐个 issue 抢救，不整体丢弃。

    坑（2026-10-20 实测·第二轮）：原来的抢救正则要求
    type→target→problem→fix→severity **严格按此顺序出现**且中间不能有别的字段。
    模型换个字段顺序、或少给一个字段，整条意见就整条丢掉——
    实测 17 条意见只救回 1 条。
    修法：先按大括号切出每个 issue 块，再逐字段独立提取，
    字段顺序无关、缺字段也能救回。
    """
    s = (raw or '').strip()
    s = re.sub(r'^```(?:json)?\s*', '', s)
    s = re.sub(r'\s*```$', '', s).strip()
    i, j = s.find('{'), s.rfind('}')
    if i >= 0 and j > i:
        try:
            obj = json.loads(s[i:j + 1])
            if isinstance(obj, dict):
                obj.setdefault('issues', [])
                return obj
        except Exception:
            pass
    # 截断兜底：切叶子块，逐块逐字段提取（字段顺序无关）
    issues = []
    seen = set()
    for blk in _leaf_blocks(s):
        if '"type"' not in blk and '"problem"' not in blk:
            continue
        it = {}
        for field in ('type', 'target', 'problem', 'fix', 'severity'):
            m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)"' % field, blk)
            if m:
                it[field] = _clean(m.group(1))
        if not (it.get('problem') or it.get('type')):
            continue
        sig = (it.get('target', ''), it.get('problem', '')[:40])
        if sig in seen:
            continue
        seen.add(sig)
        issues.append(it)
    if issues:
        return {'issues': issues,
                'summary': 'critic 输出被截断，已抢救 %d 条意见' % len(issues)}
    return {'issues': [], 'summary': 'critic 输出无法解析'}


def _json_blocks(s):
    """切出文本里所有闭合的 {...} 块（含嵌套层）。

    坑（2026-10-20 实测·第三轮）：只取「顶层」块时，
    critic 输出形如 {"issues":[{...},{...}]}，
    外层 {} 因截断永远不闭合 → 整段被当成**一个**块，
    于是 4 条意见仍然只救回 1 条。
    修法：栈式扫描，把每一层闭合的块都吐出来，由调用方按字段挑。
    """
    out = []
    stack = []
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            stack.append(i)
        elif ch == '}':
            if stack:
                st = stack.pop()
                out.append(s[st:i + 1])
    # 尾部被截断的残块（无闭合 }）——按栈里剩余的起点逐个补捞
    for st in stack:
        out.append(s[st:])
    return out


def _leaf_blocks(s):
    """只取不含嵌套 '{' 的叶子块——也就是一条条 issue 本身。"""
    return [b for b in _json_blocks(s) if '{' not in b[1:]]


def _clean(s):
    """清理 JSON 转义残留（截断抢救时残留的 \\ 和半截引号）。"""
    s = (s or '').replace('\\"', '"').replace("\\'", "'").replace('\\n', ' ')
    s = s.replace('\\\\', '').strip()
    return s.strip('"').strip()


# ================================================================== 组装
def _assemble(sections, coverage, code, name, tier_note):
    blocks = []
    for s in sections:
        if not s.get('text'):
            continue
        blocks.append({'key': s['key'], 'title': s['title'], 'text': s['text'],
                       'chars': len(s['text']),
                       'note': s.get('note') or '',
                       'unverified_numbers': s.get('unverified_numbers') or [],
                       'facts_used': s.get('facts_used') or 0})
    total = sum(b['chars'] for b in blocks)
    return {
        'code': code, 'name': name, 'coverage': coverage,
        'sections': blocks, 'total_chars': total,
        'tier_note': tier_note,
        'coverage_note': _coverage_note(coverage, blocks),
    }


def _coverage_note(coverage, blocks):
    have = {b['key'] for b in blocks}
    missing = [s['title'] for s in SECTIONS if s['key'] not in have]
    if coverage == 'A':
        return '外部深度数据覆盖完整，六段全出。'
    if missing:
        return '外部深度数据覆盖 %s 级，%s 因无可核验数据源未展开（不做常识补写）。' % (
            coverage, '、'.join(missing))
    return '外部深度数据覆盖 %s 级。' % coverage


# ================================================================== 主流程
def build_deep(code, name, facts_blocks, research, payload=None, key=None,
               coverage=None, regenerate=True, on_section=None, timing=None,
               industry_raw=None, industry_facts=None):
    """生成深度分析。

    facts_blocks: list of facts 列表（每项 {'key','label','value','text','source'}）
    research: research block（stockscore_research.get_research 的返回）
    payload: v3 打分 payload（用于取 tier_note）
    on_section: 可选回调。每当一段正文生成完成就调用一次（section dict），
                用于「首段先出」——不等六段跑完就先给前端渲染。
    timing: 可选 dict，调用方可读回各阶段耗时（用于定位慢在哪一段）。
    industry_raw / industry_facts: 调用方已取好的行业结构数据。
        坑（2026-10-21 实测）：原来 build_deep 内部自己再取一次 get_industry，
        而调用方（api._ss_deep_inputs）已经取过一次 ——
        行业结构要拉申万成分股实算，重复算一遍白花十几秒。
    """
    _t0 = time.time()
    _tim = timing if isinstance(timing, dict) else {}

    def _mark(k, t0):
        _tim[k] = round(time.time() - t0, 1)
        return time.time()

    from stockscore_research import facts_for_writer, coverage_level
    research_facts = facts_for_writer(research)

    # 行业结构数据（外部深度数据补漏机制的核心件）
    # 定位：research 通道拿不到行业规模/集中度/份额（研报不写、也不可核），
    # 这一层自己从申万成分股实算，数字可复算、可溯源。
    # 拿不到就静默降级（industry_facts 为空 → 不进 prompt），
    # 不许用常识补。
    _ti = time.time()
    if industry_facts is None:
        industry_facts = []
    if industry_raw is None:
        industry_raw = None
        try:
            from stockscore_industry import get_industry, facts_for_writer as _ind_facts
            industry_raw = get_industry(code)
            industry_facts = _ind_facts(industry_raw)
        except Exception as e:                      # noqa: BLE001
            industry_facts = []
            industry_raw = {'error': str(e)[:80]}
    _tim['industry_in_build'] = round(time.time() - _ti, 1)

    # coverage 必须在拿到行业数据之后算：行业层能把 B/C 票升级到 A
    coverage = coverage or coverage_level(research, industry_raw)

    # 全部 facts 拉平
    all_facts = []
    for blk in (facts_blocks or []):
        if isinstance(blk, list):
            all_facts.extend(blk)
        elif isinstance(blk, dict) and blk.get('facts'):
            all_facts.extend(blk['facts'])
    whitelist = build_whitelist([all_facts], research_facts, industry_facts)

    # 决定要写哪几段
    # 2026-10-20：coverage 由"研报通道 + 行业结构数据层"共同决定。
    # 即使还是 C 级，只要有行业层数据（集中度/份额/景气），
    # market 和 moat 两段就有可核数据可写——不能因为研报没有就整段留白。
    has_ind = bool(industry_facts) and any(
        ('集中度' in t) or ('行业市值占比' in t) or ('行业景气' in t)
        for t in industry_facts)
    if coverage == 'C':
        wanted = [s for s in SECTIONS
                  if s['key'] in ('numbers', 'valuation', 'risk')]
        if has_ind:
            wanted = [s for s in SECTIONS
                      if s['key'] in ('numbers', 'valuation', 'risk',
                                      'market', 'moat')]
    elif coverage == 'B':
        wanted = list(SECTIONS)
    else:
        wanted = list(SECTIONS)

    sections = []
    used_idx = set()          # 已经喂过的 fact 下标，后续段落降权
    # 2026-10-21：六段并行生成。
    # 坑（实测）：原来六段是串行 for 循环，每段一次 LLM 调用约 8-12s，
    # 六段累计 60-120s，首段要等 8-12s 才可见，全文要等 1 分钟以上。
    # 改并行后：首段（最短的那段）约 8-10s 出，全文约 23s（实测并行六段 23.3s）。
    # used_idx 的降权语义要保住 —— 段与段之间是「已用事实」弱依赖，
    # 不能真并行共享同一个 set，否则并发写入结果不确定。
    # 解法：先按原顺序算出每段的 facts 分配（纯本地计算，微秒级，含 used_idx 降权），
    # 再把这 6 份「事实配餐」并行送进 LLM。事实分配顺序与串行版完全一致。
    _plan = []
    _used_local = set()
    for sec in wanted:
        picked = _pick_facts(all_facts, sec['key'], used_idx=_used_local)
        _plan.append((sec, picked, set(_used_local)))
        _used_local.update(i for _, i in picked)

    def _gen_one(plan_item):
        """并行体：单段生成 + 数字回验（回验不通过则带问题重写一次）。"""
        sec, picked, used_snapshot = plan_item
        facts_lines = []
        for f, _idx in picked:
            lab = f.get('label') or ''
            txt = f.get('text') or ''
            src = f.get('source') or ''
            if txt:
                facts_lines.append('- [%s] %s%s' % (lab, txt, ('（来源：%s）' % src) if src else ''))
        research_lines = []
        for f in research_facts:
            research_lines.append('- [%s] %s' % (f.get('label'), f.get('text')))
        industry_lines = []
        if industry_facts and sec['key'] in INDUSTRY_FEED_SECTIONS:
            industry_lines = ['- %s' % t for t in industry_facts]
        user = _section_prompt(sec, facts_lines, research_lines, name, code, coverage,
                                industry_lines=industry_lines)
        text, _ = _gen_section_from_prompt(sec, user, key)
        text, hits = _guard_banned(text)
        note = ''
        if hits:
            note = '出现禁词 %s' % '、'.join(hits)
        v = verify_numbers(text, whitelist, all_facts)
        if not v['ok'] and regenerate:
            text2, _ = _gen_section_from_prompt(
                sec, user,
                key,
                extra_note='文中出现了事实清单里没有的数字 %s，'
                           '请只使用清单中的数字重写。' % '、'.join(v['bad'][:8]))
            text2, hits2 = _guard_banned(text2)
            if hits2:
                note = (note + '；' if note else '') + '重写后仍出现禁词 %s' % '、'.join(hits2)
            v2 = verify_numbers(text2, whitelist, all_facts)
            if v2['ok']:
                text, v = text2, v2
        # 2026-10-22：金额单位统一到亿元。
        # 必须在 verify_numbers **之后**做 —— 金额换算会改写数字
        # （6,400 万元 → 0.64 亿元），先做会被 verify 判成"清单外的数字"而误触发重写。
        text = _normalize_money(text)
        text = _strip_internal_terms(text)
        return {'key': sec['key'], 'title': sec['title'], 'text': text,
                'facts_used': len(picked),
                '_picked_idx': [i for _, i in picked],
                'unverified_numbers': v['bad'], 'note': note}

    if _plan:
        _tg = time.time()
        with ThreadPoolExecutor(max_workers=min(6, len(_plan))) as _pool:
            _futures = [_pool.submit(_gen_one, p) for p in _plan]
            # 2026-10-21：按完成顺序逐段发布（as_completed），不等全部跑完。
            # 六段耗时 8-23s 不等，最快的那段约 8-10s 先出来 →
            # 前端可以先渲染这一段，用户不用干等全文。
            # 收集时仍按 _plan 原顺序还原，保证页面段落顺序稳定。
            _done = {}
            for _f in as_completed(_futures):
                _r = _f.result()
                _done[_r['key']] = _r
                if on_section:
                    try:
                        on_section(_r)
                    except Exception:          # noqa: BLE001
                        pass
            for _p in _plan:
                sections.append(_done[_p[0]['key']])
        _tim['sections_parallel'] = round(time.time() - _tg, 1)
    used_idx = _used_local

    _tc = time.time()
    contradictions = detect_contradictions(sections)
    critic = run_critic(sections, key) if key else {'issues': [], 'summary': '未运行'}
    _tim['critic_first'] = round(time.time() - _tc, 1)
    _tim['to_first_sections'] = round(time.time() - _t0, 1)

    # 裁决：critic 标 high 且指向某段 → 重生成该段。
    # 轮次上限从 2 提到 3（2026-10-20 改）：原来写「两轮基本收敛」是建立在
    # critic 每次只报 1 条意见的假象上（那时的截断 bug 让 17 条只剩 1 条）。
    # critic 修好之后实测发现：第 2 轮复审会**新报出**第 1 轮没有的 high 问题
    # （688508 实例：business 段「称收入结构已向新品类倾斜」与前文「三块金额拿不到」打架），
    # 而最后一轮复审的结果只进页面、不再被处理 → 页面上挂着 high 级意见但正文没改。
    # 现在允许第 3 轮把「复审新报出的 high」也改掉。
    # 另加收敛判断：某轮复审的 high 数量没下降 → 停，避免无意义烧 token。
    rewritten = False
    rounds_used = 0
    stuck = []          # 连续两轮复现的 issue 指纹 → 判定「改不动」，页面上明示
    if regenerate and key:
        sec_by_key = {s['key']: s for s in SECTIONS}
        sec_by_title = {s['title']: s for s in SECTIONS}
        prev_high = None
        prev_fps = set()
        for _round in range(3):
            rounds_used = _round + 1
            high_by_sec = {}
            # 2026-10-20 改（三处）：
            # ① 结构性问题（越界/注水/表述不清/缺口掩盖）即使是 medium 也进队列。
            #    旧代码只挑 high，于是 5 条 medium 在结构上不可能被修。
            # ② 把 critic 的 fix 一并传给写手。旧代码只传 problem，写手知道有病不知道药方，
            #    整段重生成会再踩同一个坑（688508 实测：moat 段打了「已按审读意见重写」标记，
            #    「商誉 0.6% → 技术自研」一字未改）。
            # ③（在循环尾部）收敛判断不假装收敛：复现两轮的 issue 记成未解并明示。
            STRUCT_FIX = {'越界', '注水', '表述不清', '缺口掩盖', '逻辑矛盾'}
            for it in (critic.get('issues') or []):
                sev = (it.get('severity') or '').strip().lower()
                typ = (it.get('type') or '').strip()
                if sev != 'high' and typ not in STRUCT_FIX:
                    continue
                tgt = (it.get('target') or '').strip()
                sec = sec_by_key.get(tgt) or sec_by_title.get(tgt)
                if not sec:
                    # target 里可能夹带中文说明，取第一个能匹配上的段名
                    for k2, s2 in sec_by_key.items():
                        if tgt and (tgt in s2['title'] or tgt in k2):
                            sec = s2
                            break
                if not sec:
                    continue
                prob = (it.get('problem') or '').strip()
                fix = (it.get('fix') or '').strip()
                entry = ('%s → 改法：%s' % (prob, fix)) if fix else prob
                high_by_sec.setdefault(sec['key'], []).append(entry)
            # 数字回验不通过的段落也要重写。
            # 坑（2026-10-20 实测）：原来 verify_numbers 只把 bad 记到段上，
            # 但没人拿它当触发条件——自造派生数字（19.69、4.6）算出来了却没人管。
            for s in sections:
                if s.get('unverified_numbers'):
                    high_by_sec.setdefault(s['key'], []).append(
                        '文中出现了数据清单里没有的数字：%s。'
                        '这些是自行推算的派生值，'
                        '请删掉或者换成清单里已有的口径。'
                        % '、'.join(s['unverified_numbers'][:6]))
            # 2026-10-20 加：机械结构闸（零 token）。序号断号、段内「市值÷PE≠净利」
            # 这两类都不用 LLM 就能查出来，先拦一道，省掉「复审烧一轮 → 才发现 → 再重写」。
            for s in sections:
                _p2 = audit_structure(s['text']) + audit_numbers(s['text'])
                if _p2:
                    high_by_sec.setdefault(s['key'], []).append(
                        '机械检查发现以下硬问题，必须修掉：' + '；'.join(_p2[:3]))
            # 跨段重复（注水）：12 字片段出现在 >=3 段 → 保留最先出现的段，其余要求改写。
            # prompt 规则 22 只覆盖「核心数字不跨段重复」，定性描述的重复一直没人管。
            _dup = {}
            for _g, _ks in cross_section_repeats(sections):
                for _k in _ks[1:]:
                    _dup.setdefault(_k, []).append(_g)
            for _k, _gs in _dup.items():
                high_by_sec.setdefault(_k, []).append(
                    '以下片段在你前面的段落里已经写过（注水），必须换个角度写或直接删掉：'
                    + '；'.join(_gs[:3]))
            if not high_by_sec:
                break
            # 2026-10-21：同一轮内的多段重写改为并行。
            # 坑（实测）：原来重写是 for 循环逐段串行，一轮要改 3 段就是 3×10s=30s，
            # 三轮下来尾部延迟 90s+。各段重写互不依赖（每段只改自己），
            # 只有「读 sections 拿本段 own facts」这一步要串行，先算好再并行送 LLM。
            _rw_jobs = []
            for sec_key, probs in high_by_sec.items():
                sec = sec_by_key.get(sec_key)
                if not sec:
                    continue
                probs = [p for p in probs if p]
                # 重写时把本段自己用过的 fact 从 used_idx 里摘掉：
                # 否则降权机制会让重写版换掉自己那组数字，等于把问题换了个样。
                own = set()
                for s in sections:
                    if s['key'] == sec_key:
                        own = set(s.get('_picked_idx') or [])
                        break
                rewrite_used = used_idx - own
                _rw_jobs.append((sec_key, sec, probs, rewrite_used))

            def _rewrite_one(job):
                """并行体重写单段。返回 (sec_key, text, new_picked)。"""
                _sec_key, _sec, _probs, _rewrite_used = job
                _facts_lines = []
                for _f, _idx in _pick_facts(all_facts, _sec['key'], used_idx=_rewrite_used):
                    _lab = _f.get('label') or ''
                    _txt = _f.get('text') or ''
                    _src = _f.get('source') or ''
                    if _txt:
                        _facts_lines.append('- [%s] %s%s' % (
                            _lab, _txt, ('（来源：%s）' % _src) if _src else ''))
                _research_lines = []
                for _f in research_facts:
                    _research_lines.append('- [%s] %s' % (_f.get('label'), _f.get('text')))
                _industry_lines = []
                if industry_facts and _sec['key'] in INDUSTRY_FEED_SECTIONS:
                    _industry_lines = ['- %s' % _t for _t in industry_facts]
                _user = _section_prompt(_sec, _facts_lines, _research_lines, name, code,
                                        coverage, industry_lines=_industry_lines)
                _text, _picked = _gen_section_from_prompt(
                    _sec, _user, key,
                    extra_note=(('编辑审读发现以下问题，请修正：' + '；'.join(_probs[:3])
                                 + '只改有问题的表述；本段原有的论证链和已核对的数据必须保留，'
                                   '篇幅不得明显少于现在（约 %d 字以上）。'
                                   % max(300, int(len(_sec.get('text') or '') * 0.8)))
                                if _probs else ''))
                _text, _ = _guard_banned(_text)
                # 2026-10-22：重写路径同样做金额单位统一 + 内部术语收口
                _text = _normalize_money(_text)
                _text = _strip_internal_terms(_text)
                return _sec_key, _text, _picked

            if _rw_jobs:
                with ThreadPoolExecutor(max_workers=min(6, len(_rw_jobs))) as _pool:
                    for _sec_key, text, new_picked in _pool.map(_rewrite_one, _rw_jobs):
                        for s in sections:
                            if s['key'] == _sec_key:
                                s['text'] = text
                                # note 只保留最新一次重写标记。
                                # 坑（2026-10-20 实测）：原来按 rewritten 布尔值判断 tag，
                                # 结果 note 累积成"（已按审读意见重写）（二审重写）"。
                                # 现在直接替换，页面上永远只有一个标记。
                                tag = ('（已按审读意见重写）' if not s.get('_rewritten')
                                       else '（二审重写）')
                                base = (s.get('note') or '').split('（')[0].strip()
                                s['note'] = (base + tag) if base else tag
                                s['_rewritten'] = True
                                s['unverified_numbers'] = verify_numbers(
                                    text, whitelist, all_facts)['bad']
                                s['_picked_idx'] = new_picked
                                rewritten = True
            # 本轮重写完，重新检测+复审，作为下一轮的输入
            contradictions = detect_contradictions(sections)
            critic = run_critic(sections, key) if key else {'issues': [], 'summary': '未运行'}
            if critic.get('issues'):
                critic['rereviewed'] = True
            # 收敛判断：复审出的 high 数量没比上一轮少 → 不再往下改。
            # 判据是「数量」，不是「有没有」：改不动的问题会稳定在同一个数量上，
            # 继续重写只是把同样的文字换个说法，token 翻倍。
            # 2026-10-20 改：break 不等于「已改好」。把连续两轮复现的 issue 记进 stuck，
            # 后面在段落 note 与 payload 里明示——旧代码只 break，页面看不出还有 high 挂着。
            cur_fps = {}
            for it in (critic.get('issues') or []):
                if (it.get('severity') or '').strip().lower() != 'high':
                    continue
                fp = '%s|%s' % ((it.get('type') or '').strip(),
                                (it.get('target') or '').strip())
                cur_fps[fp] = it
            _known = {x['fp'] for x in stuck}
            for fp, it in cur_fps.items():
                if fp in prev_fps and fp not in _known:
                    stuck.append({'fp': fp, 'type': it.get('type'),
                                  'target': it.get('target'),
                                  'problem': it.get('problem'),
                                  'fix': it.get('fix')})
            high_now = len(cur_fps)
            # 机械闸复检（零 token）：LLM 层「改不动」不等于可以收工——最后一轮重写
            # 常新引入硬伤（v19 实测：moat 生出「第二条」缺「第一条」，numbers 冒出未核数
            # 11826.7）。这类还能再修一轮，别浪费。
            _hard = (any(s.get('unverified_numbers') for s in sections)
                     or any(audit_structure(s['text']) + audit_numbers(s['text'])
                            for s in sections)
                     or bool(cross_section_repeats(sections)))
            if prev_high is not None and high_now >= prev_high:
                if not _hard or (_round + 1) >= 3:
                    break
            prev_high = high_now
            prev_fps = set(cur_fps)

    # 终态还有没解决的（不管是「改不动」还是「最后一轮重写新引入的」）→ 段 note 明示。
    # 旧写法挂在 `if stuck:` 上，v19 实测翻车：stuck=0（没连续两轮复现）但仍有 2 条 high，
    # 页面却一个未解标记都没有 —— 等于把没解决的说成解决了。
    _mark_tgt = {(x.get('target') or '').strip() for x in stuck}
    _mark_tgt |= {(x.get('target') or '').strip()
                  for x in (critic.get('issues') or [])
                  if (x.get('severity') or '').strip().lower() == 'high'}
    for _s in sections:
        if audit_structure(_s['text']) + audit_numbers(_s['text']) or _s.get('unverified_numbers'):
            _mark_tgt.add(_s['key'])
    for s in sections:
        if s.get('key') in _mark_tgt or s.get('title') in _mark_tgt:
            if '未解' not in (s.get('note') or ''):
                s['note'] = ((s.get('note') or '') + '（仍有审读意见未解）').strip()

    tier_note = ''
    if payload:
        # 2026-10-22：不再拼 tag.desc（"可投域/域内候选/域外优质/红旗不碰"=
        # 松果投资策略的选股结论），只留客观分数、档位与调档说明。
        tier_note = '%s 分，%s。%s' % (
            payload.get('total'), payload.get('tier'),
            payload.get('tier_note') or '')

    # 注意：矛盾检测与 critic 的结果来自上面重写循环内部的复检，
    # 报的是**最终文本**，不是改之前的版本。

    out = _assemble(sections, coverage, code, name, tier_note)
    # 2026-10-22：剥掉段落 note 里的内部流水线术语（详见 _strip_internal_note_terms）
    out = _strip_internal_note_terms(out)
    out['contradictions'] = contradictions
    out['critic'] = critic
    # 重写痕迹要透出：页面上要能看出"这段被审读意见改过"
    out['rewritten'] = rewritten
    out['rewrite_rounds'] = rounds_used
    out['sections_rewritten'] = [s['key'] for s in sections if s.get('_rewritten')]
    # 终态仍未解的 high 意见：不管复现几轮，输出时它们就是没解决，如实披露
    out['unresolved'] = [{'type': x.get('type'), 'target': x.get('target'),
                          'problem': x.get('problem'), 'fix': x.get('fix'),
                          'severity': x.get('severity')}
                         for x in (critic.get('issues') or [])
                         if (x.get('severity') or '').strip().lower() == 'high']
    # 连续两轮改不动的（诊断用，告诉我们是「写手不听话」还是「问题本身改不掉」）
    out['stuck'] = [{k: v for k, v in x.items() if k != 'fp'} for x in stuck]
    # 终检：机械闸仍未通过的段落（明示，不假装干净）
    _si = []
    for s in sections:
        _p = audit_structure(s['text']) + audit_numbers(s['text'])
        if _p:
            _si.append({'key': s['key'], 'issues': _p})
    _rep = cross_section_repeats(sections)
    if _rep:
        _si.append({'key': 'cross_section',
                    'issues': ['「%s」重复出现在：%s' % (g, '、'.join(ks)) for g, ks in _rep]})
    out['structure_issues'] = _si
    out['research_note'] = (research or {}).get('note') or ''
    out['research_reports'] = (research or {}).get('report_count', 0)
    out['unverified_numbers'] = sorted({n for s in sections for n in s.get('unverified_numbers', [])})
    # 行业结构数据（外部深度数据补漏机制的产出，前端可展示、可溯源）
    if industry_raw:
        out['industry'] = {
            'classification': industry_raw.get('industry') or {},
            'concentration': industry_raw.get('concentration'),
            'growth': industry_raw.get('growth'),
            'index': industry_raw.get('industry_index'),
            'notes': industry_raw.get('notes') or [],
        }
    out['generated_at'] = time.time()
    return out


# ================================================================== 缓存
def _cache_path(code, asof):
    # 带 PIPELINE_VERSION：生成逻辑一改，旧缓存自动失效。
    # 坑（2026-10-20 实测）：改了禁词规则和 critic 重写逻辑后，
    # 缓存 key 仍是 (code, asof)，结果 API 返回的还是改之前的旧文本。
    return os.path.join(CACHE_DIR, '%s_%s_v%d.json' % (code, asof, PIPELINE_VERSION))


def get_cached(code, asof=None):
    """只读已缓存的深度分析，不触发生成。

    给"手机端口播版"用：口播稿不需要现算六段深度分析，
    有缓存就用（免费且能对齐口径），没缓存就返回 None 让口播稿独立成稿。
    """
    asof = asof or time.strftime('%Y%m%d')
    with _lock:
        k = _mem_key(code, asof)
        if k in _mem:
            return _mem[k]
    path = _cache_path(code, asof)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            obj = json.load(f)
    except Exception:
        return None
    with _lock:
        _mem[_mem_key(code, asof)] = obj
    return obj


def invalidate(code, asof=None):
    """清掉某只股票的深度分析缓存（内存 + 磁盘）。

    坑（2026-10-21）：改成日级缓存后，数据更新不会自动生效，
    必须有显式失效入口，否则会出现「代码改了线上还是旧文本」。
    """
    asof = asof or time.strftime('%Y%m%d')
    n = 0
    with _lock:
        for k in [k for k in _mem if k[0] == code]:
            _mem.pop(k, None)
            n += 1
    try:
        d = CACHE_DIR
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.startswith(code + '_') and fn.endswith('.json'):
                    try:
                        os.remove(os.path.join(d, fn))
                        n += 1
                    except OSError:
                        pass
    except Exception:
        pass
    return n


def _strip_internal_note_terms(obj):
    """剥掉 sections[].note 里的内部流水线术语（2026-10-22）。

    坑：note 里写的是"（已按审读意见重写）""（二审重写）""（仍有审读意见未解）"
    这类重写轮次标记，是给开发和质量闸门看的，泄漏到用户端是噪音，
    而且用户会误以为"这段没写好"。内部信息仍通过 rewritten/rewrite_rounds/
    unresolved/stuck 等独立字段保留，不丢数据。

    新生成和读旧磁盘缓存都要清洗 —— 旧缓存 JSON 里已带这些标记。
    """
    if not isinstance(obj, dict):
        return obj
    for s in obj.get('sections') or []:
        if isinstance(s, dict):
            if s.get('note'):
                s['note'] = _NOTE_INTERNAL_RE.sub('', s['note']).strip()
            if s.get('text'):
                s['text'] = _strip_internal_terms(s['text'])
    # critic / unresolved / structure_issues 里的自由文本同样会带内部术语
    # 和被禁措辞（例如"易被读成隐含目标价"），一并收口。
    _clean_freetext(obj.get('critic'))
    for x in (obj.get('unresolved') or []):
        if isinstance(x, dict):
            for k in ('type', 'problem', 'fix'):
                if x.get(k):
                    x[k] = _neutralize_banned(_strip_internal_terms(str(x[k])))
    for x in (obj.get('structure_issues') or []):
        if isinstance(x, dict):
            if x.get('key'):
                x['key'] = _strip_internal_terms(str(x['key']))
            if isinstance(x.get('issues'), list):
                x['issues'] = [
                    _neutralize_banned(_strip_internal_terms(it))
                    if isinstance(it, str) else it
                    for it in x['issues']
                ]
    for c in (obj.get('contradictions') or []):
        if isinstance(c, dict):
            for k in ('detail', 'a_text', 'b_text'):
                if c.get(k):
                    c[k] = _neutralize_banned(_strip_internal_terms(str(c[k])))
    return obj


def _clean_freetext(node):
    """递归清洗 critic / 类似的自由文本节点。"""
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if isinstance(v, str):
                node[k] = _neutralize_banned(_strip_internal_terms(v))
            else:
                _clean_freetext(v)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str):
                node[i] = _neutralize_banned(_strip_internal_terms(v))
            else:
                _clean_freetext(v)
    return node


_NOTE_INTERNAL_RE = re.compile(r'[（(][^）)]*(审读|重写|二审|未解)[^）)]*[）)]')


def get_or_build(code, name, facts_blocks, research, payload=None, key=None,
                 asof=None, force=False, coverage=None, on_section=None,
                 timing=None, industry_raw=None, industry_facts=None):
    asof = asof or time.strftime('%Y%m%d')
    with _lock:
        k = _mem_key(code, asof)
        if k in _mem and not force:
            return _mem[k]
    path = _cache_path(code, asof)
    if not force and os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                obj = json.load(f)
            obj = _strip_internal_note_terms(obj)
            with _lock:
                _mem[_mem_key(code, asof)] = obj
            return obj
        except Exception:
            pass
    obj = build_deep(code, name, facts_blocks, research, payload=payload, key=key,
                      coverage=coverage, on_section=on_section, timing=timing,
                      industry_raw=industry_raw, industry_facts=industry_facts)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    except Exception:
        pass
    with _lock:
        _mem[_mem_key(code, asof)] = obj
    return obj


if __name__ == '__main__':
    import sys
    sys.path.insert(0, '.')
    import api as _api
    import stockscore_v3 as V
    import stockscore_facts as FA
    import stockscore_research as RS
    import stockscore_modules as M

    code = sys.argv[1] if len(sys.argv) > 1 else '688508'
    payload, _ = V.compute_v3(code)
    r = RS.get_research(code, '20261020', _api.DS_KEY)
    fk = FA.build_facts(code)
    vb = M.build_valuation_block(code, research=r)
    kb = M.build_risk_block(code, research=r, payload=payload) if False else \
        M.build_risk_block(code, research=r)
    out = build_deep(code, payload.get('name', code),
                     [fk.get('facts') or [], vb['facts'], kb['facts']],
                     r, payload=payload, key=_api.DS_KEY)
    with open('deep_out.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print('written deep_out.json chars=%s cov=%s' % (out['total_chars'], out['coverage']))
