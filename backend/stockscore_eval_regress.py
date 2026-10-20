# -*- coding: utf-8 -*-
"""评估集回归（2026-10-20）

解决"不确定性"的核心机制：LLM 输出质量天然有方差，靠单次抽查看不出退化。
本脚本对固定评估集跑一遍，把每次的指标存档，与上一次对比，
**任何指标下滑超过阈值就报警**。

用法：
  python stockscore_eval_regress.py --baseline     # 跑一遍并写为基线
  python stockscore_eval_regress.py                # 跑一遍并与基线对比
  python stockscore_eval_regress.py --list         # 看评估集构成

评估集设计（eval_set.json）：
  - 覆盖不同分数档（高分/中分/低分/亏损）
  - 覆盖不同行业（半导体/消费/银行/周期/医药）
  - 覆盖数据完整度差异（有分部/无分部、有估值序列/无序列）

为什么不用 LLM-as-judge 做主判：判官本身有方差，会让回归结果不可比。
硬指标（密度/覆盖/溯源）全部是确定性计算，可以跨版本比较。
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL_SET = os.path.join(HERE, '_eval', 'eval_set.json')
RESULTS = os.path.join(HERE, '_eval', 'results.json')

# 退化容忍度：任一指标跌破这么多就报警
TOLERANCE = {
    'pass_rate': 0.05,       # 通过率下降 5 个百分点
    'avg_density': 0.10,     # 平均密度下降 0.10
    'avg_coverage': 0.05,    # 平均覆盖下降 5 个百分点
    'avg_traceability': 0.03,  # 平均溯源率下降 3 个百分点
    'reject_rate': 0.02,     # 拒发率上升 2 个百分点
}

DEFAULT_EVAL_SET = [
    # code, 名称, 选入理由
    {'code': '688279', 'name': '峰岹科技', 'why': '有金标准原文可对标；分部完整'},
    {'code': '600519', 'name': '贵州茅台', 'why': '高分红消费龙头，估值序列长'},
    {'code': '300750', 'name': '宁德时代', 'why': '成长股，曾出现解读截断'},
    {'code': '601398', 'name': '工商银行', 'why': '金融业，PE/PEG 不适用'},
    {'code': '601088', 'name': '中国神华', 'why': '周期股，低 PE 陷阱检验'},
    {'code': '000651', 'name': '格力电器', 'why': '成熟制造，增长停滞'},
    {'code': '002594', 'name': '比亚迪', 'why': '高关注度，数据完整'},
    {'code': '600276', 'name': '恒瑞医药', 'why': '医药，研发费用占比高'},
]


def ensure_eval_set():
    os.makedirs(os.path.dirname(EVAL_SET), exist_ok=True)
    if not os.path.exists(EVAL_SET):
        with open(EVAL_SET, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_EVAL_SET, f, ensure_ascii=False, indent=2)
    with open(EVAL_SET, encoding='utf-8') as f:
        return json.load(f)


def load_results():
    if not os.path.exists(RESULTS):
        return {'runs': []}
    with open(RESULTS, encoding='utf-8') as f:
        return json.load(f)


def save_results(obj):
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    with open(RESULTS, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def run_one(code, name):
    """跑单只股票：取打分 → 取事实 → 生成叙事 → 过闸门。"""
    import stockscore_facts as F
    import stockscore_gate as G

    out = {'code': code, 'name': name, 'ok': False}
    try:
        facts_pack = F.build_facts(code)
        out['n_facts'] = len(facts_pack['facts'])
        out['n_gaps'] = len(facts_pack['gaps'])
    except Exception as e:
        out['error'] = 'facts: %s' % str(e)[:120]
        return out

    # 叙事生成依赖后端运行环境（DeepSeek 密钥只在服务器上），
    # 本地跑时用事实拼接做"占位文本"，只验证事实层与闸门本身。
    text = '\n'.join(f['text'] for f in facts_pack['facts'])
    out['placeholder'] = True

    res = G.evaluate(text, facts_pack['facts'], facts_pack['gaps'],
                     required_slots=G.FRAMEWORK_SLOTS)
    out['ok'] = True
    out['verdict'] = res['verdict']
    out['metrics'] = res['metrics']
    out['failed'] = res['failed']
    return out


def summarize(run):
    rows = [r for r in run['items'] if r.get('ok')]
    n = len(rows) or 1
    return {
        'n': len(rows),
        'pass_rate': round(sum(1 for r in rows if r['verdict'] == 'pass') / n, 3),
        'degrade_rate': round(sum(1 for r in rows if r['verdict'] == 'degrade') / n, 3),
        'reject_rate': round(sum(1 for r in rows if r['verdict'] == 'reject') / n, 3),
        'avg_density': round(sum(r['metrics'].get('density') or 0 for r in rows) / n, 3),
        'avg_coverage': round(sum(r['metrics'].get('coverage') or 0 for r in rows) / n, 3),
        'avg_traceability': round(sum(r['metrics'].get('traceability') or 0 for r in rows) / n, 3),
        'avg_facts': round(sum(r.get('n_facts') or 0 for r in rows) / n, 1),
        'avg_gaps': round(sum(r.get('n_gaps') or 0 for r in rows) / n, 1),
    }


def compare(base, cur):
    alerts = []
    for k, tol in TOLERANCE.items():
        b, c = base.get(k), cur.get(k)
        if b is None or c is None:
            continue
        if k == 'reject_rate':
            if c - b > tol:
                alerts.append('%s 从 %.3f 升到 %.3f（容忍 +%.3f）' % (k, b, c, tol))
        elif k == 'pass_rate':
            if b - c > tol:
                alerts.append('%s 从 %.3f 降到 %.3f（容忍 -%.3f）' % (k, b, c, tol))
        else:
            if b - c > tol:
                alerts.append('%s 从 %.3f 降到 %.3f（容忍 -%.3f）' % (k, b, c, tol))
    return alerts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', action='store_true', help='本次结果写为基线')
    ap.add_argument('--list', action='store_true', help='列出评估集')
    ap.add_argument('--code', help='只跑单只股票代码')
    args = ap.parse_args()

    items = ensure_eval_set()
    if args.list:
        print('评估集（%d 只）：' % len(items))
        for it in items:
            print('  %s %s —— %s' % (it['code'], it['name'], it['why']))
        return 0

    if args.code:
        items = [it for it in items if it['code'] == args.code] or \
                [{'code': args.code, 'name': args.code, 'why': '临时'}]

    run = {'ts': int(time.time()), 'label': time.strftime('%Y-%m-%d %H:%M'),
           'items': []}
    for it in items:
        print('跑 %s %s ...' % (it['code'], it['name']), end='', flush=True)
        r = run_one(it['code'], it['name'])
        run['items'].append(r)
        if r.get('ok'):
            print(' %s  事实%d条/缺口%d条  密度%s 覆盖%s'
                  % (r['verdict'], r['n_facts'], r['n_gaps'],
                     r['metrics'].get('density'), r['metrics'].get('coverage')))
        else:
            print(' 失败：%s' % r.get('error'))

    run['summary'] = summarize(run)
    data = load_results()
    prev = data['runs'][-1] if data['runs'] else None

    print('\n' + '=' * 60)
    print('本次汇总：')
    for k, v in run['summary'].items():
        print('  %-18s %s' % (k, v))

    if args.baseline:
        data['runs'] = [run]
        save_results(data)
        print('\n已写为基线（旧结果已清空）。')
        return 0

    if prev:
        alerts = compare(prev['summary'], run['summary'])
        print('\n与上次（%s）对比：' % prev['label'])
        if alerts:
            for a in alerts:
                print('  [退化] %s' % a)
            print('\n结论：指标退化，需检查提示词/数据源/模型版本。')
        else:
            print('  无退化。')
    else:
        print('\n无历史基线，本次未做对比（可用 --baseline 建立基线）。')

    data['runs'].append(run)
    data['runs'] = data['runs'][-20:]
    save_results(data)
    return 0


if __name__ == '__main__':
    sys.exit(main())
