# -*- coding: utf-8 -*-
"""质量闸门（2026-10-20）

回答一个具体问题：**如何确保模型产出的分析内容稳定达到"微信深度文章"的信息密度，
而不是时好时坏的漂亮空话？**

答案不是"把提示词写得更好"，而是把"丰满度"拆成可程序化检验的硬指标，
让不达标的输出无法上线。本模块只做判定，不改写内容。

八项指标（前六项是硬闸门，后两项是软评分）：

  1. 数字密度 density      每 100 字含数值事实的句子数 —— 防"正确的废话"
  2. 维度覆盖 coverage     框架要求的必答槽位是否都有内容 —— 防"漏掉关键问题"
  3. 溯源率 traceability   文中数字能在事实包里找到来源的比例 —— 防幻觉
  4. 禁词合规 banned       不得出现买卖推荐类表述 —— 合规红线
  5. 缺口诚实 gaps_declared 事实包里的缺口是否被显式声明 —— 防"假装什么都知道"
  6. 长度区间 length        过短说明没展开，过长说明注水
  7. 具体度 specificity    具名实体（公司/产品/客户/竞品）数量 —— 软评分
  8. 一致性 consistency    结论方向与规则引擎打分是否矛盾 —— 软评分

判定结果三档：
  pass    —— 全部硬闸门通过，可直接发布
  degrade —— 有硬闸门未过但内容可用，降级为"精简版 + 缺口清单"
  reject  —— 触发合规红线或溯源率过低，不发布

设计原则：宁可发一份诚实标注缺口的短内容，也不发一份看着丰满、实则编造的长内容。
"""
import re

# ---------------------------------------------------------------- 阈值
# 阈值不是拍脑袋定的，是用金标准反推的（见 stockscore_gate_calib.py）：
#   微信深度文章（峰岹科技，2884 字）实测密度 0.88
#   元宝总结版（同题材，2366 字）实测密度 1.00
#   纯定性空话（356 字）实测密度 0.00
# 因此密度阈值取 0.70——对金标准留约 20% 余量，同时与空话（0.00）有巨大区分度。
# 若后续换模型/改框架，必须重跑校准脚本，不得直接改这里。
THRESHOLDS = {
    'density_min': 0.70,       # 每 100 字至少 0.7 句带数值
    'coverage_min': 0.75,      # 必答槽位覆盖率
    'traceability_min': 0.85,  # 数字溯源率
    'length_min': 600,         # 正文最少字数
    'length_max': 6000,        # 正文最多字数（防注水）
    'specificity_min': 3,      # 至少 3 个具名实体
}

# 合规红线（沿用线上 V1/V3 的 BANNED_RE 口径）
BANNED_RE = re.compile(
    r'买入|卖出|加仓|减仓|建仓|清仓|目标价|必涨|必跌|稳赚|包赚|'
    r'推荐(?:买|卖|该股|这只)|建议(?:买|卖|持有)|可以(?:买|卖|上车)|'
    r'抄底|梭哈|满仓|翻倍股|涨停板')

# 数值识别：支持 3.91亿 / 69.7% / 12 倍 / -64% / 4385 万
NUM_RE = re.compile(
    r'[-+]?\d+(?:\.\d+)?\s*(?:%|亿|万|倍|元|个百分点|pct|bp)?')

# 句末切分（中英文句号、分号、换行）
SENT_SPLIT_RE = re.compile(r'[。！？；\n]+')

# 具名实体：带"芯片/科技/股份/集团/公司"等后缀的专名，或已知竞品词表
ENTITY_RE = re.compile(
    r'[\u4e00-\u9fa5A-Za-z]{2,12}(?:科技|股份|集团|电子|半导体|电气|医疗|医药|'
    r'能源|材料|控股|微电子|光电|精密|重工|汽车|银行|证券|保险)')


def _sentences(text):
    return [s.strip() for s in SENT_SPLIT_RE.split(text or '') if s.strip()]


def _numbers_in(text):
    """抽出文中所有数值 token（归一化空白）。"""
    return [m.group(0).replace(' ', '') for m in NUM_RE.finditer(text or '')]


def _normalize_num(tok):
    """把 '3.91亿' / '69.7%' 归一成可比较的数值 + 单位。"""
    m = re.match(r'([-+]?\d+(?:\.\d+)?)\s*(.*)', tok)
    if not m:
        return None, ''
    try:
        return float(m.group(1)), m.group(2)
    except ValueError:
        return None, ''


# ---------------------------------------------------------------- 指标计算
def density(text):
    """数字密度：每 100 字里含数值的句子数。"""
    sents = _sentences(text)
    if not sents:
        return 0.0
    n_chars = sum(len(s) for s in sents)
    if n_chars == 0:
        return 0.0
    with_num = sum(1 for s in sents if NUM_RE.search(s))
    return round(with_num / (n_chars / 100.0), 2)


def coverage(text, required_slots):
    """维度覆盖：required_slots 里每个槽位在正文中是否有实质内容。

    required_slots = [{'key','label','patterns':[regex,...],'min_chars'}]
    判定：该槽位任一 pattern 命中，且命中处附近 200 字内出现数值或长度达 min_chars。
    """
    text = text or ''
    hit, missing = [], []
    for slot in required_slots:
        ok = False
        for pat in slot.get('patterns') or []:
            m = re.search(pat, text)
            if not m:
                continue
            seg = text[m.start():m.start() + 300]
            if NUM_RE.search(seg) or len(seg) >= slot.get('min_chars', 120):
                ok = True
                break
        (hit if ok else missing).append(slot.get('key'))
    total = len(required_slots) or 1
    return round(len(hit) / total, 2), hit, missing


def traceability(text, facts):
    """溯源率：文中数值能在事实包中找到的比例。

    宽松匹配：只要文中某数值与某条事实的数值在 1% 相对误差内，
    或与事实文本中的任一数值相等，即视为有源。
    """
    fact_nums = set()
    for f in facts or []:
        for tok in _numbers_in(f.get('text') or ''):
            v, _ = _normalize_num(tok)
            if v is not None:
                fact_nums.add(round(v, 4))
        v = f.get('value')
        if isinstance(v, (int, float)):
            fact_nums.add(round(float(v), 4))

    nums = []
    for tok in _numbers_in(text):
        v, unit = _normalize_num(tok)
        if v is None:
            continue
        # 忽略年份、序号这类噪声
        if unit == '' and (1900 <= abs(v) <= 2100 or abs(v) <= 12):
            continue
        nums.append(round(v, 4))

    if not nums:
        return 1.0, 0, 0
    hit = 0
    for v in nums:
        if v in fact_nums:
            hit += 1
            continue
        # 相对误差 1% 内视为命中
        if any(abs(v - x) <= max(abs(x) * 0.01, 1e-6) for x in fact_nums):
            hit += 1
    return round(hit / len(nums), 2), hit, len(nums)


def banned_hits(text):
    return sorted(set(m.group(0) for m in BANNED_RE.finditer(text or '')))


def specificity(text):
    """具体度：具名实体去重数量。"""
    return len(set(ENTITY_RE.findall(text or '')))


def length_of(text):
    return len(re.sub(r'\s', '', text or ''))


def gaps_declared(text, gaps):
    """缺口是否被显式声明。

    对事实包里的每个缺口，检查正文是否出现"未披露/不可得/缺失/无数据"等
    表述并伴随该缺口的关键词。允许合并声明（一处声明覆盖多个缺口）。
    """
    if not gaps:
        return 1.0, []
    text = text or ''
    has_disclaimer = re.search(
        r'未披露|不可得|缺失|无数据|无法获取|没有公开|暂缺|未返回', text)
    if not has_disclaimer:
        return 0.0, [g.get('label') for g in gaps]
    declared = []
    undeclared = []
    for g in gaps:
        label = g.get('label') or ''
        # 缺口标签或其中的关键实体出现在正文中，视为已声明
        key = re.sub(r'[（(].*?[)）]', '', label)
        if key and (key in text or any(
                part in text for part in re.split(r'[/、]', key) if len(part) >= 2)):
            declared.append(label)
        else:
            undeclared.append(label)
    # 只要有一处兜底声明，未逐项点名的缺口按已覆盖处理（避免过度苛刻）
    ratio = 1.0 if has_disclaimer else 0.0
    return ratio, undeclared


def consistency(text, score_payload):
    """结论方向与规则引擎打分是否矛盾。

    只在能明确判断时返回问题，不做语义推断的过度解读。
    """
    issues = []
    total = score_payload.get('total')
    tier = score_payload.get('tier')
    if total is None:
        return issues
    t = text or ''
    # 高分（>=70）却通篇负面定调，或低分（<50）却通篇正面定调
    positive = len(re.findall(r'优秀|突出|领先|强劲|稳健|扎实|优势明显|高质量', t))
    negative = len(re.findall(r'恶化|承压|下滑|风险较大|较弱|不佳|隐患|困境', t))
    if total >= 70 and negative > positive * 2 and negative >= 4:
        issues.append('总分 %s（%s）偏正面，但正文负面表述显著偏多' % (total, tier))
    if total < 50 and positive > negative * 2 and positive >= 4:
        issues.append('总分 %s（%s）偏低，但正文正面表述显著偏多' % (total, tier))
    return issues


# ---------------------------------------------------------------- 主判定
def evaluate(text, facts, gaps, score_payload=None, required_slots=None):
    """跑完整闸门，返回判定 + 各指标明细。

    返回 {
      'verdict': 'pass' | 'degrade' | 'reject',
      'metrics': {...}, 'failed': [...], 'warnings': [...],
      'reasons': [...]  # 人话说明，供前端直接展示
    }
    """
    required_slots = required_slots or []
    metrics, failed, warnings = {}, [], []

    d = density(text)
    metrics['density'] = d
    if d < THRESHOLDS['density_min']:
        failed.append('数字密度 %.2f < %.2f' % (d, THRESHOLDS['density_min']))

    if required_slots:
        cov, hit, missing = coverage(text, required_slots)
        metrics['coverage'] = cov
        metrics['coverage_hit'] = hit
        metrics['coverage_missing'] = missing
        if cov < THRESHOLDS['coverage_min']:
            failed.append('必答槽位覆盖 %.0f%% < %.0f%%（缺 %s）'
                          % (cov * 100, THRESHOLDS['coverage_min'] * 100,
                             '、'.join(missing)))

    tr, thit, ttotal = traceability(text, facts)
    metrics['traceability'] = tr
    metrics['traceability_hit'] = thit
    metrics['traceability_total'] = ttotal
    if tr < THRESHOLDS['traceability_min']:
        failed.append('数字溯源率 %.0f%% < %.0f%%（%d/%d 个数字找不到来源）'
                      % (tr * 100, THRESHOLDS['traceability_min'] * 100,
                         ttotal - thit, ttotal))

    bh = banned_hits(text)
    metrics['banned'] = bh
    if bh:
        failed.append('出现推荐类表述：%s' % '、'.join(bh))

    gd, gundeclared = gaps_declared(text, gaps)
    metrics['gaps_declared'] = gd
    metrics['gaps_undeclared'] = gundeclared
    if gaps and gd < 1.0:
        failed.append('事实缺口未声明：%s' % '、'.join(gundeclared or ['（全部）']))

    n = length_of(text)
    metrics['length'] = n
    if n < THRESHOLDS['length_min']:
        failed.append('正文 %d 字 < %d 字，展开不足' % (n, THRESHOLDS['length_min']))
    if n > THRESHOLDS['length_max']:
        warnings.append('正文 %d 字 > %d 字，可能注水' % (n, THRESHOLDS['length_max']))

    sp = specificity(text)
    metrics['specificity'] = sp
    if sp < THRESHOLDS['specificity_min']:
        warnings.append('具名实体仅 %d 个，表述偏抽象' % sp)

    if score_payload:
        cs = consistency(text, score_payload)
        metrics['consistency'] = cs
        if cs:
            warnings.extend(cs)

    # 判定
    hard_reject = bool(bh) or tr < 0.5
    if hard_reject:
        verdict = 'reject'
    elif failed:
        verdict = 'degrade'
    else:
        verdict = 'pass'

    reasons = []
    if verdict == 'reject':
        reasons.append('内容未通过合规或溯源底线，不予发布')
    elif verdict == 'degrade':
        reasons.append('内容可用，但存在 %d 项质量缺口，降级为精简版' % len(failed))
    else:
        reasons.append('全部硬指标通过')

    return {
        'verdict': verdict,
        'metrics': metrics,
        'failed': failed,
        'warnings': warnings,
        'reasons': reasons,
    }


# ---------------------------------------------------------------- 槽位定义
# 四段框架的必答槽位（对应微信文章的分析结构）。
# 写作层用同一份定义生成提示词，闸门用同一份定义做验收——定义只写一次。
FRAMEWORK_SLOTS = [
    # 一、业务结构与增长来源
    {'key': 'biz_base', 'label': '基本盘',
     'patterns': [r'基本盘|主业|存量业务|传统业务', r'占[比收]']},
    {'key': 'biz_segment', 'label': '分部结构',
     'patterns': [r'收入\s*[\d.]+\s*亿', r'占[比]?\s*\d+(?:\.\d+)?%']},
    {'key': 'biz_option', 'label': '增长期权',
     'patterns': [r'期权|第二曲线|新业务|增量|新兴']},
    # 二、空间与格局
    {'key': 'space', 'label': '市场空间',
     'patterns': [r'市场空间|规模|空间|天花板|渗透率|CAGR|复合增速']},
    {'key': 'competition', 'label': '竞争格局',
     'patterns': [r'竞争|份额|格局|对手|CR\d|集中度']},
    # 三、差异化与壁垒
    {'key': 'moat', 'label': '差异化壁垒',
     'patterns': [r'壁垒|护城河|差异化|定价权|粘性|转换成本']},
    # 四、数字检验
    {'key': 'capital_return', 'label': '资本回报',
     'patterns': [r'ROIC|WACC|资本回报|投入资本']},
    {'key': 'cashflow', 'label': '现金流质量',
     'patterns': [r'现金流|自由现金流|FCF|资本开支| capex|预付款']},
    # 估值与预期（新增模块）
    {'key': 'valuation', 'label': '估值与预期',
     'patterns': [r'估值|分位|PE|PB|市盈率|市净率']},
    # 风险与安全（新增模块）
    {'key': 'risk', 'label': '风险与安全',
     'patterns': [r'风险|安全边际|承压|隐患|回撤|波动']},
]
