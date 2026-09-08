# -*- coding: utf-8 -*-
"""
每日资讯解读自动更新管线
========================
每交易日收盘后运行：用真实行情(6大指数当日收盘) + 本地宏观信号(Shibor 1W)
重新生成 src/data/research_daily.json 的 latest，实现"每日解读"自动更新。

自动化的边界（严守数据真实铁律）：
  market/turnover      -> tushare 当日真实收盘(close/pct_chg/amount)，无估算
  signals[0] Shibor    -> 本地 macro_signal.json 最新周(真实)，环比较 5bp 阈值给仓位信号
  headline/signal_summary -> 真实数字 + 松果体系规则模板(中小盘强弱/成交/Shibor信号)
  viewpoints           -> 松果体系固定判断模板(宏观管仓位·个股管选股)，无需每日人写
  signals[1..3] 组合月度 -> 月度口径快照，由月度更新维护，不随每日重算(标注月份)
  focus(政策/产业热点)   -> 清单级：从信源池当日A股源(财联社/华尔街见闻/格隆汇/雪球/36氪)规则筛
                        政策/产业热点，来源可溯不编造；无当日新料则沿用最近一期并如实标注

用法: python scripts/build_research_daily.py
输出: src/data/research_daily.json（latest 更新到最近已收盘交易日）
"""
import os, json, io, sys, csv
import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

TOKEN_ENV = os.path.expanduser(r'~/AppData/Local/hermes/.env')
OUT = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data\research_daily.json'
MACRO = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data\macro_signal.json'

INDEXES = [
    ('000001.SH', '上证指数'), ('399001.SZ', '深证成指'), ('399006.SZ', '创业板指'),
    ('000300.SH', '沪深300'), ('000905.SH', '中证500'), ('000016.SH', '上证50'),
]
# 两市中"大盘"代理与"中小盘"代理（相对强弱判断）
BIG = '000300.SH'    # 沪深300
SMALL = '000905.SH'  # 中证500

def load_token():
    for line in open(TOKEN_ENV, encoding='utf-8'):
        line = line.strip()
        if line.startswith('TUSHARE_API_KEY='):
            return line.split('=', 1)[1].strip()
    raise SystemExit('未找到 TUSHARE_API_KEY')

def tq(api, params, fields, tok):
    r = requests.post('http://api.tushare.pro/dataapi/' + api,
                      json={'api_name': api, 'token': tok, 'params': params, 'fields': fields}, timeout=15)
    b = r.json()
    if b.get('code') != 0:
        return None, b.get('msg')
    d = b['data']
    return d['items'], d['fields']

def latest_trade_date(tok):
    # 用上证最近几日探测最新已收盘交易日
    rows, _ = tq('index_daily', {'ts_code': '000001.SH', 'start_date': '20260801', 'end_date': '20261231'},
                 'trade_date', tok)
    if not rows:
        raise SystemExit('无法获取交易日历')
    return sorted({r[0] for r in rows})[-1]

def fmt_chg(x):
    try:
        return f"{float(x):+.2f}%"
    except:
        return str(x)

def main():
    tok = load_token()
    td = latest_trade_date(tok)
    print(f'最新已收盘交易日: {td}  ({td[:4]}-{td[4:6]}-{td[6:]})')

    # 1) 6 大指数当日收盘（close/pct_chg/amount，amount 为成交额千元）
    market, amount_sum = [], 0.0
    for code, name in INDEXES:
        rows, cols = tq('index_daily', {'ts_code': code, 'trade_date': td},
                        'trade_date,close,pct_chg,amount', tok)
        if not rows:
            raise SystemExit(f'{name} {code} 无 {td} 数据: {cols}')
        row = rows[-1]
        close, chg, amount = row[1], row[2], float(row[3] or 0)
        if code in ('000001.SH', '399001.SZ'):  # 两市=上证+深证，避免成分指数重复计入
            amount_sum += amount
        market.append({'index': name, 'close': f"{close:.2f}", 'chg': fmt_chg(chg), 'vol': f"{amount/1e5:.0f} 亿"})
    turn_trillion = amount_sum / 1e9  # 千元 -> 万亿 (1万亿 = 1e9 千元)
    print(f'6 指数收盘已取, 两市成交约 {turn_trillion:.2f} 万亿')

    # 大盘 vs 中小盘相对强弱
    def chg_of(code):
        for m in market:
            pass
        rows, _ = tq('index_daily', {'ts_code': code, 'trade_date': td}, 'pct_chg', tok)
        return float(rows[-1][0])
    strong_small = chg_of(SMALL) > chg_of(BIG)

    # 2) Shibor 1W 最新周信号（本地 macro_signal.json）
    macro = json.load(open(MACRO, encoding='utf-8'))
    w = macro['weeks'][-1]
    shibor_signal = '宽松 → 指数仓位可进攻' if w['action'] == '买入中证500' else '收紧 → 指数择时继续空仓等待'
    sig0 = {
        'name': f"Shibor 1W（{w['week']}）",
        'value': f"{w['shibor']}%（环比 {w['diff_bp']:+.2f}bp 对上周）",
        'verdict': '宽松/可进攻' if w['action'] == '买入中证500' else '收紧/空仓',
        'note': f"未过 5bp 宽松阈值" if w['diff_bp'] >= -5 and w['action'] != '买入中证500' else '环比下行超 5bp，触发宽松',
    }

    # 3) 组合月度信号（月度口径快照，标注月份；由月度更新维护，不随每日重算）
    month_snapshot = [
        {'name': 'ETF 四拼图（防守组合月度）', 'value': '截至 2026-08', 'verdict': '防守组合 YTD 正', 'note': '月度口径，月底更新'},
        {'name': '公募组合（防守组合月度）', 'value': '截至 2026-08', 'verdict': '防守组合 YTD 正', 'note': '月度口径，月底更新'},
        {'name': '沪深300（基准）', 'value': 'YTD 以月末对比', 'verdict': '防守类显著跑赢', 'note': '月度口径，月底更新'},
    ]

    # 4) headline / signal_summary（真实数字 + 体系规则模板）
    sh, sc = market[0]['close'], market[0]['chg']
    zx = market[3]['close']  # 沪深300
    turnover_txt = f"两市合计成交约 {turn_trillion:.2f} 万亿。"
    small_txt = "中小盘（中证500）强于大盘，风险偏好边际修复。" if strong_small else "大盘强于中小盘，资金偏防御。"
    headline = (
        f"{td[:4]}年{int(td[4:6])}月{int(td[6:])}日收盘：上证收于 {sh} 点（{sc}），{turnover_txt}{small_txt}"
        f"宏观流动性{Shibor_desc(w['diff_bp'])}，择时按 {sig0['verdict']}。"
    )
    signal_summary = (
        f"Shibor 1W 最新 {w['shibor']}%（环比 {w['diff_bp']:+.2f}bp）→ {shibor_signal}；"
        f"防守组合月度口径继续跑赢（月末刷新）。"
    )

    # 5) viewpoints（松果体系固定判断模板，无需每日人写）
    views = [
        {'topic': '仓位', 'point': '宏观信号定指数择时；个股/组合仓位按个人回撤容忍度执行，不与宏观信号混为一谈（宏观管仓位、个股管选股）。'},
        {'topic': '风格', 'point': '资金流向低估值防御 + 政策催化双主线；追高风险大于等待风险。'},
        {'topic': '防守组合', 'point': '债/金/红利/QDII 四拼图无需因单日波动调整，季度审视即可。'},
    ]

    # 6) focus（清单级：信源池当日 A 股源规则筛选，来源可溯，不编造）
    try:
        old = json.load(open(OUT, encoding='utf-8'))
        last_focus = old['latest'].get('focus', [])
    except Exception:
        last_focus = []
    focus = build_focus(last_focus)

    new = {
        'version': '1.1',
        'source': f'松果每日解读管线自动生成 · 数据截至 {td[:4]}-{td[4:6]}-{td[6:]} 收盘（tushare 当日真实行情）',
        'update_note': '本数据由松果每日解读管线自动生成（数据+信号每日收盘后自动更新）；focus 今日关注从信源池当日A股源(财联社/华尔街见闻/格隆汇/雪球/36氪)规则筛选、来源可溯；无当日新料则沿用最近一期并如实标注。网页展示最新一期。',
        'latest': {
            'date': td,
            'market_date': f'{td[:4]}-{td[4:6]}-{td[6:]}',
            'headline': headline,
            'market': market,
            'turnover_note': f"{turnover_txt}中小盘({market[4]['index']} {market[4]['chg']}) vs 大盘({market[3]['index']} {market[3]['chg']})，{'中小盘强' if strong_small else '大盘强'}。",
            'signals': [sig0] + month_snapshot,
            'signal_summary': signal_summary,
            'focus': focus,
            'viewpoints': views,
        },
    }

    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(new, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print(f'✅ 已更新 {OUT}')
    print(json.dumps(new['latest'], ensure_ascii=False, indent=1)[:800])

def build_focus(last_focus):
    """清单级 focus：从信源池当日 A 股财经源规则筛政策/产业热点。
    返回 [{title, point, source, link, note_asof}]，最多 4 条。
    真实性边界：只筛不造——title/point 取自真实源条目标题/摘要；无当日新料则沿用上一期并如实标注。
    """
    from datetime import datetime
    LATEST = r'D:\studynotes\00_体系\信源池\rss_cache\latest.json'
    FIN = ('财联社电报', '华尔街见闻快讯', '格隆汇', '雪球热帖', '36氪快讯')
    POL = ['央行','证监会','国务院','发改委','财政部','工信部','国常会','政策','降准','降息','利率','LPR','专项债',
           '新规','监管','试点','规划','审议','改革','印发','发布','通知','关税','PMI','社融','信贷','汇率',
           '北向','增量','稳增长','扩内需','提振','万亿','批文','核准','注册制','再融资','分红','A股','港股','中概']
    IND = ['新能源','光伏','储能','锂电','半导体','芯片','算力','机器人','化工','新材料','医药','创新药','生物',
           '汽车','消费','白酒','地产','证券','银行','保险','军工','物流','航运','航空','电力','煤炭','钢铁','有色',
           '电子','软件','数据','并购','重组','IPO','增持','回购','解禁','减持','订单','中标','预增','财报','美股']

    def parse_date(s):
        core = (s or '').split('GMT')[0].split('+')[0].strip()
        try:
            return datetime.strptime(core, '%a, %d %b %Y %H:%M:%S')
        except Exception:
            return None

    try:
        pool = json.load(open(LATEST, encoding='utf-8')).get('items', [])
    except Exception:
        pool = []

    cands = []
    for x in pool:
        if x.get('source') not in FIN:
            continue
        dt = parse_date(x.get('date'))
        if not dt:
            continue
        if (datetime.now() - dt).total_seconds() > 72 * 3600:
            continue
        t = f"{x.get('title','')} {x.get('summary','')}"
        n_pol = sum(1 for k in POL if k in t)
        n_ind = sum(1 for k in IND if k in t)
        if n_pol or n_ind:
            cands.append((n_pol, n_ind, x))

    if not cands:
        for f in last_focus:
            f['note_asof'] = '当日信源池未筛出新增政策/产业热点，沿用最近一期（每日16:00复筛）'
        return last_focus

    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)
    focus = []
    for n_pol, n_ind, x in cands[:4]:
        title = x.get('title', '').strip() or '（无标题条目）'
        summary = (x.get('summary') or '').strip()
        import re as _re
        # 通用规则：规整信源摘要中的明显错别字（只改确定性错字、不臆改事实；不确定的保留原样）
        # 《信息通信行业》等词若被摘成同音错字需按此表纠正，凡出现的新错字先加入此表再规整
        for _bad, _good in (('证监会皮肤', '证监会批准'),):
            summary = summary.replace(_bad, _good)
        # 取正文中最长段落（剔除"进化/发行价为…第三高"等短导语/标签前缀段）作为解说源，
        # 确保解说从真正事件句起、与标题同一主题、逻辑连贯
        paras = [_re.sub(r'<[^>]+>', ' ', p) for p in _re.split(r'\n+', summary)]
        paras = [_re.sub(r'\s+', ' ', p).strip() for p in paras if p.strip()]
        summary_clean = max(paras, key=len) if paras else summary.strip()
        # 解说限制在约两排字内（≤92字符），尽量按完整句收尾、不残句
        def clip(s, limit=92):
            if len(s) <= limit:
                return s.strip()
            buf, segs = '', _re.split(r'(?<=[。！？；])', s)
            for seg in segs:
                if len(buf) + len(seg) > limit and buf:
                    break
                buf += seg
            if buf.strip():
                return buf.strip()
            cut = s[:limit]
            for mark in ('。', '！', '？', '，', '；', '、', ' '):
                k = cut.rfind(mark)
                if k > max(10, limit * 3 // 5):
                    return cut[:k + 1].strip()
            return cut + '…'
        point = (clip(summary_clean) if n_pol and summary_clean and len(summary_clean) > 8
                 else title if len(title) <= 44 else title[:44] + '…')
        link = x.get('link') or ''
        focus.append({
            'title': title,
            'point': point,
            'source': x.get('source', ''),
            'link': link,
            'note_asof': '每日16:00由信源池当日A股源自动筛选，来源可溯',
        })
    return focus


def Shibor_desc(diff_bp):
    if diff_bp is None:
        return '（起始周）'
    return '环比下行、边际释放' if diff_bp < 0 else '仍偏紧'

if __name__ == '__main__':
    main()
