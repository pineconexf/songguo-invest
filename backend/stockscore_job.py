# -*- coding: utf-8 -*-
"""深度分析作业态（2026-10-21）

解决三件事：
1. **首段 8-10 秒可见**：生成过程是后台线程，每出一段就把该段塞进作业快照，
   前端轮询 /api/stockscore_v3_deep_progress 就能先渲染第一段，不用等全文。
2. **全文 60-90 秒完成**：六段并行（stockscore_deep 内部），
   critic 走 deepseek-chat（实测 3.4s vs 25.6s），同轮多段重写也并行。
3. **总览页后台预热，点深度页近 0 秒读缓存**：
   总览页调 prewarm() 触发后台生成（不等结果），
   深度页调 get() 直接拿快照 —— 命中缓存则近 0 秒返回。

为什么不用 SSE：ECS 上的 nginx 走的是 HTTP/1.1 反代，
SSE 长连接在反代层容易被缓冲/截断（proxy_read_timeout 60s 一刀切，
而深度分析要 90s）。轮询是更稳的选择：每次响应都很小、
不依赖连接保持、反代层零改造。

线程模型：一个 code 一个后台线程（去重靠 _JOBS 字典的原子占位），
段落级快照用锁保护。快照只存正文文本与状态，不存 LLM 原始响应。
"""
import threading
import time

# code -> 作业快照
_JOBS = {}
_LOCK = threading.Lock()

# 快照最多留多少个（防止内存无限增长）
_MAX_JOBS = 64
# 作业完成后快照保留多久（秒）—— 之后清理，磁盘缓存仍然有效
_KEEP = 3600


def _now():
    return time.time()


def _new_job(code):
    return {
        'code': code,
        'state': 'running',        # running | done | error
        'started_at': _now(),
        'updated_at': _now(),
        'sections': {},           # key -> {key,title,text,chars,note,stage}
        'order': [],              # 段落发布顺序（按到达顺序）
        'coverage': None,
        'total_chars': 0,
        'meta': {},
        'error': None,
        'final': None,            # 完成后放完整 deep payload
    }


def _gc_locked():
    now = _now()
    if len(_JOBS) > _MAX_JOBS:
        # 先删最老的已完成作业
        done = [k for k, v in _JOBS.items() if v['state'] != 'running']
        for k in sorted(done, key=lambda k: _JOBS[k]['updated_at'])[:len(done) // 2 or 1]:
            _JOBS.pop(k, None)
    for k, v in list(_JOBS.items()):
        if v['state'] != 'running' and now - v['updated_at'] > _KEEP:
            _JOBS.pop(k, None)


def publish_section(code, sec):
    """生成线程回调：一段正文完成，立刻写进作业快照。"""
    with _LOCK:
        j = _JOBS.get(code)
        if not j:
            return
        key = sec.get('key')
        if not key:
            return
        if key not in j['sections']:
            j['order'].append(key)
        text = sec.get('text') or ''
        j['sections'][key] = {
            'key': key,
            'title': sec.get('title') or key,
            'text': text,
            'chars': len(text),
            'note': sec.get('note') or '',
            'facts_used': sec.get('facts_used') or 0,
            'unverified_numbers': sec.get('unverified_numbers') or [],
        }
        j['total_chars'] = sum(s['chars'] for s in j['sections'].values())
        j['updated_at'] = _now()


def finish(code, final=None, coverage=None, meta=None, error=None):
    """生成线程回调：作业结束。"""
    with _LOCK:
        j = _JOBS.get(code)
        if not j:
            return
        if error:
            j['state'] = 'error'
            j['error'] = str(error)[:300]
        else:
            j['state'] = 'done'
        if coverage:
            j['coverage'] = coverage
        if meta:
            j['meta'].update(meta)
        if final is not None:
            j['final'] = final
        j['updated_at'] = _now()


def claim(code):
    """占位：返回 True 表示本次调用负责启动后台生成，False 表示已有作业在跑。"""
    with _LOCK:
        _gc_locked()
        j = _JOBS.get(code)
        if j and j['state'] == 'running':
            return False
        _JOBS[code] = _new_job(code)
        return True


def get(code):
    """取作业快照（只读，不启动）。"""
    with _LOCK:
        j = _JOBS.get(code)
        if not j:
            return None
        return {
            'code': j['code'],
            'state': j['state'],
            'started_at': j['started_at'],
            'updated_at': j['updated_at'],
            'elapsed': round(_now() - j['started_at'], 1),
            'sections': [j['sections'][k] for k in j['order'] if k in j['sections']],
            'coverage': j['coverage'],
            'total_chars': j['total_chars'],
            'meta': j['meta'],
            'error': j['error'],
            'has_final': j['final'] is not None,
        }


def has_running(code):
    with _LOCK:
        j = _JOBS.get(code)
        return bool(j and j['state'] == 'running')


def clear(code):
    with _LOCK:
        _JOBS.pop(code, None)
