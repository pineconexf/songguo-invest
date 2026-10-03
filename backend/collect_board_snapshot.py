#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
概念板块每日快照采集器（个股打分卡 ⑥ 维「概念20日位次」子项的数据来源）
================================================================
背景（实测结论，见 spec.md §0 与「接口可用性矩阵报告.md」）：
  - push2.eastmoney.com/clist 属【高危区】：2-3 次成功即触发 IP 级 RST，
    10+ 分钟不恢复且不返 403/429。因此本脚本是**全工程唯一**允许调用
    clist 的地方，且**每日最多调用 1 次**，靠落盘快照为打分卡供数。
  - 打分卡引擎（backend/stockscore.py）只读快照文件，绝不实时调 clist。

产出：
  backend/data/board_snapshots/boards_YYYYMMDD.json
  格式：{"BK0590": 1.23, "BK0665": -0.45, ...}   # 板块代码 → 当日涨跌幅%
  引擎需连续 21 个交易日（20 日涨幅 = 21 个点位连乘）后自动启用该子项。

用法：
  python collect_board_snapshot.py            # 采集今日快照（已存在则跳过）
  python collect_board_snapshot.py --force    # 覆盖重采（仅当日，历史日禁覆盖）
  python collect_board_snapshot.py --date 2026-10-03   # 补采指定交易日
  python collect_board_snapshot.py --status   # 查看已积累天数与最近日期

退出码：0 成功/已存在；1 采集失败（重试全用尽）；2 参数/环境错误。
幂等：同日重跑直接跳过（--force 除外），cron 配置失败重试不会产生脏数据。
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("[FATAL] 缺 requests：pip install requests", file=sys.stderr)
    sys.exit(2)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(BASE_DIR, 'data', 'board_snapshots')
LOG_FILE = os.path.join(BASE_DIR, 'data', 'collect_boards.log')

# 退避梯度（秒）：高危区失败后必须长退避，短退避只会加重 RST
BACKOFF_STEPS = [30, 120, 600]

# 概念板块（m:90 t:3）；fields: f12=板块代码 f14=板块名 f3=涨跌幅 f8=换手率 f20=总市值
CLIST_URL = (
    "https://push2.eastmoney.com/api/qt/clist/get"
    "?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3"
    "&fs=m:90+t:3+f:!50&fields=f12,f3,f14"
)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
}
# 备用通道：datacenter-web 稳定区没有板块实时涨跌幅，
# 若 push2 全挂，次日早上再补；这里不做多域名轮询以免放大封禁。


def log(msg):
    line = "[{}] {}".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line)
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except OSError:
        pass


def snap_path(date_str):
    return os.path.join(SNAP_DIR, 'boards_{}.json'.format(date_str.replace('-', '')))


def fetch_one_page(pn, timeout=20):
    r = requests.get(CLIST_URL.format(pn=pn), headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    d = r.json()
    data = (d or {}).get('data') or {}
    return data.get('diff') or [], int(data.get('total') or 0)


def collect_once():
    """一次完整抓取（分页至覆盖 total）。任何一页失败即整体抛错，不产半截文件。"""
    out, page, total = {}, 1, None
    while True:
        diff, tot = fetch_one_page(page)
        if total is None:
            total = tot
        if not diff:
            break
        for row in diff:
            code, chg = row.get('f12'), row.get('f3')
            if not code:
                continue
            if isinstance(chg, (int, float)):
                out[code] = round(float(chg), 4)
            elif chg not in ('-', None):
                try:
                    out[code] = round(float(chg), 4)
                except (TypeError, ValueError):
                    pass
        if len(out) >= total or page * 100 >= total:
            break
        page += 1
        if page > 15:
            break
        time.sleep(1.5)  # 分页间隔，勿并发打 push2
    if len(out) < 100:
        raise RuntimeError("板块数异常（{}<100），视为抓取失败".format(len(out)))
    return out, total


def is_trading_day(date_str):
    """用腾讯行情（最稳通道）判断是否交易日：拉沪指当日K线最后日期。"""
    try:
        url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               "?param=sh000001,day,{}T00:00:00,{}T23:59:59,10,qfq".format(date_str, date_str))
        r = requests.get(url, headers={'User-Agent': HEADERS['User-Agent']}, timeout=15)
        d = r.json()
        node = d['data']['sh000001']
        days = node.get('qfqday') or node.get('day') or []
        return bool(days) and days[-1][0] == date_str
    except Exception:
        # 判不了交易日时：工作日默认放行（数据错一天不如没数据，但引擎按日期对齐连乘，
        # 非交易日快照会因日期目录不同被自然隔离——文件名即日期）
        wd = datetime.strptime(date_str, '%Y-%m-%d').weekday()
        return wd < 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='覆盖当日已存在的快照')
    ap.add_argument('--date', default=None, help='采集指定日期 YYYY-MM-DD（默认今天）')
    ap.add_argument('--status', action='store_true', help='查看积累状态')
    args = ap.parse_args()

    os.makedirs(SNAP_DIR, exist_ok=True)
    date_str = args.date or datetime.now().strftime('%Y-%m-%d')

    if args.status:
        files = sorted(f for f in os.listdir(SNAP_DIR) if f.startswith('boards_'))
        need = 21
        log("已积累 {} 个交易日快照（引擎启用阈值 {}）".format(len(files), need))
        if files:
            log("最早 {}，最近 {}".format(files[0], files[-1]))
        return 0

    path = snap_path(date_str)
    if os.path.exists(path) and not args.force:
        log("快照已存在，跳过：{}".format(path))
        return 0

    if not is_trading_day(date_str):
        log("非交易日（{}），不采集".format(date_str))
        return 0

    last_err = None
    for attempt, wait in enumerate([0] + BACKOFF_STEPS):
        if wait:
            log("第 {} 次重试，退避 {}s（push2 高危区，长退避）".format(attempt, wait))
            time.sleep(wait)
        try:
            boards, total = collect_once()
            tmp = path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(boards, f, ensure_ascii=False)
            os.replace(tmp, path)
            log("采集成功：{} 个概念板块（total={}）→ {}".format(len(boards), total, path))
            return 0
        except Exception as e:
            last_err = e
            log("抓取失败（第 {} 次）：{}: {}".format(attempt + 1, type(e).__name__, e))
    log("[GIVEUP] 全部重试失败：{}".format(last_err))
    return 1


if __name__ == '__main__':
    sys.exit(main())
