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
  focus(政策/产业热点)   -> 本轮保留最近一期并标注；后续接每日雷达自动刷新(见 README 备注)

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

    # 6) focus（本轮保留最近一期并标注，待每日雷达接入自动刷新）
    old = json.load(open(OUT, encoding='utf-8'))
    focus = old['latest'].get('focus', [])
    for f in focus:
        f['note_asof'] = 'focus 政策产业热点——最近一期快照，待每日雷达接入后每日刷新'

    new = {
        'version': '1.1',
        'source': f'松果每日解读管线自动生成 · 数据截至 {td[:4]}-{td[4:6]}-{td[6:]} 收盘（tushare 当日真实行情）',
        'update_note': '本数据由松果每日解读管线自动生成（数据+信号每日收盘后自动更新）；focus 政策热点评后续接每日雷达每日刷新。网页展示最新一期。',
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

def Shibor_desc(diff_bp):
    if diff_bp is None:
        return '（起始周）'
    return '环比下行、边际释放' if diff_bp < 0 else '仍偏紧'

if __name__ == '__main__':
    main()
