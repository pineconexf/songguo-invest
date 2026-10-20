# -*- coding: utf-8 -*-
"""闸门校准：用人工金标准文本验证阈值合理性（2026-10-20）

用法：
  python stockscore_gate_calib.py            # 跑内置样本
  python stockscore_gate_calib.py <文件>      # 跑外部文本

校准样本：
  gold_wechat   微信深度文章原文（峰岹科技，公认达到"文章级"密度）
  gold_yuanbao  元宝总结版（同题材，短摘要级）
  bad_empty     纯定性空话（应当被 reject / degrade）

判据：金标准必须 pass，空话必须 degrade 或 reject。
若金标准被判 degrade，说明阈值过严，需下调；若空话被判 pass，说明阈值过松。
"""
import io
import json
import os
import sys

import stockscore_gate as G

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, '_gate_fixtures')


def load(name):
    p = os.path.join(FIX, name)
    if not os.path.exists(p):
        return None
    return io.open(p, encoding='utf-8').read()


def main():
    samples = []
    # 微信原文写于新增两个模块之前，本身不含"估值与预期""风险与安全"两节，
    # 因此校准时排除这两个槽位——否则等于用旧标准否定新框架。
    wechat_slots = [s for s in G.FRAMEWORK_SLOTS
                    if s['key'] not in ('valuation', 'risk')]
    for fn, label, expect, slots in (
            ('gold_wechat.txt', '微信深度文章（峰岹科技）', 'pass', wechat_slots),
            ('gold_yuanbao.txt', '元宝总结版（峰岹科技）', 'pass', G.FRAMEWORK_SLOTS),
            ('bad_empty.txt', '纯定性空话', 'not_pass', G.FRAMEWORK_SLOTS)):
        t = load(fn)
        if t:
            samples.append((label, expect, t, slots))

    if len(sys.argv) > 1:
        p = sys.argv[1]
        samples = [('外部文件 %s' % os.path.basename(p), 'pass',
                    io.open(p, encoding='utf-8').read(), G.FRAMEWORK_SLOTS)]

    if not samples:
        print('未找到校准样本，请先运行 make_fixtures.py 生成 _gate_fixtures/')
        return 1

    ok = True
    for label, expect, text, slots in samples:
        # 金标准样本没有事实包，用文中自身数字构造伪事实，只测密度/覆盖/长度
        facts = []
        for tok in G._numbers_in(text):
            v, _ = G._normalize_num(tok)
            if v is not None:
                facts.append({'text': tok, 'value': v})
        res = G.evaluate(text, facts, gaps=[], required_slots=slots)
        m = res['metrics']
        print('=' * 62)
        print('%s' % label)
        print('  判定      : %s（期望 %s）' % (res['verdict'], expect))
        print('  字数      : %s' % m.get('length'))
        print('  数字密度  : %s' % m.get('density'))
        print('  槽位覆盖  : %s  (缺 %s)' % (m.get('coverage'), m.get('coverage_missing')))
        print('  溯源率    : %s  (%s/%s)' % (m.get('traceability'),
                                             m.get('traceability_hit'),
                                             m.get('traceability_total')))
        print('  具体度    : %s' % m.get('specificity'))
        if res['failed']:
            print('  未过项    :')
            for f in res['failed']:
                print('      - %s' % f)
        if res['warnings']:
            print('  提示      :')
            for w in res['warnings']:
                print('      - %s' % w)

        if expect == 'pass' and res['verdict'] != 'pass':
            ok = False
            print('  >>> 校准失败：金标准被判 %s，阈值过严' % res['verdict'])
        if expect == 'not_pass' and res['verdict'] == 'pass':
            ok = False
            print('  >>> 校准失败：空话被判 pass，阈值过松')

    print('=' * 62)
    print('校准结果：%s' % ('通过' if ok else '需要调阈值'))
    return 0 if ok else 2


if __name__ == '__main__':
    sys.exit(main())
