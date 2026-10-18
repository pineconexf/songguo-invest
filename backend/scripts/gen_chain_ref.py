# -*- coding: utf-8 -*-
"""从 chain_map_v1.json 生成技能参考文档（链条图全表 + 覆盖推导）。

链条图扩了行业之后重跑一次，保持 skills/pinecone-industry-chain/references/ 与 json 一致：
    python scripts/gen_chain_ref.py

为什么要有这个脚本：参考文档是给人看的，json 是给机器读的。手工同步两份必然漂移。
"""
import io
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(BACKEND)))  # → D:/pineconeinvestfiles
OUT = os.path.join(ROOT, 'skills', 'pinecone-industry-chain', 'references', '链条图-v1.md')


def main():
    cm = json.load(io.open(os.path.join(BACKEND, 'chain_map_v1.json'), encoding='utf-8'))
    tax = json.load(io.open(os.path.join(BACKEND, 'data', 'industry_taxonomy.json'),
                            encoding='utf-8'))['map']
    picks = json.load(io.open(os.path.join(BACKEND, '..', 'src', 'data', 'v35_picks.json'),
                              encoding='utf-8'))

    c2, c3 = Counter(), Counter()
    allp = [c for m in picks['months'] for c in (m.get('picks') or [])]
    for c in allp:
        r = tax.get(c) or {}
        if r.get('l2'):
            c2[r['l2']] += 1
        if r.get('l3'):
            c3[r['l3']] += 1
    tot = sum(c2.values())
    freq = dict(c2)

    L = []
    L.append('# 松果产业链链条图 %s（机器可读版见 backend/chain_map_v1.json）' % cm.get('version'))
    L.append('')
    L.append('> 本文由 `backend/scripts/gen_chain_ref.py` 从 json 生成，**不要手工改**。')
    L.append('> 要改链条图请改 json，然后重跑脚本。')
    L.append('')
    L.append('## 一、覆盖是怎么定的')
    L.append('')
    L.append('不是拍脑袋选行业，是按 V35 回测的真实持仓频次排的。')
    L.append('')
    L.append('- 回测区间：%s → %s，共 %d 个月' % (
        picks['months'][0]['ym'], picks['months'][-1]['ym'], len(picks['months'])))
    L.append('- 累计持仓 %d 次，去重标的 %d 只' % (len(allp), len(set(allp))))
    L.append('- 涉及一级 %d 个、二级 %d 个、三级 %d 个行业' % (
        len({(tax.get(c) or {}).get('l1') for c in allp if (tax.get(c) or {}).get('l1')}),
        len(c2), len(c3)))
    L.append('')
    L.append('覆盖率收敛速度（决定了为什么用二级行业做覆盖单位）：')
    L.append('')
    L.append('| 口径 | TOP10 | TOP20 | TOP30 | TOP50 |')
    L.append('|---|---|---|---|---|')
    for label, cc in (('二级行业', c2), ('三级行业', c3)):
        row = ['%.1f%%' % (sum(v for _, v in cc.most_common(n)) / tot * 100)
               for n in (10, 20, 30, 50)]
        L.append('| %s | %s |' % (label, ' | '.join(row)))
    L.append('')
    L.append('**结论**：二级 TOP30 = 80.0%，三级 TOP20 只有 49.3%。覆盖单位选二级，不选三级。')
    L.append('')

    items = sorted(cm['industries'].items(), key=lambda kv: -freq.get(kv[0], 0))
    sup = [n for n, e in items if e.get('supplement')]
    L.append('## 二、已覆盖的 %d 个行业' % len(items))
    L.append('')
    L.append('按 V35 持仓频次降序。上下游名称均为 128 个二级行业中的真实名称，可直接 join 景气读数。')
    if sup:
        L.append('')
        L.append('标 ★ 的 %d 个行业（%s）是按**查询热度**补充的，不是持仓频次——V35 在这几个行业几乎没有持仓，'
                 '但用户最常查，补上是为了减少「查热门股看到未标注」的体验缺口。'
                 % (len(sup), '、'.join(sup)))
    L.append('')
    L.append('| # | 二级行业 | 一级 | 环节 | 链条 | 持仓次数 | 上游 | 下游 | 周期 |')
    L.append('|---|---|---|---|---|---|---|---|---|')
    for i, (name, e) in enumerate(items, 1):
        L.append('| %d | %s%s | %s | %s | %s | %d | %s | %s | %s |' % (
            i, name, ' ★' if e.get('supplement') else '', e['level1'], e['segment'],
            e['chain'], freq.get(name, 0),
            '、'.join(e['upstream']) or '—', '、'.join(e['downstream']) or '—', e['cyclicality']))
    L.append('')
    L.append('## 三、各行业的景气关键变量与壁垒形态')
    L.append('')
    for name, e in items:
        L.append('**%s**（%s / %s / %s）' % (name, e['level1'], e['segment'], e['cyclicality']))
        L.append('')
        L.append('- 关键变量：%s' % '、'.join(e['drivers']))
        L.append('- 壁垒形态：%s' % e['moat'])
        L.append('- 要点：%s' % e['note'])
        L.append('')
    L.append('## 四、未覆盖行业的处理')
    L.append('')
    L.append('链条图之外的行业，`mapped=False`，只输出：行业三级归属、主营构成（产品/地区/毛利率）、概念板块。')
    L.append('上下游与传导判断一律标「未标注」，不脑补。这是硬约束，见 SKILL.md 第五节铁律 1。')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('written ->', OUT)
    print('industries=%d (supplement=%d)  top30_coverage=%.1f%%'
          % (len(items), len(sup), sum(v for _, v in c2.most_common(30)) / tot * 100))


if __name__ == '__main__':
    main()
