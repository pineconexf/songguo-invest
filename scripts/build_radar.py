#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行业雷达消费端 —— 把最新一期 radar_YYYYMMDD.json 写入网站 research_industry.json
=============================================================================
数据源：D:/pineconeinvestfiles/松果商业生态/radar/radar_YYYYMMDD.json（每周五产线产出）
只覆盖 hot_sectors / events / warnings / source 的雷达段；monthly_report 段保持不动（月报脚本管）。

用法: python scripts/build_radar.py [--check]
  --check  只报告是否有更新，不写入
"""
import json, os, sys, glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'src', 'data')
RADAR_DIRS = [
    r'D:\pineconeinvestfiles\松果商业生态\radar',
    '/root/sync/pineconeinvestfiles/松果商业生态/radar',   # 云端兜底
]

def radar_files():
    out = []
    for d in RADAR_DIRS:
        out += glob.glob(os.path.join(d, 'radar_*.json'))
    return out

def latest_radar():
    """取 issue 最大的一期；无 issue 则按文件名日期降序"""
    files = radar_files()
    if not files:
        return None, None
    best, best_key = None, None
    for p in files:
        try:
            with open(p, encoding='utf-8') as f:
                r = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        key = (int(r.get('issue') or 0), str(r.get('date') or ''))
        if best_key is None or key > best_key:
            best, best_key = r, key
    return best, best_key

def main():
    check_only = '--check' in sys.argv
    radar, key = latest_radar()

    ind_path = os.path.join(DATA, 'research_industry.json')
    with open(ind_path, encoding='utf-8') as f:
        ind = json.load(f)

    if not radar:
        print("[SKIP] 无雷达产出文件（radar_*.json），保持现状")
        return 0

    for field in ('hot_sectors', 'events', 'warnings'):
        if not radar.get(field):
            print(f"[WARN] 雷达第{radar.get('issue')}期缺 {field}，跳过本次写入", file=sys.stderr)
            return 0

    old_src = ind.get('source', '')
    new_src = radar.get('source') or f"松果每周行业雷达第{radar['issue']}期（{radar.get('date')}）"
    # source 保留月报段（月报脚本维护）
    month_part = ''
    if '+ 策略月报' in old_src:
        month_part = ' + ' + old_src.split('+ 策略月报', 1)[1].strip()
    src = new_src + month_part

    changed = (
        ind.get('hot_sectors') != radar['hot_sectors']
        or ind.get('events') != radar['events']
        or ind.get('warnings') != radar['warnings']
        or old_src != src
    )
    if check_only:
        print(f"[CHECK] 最新雷达 第{radar['issue']}期({radar.get('date')}) | 变化={changed}")
        return 0
    if not changed:
        print(f"[OK] 雷达数据无变化（第{radar['issue']}期）")
        return 0

    ind['hot_sectors'] = radar['hot_sectors']
    ind['events'] = radar['events']
    ind['warnings'] = radar['warnings']
    ind['source'] = src
    with open(ind_path, 'w', encoding='utf-8') as f:
        json.dump(ind, f, ensure_ascii=False, indent=2)

    print(f"[OK] 雷达已更新 → 第{radar['issue']}期（{radar.get('date')}）")
    for h in radar['hot_sectors']:
        print(f"    #{h.get('rank')} {h.get('name')} [{h.get('heat')}]")
    return 0

if __name__ == '__main__':
    sys.exit(main())
