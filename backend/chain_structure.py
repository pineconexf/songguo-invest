# -*- coding: utf-8 -*-
"""产业链结构层（路线 2，2026-10-18）

为什么不是投入产出表：国家统计局 `data.stats.gov.cn` 全路径被 WAF 按 URL ACL 拦截（403），
153 部门直接消耗系数矩阵取不到。改用「申万三级归属 + 主营构成 + 概念板块 + 人工维护的链条图」，
精度低一档，但全自动、可持续更新、可审计。

三层数据：
  L1 归属  申万一级/二级/三级 + 证监会行业 —— 东财 F10，全市场 5265 只，已落盘 data/industry_taxonomy.json
  L2 落点  主营构成（按产品/按地区，含收入占比与毛利率）—— 东财 F10 RPT_F10_FN_MAINOP
  L3 结构  上下游关系 —— chain_map_v1.json（人工维护、版本化，覆盖 V35 持仓频次 TOP30 二级行业 = 80.0%）

关键设计：上下游不是查完就完，还要把**上下游当前的景气读数**接进来（board_prosperity），
这样才能回答「传导到哪」，而不是只画一张静态关系图。

口径铁律：
  - 链条图未覆盖的行业 → mapped=False，如实显示「结构未标注」，不猜
  - 上游/下游为空是真实语义（煤炭开采无上游、一般零售无下游行业），不是缺失
  - 传导判断只依据上下游与本环节的营收增速中位数差，不做主观推测
"""
import json
import os

from stockscore import pct_rank

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(BASE_DIR, 'chain_map_v1.json')
TAX_PATH = os.path.join(BASE_DIR, 'data', 'industry_taxonomy.json')

_MAP = {'data': None}
_TAX = {'data': None}

# 传导判断阈值（营收增速中位数差，百分点）。低于此视为同步，不硬解读导。
GAP_PP = 5.0
# 同一端（上游/下游）各行业增速极差超过此值，视为分化，方向一致性弱
SPREAD_PP = 15.0


def load_map():
    if _MAP['data'] is None:
        try:
            with open(MAP_PATH, encoding='utf-8') as f:
                _MAP['data'] = json.load(f)
        except Exception:
            _MAP['data'] = {'version': None, 'industries': {}}
    return _MAP['data']


def load_taxonomy():
    if _TAX['data'] is None:
        try:
            with open(TAX_PATH, encoding='utf-8') as f:
                _TAX['data'] = json.load(f).get('map') or {}
        except Exception:
            _TAX['data'] = {}
    return _TAX['data']


def _prod_rows(mb_rows):
    """主营构成 → 按产品 / 按地区。MAINOP_TYPE: 2=按产品 3=按地区。

    「其他」「其他(补充)」「合计」这类汇总行必须剔除：它们不是产品线，
    留着会污染「毛利率最高的产品」判断（中芯国际曾把「其他」当成最高毛利产品）。
    """
    prod, reg = [], []
    SKIP = ('其他', '合计', '总计', '小计', '分部间', '内部抵销', '抵消')
    for r in mb_rows or []:
        t = str(r.get('MAINOP_TYPE') or '')
        name = str(r.get('ITEM_NAME') or '').strip()
        if not name:
            continue
        head = name.split('(')[0].split('（')[0].strip()
        if head in SKIP:
            continue
        ratio = r.get('MBI_RATIO')
        gm = r.get('GROSS_RPOFIT_RATIO')
        item = {
            'name': name,
            'share': round(float(ratio) * 100.0, 2) if ratio is not None else None,
            'gm': round(float(gm) * 100.0, 2) if gm is not None else None,
        }
        if t == '2':
            prod.append(item)
        elif t == '3':
            reg.append(item)
    prod.sort(key=lambda x: -(x['share'] or 0))
    reg.sort(key=lambda x: -(x['share'] or 0))
    return prod, reg


def _board_now(bp, name):
    """按二级行业名取当前景气读数（含分位）。"""
    if not bp or not name:
        return None
    bk = None
    for k, v in (bp.get('names') or {}).items():
        if v == name:
            bk = k
            break
    if not bk:
        return None
    row = (bp.get('boards') or {}).get(bk) or {}
    out = {'industry': name}
    if row.get('rev_med') is not None:
        out['rev_med'] = round(row['rev_med'], 2)
        out['rev_pctl'] = round(pct_rank(bp.get('rev_pool') or [], row['rev_med']), 1)
    if row.get('dnp_med') is not None:
        out['dnp_med'] = round(row['dnp_med'], 2)
        out['dnp_pctl'] = round(pct_rank(bp.get('dnp_pool') or [], row['dnp_med']), 1)
    if row.get('loss_pct') is not None:
        out['loss_pct'] = round(row['loss_pct'], 2)
    out['peers'] = row.get('n')
    return out if len(out) > 1 else None


def _transmission(own_rev, ups, downs):
    """只依据营收增速中位数差判断传导方向，不做主观推测。

    端内分化必须提示：用均值定方向，但若同一端各行业增速极差 > SPREAD_PP，
    方向的一致性就弱，必须如实标注，不能让一个强项把整端拉成「需求旺盛」。
    """
    up_v = [u['rev_med'] for u in ups if u.get('rev_med') is not None]
    dn_v = [d['rev_med'] for d in downs if d.get('rev_med') is not None]
    up = round(sum(up_v) / len(up_v), 2) if up_v else None
    dn = round(sum(dn_v) / len(dn_v), 2) if dn_v else None
    out = {'upstream_rev_avg': up, 'downstream_rev_avg': dn,
           'own_rev': round(own_rev, 2) if own_rev is not None else None,
           'verdict': None, 'detail': None}
    for tag, vals in (('upstream', up_v), ('downstream', dn_v)):
        if len(vals) >= 2:
            out[tag + '_spread'] = round(max(vals) - min(vals), 2)
            out[tag + '_range'] = [round(min(vals), 2), round(max(vals), 2)]
    if own_rev is None or (up is None and dn is None):
        out['verdict'] = 'unknown'
        out['detail'] = '上下游或本环节景气数据不足，不做传导判断'
        return out
    tags = []
    if up is not None:
        gap = up - own_rev
        out['up_gap'] = round(gap, 2)
        if gap > GAP_PP:
            tags.append(f'上游景气高于本环节 {gap:.1f}pp，成本端有压力，能否顺价决定毛利')
        elif gap < -GAP_PP:
            tags.append(f'上游景气低于本环节 {gap:.1f}pp，成本端在缓解')
    if dn is not None:
        gap = dn - own_rev
        out['down_gap'] = round(gap, 2)
        if gap > GAP_PP:
            tags.append(f'下游均值高于本环节 {gap:.1f}pp，有提价或放量空间')
        elif gap < -GAP_PP:
            tags.append(f'下游均值低于本环节 {gap:.1f}pp，警惕订单见顶')
    if tags:
        out['verdict'] = 'divergent'
        out['detail'] = '；'.join(tags)
    else:
        out['verdict'] = 'aligned'
        out['detail'] = '上下游与本环节景气大致同步，无显著传导错位'
    # 分化提示：方向一致性弱时必须说清，避免「均值一句话盖过结构分化」
    caveats = []
    for label, key in (('上游', 'upstream'), ('下游', 'downstream')):
        sp, rg = out.get(key + '_spread'), out.get(key + '_range')
        if sp is not None and sp > SPREAD_PP and rg:
            caveats.append(f'{label}内部分化大（{rg[0]}% ~ {rg[1]}%，极差 {sp}pp），'
                           f'方向一致性弱，不要只看均值')
    if caveats:
        out['detail'] = out['detail'] + '。但注意：' + '；'.join(caveats) + '。'
        out['dispersion_warning'] = True
    return out



def build(code, basic, bp, mb_rows, own_rev=None):
    """组装一只股票的产业链结构记录。

    basic    东财 F10 基础信息（含三级行业与概念板块）
    bp       stockscore_v3.board_prosperity() 的输出
    mb_rows  stockscore_v3.main_business() 的行
    own_rev  本股单季营收同比（用于传导判断），可为 None
    """
    cm = load_map()
    industries = cm.get('industries') or {}
    basic = basic or {}

    l1 = basic.get('BOARD_NAME_1LEVEL')
    l2 = basic.get('BOARD_NAME_2LEVEL')
    l3 = basic.get('BOARD_NAME_3LEVEL')
    csrc = basic.get('CSRC_INDUSTRY_NAME')

    # 分类缺失时用落盘的分类表兜底
    if not l2:
        t = load_taxonomy().get(code if '.' in str(code) else None) or {}
        if not t:
            for sc, v in load_taxonomy().items():
                if str(sc).split('.')[0] == str(code):
                    t = v
                    break
        l1, l2, l3, csrc = t.get('l1'), t.get('l2'), t.get('l3'), t.get('csrc')

    entry = industries.get(l2) if l2 else None
    prod, reg = _prod_rows(mb_rows)
    concepts = [c for c in str(basic.get('BLGAINIAN') or '').split(',') if c]

    ups = [x for x in (_board_now(bp, n) for n in (entry or {}).get('upstream') or []) if x]
    downs = [x for x in (_board_now(bp, n) for n in (entry or {}).get('downstream') or []) if x]
    own_now = _board_now(bp, l2)

    out = {
        'version': cm.get('version'),
        'mapped': bool(entry),
        'l1': l1, 'l2': l2, 'l3': l3, 'csrc': csrc,
        'segment': (entry or {}).get('segment'),
        'chain': (entry or {}).get('chain'),
        'cyclicality': (entry or {}).get('cyclicality'),
        'moat': (entry or {}).get('moat'),
        'drivers': (entry or {}).get('drivers') or [],
        'note': (entry or {}).get('note'),
        'products': prod[:5],
        'regions': reg[:3],
        'concepts': concepts[:12],
        'upstream': ups,
        'downstream': downs,
        'own_now': own_now,
        'transmission': _transmission(own_rev, ups, downs) if entry else None,
    }
    out['narration'] = narrate(out)
    return out


def narrate(s):
    """规则生成解说（确定性，不调 LLM；每个结论都能回溯到上方的数字）。
    返回 [{'h': 小标题, 't': 正文}]，可直接喂给页面 blocks。"""
    lines = []
    name_bits = ' / '.join([x for x in (s.get('l1'), s.get('l2'), s.get('l3')) if x])
    if s.get('mapped'):
        lines.append({'h': '产业链定位', 't':
            f"{name_bits}。在「{s['chain']}」这条链上处于 {s['segment']} 环节，"
            f"属性偏{s['cyclicality']}。壁垒形态：{s['moat']}。{s.get('note') or ''}"})
    else:
        lines.append({'h': '产业链定位', 't':
            f"{name_bits}。该行业尚未纳入链条图（当前覆盖 V35 持仓频次 TOP30 二级行业 = 80.0%），"
            f"上下游关系未标注——不猜，只给行业归属与主营构成。"})

    if s.get('products'):
        top = s['products'][0]
        gm_items = [p for p in s['products'] if p.get('gm') is not None]
        gm_best = max(gm_items, key=lambda x: x['gm']) if gm_items else None
        seg = f"{top['name']} 占 {top['share']}%" if top.get('share') is not None \
            else f"{top['name']} 为第一大产品"
        if gm_best and gm_best is not top and gm_best.get('share') is not None:
            seg += f"；毛利率最高的是 {gm_best['name']}（{gm_best['gm']}%，占 {gm_best['share']}%）"
        elif gm_best and gm_best.get('gm') is not None:
            seg += f"；自身毛利率 {gm_best['gm']}%"
        if len(s['products']) > 1:
            seg = '主营构成：' + seg + f"。共 {len(s['products'])} 条产品线，按收入排序取前 {len(s['products'])}"
        else:
            seg = '主营构成：' + seg
        lines.append({'h': '主营落点', 't': seg})
    else:
        lines.append({'h': '主营落点', 't': '主营构成未披露按产品的拆分，只能按行业口径看。'})

    if s.get('mapped'):
        if s['upstream']:
            bits = [f"{u['industry']}（营收中位 {u['rev_med']}%，分位 {u['rev_pctl']}）"
                    for u in s['upstream'] if u.get('rev_med') is not None]
            if bits:
                lines.append({'h': '上游景气', 't': '；'.join(bits) + '。'})
        else:
            lines.append({'h': '上游景气', 't': '本环节处于链条起点（上游为自然资源），无行业上游。'})
        if s['downstream']:
            bits = [f"{d['industry']}（营收中位 {d['rev_med']}%，分位 {d['rev_pctl']}）"
                    for d in s['downstream'] if d.get('rev_med') is not None]
            if bits:
                lines.append({'h': '下游景气', 't': '；'.join(bits) + '。'})
        else:
            lines.append({'h': '下游景气', 't': '本环节直接面向最终需求，下游无行业可接。'})

    tr = s.get('transmission') or {}
    if tr.get('detail'):
        lines.append({'h': '传导判断', 't': tr['detail'] + '。'})
    return lines

