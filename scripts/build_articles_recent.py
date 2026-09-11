# -*- coding: utf-8 -*-
"""
「近期文章」目录自动生成管线
============================
扫描松果商业生态目录下每天产出的文章，生成网站服务页「近期文章」表。

数据源（均为本地真实产出物，不编造）：
  spec_YYYYMMDD_<key>.json    -> 发布批次：栏目(column) + 各平台标题/备选标题
  文章_YYYYMMDD_<key>_母本.md  -> 文章正文标题(H1)，每篇一条
  四平台发布包_YYYYMMDD\\       -> 已分发证据

规则：
  - 只收录 date <= 今天 的条目（未来日期属预排产，不展示）
  - **母本为主键**：每篇母本 = 一条，标题用母本 H1
  - 栏目(column)：用当天 spec 认领——先按文件名 key 互相包含匹配，再退化为标题相似度(>=0.82)；
    仍无匹配则按文件名关键词退化（默认「每日资讯」）
  - 当天有 spec 但无对应母本时，该 spec 单独成条（用其首要标题）
  - 状态：存在当日「四平台发布包」-> 已发布（公众号）；否则 -> 母本已备
  - 按日期倒序取最近 N 条（默认 15）

用法: python scripts/build_articles_recent.py
输出: src/data/articles_recent.json
"""
import os, re, io, sys, json, glob
from datetime import datetime
from difflib import SequenceMatcher

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = r'D:\pineconeinvestfiles\松果商业生态'
OUT = r'D:\pineconeinvestfiles\松果投资体系网站\01_网站开发\src\data\articles_recent.json'
LIMIT = 15
TITLE_RATIO = 0.82

KEYWORD_TYPE = [
    ('组合风控', '组合与风控'),
    ('策略换池', '月度策略'),
    ('月度策略', '月度策略'),
    ('行业雷达', '行业雷达'),
    ('茶话会', '周末茶话会'),
]


def norm(s):
    """归一化：去空白、标点、下划线，便于跨平台标题/文件名比对"""
    return re.sub(r'[\s，。、：；！？（）()\[\]"\'“”‘’|,.:;!?·—\-_%]+', '', s or '')


def read_h1(path):
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('# '):
                    t = line[2:].strip()
                    return t.split('|', 1)[1].strip() if '|' in t else t
    except Exception:
        pass
    return ''


def spec_titles(sp):
    out = []
    for v in (sp.get('platforms') or {}).values():
        if not isinstance(v, dict):
            continue
        for k in ('title', 'alt_titles'):
            val = v.get(k)
            if not val:
                continue
            for t in str(val).split('/'):
                t = t.strip()
                if t:
                    out.append(t)
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def spec_key(base):
    """spec_20260910_涨的指数跌的体感.json -> 涨的指数跌的体感"""
    return re.sub(r'^spec_\d{8}_', '', base).replace('.json', '')


def master_key(base):
    """文章_20260910_涨的指数跌的体感_母本.md -> 涨的指数跌的体感"""
    return re.sub(r'^文章_\d{8}_', '', base).replace('_母本.md', '')


def load_specs():
    out = {}
    for p in glob.glob(os.path.join(ROOT, 'spec_*.json')):
        base = os.path.basename(p)
        m = re.search(r'spec_(\d{8})_', base)
        if not m:
            continue
        try:
            sp = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        out.setdefault(m.group(1), []).append({
            'column': (sp.get('column') or '').strip(),
            'titles': spec_titles(sp),
            'key': norm(spec_key(base)),
            'file': base,
        })
    return out


def load_masters():
    out = {}
    for p in glob.glob(os.path.join(ROOT, '文章_*_母本.md')):
        base = os.path.basename(p)
        m = re.search(r'文章_(\d{8})_', base)
        if not m:
            continue
        t = read_h1(p) or master_key(base).replace('_', ' ')
        out.setdefault(m.group(1), []).append({
            'title': t, 'key': norm(master_key(base)), 'file': base,
        })
    return out


def packaged_dates():
    s = set()
    for p in glob.glob(os.path.join(ROOT, '四平台发布包_*')):
        m = re.search(r'四平台发布包_(\d{8})', os.path.basename(p))
        if m:
            s.add(m.group(1))
    return s


def fallback_type(title):
    for kw, tp in KEYWORD_TYPE:
        if kw in title:
            return tp
    return '每日资讯'


def ratio(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def match_spec(master, day_specs, claimed):
    """为一个母本挑选 spec：文件名包含优先，其次标题相似度"""
    # 1) 文件名 key 互相包含（如 '组合优化' ⊂ '组合优化判断层执行层'）
    for i, sp in enumerate(day_specs):
        if i in claimed or not sp['key']:
            continue
        if sp['key'] in master['key'] or master['key'] in sp['key']:
            return i
    # 2) 标题相似度兜底（阈值调高，避免同日近义标题误配）
    best_i, best_r = -1, 0.0
    for i, sp in enumerate(day_specs):
        if i in claimed or not sp['titles']:
            continue
        r = max(ratio(master['title'], t) for t in sp['titles'])
        if r > best_r:
            best_i, best_r = i, r
    return best_i if best_r >= TITLE_RATIO else -1


def main():
    today = datetime.now().strftime('%Y%m%d')
    specs, masters, packs = load_specs(), load_masters(), packaged_dates()

    rows = []
    for d in sorted(set(specs) | set(masters), reverse=True):
        if d > today:
            continue
        date_s = f'{d[:4]}-{d[4:6]}-{d[6:]}'
        status = '已发布（公众号）' if d in packs else '母本已备'
        day_specs = specs.get(d, [])
        claimed = set()

        for m in masters.get(d, []):
            i = match_spec(m, day_specs, claimed)
            if i >= 0:
                claimed.add(i)
                col = day_specs[i]['column'] or fallback_type(m['title'])
            else:
                col = fallback_type(m['title'])
            rows.append({'date': date_s, 'type': col, 'title': m['title'], 'status': status})

        for i, sp in enumerate(day_specs):
            if i in claimed or not sp['titles']:
                continue
            t = sp['titles'][0]
            rows.append({'date': date_s, 'type': sp['column'] or fallback_type(t), 'title': t, 'status': status})

    rows.sort(key=lambda r: r['date'], reverse=True)
    rows = rows[:LIMIT]

    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)
    print(f'✅ 已生成 {OUT}（{len(rows)} 条，截至 {today}）')
    for r in rows:
        print(f"  {r['date']} | {r['type']:12} | {r['title'][:44]:44} | {r['status']}")


if __name__ == '__main__':
    main()
