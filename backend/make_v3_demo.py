# -*- coding: utf-8 -*-
"""把 stockscore_v3 的 JSON 渲染成四页独立路由的静态演示。

产出：<outdir>/<code>/index.html  quality.html  price.html  momentum.html
四页共享同一份 payload，只是详略不同——对应 V3 方案里「一屏总览 + 三页深读」。
"""
import json
import os
import sys
from html import escape

CSS = """
:root{--ink:#1a1f26;--ink2:#33404d;--muted:#67737f;--faint:#8d99a4;--bg:#f5f6f8;
--card:#fff;--line:#e2e6ec;--line2:#eef1f4;--green:#146b52;--green-l:#e8f2ee;--green-b:#cfe3da;
--gold:#a97c2f;--gold-l:#faf3e6;--gold-b:#ecdcbf;--red:#b3392c;--red-l:#fbeeec;--red-b:#f0cfca;
--blue:#2c5f8a;--blue-l:#eaf1f7;--blue-b:#cddcea}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-size:14.5px;line-height:1.7;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:0 22px 70px}
.top{padding:26px 0 0}
.crumb{font-size:12px;color:var(--faint);margin-bottom:10px}
.crumb a{color:var(--muted);text-decoration:none}
.ident{display:flex;flex-wrap:wrap;align-items:flex-end;gap:14px;margin-bottom:4px}
.ident h1{margin:0;font-size:26px;font-weight:800;letter-spacing:-.01em}
.ident .code{font-size:14px;color:var(--faint);font-variant-numeric:tabular-nums}
.ident .ind{font-size:12.5px;color:var(--muted);background:#fff;border:1px solid var(--line);
padding:2px 9px;border-radius:5px}
.nav{display:flex;gap:2px;margin:18px 0 22px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.nav a{padding:9px 16px;font-size:13.5px;font-weight:600;color:var(--muted);text-decoration:none;
border-bottom:2px solid transparent;margin-bottom:-1px}
.nav a:hover{color:var(--ink2)}
.nav a.on{color:var(--green);border-bottom-color:var(--green)}
.card{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:20px 22px;margin-bottom:14px}
.hero{display:flex;gap:26px;align-items:center;flex-wrap:wrap}
.big{font-size:52px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.big small{font-size:15px;font-weight:600;color:var(--muted);margin-left:8px;letter-spacing:0}
.hero .meta{flex:1;min-width:260px}
.pill{display:inline-block;font-size:12px;font-weight:700;padding:3px 10px;border-radius:5px;margin:3px 6px 3px 0}
.p-in{background:var(--green-l);color:var(--green);border:1px solid var(--green-b)}
.p-out{background:var(--gold-l);color:var(--gold);border:1px solid var(--gold-b)}
.p-red{background:var(--red-l);color:var(--red);border:1px solid var(--red-b)}
.p-gray{background:#f1f3f5;color:var(--muted);border:1px solid var(--line)}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0 4px}
.gcard{border:1px solid var(--line);border-radius:9px;padding:14px 16px;background:#fcfcfd}
.gcard .k{font-size:11.5px;font-weight:800;letter-spacing:.08em;color:var(--faint)}
.gcard .v{font-size:27px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.25}
.gcard .q{font-size:12px;color:var(--muted)}
.gcard.Q{border-left:3px solid var(--green)}
.gcard.V{border-left:3px solid var(--gold)}
.gcard.M{border-left:3px solid var(--blue)}
h2.s{font-size:15px;font-weight:800;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid var(--line2);
letter-spacing:.01em}
h2.s .w{float:right;font-size:12px;font-weight:600;color:var(--faint)}
.row{display:grid;grid-template-columns:150px 1fr 58px;gap:12px;align-items:center;margin-bottom:9px}
.row .nm{font-size:13px;font-weight:600;color:var(--ink2)}
.row .nm em{font-style:normal;font-size:11px;color:var(--faint);margin-left:5px}
.bar{height:9px;background:#eef1f4;border-radius:5px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:5px;background:var(--green)}
.bar.v i{background:var(--gold)} .bar.m i{background:var(--blue)} .bar.na i{background:#dfe3e8}
.row .sc{text-align:right;font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:12.8px}
th{text-align:left;padding:8px 10px;background:#f8f9fb;border-bottom:1px solid var(--line);
font-size:12px;color:var(--ink);font-weight:700;white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid var(--line2);color:var(--ink2);vertical-align:top}
tr:last-child td{border-bottom:none}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}
.tagA,.tagB,.tagC{font-size:10.5px;font-weight:800;padding:1px 5px;border-radius:3px;white-space:nowrap}
.tagA{background:var(--green-l);color:var(--green);border:1px solid var(--green-b)}
.tagB{background:var(--gold-l);color:var(--gold);border:1px solid var(--gold-b)}
.tagC{background:#f1f3f5;color:var(--faint);border:1px solid var(--line)}
.fl{font-size:12.5px;padding:7px 12px;border-radius:6px;margin-bottom:6px;line-height:1.6}
.fl.r{background:var(--red-l);border:1px solid var(--red-b);color:#8a4a41}
.fl.y{background:var(--gold-l);border:1px solid var(--gold-b);color:#6b5427}
.fl.n{background:#f7f8fa;border:1px solid var(--line);color:var(--muted)}
.blk{margin-bottom:13px}
.blk .h{font-size:12px;font-weight:800;color:var(--green);letter-spacing:.06em;margin-bottom:3px}
.blk .t{font-size:13.5px;color:var(--ink2);line-height:1.75}
.note{font-size:11.5px;color:var(--faint);line-height:1.7;margin-top:9px}
.dimhead{display:flex;justify-content:space-between;align-items:baseline;margin:22px 0 10px;
padding-bottom:8px;border-bottom:1px solid var(--line2)}
.dimhead h3{margin:0;font-size:15px;font-weight:800}
.dimhead .sc{font-size:19px;font-weight:800;font-variant-numeric:tabular-nums}
.dimhead .sc small{font-size:11.5px;color:var(--faint);font-weight:600;margin-left:6px}
.chk{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:7px;margin-top:10px}
.chk div{font-size:12.3px;padding:7px 11px;border-radius:6px;border:1px solid var(--line);background:#fcfcfd}
.chk div.ok{border-color:var(--green-b);background:var(--green-l);color:var(--green)}
.chk div.no{border-color:var(--red-b);background:var(--red-l);color:#8a4a41}
.foot{font-size:11px;color:var(--faint);line-height:1.8;border-top:1px solid var(--line);
padding-top:16px;margin-top:26px}
@media(max-width:720px){.g3{grid-template-columns:1fr}.row{grid-template-columns:110px 1fr 46px}}
"""

PAGES = [
    ('index', '总览', 'overview'),
    ('quality', '质地', 'quality'),
    ('price', '价格', 'price'),
    ('momentum', '势能', 'momentum'),
]


def _tier_cls(t):
    return {'优': 'p-in', '良': 'p-in', '中': 'p-out', '待观察': 'p-red'}.get(t, 'p-gray')


def _tag_cls(code):
    return {'in': 'p-in', 'out': 'p-out', 'red': 'p-red'}.get(code, 'p-gray')


def _bar_cls(group):
    return {'Q': '', 'V': 'v', 'M': 'm'}.get(group, '')


def _num(v, nd=2):
    if v is None:
        return 'N/A'
    if isinstance(v, (int, float)):
        if abs(v) >= 1e6:
            return f'{v:,.0f}'
        s = f'{v:,.{nd}f}'
        if '.' in s:                      # 只在有小数位时才裁尾零，否则 100.0 会被裁成 1
            s = s.rstrip('0').rstrip('.')
        return s or '0'
    return str(v)


def _rel_tag(r):
    if r == 'A':
        return '<span class="tagA">A级·真实披露</span>'
    if r == 'B':
        return '<span class="tagB">B级·大单推算</span>'
    return ''


def _header(p, active):
    nav = ''.join(
        f'<a class="{"on" if key == active else ""}" href="{key}.html">{label}</a>'
        for key, label, _ in PAGES)
    q = p.get('quote') or {}
    return f"""<div class="wrap"><div class="top">
<div class="crumb"><a href="#">松果投资实验室</a> · <a href="#">工具</a> · 个股打分卡 V3</div>
<div class="ident"><h1>{escape(p['name'])}</h1><span class="code">{p['code']}</span>
<span class="ind">{escape(p.get('industry') or '—')}</span>
<span class="ind">数据 {p.get('data_asof')}</span></div>
<div class="nav">{nav}</div></div>"""


def _footer(p):
    errs = p.get('source_errors') or []
    err_html = ('<br>取数告警：' + escape('；'.join(errs))) if errs else ''
    return f"""<div class="foot">
总分 = 0.52×Q + 0.26×V + 0.22×M，再过闸门（🔴封顶59 / 🟡≥2降一档 / 🟡=1仅标注）。
缺失子项不进分母、整维缺失标 N/A 不填 0；每个分数带置信度，&lt;0.6 进低置信清单。<br>
本页所有数字由公开数据按页面写明口径计算，数据可能有误、口径有局限，请自行复核。
历史回测与结构化读数均不构成投资建议，不预测涨跌，不含任何买卖意见。{err_html}
</div></div></body></html>"""


def page_overview(p):
    g = p['groups']
    total = p['total']
    bars = []
    for d in p['dims']:
        grp = 'Q' if d['key'] in ('profit_quality', 'core_competence', 'growth', 'financial_health') \
            else 'V' if d['key'] == 'valuation' else 'M'
        sc = d['score']
        w = 0 if sc is None else max(0, min(100, sc))
        bars.append(
            f'<div class="row"><div class="nm">{escape(d["label"])}'
            f'<em>{int(d["weight"]*100)}%</em></div>'
            f'<div class="bar {_bar_cls(grp)}{" na" if sc is None else ""}">'
            f'<i style="width:{w:.1f}%"></i></div>'
            f'<div class="sc">{_num(sc,1)}</div></div>')

    gate = p['gate']
    fl = ''
    for r in gate['red']:
        fl += f'<div class="fl r">🔴 {escape(r)}</div>'
    for y in gate['yellow']:
        fl += f'<div class="fl y">🟡 {escape(y)}</div>'
    if not gate['red'] and not gate['yellow']:
        fl = '<div class="fl n">✅ 未触发红旗与黄旗</div>'
    fl += '<div class="fl n">未接入：' + escape('、'.join(gate['not_wired'])) + '</div>'

    chk = ''.join(
        f'<div class="{"ok" if v else "no"}">{"✅" if v else "❌"} {escape(k)}</div>'
        for k, v in (p.get('investable_checks') or {}).items())

    blocks = ''.join(
        f'<div class="blk"><div class="h">{escape(b["h"])}</div>'
        f'<div class="t">{escape(b["t"])}</div></div>'
        for b in p['pages']['overview']['blocks'])

    return _header(p, 'index') + f"""
<div class="card"><div class="hero">
  <div><div class="big">{_num(total,1)}<small>分 · {escape(p['tier'])}</small></div>
  <div class="note" style="margin-top:8px">裸分 {_num(p['total_raw'],1)}{('　' + escape(p['tier_note'])) if p.get('tier_note') else ''}</div></div>
  <div class="meta">
    <span class="pill {_tag_cls(p['tag']['code'])}">{escape(p['tag']['label'])}</span>
    <span class="pill {_tier_cls(p['tier'])}">档位 {escape(p['tier'])}</span>
    <span class="pill p-gray">红旗 {len(gate['red'])} · 黄旗 {len(gate['yellow'])}</span>
    <div class="note">{escape(p['tag']['desc'])}</div>
  </div>
</div>
<div class="g3">
  <div class="gcard Q"><div class="k">Q · 质地</div><div class="v">{_num(g['Q']['score'],1)}</div>
    <div class="q">{escape(g['Q']['question'])}｜权重 {g['Q']['weight']}</div></div>
  <div class="gcard V"><div class="k">V · 价格</div><div class="v">{_num(g['V']['score'],1)}</div>
    <div class="q">{escape(g['V']['question'])}｜权重 {g['V']['weight']}</div></div>
  <div class="gcard M"><div class="k">M · 势能</div><div class="v">{_num(g['M']['score'],1)}</div>
    <div class="q">{escape(g['M']['question'])}｜权重 {g['M']['weight']}</div></div>
</div></div>

<div class="card"><h2 class="s">八维得分<span class="w">权重合计 {p['meta']['weights_sum']:.2f}</span></h2>
{''.join(bars)}</div>

<div class="card"><h2 class="s">闸门</h2>{fl}</div>

<div class="card"><h2 class="s">松果可投性（简化 11 步 + 市值）</h2>
<div class="chk">{chk}</div>
<div class="note">完整 V35 管线含 VC∈[0.90,0.99]、行业软调节、红旗删票不补位；本卡用可公开验证的
简化口径做代理，标签含义为「落在射程内与否」，不等于买入建议。</div></div>

<div class="card"><h2 class="s">一句话结论</h2>{blocks}</div>
""" + _footer(p)


def _dim_block(d, group):
    if not d['available']:
        return (f'<div class="dimhead"><h3>{escape(d["label"])}</h3>'
                f'<div class="sc">N/A<small>权重 {int(d["weight"]*100)}%</small></div></div>'
                f'<div class="fl n">{escape(d.get("na_reason") or "该维不可用")}</div>')
    rows = ''
    for m in d['metrics']:
        rel = _rel_tag(m.get('reliability'))
        rows += (f'<tr><td>{escape(m["name"])}{("<br>" + rel) if rel else ""}'
                 f'{("<div class=\'note\'>" + escape(m["note"]) + "</div>") if m.get("note") else ""}</td>'
                 f'<td class="n">{_num(m["value"])}{escape(m.get("unit") or "")}</td>'
                 f'<td class="n">{_num(m["pctl"],0)}</td>'
                 f'<td class="n">{int(m["weight"]*100)}%</td>'
                 f'<td class="n">{m["confidence"]}</td></tr>')
    flags = ''.join(f'<div class="fl n">{escape(f)}</div>' for f in (d.get('flags') or []))
    extra = ''
    if d.get('thresh'):
        extra = f'<div class="note">口径：{escape(d["thresh"])}</div>'
    return f"""<div class="dimhead"><h3>{escape(d['label'])}</h3>
<div class="sc">{_num(d['score'],1)}<small>权重 {int(d['weight']*100)}% · 置信 {d['confidence']}</small></div></div>
<table><thead><tr><th>子指标</th><th style="text-align:right">数值</th>
<th style="text-align:right">分位/刻度</th><th style="text-align:right">维内权重</th>
<th style="text-align:right">置信</th></tr></thead><tbody>{rows}</tbody></table>
{flags}{extra}"""


def page_quality(p):
    dims = [d for d in p['dims'] if d['key'] in
            ('profit_quality', 'core_competence', 'growth', 'financial_health')]
    g = p['groups']['Q']
    blocks = ''.join(
        f'<div class="blk"><div class="h">{escape(b["h"])}</div>'
        f'<div class="t">{escape(b["t"])}</div></div>'
        for b in p['pages']['quality']['blocks'])
    return _header(p, 'quality') + f"""
<div class="card"><div class="hero"><div class="big">{_num(g['score'],1)}<small>Q · 质地</small></div>
<div class="meta"><div class="t" style="font-size:13.5px">{escape(p['pages']['quality']['headline'])}</div>
<div class="note">{escape(g.get('question',''))}</div></div></div></div>
<div class="card"><h2 class="s">四个维度合在一起看</h2>{''.join(_dim_block(d, 'Q') for d in dims)}</div>
<div class="card"><h2 class="s">结论：是不是好公司</h2>{blocks}
<div class="note">纵向=链条位置与议价力（慢变，结构）；横向=同行地位与技术代差；自身=壁垒类型与持续性。
技术代差、毛利溢价为代理指标——真正的护城河（转换成本、网络效应、心智占领）拿不到结构化数据。</div></div>
""" + _footer(p)


def page_price(p):
    d = next(x for x in p['dims'] if x['key'] == 'valuation')
    g = p['groups']['V']
    blocks = ''.join(
        f'<div class="blk"><div class="h">{escape(b["h"])}</div>'
        f'<div class="t">{escape(b["t"])}</div></div>'
        for b in p['pages']['price']['blocks'])
    return _header(p, 'price') + f"""
<div class="card"><div class="hero"><div class="big">{_num(g['score'],1)}<small>V · 价格</small></div>
<div class="meta"><div class="t" style="font-size:13.5px">{escape(p['pages']['price']['headline'])}</div>
<div class="note">{escape(g.get('question',''))}</div></div></div></div>
<div class="card"><h2 class="s">估值与安全边际</h2>{_dim_block(d, 'V')}</div>
<div class="card"><h2 class="s">结论：现在贵不贵</h2>{blocks}
<div class="note">低分位=高分。亏损股 PE 无定义时整维 N/A；金融业只计 PB。
松果 FCF 收益率为 FCFF÷市值的代理口径（未扣净债），权重 26%，是这一维里最接近策略排序逻辑的子项。</div></div>
""" + _footer(p)


def page_momentum(p):
    dims = [d for d in p['dims'] if d['key'] in
            ('chain_prosperity', 'earnings_revision', 'capital_momentum')]
    g = p['groups']['M']
    blocks = ''.join(
        f'<div class="blk"><div class="h">{escape(b["h"])}</div>'
        f'<div class="t">{escape(b["t"])}</div></div>'
        for b in p['pages']['momentum']['blocks'])
    return _header(p, 'momentum') + f"""
<div class="card"><div class="hero"><div class="big">{_num(g['score'],1)}<small>M · 势能</small></div>
<div class="meta"><div class="t" style="font-size:13.5px">{escape(p['pages']['momentum']['headline'])}</div>
<div class="note">{escape(g.get('question',''))}</div></div></div></div>
<div class="card"><h2 class="s">三个维度：景气 / 预期 / 资金</h2>
{''.join(_dim_block(d, 'M') for d in dims)}</div>
<div class="card"><h2 class="s">结论：有没有风、能持续多久</h2>{blocks}
<div class="note">资金动能按真实性分三级：A 级=融资余额/龙虎榜（真实披露，占 3.5 分）；
B 级=主力净流入（按单笔金额分档推算，<b>主力可拆单规避</b>，占 2.5 分，只读异动不读意图）；
C 级=北向资金（2024-09-30 起停止实时披露，永久剔除）。主窗口统一 20 日，与月度调仓同频。</div></div>
""" + _footer(p)


def main():
    src_dir = sys.argv[1] if len(sys.argv) > 1 else '_v3_out'
    out_root = sys.argv[2] if len(sys.argv) > 2 else '_v3_out/demo'
    files = [f for f in os.listdir(src_dir) if f.endswith('.json')]
    if not files:
        print('没有找到 JSON，先跑 stockscore_v3.py --json')
        return
    for f in files:
        with open(os.path.join(src_dir, f), encoding='utf-8') as fh:
            p = json.load(fh)
        d = os.path.join(out_root, p['code'])
        os.makedirs(d, exist_ok=True)
        pages = {'index': page_overview(p), 'quality': page_quality(p),
                 'price': page_price(p), 'momentum': page_momentum(p)}
        for key, html in pages.items():
            title = f"{p['name']} {p['code']} · {dict((k, l) for k, l, _ in PAGES)[key]}"
            doc = (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
                   f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                   f'<title>{escape(title)} · 松果个股打分卡 V3</title>'
                   f'<style>{CSS}</style></head><body>{html}')
            with open(os.path.join(d, f'{key}.html'), 'w', encoding='utf-8') as fh:
                fh.write(doc)
        print('生成', p['code'], p['name'], '->', d)


if __name__ == '__main__':
    main()
