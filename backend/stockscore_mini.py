# -*- coding: utf-8 -*-
"""小程序出口合规裁剪层（scope=mini）

【为什么存在】
个股打分卡要上微信小程序，需过「证券投资咨询」类目审核。判例红线：
行情涨跌幅 / 资金流 / 趋势预测 / 券商评级建议。打分卡数据主体（财务、
估值分位、行业基本面）在红线内侧，但有几处踩线，必须出口裁剪。

【设计铁律（2026-10-23 定，勿删）】
1. 只在**出口层**裁，绝不碰 stockscore_v3.py 的打分计算。
   → 网页版口径、线上总分、历史可比性零影响。
2. 裁剪五层全覆盖：dim / 子 metric / block 文本 / industry 结构 / 文字口径。
   只删字段不清洗文本 = 留后门（审核读的是 JSON 全量）。
3. 词表驱动 + 白名单。宁可多删，不可漏删；白名单只保护财务/估值/免责的合法语境。

【裁剪清单（2026-10-23 生产实测 600519/601318/000858 逐字段核对）】
A. 整维删除：capital_momentum（融资余额20日变化、主力净流入20日累计）
B. 子项删除：chain_prosperity→「所属行业20日市值变动」（行业总市值20日变动=行情）
             earnings_revision→「买入/增持评级占比」（字面即荐股倾向词）
C. 文本删除：blocks「风从哪来」「资金（带可靠性）」
             risk_facts 里的券商评级类（「维持"买入"评级」「强烈推荐」）
D. 结构删除：industry.industry_index（口径=区间涨跌幅）、industry.notes 的行业景气条目、
             industry_facts 的行业景气条目
E. 文字改口径：估值「当前 X」→「数据截至 {asof} 为 X」；「低估区/高估区」→
             「历史低分位/历史高分位」；「筑底」等技术面词→中性表述
F. 改名：势能→行业与周期；产业链景气→行业基本面；预期修正→分析师预期

【分数重算（M_MODE）——峰哥拍板项】
删掉子项后，原分数仍含已删因子的贡献（展示 4 个子项、分数是 5 个算的），
这构成「隐含行情因子」。两种处理见 M_MODE。三层数学已用生产数据反推验证：
    dim   = Σ(w × contrib) / Σw           600519: 38.0684 vs 线上 38.07 ✅
    group = Σ(w × s) / Σw                 M: 52.459 vs 线上 52.46 ✅
    total = Σ(dim.weight × dim.score)     65.8378 / 66.3308 / 63.1130 三只全中 ✅
    tier  = ≥80 优 / ≥65 良 / ≥45 中 / 其余待观察（与 stockscore.tier_of 一致）
"""
import copy
import re

# ────────────────────────────────────────────────────────────────────
# 口径开关（峰哥拍板项）
#   'renorm' = 删子项后 dim→M→total→tier 全链重算。
#              ✅ 数学自洽，彻底不含已删因子；❌ 小程序总分与网页版会差 3~5 分，
#              600519 实测 65.84（良）→ 61.81（中），档位会掉。
#   'keep'   = 总分/档位全沿用网页版，只裁展示字段与 dim 分。
#              ✅ 两版分数一致；❌ 总分里仍含资金动能等已删因子贡献，
#              审核若追问「M 组 22% 权重算什么」将无法自圆其说。
# ────────────────────────────────────────────────────────────────────
M_MODE = 'renorm'

# 需要整维删除的维度
DROP_DIMS = ('capital_momentum',)

# 子 metric 删除正则（作用于 metric['name']）
DROP_METRIC_RE = re.compile(
    r'20日市值变动|日市值变动|区间涨跌幅|等权合成指数|'
    r'融资余额|主力净流入|龙虎榜|北向资金|主力资金|'
    r'买入/增持评级|卖出/减持评级'
)

# block 标题删除
DROP_BLOCK_TITLES = ('风从哪来', '资金（带可靠性）')

# industry_facts / industry.notes 删除正则
DROP_FACT_RE = re.compile(r'行业景气|等权合成指数|区间涨跌幅|成分股行情不足以合成')

# 券商评级类条目：整条删（不能只改词，「维持买入评级」本身就是建议）。
# 2026-10-23 生产 9 只实测补漏：「优于大市/强于大市/持有」等券商档位词必须入表，
# 否则 601318/000651/603259 的「维持"优于大市"评级」会漏网。
_RATING_TIER = (r'买入|增持|卖出|减持|强烈推荐|推荐|中性|持有|观望|优于大市|强于大市|'
                r'弱于大市|跑赢大市|跑输大市|与大市同步|跑赢|跑输')
ADVICE_RE = re.compile(
    r'维持[“"]?\s*(' + _RATING_TIER + r')[”"]?\s*评级|'
    r'研报维持[“"]?\s*(' + _RATING_TIER + r')[”"]?\s*评级|'
    # 宽松兜底：「维持盈利预测与"优于大市"评级」这种中间夹词的（000333 生产实测漏网）
    r'维持.{0,15}?(' + _RATING_TIER + r').{0,10}?评级|'
    r'投资评级|评级建议|给予.{0,8}(评级|评价)|目标价|隐含回报率'
)

# 文本兜底清洗：(正则, 替换)。占位符 __ASOF__ 由 _scrub 注入。
# 「当前 X」一律改「数据截至 {asof} 为 X」：既去「当前」这个行情味词，
# 又保住财务口径信息（当前 89.83% → 数据截至 2026-10-23 为 89.83%）。
# 2026-10-23 补：负值要能匹配（五粮液「当前 -0.24倍」）。
SCRUB_RULES = [
    # 【最高优先】抹除内部策略代号。链条图覆盖率原句含「V35 持仓频次 TOP30」，
    # 小程序对外暴露内部策略体系代号，比任何行情词都严重，整段替换。
    (re.compile(r'(当前覆盖|已覆盖)[^）)]*'), '覆盖范围有限'),
    (re.compile(r'(?<!净)当前\s*(-?[0-9][0-9.]*)'), r'数据截至 __ASOF__ 为 \1'),
    # 「DCF 当前不适用」的「当前」是方法适用性，不是估值当前值 → 暂不
    (re.compile(r'当前不(?![确定])'), '暂不'),
    # 业务进展语境的「突破」（如「数据中心液冷实现突破」）会被误读为股价突破
    (re.compile(r'(实现|取得|获得)突破'), '已落地应用'),
    (re.compile(r'当前股价'), '数据截至 __ASOF__'),
    (re.compile(r'高估区'), '历史高分位'),
    (re.compile(r'低估区'), '历史低分位'),
    (re.compile(r'处于低估'), '处于历史低分位'),
    (re.compile(r'处于高估'), '处于历史高分位'),
    # 模块名与维度名（先改名，headline/verdict 再基于新名生成）
    (re.compile(r'资金动能'), '分析师预期与行业基本面'),
    (re.compile(r'产业链景气'), '行业基本面'),
    (re.compile(r'预期修正'), '分析师预期'),
    (re.compile(r'势能'), '行业与周期'),
    # 技术面 / 趋势词 → 中性表述
    (re.compile(r'筑底'), '调整'),
    (re.compile(r'行情历史'), '数据历史'),
    (re.compile(r'现在有没有风'), '所处行业基本面如何'),
]

# 白名单：财务/估值/免责语境合法，禁止误杀
WHITELIST_RE = re.compile(
    r'净占用.*资金|自由现金流收益率|FCF\s*收益率|现金流收益率|'
    r'不是涨跌预测|未扣净债|运营资金|营运资金|'
    r'不构成买卖建议|不构成投资建议|'
    r'大股东减持（接口未接）|数据截至'
)

_TIER = ('待观察', '中', '良', '优')   # 与 stockscore.tier_of 一致


def tier_of(total):
    """与 backend/stockscore.py::tier_of 保持一致（80/65/45）。"""
    if total is None:
        return None
    return '优' if total >= 80 else '良' if total >= 65 else '中' if total >= 45 else '待观察'


def _scrub(text, asof):
    if not isinstance(text, str) or not text:
        return text
    if WHITELIST_RE.search(text):
        return text
    out = text
    for pat, rep in SCRUB_RULES:
        out = pat.sub(rep.replace('__ASOF__', asof or '最新披露日'), out)
    return out


def _deep_scrub(node, asof):
    if isinstance(node, dict):
        return {k: _deep_scrub(v, asof) for k, v in node.items()}
    if isinstance(node, list):
        return [_deep_scrub(v, asof) for v in node]
    if isinstance(node, str):
        return _scrub(node, asof)
    return node


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _recalc_dim(d):
    """删子项后重算 dim 分：score = Σ(w×contrib)/Σw（已用生产数据验证）。"""
    sw = sc = 0.0
    for m in (d.get('metrics') or []):
        w, c = _num(m.get('weight')), _num(m.get('contrib'))
        if w is None or c is None:
            continue
        sw += w
        sc += w * c
    if not sw:
        d['score'] = None
        d['available'] = False
        return d
    d['score'] = round(sc / sw, 2)
    d['available'] = True
    return d


def _drop_advice_items(items):
    """删掉带券商评级/建议的条目（risk_facts / risk_flags 等）。"""
    if not isinstance(items, list):
        return items
    out = []
    for it in items:
        txt = it.get('text') if isinstance(it, dict) else str(it)
        if isinstance(txt, str) and ADVICE_RE.search(txt):
            continue
        out.append(it)
    return out


def _strip_risk(r, asof):
    r = copy.deepcopy(r)
    for k in ('risk_facts', 'risk_flags', 'unresolved', 'contradictions'):
        r[k] = _drop_advice_items(r.get(k))
    return _deep_scrub(r, asof)


def _strip_momentum(m, asof):
    """裁 momentum 模块。返回新 dict，原对象不改。"""
    m = copy.deepcopy(m)

    # D1. industry：index 整块删 + notes 里的行业景气条目删
    ind = m.get('industry')
    if isinstance(ind, dict):
        ind.pop('industry_index', None)
        ind.pop('industry_data_gap', None)
        for k in ('notes', 'gaps', 'data_gap'):
            v = ind.get(k)
            if isinstance(v, list):
                ind[k] = [x for x in v if not (isinstance(x, str) and DROP_FACT_RE.search(x))]
        for k in list(ind.keys()):
            if isinstance(ind[k], str) and DROP_FACT_RE.search(ind[k]):
                ind.pop(k, None)

    # D2. industry_facts
    if isinstance(m.get('industry_facts'), list):
        m['industry_facts'] = [f for f in m['industry_facts']
                               if not (isinstance(f, str) and DROP_FACT_RE.search(f))]

    # D3. dims：整维删 + 子 metric 删 + 改名 + 重算
    keep = []
    for d in (m.get('dims') or []):
        if d.get('key') in DROP_DIMS:
            continue
        d = copy.deepcopy(d)
        d['metrics'] = [mt for mt in (d.get('metrics') or [])
                        if not DROP_METRIC_RE.search(str(mt.get('name') or ''))]
        d.pop('reliability', None)
        if not d['metrics']:
            d['available'] = False
            d['score'] = None
            d['flags'] = list(d.get('flags') or []) + ['小程序口径：行情与评级类子项已剔除，本维不再计分']
            keep.append(d)
            continue
        d = _recalc_dim(d)                      # 子项已删，不重算就自相矛盾
        d['label'] = _scrub(d.get('label') or '', asof)
        keep.append(d)
    m['dims'] = keep

    # C. blocks
    if isinstance(m.get('blocks'), list):
        m['blocks'] = [b for b in m['blocks'] if b.get('h') not in DROP_BLOCK_TITLES]

    m['title'] = '行业与周期'
    m['headline'] = _mom_headline(keep, asof)
    m['verdict'] = _mom_verdict(keep, asof)

    # 【末尾统一清洗】blocks / industry.notes / metrics 的文字必须过 scrub。
    # 2026-10-23 生产实测教训：只 scrub dims.label 会漏掉 blocks 正文，
    # 「链条图（当前覆盖 V35 持仓频次...）」整句漏网 = 内部策略代号外泄。
    # 在出口层做最后一次全量清洗，保证任何新增字段路径都不会漏。
    m = _deep_scrub(m, asof)
    return m


def _mom_score(dims):
    if M_MODE == 'drop':
        return None
    sw = sc = 0.0
    for d in dims:
        w, s = _num(d.get('weight')), _num(d.get('score'))
        if s is None or not d.get('available'):
            continue
        sw += w or 0.0
        sc += (w or 0.0) * s
    return round(sc / sw, 1) if sw else None


def _mom_headline(dims, asof):
    parts = []
    for d in dims:
        if d.get('key') in DROP_DIMS:
            continue
        s = _num(d.get('score'))
        if s is None or not d.get('available'):
            continue
        parts.append(f"{d.get('label')} {s:.1f}")
    head = ' / '.join(parts) if parts else '所处行业基本面数据不足'
    return f'{head}（数据截至 {asof}）'


def _mom_verdict(dims, asof):
    ok = sorted([(d.get('label'), _num(d.get('score'))) for d in dims
                 if d.get('key') not in DROP_DIMS
                 and d.get('available') and _num(d.get('score')) is not None],
                key=lambda x: x[1])
    if not ok:
        return f'所处行业基本面数据不足，本页只给行业归属与主营构成，不做打分。数据截至 {asof}。'
    score = _mom_score(dims)
    weak, ws = ok[0]
    strong, ss = ok[-1]
    return (f'行业与周期 {score:.1f} 分。相对更强的是{strong}（{ss:.1f} 分），'
            f'更弱的是{weak}（{ws:.1f} 分）。本页只描述所处行业的基本面位置，'
            f'不预测价格走势。数据截至 {asof}。')


def _recalc_overview(ov, mods):
    """dim→M→total→tier 全链重算。"""
    ov = copy.deepcopy(ov)
    dims_all = []
    for gk, mk in (('Q', 'quality'), ('V', 'price'), ('M', 'momentum')):
        for d in (mods.get(mk) or {}).get('dims') or []:
            dims_all.append((gk, d))

    if M_MODE == 'keep':
        # 总分/档位沿用网页版；仅把 M 组 dim 分改为已裁口径（子项已删，必须一致）
        ms = _mom_score((mods.get('momentum') or {}).get('dims') or [])
        if ms is not None:
            ov['groups']['M']['score'] = ms
        ov['groups']['M']['label'] = '行业与周期'
        ov['groups']['M']['question'] = '所处行业基本面如何'
        return ov

    # ── renorm：三层重算 ──
    total_raw = 0.0
    for gk, d in dims_all:
        w, s = _num(d.get('weight')), _num(d.get('score'))
        if s is None or not d.get('available'):
            continue
        total_raw += (w or 0.0) * s
    total_raw = round(total_raw, 2)

    gate = ov.get('gate') or {}
    red = gate.get('red') or []
    yellow = gate.get('yellow') or []
    total = min(total_raw, 59.0) if red else total_raw
    gate_hit = ('red' if red else 'yellow2' if len(yellow) >= 2
                else 'yellow1' if len(yellow) == 1 else 'none')

    base_tier = tier_of(total)
    tier = base_tier
    if gate_hit == 'yellow2' and tier in _TIER:
        tier = _TIER[max(0, _TIER.index(tier) - 1)]

    if gate_hit == 'yellow2':
        tier_note = (f'风险提示 {len(yellow)} 条 → 分档下调一档（{base_tier} → {tier}）'
                     if base_tier != tier
                     else f'风险提示 {len(yellow)} 条 → 已在下限档（{tier}），不再下调')
    elif gate_hit == 'yellow1':
        tier_note = f'风险提示 1 条 → 仅标注，不调档（{tier}）'
    elif gate_hit == 'red':
        tier_note = f'风险提示 {len(red)} 条 → 总分封顶 59（裸分 {total_raw}）'
    else:
        tier_note = None

    for gk in ('Q', 'V', 'M'):
        gd = [d for g, d in dims_all if g == gk and d.get('available') and _num(d.get('score')) is not None]
        gw = sum((_num(d.get('weight')) or 0.0) for d in gd)
        if gw:
            ov['groups'][gk]['score'] = round(sum((_num(d.get('weight')) or 0.0) *
                                                 _num(d.get('score')) for d in gd) / gw, 2)
            ov['groups'][gk]['available'] = True
        else:
            ov['groups'][gk]['score'] = None
            ov['groups'][gk]['available'] = False

    ov['groups']['M']['label'] = '行业与周期'
    ov['groups']['M']['question'] = '所处行业基本面如何'
    if M_MODE == 'drop':
        ov['groups']['M']['score'] = None
        ov['groups']['M']['available'] = False
        ov['groups']['M']['note'] = '小程序口径：本组不打分，仅做客观描述'

    ov['total'] = total
    ov['total_raw'] = total_raw
    ov['tier'] = tier
    ov['tier_note'] = tier_note

    try:
        ranked = [(g['label'], g['score']) for g in
                  (ov['groups']['Q'], ov['groups']['V'], ov['groups']['M'])
                  if g.get('score') is not None]
        ranked.sort(key=lambda x: x[1])
        strong, ss = ranked[-1]
        weak, ws = ranked[0]
        note_map = {'优': '表现突出', '良': '较强', '中': '中等', '待观察': '需重点观察'}
        ov['one_liner'] = (f'综合打分 {total} 分，{note_map.get(tier, tier)}。'
                           f'强在{strong}（{ss} 分），弱在{weak}（{ws} 分）。'
                           f'这是按打分卡算出的质地水平，不构成买卖建议。')
        ov['headline'] = ' / '.join(f'{lb} {sc}' for lb, sc in ranked if sc is not None)
        if yellow:
            ov['headline'] += f'；风险提示 {len(yellow)} 条'
    except Exception:
        pass
    return ov


def strip(bundle):
    """小程序出口裁剪入口。返回新 dict，入参不被修改。"""
    b = copy.deepcopy(bundle)
    asof = b.get('data_asof') or '最新披露日'
    mods = b.get('modules') or {}

    if isinstance(mods.get('momentum'), dict):
        mods['momentum'] = _strip_momentum(mods['momentum'], asof)
    for k in ('price', 'quality'):
        if isinstance(mods.get(k), dict):
            mods[k] = _deep_scrub(mods[k], asof)
    if isinstance(mods.get('risk'), dict):
        mods['risk'] = _strip_risk(mods['risk'], asof)

    # overview.key_risks 是 dict 列表，之前漏 scrub（生产实测「杠杆水平：当前 89.83%」漏网）
    if isinstance(b.get('overview'), dict):
        ov0 = b['overview']
        ov0['key_risks'] = _deep_scrub(ov0.get('key_risks'), asof)
        for k in ('notes', 'gaps', 'data_gap'):
            v = ov0.get(k)
            if isinstance(v, list):
                ov0[k] = _deep_scrub(v, asof)
        # 总分/档位重算（依赖已裁剪的 mods）
        b['overview'] = _recalc_overview(ov0, mods)

    # momentum 分与 overview 同步
    mom = mods.get('momentum')
    if isinstance(mom, dict):
        mom['score'] = _mom_score(mom.get('dims') or [])
        mom['headline'] = _mom_headline(mom.get('dims') or [], asof)
        mom['verdict'] = _mom_verdict(mom.get('dims') or [], asof)

    # risk 结论块引用了旧总分，重写
    rk = mods.get('risk')
    if isinstance(rk, dict) and isinstance(rk.get('blocks'), list) and isinstance(b.get('overview'), dict):
        ov = b['overview']
        for bl in rk['blocks']:
            if bl.get('h') == '结论':
                bl['t'] = (f'总分 {ov["total"]}，属于{ov["tier"]}这一档。'
                           f'这是按打分卡算出的质地水平，不构成买卖建议。')

    if 'research_reports' in b:
        b['research_reports'] = _deep_scrub(b['research_reports'], asof)

    b['compliance'] = {
        'scope': 'mini',
        'data_asof': asof,
        'notice': f'数据截至 {asof}。本页为公司基本面与历史财务数据展示，不构成投资建议。',
        'm_mode': M_MODE,
        # 注意：这里不能出现「行情/评级/资金/动量」等词——审核扫的是整份 JSON，
        # 合规说明本身带禁词等于自己举报自己（生产实测命中过）。
        'score_caliber': ('小程序口径：剔除非基本面类因子后重算' if M_MODE == 'renorm'
                          else '与网页版同口径'),
    }
    return b


def strip_many(bundles):
    """批量裁剪（预热 / 异步端点用）。"""
    return [strip(x) for x in bundles]
