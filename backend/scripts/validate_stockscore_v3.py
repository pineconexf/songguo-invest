# -*- coding: utf-8 -*-
"""V3 打分卡 · 产出有效性批量验证（2026-10-18）

目的：证明「产出是有效的」，不是跑三只票看看。样本设计覆盖：
  - 同一二级行业的多只票（验证横截面区分度——P2 修的就是这个）
  - 链条图已覆盖 / 未覆盖的行业（验证降级路径）
  - 金融、地产、周期、成长（验证不同资产类型都不崩）
  - 亏损股（验证估值维 N/A 是否如实标注，而不是填 0）

用法：python scripts/validate_stockscore_v3.py          # 跑全样本
      python scripts/validate_stockscore_v3.py --quick  # 只跑前 10 只，冒烟
"""
import json
import os
import sys
import time
import traceback

# 样本：[{code, note}]，note 说明为什么选它
SAMPLE = [
    # —— 同行业对照（验证横截面区分度）——
    ('600519', '白酒Ⅱ · 龙头'),
    ('000858', '白酒Ⅱ · 次龙头（与茅台对比）'),
    ('000596', '非白酒 · 古井贡'),
    ('600809', '白酒Ⅱ · 山西汾酒（第三只同行业）'),
    ('688981', '半导体 · 中芯国际'),
    ('603501', '半导体 · 韦尔股份（同行业第二只）'),
    # —— 链条图已覆盖的重点行业 ——
    ('600269', '铁路公路 · 高速公路（V35 持仓频次第一）'),
    ('600900', '电力 · 长江电力'),
    ('600276', '化学制药 · 恒瑞医药'),
    ('000538', '中药Ⅱ · 云南白药'),
    ('600309', '化学制品 · 万华化学'),
    ('300750', '电池 · 宁德时代（热度补充）'),
    ('601012', '光伏设备 · 隆基绿能（热度补充）'),
    ('688128', '专用设备 · 中国电研（V35 实盘持仓）'),
    # —— 链条图未覆盖（验证诚实降级）——
    ('000001', '银行Ⅱ · 平安银行'),
    ('600036', '银行Ⅱ · 招商银行（金融只 PB）'),
    ('601318', '保险Ⅱ · 中国平安'),
    ('000002', '房地产开发 · 万科A'),
    ('601668', '房屋建设Ⅱ · 中国建筑'),
    ('000333', '白色家电 · 美的集团'),
    ('002714', '养殖业 · 牧原股份'),
    ('002460', '能源金属 · 赣锋锂业'),
    ('601633', '乘用车 · 长城汽车'),
    ('601888', '旅游零售Ⅱ · 中国中免'),
    # —— 不同市值/类型 ——
    ('600030', '证券Ⅱ · 中信证券'),
    ('601899', '工业金属 · 紫金矿业'),
    ('002415', '软件开发 · 海康威视'),
    ('300760', '医疗器械 · 迈瑞医疗'),
]

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BACKEND, "_validate_out")
os.makedirs(OUT_DIR, exist_ok=True)

DIMS = ['profit_quality', 'core_competence', 'growth', 'financial_health',
        'valuation', 'chain_prosperity', 'earnings_revision', 'capital_momentum']


def main():
    quick = '--quick' in sys.argv
    sample = SAMPLE[:10] if quick else SAMPLE
    import stockscore_v3 as V

    rows = []
    t_all = time.time()
    for i, (code, note) in enumerate(sample, 1):
        t0 = time.time()
        rec = {'code': code, 'note': note}
        try:
            p, st = V.compute_v3(code)
        except Exception as e:
            rec.update(ok=False, err=f'{type(e).__name__}: {e}',
                       tb=traceback.format_exc()[-800:])
            rows.append(rec)
            print(f'[{i}/{len(sample)}] {code} ❌ {rec["err"]}')
            continue
        if not p:
            rec.update(ok=False, err=f'无数据 status={st}')
            rows.append(rec)
            print(f'[{i}/{len(sample)}] {code} ❌ {rec["err"]}')
            continue

        dmap = {d['key']: d for d in p['dims']}
        na = [k for k in DIMS if not dmap[k]['available']]
        ch = p.get('chain') or {}
        rec.update(
            ok=True, name=p['name'], total=p['total'], tier=p['tier'],
            gate=p['gate_hit'], tag=(p.get('tag') or {}).get('label'),
            Q=p['groups']['Q']['score'], V_=p['groups']['V']['score'],
            M=p['groups']['M']['score'],
            l2=ch.get('l2'), l3=ch.get('l3'), mapped=ch.get('mapped'),
            segment=ch.get('segment'),
            n_up=len(ch.get('upstream') or []), n_down=len(ch.get('downstream') or []),
            n_prod=len(ch.get('products') or []),
            verdict=(ch.get('transmission') or {}).get('verdict'),
            na_dims='|'.join(na),
            n_na=len(na),
            low_conf=len(p.get('low_confidence') or []),
            secs=round(time.time() - t0, 1),
        )
        for k in DIMS:
            rec['d_' + k] = dmap[k]['score']
        rows.append(rec)
        print('[%d/%d] %s %-8s 总=%5.1f %-3s %s | 链=%s%s | NA维=%d | %.1fs'
              % (i, len(sample), code, p['name'], p['total'], p['tier'],
                 (p.get('tag') or {}).get('label'), ch.get('l2'),
                 '' if ch.get('mapped') else '(未标注)',
                 len(na), rec['secs']))

    # ---------- 汇总 ----------
    ok = [r for r in rows if r.get('ok')]
    bad = [r for r in rows if not r.get('ok')]
    print('\n' + '=' * 78)
    print('汇总')
    print('=' * 78)
    print('样本 %d 只，成功 %d，失败 %d，成功率 %.1f%%，总耗时 %.0fs'
          % (len(rows), len(ok), len(bad), len(ok) / max(1, len(rows)) * 100, time.time() - t_all))
    if bad:
        print('失败明细：')
        for r in bad:
            print('   %s  %s' % (r['code'], r.get('err')))
        print('   （失败堆栈见 _validate_out/<code>.json）')
    if ok:
        import statistics as S
        tot = [r['total'] for r in ok]
        print('总分：min=%.1f  max=%.1f  mean=%.1f  sd=%.1f'
              % (min(tot), max(tot), S.mean(tot), S.stdev(tot) if len(tot) > 1 else 0))
        from collections import Counter
        print('档位分布：', dict(Counter(r['tier'] for r in ok)))
        print('标签分布：', dict(Counter(r['tag'] for r in ok)))
        print('闸门命中：', dict(Counter(r['gate'] for r in ok)))
        mapped = [r for r in ok if r['mapped']]
        print('链条图覆盖：%d/%d = %.1f%%' % (len(mapped), len(ok), len(mapped) / len(ok) * 100))
        # 逐维可用率
        print('逐维可用率（N/A 率）：')
        for k in DIMS:
            n_ok = sum(1 for r in ok if r.get('d_' + k) is not None)
            print('   %-18s %2d/%2d 可用 (%.0f%%)' % (k, n_ok, len(ok), n_ok / len(ok) * 100))
        # 同行业区分度
        print('同行业横截面区分度（P2 修的重点）：')
        for l2 in ('白酒Ⅱ', '半导体', '银行Ⅱ'):
            grp = [r for r in ok if r['l2'] == l2]
            if len(grp) >= 2:
                vals = [(r['name'], r.get('d_chain_prosperity')) for r in grp]
                same = len({round(v[1], 2) for v in vals if v[1] is not None}) <= 1
                print('   %-8s %s → %s' % (l2, vals, '⚠ 同分（仍有问题）' if same else '✅ 已区分'))
        # 上下游覆盖率
        have_up = sum(1 for r in ok if r['n_up'] > 0)
        have_dn = sum(1 for r in ok if r['n_down'] > 0)
        have_pr = sum(1 for r in ok if r['n_prod'] > 0)
        print('成功率外还有：有上游 %d/%d、有下游 %d/%d、有产品落点 %d/%d'
              % (have_up, len(ok), have_dn, len(ok), have_pr, len(ok)))
        print('传导判断分布：', dict(Counter(r['verdict'] for r in ok if r['verdict'])))

    json.dump(rows, open(os.path.join(OUT_DIR, 'result.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=str)
    print('\n明细已存 backend/_validate_out/result.json')


if __name__ == '__main__':
    main()
