# -*- coding: utf-8 -*-
"""生活投资策略月度明细 → 网站图表 JSON（ETF/公募版）"""
import json, os

BASE = r'D:\pineconeinvestfiles\生活投资策略\三版本定稿'
OUT = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data'

def convert(fname, out_name, label):
    path = os.path.join(BASE, fname)
    labels, navs = [], []
    with open(path, encoding='utf-8-sig') as f:
        next(f)  # header
        for line in f:
            parts = line.strip().split(',')
            if len(parts) < 3:
                continue
            ym, ret, nav = parts[0], parts[1], parts[2]
            labels.append(ym)
            navs.append(round(float(nav), 4))
    data = {'label': label, 'labels': labels, 'nav': navs}
    with open(os.path.join(OUT, out_name), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    print(f'{out_name}: {len(labels)} 个月 | 起点 {labels[0]} → 终点 {labels[-1]} 净值 {navs[-1]}')

convert('全ETF版_2014起_月度明细.csv', 'life_etf.json', '全ETF组合')
convert('全公募版_2016起_月度明细.csv', 'life_fund.json', '全公募组合')
