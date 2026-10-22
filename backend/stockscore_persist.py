# -*- coding: utf-8 -*-
"""
磁盘日级缓存层（进程重启后仍命中）。

背景（2026-10-22 公网验收实测）：
  生产 uvicorn 重启后，api.py 里的 _CACHE 内存字典全丢，
  冷启动一次 /api/stockscore_v3_bundle 要重新算：
      compute_v3    28.9s   （打分卡 payload）
      build_facts    9.7s   （F10 财务多期事实层）
      modules       18.4s   （估值块 + 风险块）
      合计 ≈ 57s
  这 57s 全部发生在深度正文生成**之前**，导致：
      - 首段可见时间被推到 40s（目标 8–10s）
      - 全文完成被推到 ≈100s（目标 60–90s）
      - 服务重启/扩容后第一批用户必然吃到冷读

方案：
  把「当日不变」的确定性结果层（payload / facts / modules）落盘到
  data/persist/<key>.<YYYYMMDD>.json，进程重启后直接读盘。
  写盘用 JSON（不是 pickle，避免反序列化执行风险）；
  任何异常一律降级为「缓存未命中」，退回原计算路径，绝不因此报错。

只用在本项目自己写入的本地文件，不接受外部输入。
"""
import json
import os
import threading
import time

_LOCK = threading.Lock()
_DIR = None


def _dir():
    global _DIR
    if _DIR is None:
        _DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            'data', 'persist')
        try:
            os.makedirs(_DIR, exist_ok=True)
        except Exception:      # noqa: BLE001
            pass
    return _DIR


def _path(key, day):
    safe = ''.join(c for c in key if c.isalnum() or c in '-_.')
    if not safe:
        safe = 'x'
    return os.path.join(_dir(), f'{safe}.{day}.json')


def get(key, day=None):
    """读盘。命中返回对象，miss/异常返回 None（调用方须自行走计算路径）。"""
    if day is None:
        day = time.strftime('%Y%m%d')
    p = _path(key, day)
    try:
        if not os.path.exists(p):
            return None
        # 超过 12 小时的落盘视为过期，避免跨日/陈旧数据长期驻留
        if time.time() - os.path.getmtime(p) > 12 * 3600:
            return None
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:          # noqa: BLE001
        return None


def put(key, obj, day=None):
    """写盘。失败静默（缓存不是关键路径，不该因写盘失败影响主流程）。"""
    if day is None:
        day = time.strftime('%Y%m%d')
    p = _path(key, day)
    try:
        with _LOCK:
            tmp = p + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(obj, f, ensure_ascii=False, default=str)
            os.replace(tmp, p)
        return True
    except Exception:          # noqa: BLE001
        return False


def clear(code=None):
    """清理落盘缓存（code=None 清全部）。返回删除文件数。"""
    n = 0
    d = _dir()
    try:
        for fn in os.listdir(d):
            if not fn.endswith('.json'):
                continue
            if code and code not in fn:
                continue
            try:
                os.remove(os.path.join(d, fn))
                n += 1
            except Exception:  # noqa: BLE001
                pass
    except Exception:          # noqa: BLE001
        pass
    return n
