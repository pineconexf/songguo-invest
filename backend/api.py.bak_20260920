# -*- coding: utf-8 -*-
"""松果个股体检 API（华纳云部署版）
POST /api/check  {"code": "600729"} → 完整体检报告 JSON

安全口径（2026-09-15 审计批次0）：
- 密钥优先级：环境变量 > 本地 .env（生产用 systemd EnvironmentFile 注入）
- CORS 白名单：仅本站两条来源，不用通配
- 入参长度上限 + 同码结果缓存（省 LLM 额度、抗重复刷）
- 结论字段一律中性化：只给画像/评级，禁止任何买卖、持仓类表述
"""
import os, json, re, time, threading
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_ds_key():
    """密钥优先级：环境变量 > 本地 .env 文件。

    生产环境由 systemd `EnvironmentFile=` 注入（文件权限 600），
    这样密钥轮换（改 env + 重启）立即生效，磁盘明文不再是唯一来源。
    """
    v = (os.environ.get('DEEPSEEK_API_KEY') or '').strip()
    if v:
        return v
    env_path = os.path.join(BASE_DIR, '.env')
    if os.path.exists(env_path):
        with open(env_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('DEEPSEEK_API_KEY='):
                    return line.split('=', 1)[1].strip()
    return ''


DS_KEY = load_ds_key()

# CORS 白名单：仅本站来源（含本地开发端口），不开放通配
ALLOW_ORIGINS = [
    'https://pinecone-lab.cn',
    'https://www.pinecone-lab.cn',
    'http://localhost:4321',
    'http://127.0.0.1:4321',
]

app = FastAPI(title='松果个股体检', version='0.2')
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=['GET', 'POST', 'OPTIONS'],
    allow_headers=['Content-Type'],
)


class Req(BaseModel):
    code: str = Field(..., max_length=16, description='6 位 A 股代码')


# ---------- 同码结果缓存（TTL 10 分钟） ----------
_CACHE = {}
_CACHE_TTL = 600
_CACHE_MAX = 500
_CACHE_LOCK = threading.Lock()


def cache_get(code):
    with _CACHE_LOCK:
        item = _CACHE.get(code)
        if not item:
            return None
        ts, payload = item
        if time.time() - ts > _CACHE_TTL:
            _CACHE.pop(code, None)
            return None
        return payload


def cache_put(code, payload):
    with _CACHE_LOCK:
        _CACHE[code] = (time.time(), payload)
        if len(_CACHE) > _CACHE_MAX:  # 上限保护，防内存无限增长
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:200]:
                _CACHE.pop(k, None)


# ---------- 数据 ----------
def fetch_finance(code):
    mkt = 'SH' if code.startswith(('6', '9')) else 'SZ'
    url = ("https://datacenter.eastmoney.com/securities/api/data/v1/get"
           "?reportName=RPT_F10_FINANCE_MAINFINADATA"
           "&columns=SECUCODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_DATE_NAME,"
           "TOTALOPERATEREVE,PARENTNETPROFIT,XSMLL,ROEJQ,EPSJB,TOTALOPERATEREVETZ,PARENTNETPROFITTZ"
           f"&filter=(SECUCODE%3D%22{code}.{mkt}%22)"
           "&pageNumber=1&pageSize=12&sortTypes=-1&sortColumns=REPORT_DATE&source=HSF10&client=PC")
    for _ in range(3):
        try:
            r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            d = r.json()
            if d.get('result') and d['result'].get('data'):
                return d['result']['data']
            return None
        except Exception:
            time.sleep(2)
    return None


def fetch_quote(code):
    prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
    url = f"http://qt.gtimg.cn/q={prefix}{code}"
    for _ in range(3):
        try:
            r = requests.get(url, timeout=15, headers={'User-Agent': 'Mozilla/5.0'})
            r.encoding = 'gbk'
            f = r.text.split('"')[1].split('~')
            return {'price': float(f[3]) if f[3] else 0, 'pe': float(f[39]) if f[39] else 0,
                    'mv_yi': float(f[45]) if f[45] else 0, 'pb': float(f[46]) if f[46] else 0}
        except Exception:
            time.sleep(2)
    return None


# ---------- 评分 ----------
def is_annual(d):
    return '12-31' in str(d)


def compute_scores(rows, q):
    annual = [r for r in rows if is_annual(r['REPORT_DATE'])][:3]
    roe_vals = [float(r.get('ROEJQ') or 0) for r in annual]
    roe_min = min(roe_vals) if roe_vals else 0
    roe_s = 20 if roe_min > 10 else 15 if roe_min > 5 else 10 if roe_min > 3 else 5 if roe_min > 0 else 0
    profit_vals = [float(r.get('PARENTNETPROFIT') or 0) for r in annual]
    neg = sum(1 for v in profit_vals if v < 0)
    prof_s = 20 if neg == 0 else 10 if neg == 1 else 0
    pe = float(q.get('pe') or 0)
    pe_s = 20 if 0 < pe <= 15 else 15 if pe <= 25 else 10 if pe <= 40 else 5 if pe <= 60 else 0
    mv = float(q.get('mv_yi') or 0)
    mv_s = 20 if mv < 100 else 15 if mv <= 300 else 10 if mv <= 600 else 5 if mv <= 1000 else 0
    yoy = float(rows[0].get('PARENTNETPROFITTZ') or 0) if rows else 0
    gr_s = 20 if yoy > 30 else 15 if yoy > 10 else 10 if yoy > 0 else 5 if yoy > -20 else 0
    total = roe_s + prof_s + pe_s + mv_s + gr_s
    grade = '优' if total >= 80 else '良' if total >= 60 else '中' if total >= 40 else '差'
    return {
        'roe': {'score': roe_s, 'max': 20, 'detail': f'近3年ROE最低 {roe_min:.1f}%', 'thresh': 'V35：ROE连续3年>3%'},
        'profit': {'score': prof_s, 'max': 20, 'detail': f'近3年净利负值年数 {neg}/3', 'thresh': 'V35：连续盈利'},
        'pe': {'score': pe_s, 'max': 20, 'detail': f'PE(TTM) {pe:.1f}', 'thresh': '估值维度（FCF/EV待接入）'},
        'mv': {'score': mv_s, 'max': 20, 'detail': f'总市值 {mv:.0f}亿', 'thresh': 'V35：市值≤300亿'},
        'growth': {'score': gr_s, 'max': 20, 'detail': f'净利同比 {yoy:.1f}%', 'thresh': '成长维度（牛市增强信号）'},
        'total': total, 'grade': grade
    }


PROMPT = """你是「松果投资体系」的个股体检助手。请基于给定评分数据，输出一份专业的个股体检报告。

股票：{name}（{code}），现价 {price} 元，PE(TTM) {pe}，总市值 {mv} 亿，PB {pb}
体系总分：{total}/100，评级：{grade}

分项评分（各20分制）：
- 质量·ROE（{roe_score}分）：{roe_detail}
- 盈利持续性（{profit_score}分）：{profit_detail}
- 估值（{pe_score}分）：{pe_detail}
- 市值（{mv_score}分）：{mv_detail}
- 成长（{growth_score}分）：{growth_detail}

请输出 JSON：
{{
  "summary": "一句话定位（60字内，讲清楚这是一只什么风格的股票）",
  "style_analysis": "松果 V35 画像匹配分析（150字内：低估值+高质量+中小盘三个维度分别匹配度）",
  "strengths": ["优势1", "优势2", "优势3"],
  "risks": ["风险1", "风险2", "风险3"],
  "verdict": "体系画像定位（120字内：从五维评分说明该股的画像特征，如质量型 / 成长型 / 低估型 / 混合型，说明强项与短板各在哪个维度）",
  "action_hint": "画像归类（60字内：把该股归入「质量型 / 成长型 / 低估型 / 混合型 / 不符合画像」之一，并一句话说明依据）"
}}

铁律：只做客观画像描述与评分陈述。禁止出现任何买入、卖出、加仓、减仓、持有、建仓、清仓、目标价、涨跌预测、收益承诺类表述。"""


def _build_prompt(code, name, q, scores):
    return PROMPT.format(
        name=name, code=code, price=q['price'], pe=q['pe'], mv=q['mv_yi'], pb=q['pb'],
        total=scores['total'], grade=scores['grade'],
        roe_score=scores['roe']['score'], roe_detail=scores['roe']['detail'],
        profit_score=scores['profit']['score'], profit_detail=scores['profit']['detail'],
        pe_score=scores['pe']['score'], pe_detail=scores['pe']['detail'],
        mv_score=scores['mv']['score'], mv_detail=scores['mv']['detail'],
        growth_score=scores['growth']['score'], growth_detail=scores['growth']['detail'])


def _call_llm(prompt):
    url = "https://api.deepseek.com/chat/completions"
    headers = {'Authorization': f'Bearer {DS_KEY}', 'Content-Type': 'application/json'}
    body = {"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3, "response_format": {"type": "json_object"}, "max_tokens": 1500}
    last_err = None
    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=90)
            if r.status_code != 200:
                last_err = f'LLM HTTP {r.status_code}'
                continue
            content = r.json()['choices'][0]['message']['content']
            return json.loads(content)
        except Exception as e:
            last_err = str(e)
            time.sleep(2)
    raise HTTPException(500, f'报告生成失败: {last_err}')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'service': 'songguo-stock-check'}


@app.post('/api/check')
def check(req: Req):
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')

    cached = cache_get(code)
    if cached:
        return cached

    rows = fetch_finance(code)
    if not rows:
        raise HTTPException(404, '未获取到该股票的财务数据，请核对代码')
    name = rows[0].get('SECURITY_NAME_ABBR', code)
    q = fetch_quote(code) or {'price': 0, 'pe': 0, 'mv_yi': 0, 'pb': 0}
    scores = compute_scores(rows, q)
    report = _call_llm(_build_prompt(code, name, q, scores))

    payload = {'name': name, 'code': code,
               'quote': {'price': q['price'], 'pe': q['pe'], 'mv': q['mv_yi'], 'pb': q['pb']},
               'scores': scores, 'report': report}
    cache_put(code, payload)
    return payload


# ---------- 匿名工具使用埋点（2026-09-18）----------
# 只记录：工具名/事件/随机sid/停留秒数。不记录IP、不记录用户输入内容。
# 数据按日切 JSONL 存 track/，90 天归档压缩。埋点失败静默，绝不影响主服务。
TRACK_DIR = os.path.join(BASE_DIR, 'track')
TRACK_TOOLS = {'backtest-compare', 'compound', 'daily-insight', 'etf-allocator', 'fund-ranking',
               'fund-scorecard', 'industry-compare', 'industry-report', 'macro-signal', 'stockcheck', 'valuator'}
TRACK_EVENTS = {'view', 'run', 'result', 'error', 'dwell'}
_TRACK_LOCK = threading.Lock()


class TrackReq(BaseModel):
    tool: str = Field('', max_length=32)
    event: str = Field('', max_length=8)
    sid: str = Field('', max_length=32)
    dwell: float = None


@app.post('/api/track')
def track(req: TrackReq):
    if req.tool not in TRACK_TOOLS or req.event not in TRACK_EVENTS:
        return {'ok': False}
    sid = re.sub(r'[^a-zA-Z0-9]', '', req.sid or '')[:24]
    d = None
    if req.dwell is not None:
        try:
            d = max(0.0, min(float(req.dwell), 3600.0))
        except (TypeError, ValueError):
            d = None
    try:
        # 文件名用北京时间（UTC+8），与日报口径一致
        fname = time.strftime('%Y-%m-%d', time.gmtime(time.time() + 28800)) + '.jsonl'
        rec = {'ts': int(time.time()), 'tool': req.tool, 'event': req.event, 'sid': sid}
        if d is not None:
            rec['dwell'] = round(d, 1)
        os.makedirs(TRACK_DIR, exist_ok=True)
        with _TRACK_LOCK:
            with open(os.path.join(TRACK_DIR, fname), 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return {'ok': True}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))
