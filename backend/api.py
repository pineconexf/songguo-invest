# -*- coding: utf-8 -*-
"""松果个股体检 API（华纳云部署版）
POST /api/check  {"code": "600729"} → 完整体检报告 JSON
POST /api/stockscore {"code": "600519"} → 六维个股打分卡（spec v1.0，2026-10-03）
  旧「个股体检」保持在线不动；打分卡引擎在 backend/stockscore.py，另开代码。

安全口径（2026-09-15 审计批次0）：
- 密钥优先级：环境变量 > 本地 .env（生产用 systemd EnvironmentFile 注入）
- CORS 白名单：仅本站两条来源，不用通配
- 入参长度上限 + 同码结果缓存（省 LLM 额度、抗重复刷）
- 结论字段一律中性化：只给画像/评级，禁止任何买卖、持仓类表述
"""
import os, json, re, time, threading
import requests
from fastapi import FastAPI, HTTPException, Request
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
    # GitHub Pages 镜像站没有后端，前端直连云站 API（2026-10-19）
    'https://pineconexf.github.io',
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


# ---------- 同码结果缓存（分级 TTL） ----------
# 坑（2026-10-21 公网验收实测发现）：原来只有一个 10 分钟 TTL，
# 但下面几层注释都写着「日级缓存」—— 实际实现是 10 分钟，承诺与实现不符。
# 后果：10 分钟后 facts/research/industry/modules 全部重算，
# bundle 从 0.3s 掉回 30-40s（实测 688508 隔 73s 就掉到 41.85s）。
#
# 修法：每条目自带 TTL。
#   - ss3: payload（打分横截面）→ 日级：财报是季度更新，行情敏感性由
#     stockscore.universe() 的日级刷新承担；10 分钟 TTL 只是让用户每 10 分钟
#     白等 40s 重算，没有信息增益。
#   - ss3f:/ss3r:/ss3i:/ss3m:（facts/研报/行业/估值风险块）→ 24 小时：当日不变
# 需要强制刷新时打 /api/stockscore_v3_refresh（清该股全部缓存）。
_CACHE = {}
_CACHE_TTL = 600            # 默认 10 分钟
_CACHE_TTL_DAY = 86400      # 日级 24 小时

# 磁盘落盘缓存的版本护栏（2026-10-22）。
# payload / facts / modules 的结构或文案一变，必须 +1，
# 否则旧落盘文件会继续被当作有效缓存返回给用户。
_SS_PAYLOAD_VERSION = 3      # v3: payload 快照里的价格维度 label 去掉'松果FCF收益率''松果安全边际'品牌口径；v2: 删 groups.v35、tag 改中性、headline/tier_note 改「风险提示」
_SS_FACTS_VERSION = 2   # v2: facts 里的 dims label 去掉'松果FCF收益率'品牌口径
_SS_MODULES_VERSION = 2   # v2: '松果FCF收益率' → '自由现金流收益率(FCFF÷市值)'（去掉策略品牌口径，与前端口径一致）
_CACHE_MAX = 500
_CACHE_LOCK = threading.Lock()


def cache_get(code, ttl=None):
    """取缓存。ttl=None 用默认 10 分钟；ttl=_CACHE_TTL_DAY 取日级条目。"""
    with _CACHE_LOCK:
        item = _CACHE.get(code)
        if not item:
            return None
        ts, payload = item[0], item[1]
        eff_ttl = item[2] if len(item) > 2 else _CACHE_TTL
        if ttl is not None:
            eff_ttl = ttl
        if time.time() - ts > eff_ttl:
            _CACHE.pop(code, None)
            return None
        return payload


def cache_put(code, payload, ttl=None):
    """写缓存。ttl=_CACHE_TTL_DAY 表示当日不变的数据层。"""
    with _CACHE_LOCK:
        _CACHE[code] = (time.time(), payload, ttl or _CACHE_TTL)
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
        'roe': {'score': roe_s, 'max': 20, 'detail': f'近3年ROE最低 {roe_min:.1f}%', 'thresh': 'ROE 连续 3 年 >3%'},
        'profit': {'score': prof_s, 'max': 20, 'detail': f'近3年净利负值年数 {neg}/3', 'thresh': '连续盈利'},
        'pe': {'score': pe_s, 'max': 20, 'detail': f'PE(TTM) {pe:.1f}', 'thresh': '估值维度（FCF/EV待接入）'},
        'mv': {'score': mv_s, 'max': 20, 'detail': f'总市值 {mv:.0f}亿', 'thresh': '市值 ≤300 亿'},
        'growth': {'score': gr_s, 'max': 20, 'detail': f'净利同比 {yoy:.1f}%', 'thresh': '成长维度（牛市增强信号）'},
        'total': total, 'grade': grade
    }


PROMPT = """你是个股体检助手。请基于给定评分数据，输出一份专业的个股体检报告。

股票：{name}（{code}），现价 {price} 元，PE(TTM) {pe}，总市值 {mv} 亿，PB {pb}
总分：{total}/100，评级：{grade}

分项评分（各20分制）：
- 质量·ROE（{roe_score}分）：{roe_detail}
- 盈利持续性（{profit_score}分）：{profit_detail}
- 估值（{pe_score}分）：{pe_detail}
- 市值（{mv_score}分）：{mv_detail}
- 成长（{growth_score}分）：{growth_detail}

请输出 JSON：
{{
  "summary": "一句话定位（60字内，讲清楚这是一只什么风格的股票）",
  "style_analysis": "五维画像匹配分析（150字内：低估值+高质量+中小盘三个维度分别匹配度）",
  "strengths": ["优势1", "优势2", "优势3"],
  "risks": ["风险1", "风险2", "风险3"],
  "verdict": "画像定位（120字内：从五维评分说明该股的画像特征，如质量型 / 成长型 / 低估型 / 混合型，说明强项与短板各在哪个维度）",
  "action_hint": "画像归类（60字内：把该股归入「质量型 / 成长型 / 低估型 / 混合型」之一，并一句话说明依据）"
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


# ============================================================
# 个股打分卡（spec v1.0 六维，2026-10-03）—— 与旧体检并存、互不影响
# 引擎：backend/stockscore.py；缓存复用 10 分钟 TTL，键前缀 ss: 隔离
# ============================================================
import stockscore as _ss  # noqa: E402


def _cache_get_ss(code):
    return cache_get('ss:' + code)


def _cache_put_ss(code, payload):
    cache_put('ss:' + code, payload)


SS_PROMPT = """你是「松果投资体系」个股打分卡的报告生成器。以下是某只 A 股的六维打分卡结果（分数与口径，无任何交易建议信息）。

{facts}

请输出 JSON：
{{
  "summary": "一句话定位（60字内：这是一只什么特征的股票，从分数结构出发）",
  "profile_analysis": "分数归因（150字内：强项维为什么强、短板维为什么短，引用具体指标分位）",
  "strengths": ["优势1", "优势2", "优势3"],
  "risks": ["短板与风险1", "短板与风险2", "短板与风险3"],
  "verdict": "档位定位（120字内：结合季频基本面小计与日频交易小计的分化，说明当前分数主要由哪一侧驱动）",
  "caveats": ["数据口径限制/未纳入维度/低置信项的具体说明，逐条列出"]
}}

铁律（合规红线，逐条遵守）：
1. 只做档位定位、分数归因、短板说明。禁止出现买入、卖出、加仓、减仓、持有、建仓、清仓、目标价、涨跌预测、收益承诺、推荐 等任何词。
2. 禁止人格化/标签化称谓（如"超级牛股""陷阱股"）。
3. 未纳入(excluded)与低置信(low_confidence)的维度必须如实写进 caveats，不得掩盖。
4. 只依据给定数字，不得编造任何指标或事件。"""


def _build_ss_prompt(payload):
    facts = _ss.llm_report_input(payload)
    ex = '；'.join(f"{e['dim']}：{e['reason']}" for e in payload['excluded']) or '无'
    lc = '；'.join(f"{x['dim']}：{','.join(x['metrics_below_0.6']) or x['dim_confidence']}"
                   for x in payload['low_confidence']) or '无'
    facts += f"\n未纳入维度: {ex}\n低置信项: {lc}"
    return SS_PROMPT.format(facts=facts)


def _sanitize_llm_text(obj):
    """LLM 输出兜底扫描：命中禁词的句子整句丢弃，绝不带病返回（spec §6 铁律）。"""
    if isinstance(obj, str):
        return None if _ss.BANNED_RE.search(obj) else obj
    if isinstance(obj, list):
        out = []
        for x in obj:
            s = _sanitize_llm_text(x)
            if s is not None:
                out.append(s)
        return out
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            s = _sanitize_llm_text(v)
            if s is not None:
                out[k] = s
        return out
    return obj


@app.post('/api/stockscore')
def stockscore(req: Req):
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')

    cached = _cache_get_ss(code)
    if cached:
        return cached

    try:
        payload, status = _ss.compute_stock_score(code)
    except Exception as e:
        raise HTTPException(500, f'打分卡计算异常: {type(e).__name__}: {e}')
    if payload is None:
        raise HTTPException(404, '未获取到该股票数据，请核对代码')

    # LLM 画像：失败不阻断（打分本体是确定性规则，可独立成立）
    # _call_llm 内部 3 连发无退避，DeepSeek 突发限流时会全灭；这里再补一轮长退避重试
    report = None
    for round_i in range(2):
        try:
            report = _sanitize_llm_text(_call_llm(_build_ss_prompt(payload)))
            break
        except HTTPException:
            if round_i == 0:
                time.sleep(20)
    if isinstance(report, dict) and report:
        payload['report'] = report
    else:
        payload['report'] = {'summary': None,
                             'caveats': ['AI 画像生成失败或含违规表述，已拦截；分数本体不受影响']}
    payload['report']['input_mode'] = '仅分数与口径，无买卖倾向词'
    _cache_put_ss(code, payload)
    return payload


@app.on_event('startup')
def _ss_warmup():
    """启动预热日级横截面宇宙（避免首个请求等 30s）。失败静默，请求路径会自愈重试。"""
    _ss.warmup_async()


# ============================================================
# 个股打分卡 V3（2026-10-18）：3 组 8 维 / 闸门 / 松果可投性 / 四页
# 引擎 backend/stockscore_v3.py，复用 V1 的数据层与日级横截面宇宙。
# 解说文本为确定性规则生成（非 LLM），保证可复现、无合规词风险。
# ============================================================
import stockscore_v3 as _ss3  # noqa: E402
import stockscore_resolve as _ssr  # noqa: E402


@app.get('/api/stockscore_resolve')
def stockscore_resolve(q: str = ''):
    """股票代码/名称 → 候选代码。供打分卡输入框使用（名称模糊匹配，三源合并）。"""
    try:
        return _ssr.resolve(q)
    except Exception as e:
        raise HTTPException(500, f'解析异常: {type(e).__name__}: {e}')


@app.post('/api/stockscore_v3')
def stockscore_v3(req: Req):
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')

    cached = cache_get('ss3:' + code, ttl=_CACHE_TTL_DAY)
    if cached:
        return cached

    try:
        payload, status = _ss3.compute_v3(code)
    except Exception as e:
        raise HTTPException(500, f'V3 打分异常: {type(e).__name__}: {e}')
    if payload is None:
        raise HTTPException(404, '未获取到该股票数据，请核对代码')

    cache_put('ss3:' + code, payload, ttl=_CACHE_TTL_DAY)
    return payload


# ---------- 白话解读（LLM 只解释分数，不产生分数）----------
import stockscore_narrative as _ssn  # noqa: E402


@app.post('/api/stockscore_v3_narrative')
def stockscore_v3_narrative(req: Req):
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')

    payload = cache_get('ss3:' + code, ttl=_CACHE_TTL_DAY)
    if not payload:
        payload, _ = _ss3.compute_v3(code)
        if payload is None:
            raise HTTPException(404, '未获取到该股票数据，请核对代码')
        cache_put('ss3:' + code, payload, ttl=_CACHE_TTL_DAY)

    try:
        return _ssn.get_or_build(payload, DS_KEY)
    except Exception as e:
        raise HTTPException(503, f'解读生成失败: {type(e).__name__}: {e}')


# ---------- 深度分析 + 元宝总结版（2026-10-20）----------
# 链路：外部深度数据自动补漏（研报抽取）→ 估值与预期/风险与安全确定性计算
#       → 六段深度分析（逐段生成+数字回验+矛盾检测+critic）→ 元宝口播总结版
import stockscore_research as _ssres  # noqa: E402
import stockscore_modules as _ssmod  # noqa: E402
import stockscore_deep as _ssdeep  # noqa: E402
import stockscore_summary as _sssum  # noqa: E402
import stockscore_job as _ssjob  # noqa: E402
import stockscore_persist as _sspersist  # noqa: E402


def _ss_deep_inputs(code, timing=None):
    """把深度分析需要的全部输入一次性备齐（供 deep / prewarm / progress 复用）。

    坑（2026-10-20 修）：之前 4 个端点（modules/deep/summary/talk）
    各自算 coverage，其中只有 deep 传了 industry_raw，另外三处没传。
    结果同一只票在「深度」页显示 A 级、在「模块」和「口播」页显示 B 级——
    页面之间自相矛盾。coverage 是全局口径，必须一处算、处处用。

    这里统一返回 (payload, fk, research, industry_raw, industry_facts, cov)。

    2026-10-21：加 timing 埋点。坑（实测）：首次调用要 60s+ 才出首段，
    但不知道慢在哪一段 —— 研报抓取？行业结构？v3 全市场横截面？
    分段计时才能对症。
    """
    _tim = timing if isinstance(timing, dict) else {}
    _t = time.time()
    payload, fk = _ss_core(code)
    _tim['core_v3'] = round(time.time() - _t, 1)
    _t = time.time()
    research = {}
    try:
        research = _ssres.get_research(code, time.strftime('%Y%m%d'), DS_KEY)
    except Exception:
        research = {}
    _tim['research'] = round(time.time() - _t, 1)
    _t = time.time()
    industry_raw = None
    industry_facts = []
    try:
        import stockscore_industry as _ssind
        industry_raw = _ssind.get_industry(code)
        industry_facts = _ssind.facts_for_writer(industry_raw)
    except Exception:
        industry_raw = {'error': '行业结构数据层不可得'}
    _tim['industry'] = round(time.time() - _t, 1)
    cov = _ssres.coverage_level(research, industry_raw)
    return payload, fk, research, industry_raw, industry_facts, cov


def _ss_run_deep(code, payload, fk, research, cov):
    """跑一次深度分析（同步）。用模块/风险 facts 一起喂进去。"""
    vb = _ssmod.build_valuation_block(code, research=research)
    kb = _ssmod.build_risk_block(code, research=research)
    return _ssdeep.get_or_build(
        code, payload.get('name', code),
        [fk.get('facts') or [], vb['facts'], kb['facts']],
        research, payload=payload, key=DS_KEY, coverage=cov)


def _ss_industry(code):
    """取行业结构数据（raw, facts_for_writer）。日级缓存。

    坑（2026-10-21 实测）：行业结构要拉申万成分股实算，是重活；
    但它**当日不变**，所以缓存住，别让 bundle 和预热各算一遍。
    """
    raw = cache_get('ss3i:' + code, ttl=_CACHE_TTL_DAY)
    facts = []
    if not raw:
        try:
            import stockscore_industry as _ssind
            raw = _ssind.get_industry(code)
            facts = _ssind.facts_for_writer(raw)
        except Exception:
            raw = {'error': '行业结构数据层不可得'}
        cache_put('ss3i:' + code, raw, ttl=_CACHE_TTL_DAY)
    else:
        try:
            import stockscore_industry as _ssind
            facts = _ssind.facts_for_writer(raw)
        except Exception:
            facts = []
    return raw, facts


def _ss_research(code):
    """取研报抽取结果。日级缓存。"""
    research = cache_get('ss3r:' + code, ttl=_CACHE_TTL_DAY)
    if not research:
        try:
            research = _ssres.get_research(code, time.strftime('%Y%m%d'), DS_KEY)
        except Exception:
            research = {}
        cache_put('ss3r:' + code, research, ttl=_CACHE_TTL_DAY)
    return research


def _ss_modules(code, research):
    """取估值块 + 风险块。日级缓存（确定性结果，当天算一次）。"""
    mods = cache_get('ss3m:' + code, ttl=_CACHE_TTL_DAY)
    if not mods:
        mods = _sspersist.get('ss3m_' + code, version=_SS_MODULES_VERSION)
    if not mods:
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=2) as _pool:
            _f_vb = _pool.submit(_ssmod.build_valuation_block, code, research=research)
            _f_kb = _pool.submit(_ssmod.build_risk_block, code, research=research)
            vb = _f_vb.result()
            kb = _f_kb.result()
        # 出口闸门：确定性层的文字也要过禁词（见 _ss_banned_guard 说明）
        _ss_banned_guard(vb)
        _ss_banned_guard(kb)
        mods = {'vb': vb, 'kb': kb}
        cache_put('ss3m:' + code, mods, ttl=_CACHE_TTL_DAY)
        _sspersist.put('ss3m_' + code, mods, version=_SS_MODULES_VERSION)
    else:
        vb, kb = mods['vb'], mods['kb']
    return vb, kb


# 变相目标价/涨跌预测的出口闸门。
# 坑（2026-10-21 公网验收实测发现）：LLM 层的禁词闸门很严，
# 但**确定性事实层**（估值块/风险块，规则生成不经 LLM）没人管 ——
# 于是「下行空间 67.3%」「回归中位空间 27.1%」这种变相目标价直接上了页面。
# 光靠逐点改代码会漏（下次加新 fact 又冒出来），所以在出口统一拦一道。
# 判定口径：出现"空间/上涨/下行" + 数字百分比 → 判为变相预测，丢弃整条。
_BANNED_PREDICT_FACT = re.compile(
    r'(下行|上行|上涨|下跌|反弹|回撤)?\s*空间\s*(约|大概|为)?\s*\d|'
    r'对应\s*\d+(\.\d+)?\s*%\s*(的)?\s*(上涨|下行|上行|涨幅|跌幅|空间)|'
    r'(上涨|下行|上行)\s*空间\s*(约|大概|为)?\s*\d|'
    r'目标价|合理价位|估值区间|预期回报')


def _ss_banned_guard(block):
    """在确定性层出口扫变相目标价，命中就丢弃该条 fact（不静默改写）。

    为什么不静默改写：改写会生成"看似合规实则仍倒算幅度"的句子，
    比如把"下行空间 67.3%"改成"下行空间较小"——照样是价格预测。
    直接丢掉这条事实，让页面少一条，而不是多一条假合规。
    """
    if not isinstance(block, dict):
        return
    facts = block.get('facts') or []
    keep = []
    for f in facts:
        blob = '%s %s' % (f.get('label') or '', f.get('text') or '')
        if _BANNED_PREDICT_FACT.search(blob):
            continue
        keep.append(f)
    block['facts'] = keep


def _verdict_overall(total, tier, groups):
    """总览页的"总体描述评价结果"。

    2026-10-22 新增。用户在总览页要三块：分数总览 / 总体描述评价结果 /
    打分卡结构特点。第二块不能只是"总分 65，中等"—— 还得说清强在哪、弱在哪。

    严格约束：只描述质地本身；不给买卖建议、不给目标价、不给涨跌预测、
    不出现可投域/域内域外这类选股结论。
    """
    if total is None:
        return '打分卡数据暂缺，暂时给不出总体评价。'
    sc = round(float(total), 1)
    if sc >= 80:
        lv = '很强'
    elif sc >= 65:
        lv = '较强'
    elif sc >= 45:
        lv = '中等'
    else:
        lv = '偏弱'
    parts = ['综合打分 %s 分，%s。' % (sc, lv)]
    avail = [(k, g) for k, g in (groups or {}).items()
             if isinstance(g, dict) and g.get('score') is not None]
    if not avail:
        parts.append('但细分维度数据暂缺，明细页可查。')
        return ''.join(parts)
    strong_k, strong_g = max(avail, key=lambda x: x[1].get('score') or 0)
    weak_k, weak_g = min(avail, key=lambda x: x[1].get('score') or 0)
    name_map = {'Q': '质地', 'V': '价格', 'M': '势能'}
    sn = name_map.get(strong_k, strong_g.get('label') or strong_k)
    wn = name_map.get(weak_k, weak_g.get('label') or weak_k)
    if strong_k != weak_k:
        parts.append('强在%s（%s 分），弱在%s（%s 分）。'
                     % (sn, round(float(strong_g.get('score')), 1),
                        wn, round(float(weak_g.get('score')), 1)))
    else:
        parts.append('三个切面表现比较均衡。')
    parts.append('这是按打分卡算出的质地水平，不构成买卖建议。')
    return ''.join(parts)


def _mval(val, unit=''):
    """指标值的展示格式化：按单位决定小数位，并把金额统一到亿元。

    坑：metric 的 value 是 round(value, 4) 出来的，直接拼出来是
    "-11.3955%" / "-1.3774亿元" 这种没人愿意读的数字。
    """
    if val is None:
        return '—'
    try:
        f = float(val)
    except (TypeError, ValueError):
        return str(val)
    u = (unit or '').strip()
    if u in ('%', 'pct', '％'):
        nd = 2 if abs(f) < 100 else 1
        return ('%.' + str(nd) + 'f') % f + '%'
    if u in ('亿元', '亿'):
        return ('%.2f' % f).rstrip('0').rstrip('.') + ' 亿元'
    if u in ('万元', '万'):
        # 统一亿元口径，小额保留 4 位小数，不回落万元
        yi = f / 1e4
        if abs(yi) >= 0.01:
            return ('%.2f' % yi).rstrip('0').rstrip('.') + ' 亿元'
        return ('%.4f' % yi).rstrip('0').rstrip('.') + ' 亿元'
    if u == '元':
        yi = f / 1e8
        if abs(yi) >= 0.01:
            return ('%.2f' % yi).rstrip('0').rstrip('.') + ' 亿元'
        return ('%.4f' % yi).rstrip('0').rstrip('.') + ' 亿元'
    if u in ('分', '倍', 'x', 'X'):
        nd = 2 if abs(f) < 100 else 1
        txt = (('%.' + str(nd) + 'f') % f).rstrip('0').rstrip('.')
        if txt in ('', '-0'):
            txt = '0'
        return txt + ' ' + u
    if abs(f) < 100:
        return ('%.2f' % f).rstrip('0').rstrip('.')
    return ('%.0f' % f)


# ── 金额单位收口 ───────────────────────────────────────────────────────────
# v3 页面里的文字（风险 flags/facts、闸门说明、总体评价）里混着万元口径，
# 而深度正文早就是亿元了 —— 同一页面上"8.55 亿元"和"85,513.23 万"并存，
# 用户读起来是两种货币。所以在 api 返回前统一收口一次。
# 只动字符串字段，不动 metrics 的 value/unit（那是数值列，交给前端渲染）。
import re as _re

# 注意：排除字符集里不能有"元"。"85,623.26 万元"里的"万元"正是要转的目标，
# 把"元"列进排除会让整条正则永远不匹配。
_AMT_WAN_RE = _re.compile(r'(?P<num>-?\d[\d,，]*(?:\.\d+)?)\s*万(?![亿股人份户家次批名])')


def _amt_to_yi_text(m):
    """万元字符串 → 亿元字符串。统一亿元口径（小额保留 4 位小数，不回落万元）。"""
    try:
        v = float(m.group('num').replace(',', '').replace('，', ''))
    except ValueError:
        return m.group(0)
    yi = v / 1.0e4
    nd = 2 if abs(yi) >= 0.01 else 4
    txt = ('%.*f' % (nd, yi)).rstrip('0').rstrip('.')
    if txt in ('', '-0'):
        txt = '0'
    return txt + ' 亿元'


def _money_in_text(t):
    if not isinstance(t, str) or '万' not in t:
        return t
    return _AMT_WAN_RE.sub(_amt_to_yi_text, t)


def _money_in_obj(o):
    """递归把 payload 里字符串字段中的"万元"换成"亿元"。"""
    if isinstance(o, str):
        return _money_in_text(o)
    if isinstance(o, list):
        return [_money_in_obj(x) for x in o]
    if isinstance(o, dict):
        return {k: _money_in_obj(v) for k, v in o.items()}
    return o


def _verdict_risk(gate, flags, gaps):
    """风险与安全维度的总体评价。

    2026-10-22 新增。风险维度没有分数（它不是打分维度，是一组客观事实），
    所以 _verdict 只能吐"数据暂缺，给不出总体评价"—— 用户看到这句是坏体验。
    改成用风险项/关注项/缺口条数给一条具体判断。

    2026-10-22 再改：原文用"红旗/黄旗"，那是策略内部标记口径，
    改为"风险项/关注项"，口径不变，只换用户可见的说法。
    """
    red = gate.get('red') or []
    yel = gate.get('yellow') or []
    parts = []
    if red:
        parts.append('命中 %d 条风险项（%s），属于需要先弄清楚再谈别的类型。'
                     % (len(red), '、'.join(str(x) for x in red[:3])))
    elif yel:
        parts.append('没有硬性风险项，但有 %d 条关注项——不算硬伤，属于要跟踪的瑕疵。' % len(yel))
    else:
        parts.append('没有命中风险项或关注项，风险面上暂时挑不出明显硬伤。')
    hard = [f for f in flags if str(f.get('level') or '') in ('high', '高')]
    if hard:
        parts.append('已兑现风险里有 %d 条偏高强度，值得单独看。' % len(hard))
    if gaps:
        parts.append('另有 %d 处数据缺口，相关结论要打个折扣看。' % len(gaps))
    else:
        parts.append('关键数据基本齐，判断依据比较完整。')
    return ''.join(parts)


def _verdict(key, title, dims, group):
    """生成某模块的"总体评价"：分数档位 + 一句判断 + 最关键短板。

    2026-10-22 新增。用户诉求是"先看分数及总体评价，再看具体深度分析"，
    所以需要一条结论式的句子，而不是原来 headline 那种维度分数罗列。

    严格约束：
      - 只描述质地/价格/势能本身，不给投资建议、不给买卖倾向
      - 不出现目标价、涨跌预测、可投域判断
      - 数据不足时如实说"该维数据暂缺"，不硬凑
    """
    sc = group.get('score')
    if sc is None:
        return '%s维度数据暂缺，暂时给不出总体评价。' % title
    sc = round(float(sc), 1)
    # 档位判断（纯分数语义，不涉及投资策略）
    if sc >= 80:
        lv = '很强'
    elif sc >= 65:
        lv = '较强'
    elif sc >= 45:
        lv = '中等'
    else:
        lv = '偏弱'
    avail = [d for d in (dims or []) if d.get('score') is not None]
    if not avail:
        return '%s %s 分（%s），但支撑该分数的明细数据暂缺。' % (title, sc, lv)
    strong = max(avail, key=lambda d: d.get('score') or 0)
    weak = min(avail, key=lambda d: d.get('score') or 0)
    parts = ['%s %s 分，%s。' % (title, sc, lv)]
    if len(avail) == 1:
        # 坑：只有一个可用维度时 strong 和 weak 必然是同一个，
        # 老逻辑会走"各项表现比较均衡"分支 —— 17 分也说均衡，是错的。
        # 2026-10-22：措辞改具体。"只有一项明细"读者不知道指什么，
        # 现在明确说清是"一个子维度"、以及为什么强弱对比无意义。
        sub = weak.get('label') or weak.get('name') or ''
        if sub:
            parts.append('这一档目前只有一个子维度（%s），还没有更多子维度可以横向比较。' % sub)
        else:
            parts.append('这一档目前只有一个子维度，还没有更多子维度可以横向比较。')
    elif strong.get('label') and weak.get('label') and strong.get('key') != weak.get('key'):
        parts.append('强在%s（%s 分），弱在%s（%s 分）。'
                     % (strong.get('label'), round(float(strong.get('score')), 1),
                        weak.get('label'), round(float(weak.get('score')), 1)))
    else:
        parts.append('各项表现比较均衡。')
    # 短板补充：取短板维度里 contrib 最低的那个指标。
    # 坑：metric 的字段是 name/value/unit/contrib，不是 label/score ——
    # contrib 才是该指标实际贡献的分（pctl 方向已按 direction 折算），
    # 拿 pctl 直接比会把"越低越好"的指标（毛利率波动等）判反。
    try:
        wm = [m for m in (weak.get('metrics') or []) if m.get('contrib') is not None]
        if wm:
            m0 = min(wm, key=lambda m: m.get('contrib') or 0)
            if m0.get('name'):
                val = m0.get('value')
                unit = m0.get('unit') or ''
                if val is not None:
                    u = (unit or '').strip()
                    if u == '分':
                        # 分数类指标写成"（得分 0.0）"，避免"0.00 分"这种
                        # 读起来像计算错误的写法
                        parts.append('关键短板在%s（得分 %s）。'
                                     % (m0.get('name'),
                                        ('%.1f' % float(val)).rstrip('0').rstrip('.')
                                        or '0'))
                    elif u in ('倍', 'x', 'X', '%', 'pct', '％'):
                        parts.append('关键短板在%s（%s）。'
                                     % (m0.get('name'), _mval(val, unit)))
                    else:
                        parts.append('关键短板在%s：%s。'
                                     % (m0.get('name'), _mval(val, unit)))
                else:
                    parts.append('关键短板在%s（数据暂缺）。' % m0.get('name'))
    except Exception:
        pass
    return ''.join(parts)


def _ss_start_deep_job(code, force=False):
    """启动后台深度分析作业（去重）。返回是否由本次调用启动。"""
    if not force and _ssdeep.get_cached(code) is not None:
        return False
    if not _ssjob.claim(code):
        return False

    def _worker():
        try:
            _tim = {}
            _t = time.time()
            # 坑（2026-10-21 实测）：前置几件事（v3 payload / facts / research /
            # industry / modules）合计 22-68s，六段并行只要 4.5s。
            # 所以「首段 8-10 秒可见」的前提是**前置已完成**。
            # 修法：
            # ① 走 bundle 的同一套日级缓存（facts/research/industry/modules），
            #    预热线程不重复算；
            # ② 互不依赖的块并行算；
            # ③ 总览页先调 bundle（v3 payload 进 10 分钟内存缓存），预热时 v3 秒回。
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=3) as _pool:
                _f_core = _pool.submit(_ss_core, code)
                _f_res = _pool.submit(_ss_research, code)
                _f_ind = _pool.submit(_ss_industry, code)
                payload, fk = _f_core.result()
                research = _f_res.result() or {}
                industry_raw, industry_facts = _f_ind.result()
            _tim['core_and_sources'] = round(time.time() - _t, 1)
            _t = time.time()
            cov = _ssres.coverage_level(research, industry_raw)
            vb, kb = _ss_modules(code, research)
            _tim['modules'] = round(time.time() - _t, 1)
            final = _ssdeep.get_or_build(
                code, payload.get('name', code),
                [fk.get('facts') or [], vb['facts'], kb['facts']],
                research, payload=payload, key=DS_KEY, coverage=cov,
                on_section=lambda s: _ssjob.publish_section(code, s),
                timing=_tim,
                industry_raw=industry_raw, industry_facts=industry_facts)
            _tim['total'] = round(time.time() - _t, 1)
            _ssjob.finish(code, final=final, coverage=cov, meta={'timing': _tim})
        except Exception as e:                       # noqa: BLE001
            _ssjob.finish(code, error='%s: %s' % (type(e).__name__, e))

    t = threading.Thread(target=_worker, daemon=True,
                         name='deep-%s' % code)
    t.start()
    return True


def _ss_core(code):
    """取 v3 payload + facts（内存缓存 → 磁盘日级缓存 → 现算）。"""
    payload = cache_get('ss3:' + code, ttl=_CACHE_TTL_DAY)
    if not payload:
        # 2026-10-22：加磁盘层。生产 uvicorn 重启后内存缓存全丢，
        # 冷启动 compute_v3(29s)+build_facts(10s)=39s 卡在正文生成之前，
        # 首段被推到 40s。落盘后重启即命中。
        # 版本护栏：payload 结构一变（如删字段/改文案），旧落盘文件
        # 必须失效，否则旧结构的缓存会继续吐给用户。
        payload = _sspersist.get('ss3_' + code, version=_SS_PAYLOAD_VERSION)
    if not payload:
        payload, _ = _ss3.compute_v3(code)
        if payload is None:
            raise HTTPException(404, '未获取到该股票数据，请核对代码')
        cache_put('ss3:' + code, payload, ttl=_CACHE_TTL_DAY)
        _sspersist.put('ss3_' + code, payload, version=_SS_PAYLOAD_VERSION)
    import stockscore_facts as _ssf
    # 坑（2026-10-21 实测）：build_facts 要 9.5s（拉 F10 财务多期），
    # 但 facts 是**当日不变**的静态事实层 —— 用日级缓存，
    # 避免预热、bundle、deep 三条线各算一遍。
    fk = cache_get('ss3f:' + code, ttl=_CACHE_TTL_DAY)
    if not fk:
        fk = _sspersist.get('ss3f_' + code, version=_SS_FACTS_VERSION)
    if not fk:
        fk = _ssf.build_facts(code)
        cache_put('ss3f:' + code, fk, ttl=_CACHE_TTL_DAY)
        _sspersist.put('ss3f_' + code, fk, version=_SS_FACTS_VERSION)
    return payload, fk


def _ss_context(code):
    """一次性取齐 4 个数据源 + 统一 coverage 口径。

    坑（2026-10-20 修）：之前 4 个端点（modules/deep/summary/talk）
    各自算 coverage，其中只有 deep 传了 industry_raw，另外三处没传。
    结果同一只票在「深度」页显示 A 级、在「模块」和「口播」页显示 B 级——
    页面之间自相矛盾。coverage 是全局口径，必须一处算、处处用。

    这里统一返回 (payload, fk, research, industry_raw, industry_facts, cov)。
    """
    payload, fk = _ss_core(code)
    research = {}
    try:
        research = _ssres.get_research(code, time.strftime('%Y%m%d'), DS_KEY)
    except Exception:
        research = {}
    industry_raw = None
    industry_facts = []
    try:
        import stockscore_industry as _ssind
        industry_raw = _ssind.get_industry(code)
        industry_facts = _ssind.facts_for_writer(industry_raw)
    except Exception:
        industry_raw = {'error': '行业结构数据层不可得'}
    cov = _ssres.coverage_level(research, industry_raw)
    return payload, fk, research, industry_raw, industry_facts, cov


@app.post('/api/stockscore_v3_research')
def stockscore_v3_research(req: Req):
    """外部深度数据自动补漏：抓研报 → 抽取 → 回验 → coverage 分级。"""
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    try:
        return _ssres.get_research(code, time.strftime('%Y%m%d'), DS_KEY)
    except Exception as e:
        raise HTTPException(503, f'外部数据抓取失败: {type(e).__name__}: {e}')


@app.post('/api/stockscore_v3_modules')
def stockscore_v3_modules(req: Req):
    """估值与预期 + 风险与安全：纯确定性计算，不含 LLM。"""
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    payload, fk, research, industry_raw, industry_facts, cov = _ss_context(code)
    vb = _ssmod.build_valuation_block(code, research=research)
    kb = _ssmod.build_risk_block(code, research=research)
    return {
        'code': code,
        'name': payload.get('name', code),
        'total': payload.get('total'),
        'tier': payload.get('tier'),
        'valuation': {'facts': vb['facts'], 'gaps': vb['gaps']},
        'risk': {'facts': kb['facts'], 'flags': kb['flags'], 'gaps': kb['gaps']},
        'coverage': cov,
    }


@app.post('/api/stockscore_v3_deep')
def stockscore_v3_deep(req: Req):
    """六段深度分析：逐段生成 + 数字回验 + 矛盾清单 + critic。

    2026-10-21：改为走作业态。
    - 若后台已有作业在跑（总览页预热过），直接返回缓存结果；
    - 否则同步跑一次（保持旧语义，前端可继续用这个端点）。
    新前端优先用 /api/stockscore_v3_deep_progress（轮询，首段先出）。
    """
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    cached = _ssdeep.get_cached(code)
    if cached is not None:
        return cached
    payload, fk, research, industry_raw, industry_facts, cov = _ss_context(code)
    vb = _ssmod.build_valuation_block(code, research=research)
    kb = _ssmod.build_risk_block(code, research=research)
    try:
        return _ssdeep.get_or_build(
            code, payload.get('name', code),
            [fk.get('facts') or [], vb['facts'], kb['facts']],
            research, payload=payload, key=DS_KEY, coverage=cov)
    except Exception as e:
        raise HTTPException(503, f'深度分析生成失败: {type(e).__name__}: {e}')


@app.post('/api/stockscore_v3_deep_prewarm')
def stockscore_v3_deep_prewarm(req: Req):
    """总览页后台预热：启动深度分析作业，不等结果。

    坑（2026-10-21 实测）：用户从总览点进深度页时，若深度分析还没生成，
    要等 60-90 秒。总览页加载时就调这个端点把活干起来，
    用户点进深度页时多数已经命中缓存 → 近 0 秒读出。

    重复调用是幂等的：已有作业在跑就直接返回 running，已有缓存直接返回 cached。
    """
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    if _ssdeep.get_cached(code) is not None:
        return {'code': code, 'state': 'cached'}
    started = _ss_start_deep_job(code)
    snap = _ssjob.get(code)
    return {'code': code,
            'state': (snap or {}).get('state', 'running'),
            'started': started}


@app.post('/api/stockscore_v3_deep_progress')
def stockscore_v3_deep_progress(req: Req):
    """轮询深度分析进度：已完成的段落逐段返回（首段 8-10 秒即可见）。

    返回 {state, sections[], total_chars, elapsed, coverage, cached}。
    state: running | done | error | idle
    - idle  : 从未生成过（前端应先调 prewarm 或让本端点触发）
    - running: 正在生成，sections 里是已完成的段落
    - done   : 全文完成，sections 是最终正文
    """
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    snap = _ssjob.get(code)
    if snap is None:
        cached = _ssdeep.get_cached(code)
        if cached is not None:
            return {
                'code': code, 'state': 'done', 'elapsed': 0,
                'sections': cached.get('sections') or [],
                'total_chars': cached.get('total_chars') or 0,
                'coverage': cached.get('coverage'),
                'meta': {
                    'contradictions': cached.get('contradictions') or [],
                    'critic': cached.get('critic') or {},
                    'rewrite_rounds': cached.get('rewrite_rounds') or 0,
                    'unresolved': cached.get('unresolved') or [],
                    'structure_issues': cached.get('structure_issues') or [],
                    'unverified_numbers': cached.get('unverified_numbers') or [],
                    'research_reports': cached.get('research_reports') or 0,
                    'coverage_note': cached.get('coverage_note') or '',
                    'industry': cached.get('industry'),
                },
                'cached': True,
            }
        # 没人预热过 → 顺手启动一份，前端下一轮轮询就有内容了
        _ss_start_deep_job(code)
        return {'code': code, 'state': 'running', 'elapsed': 0,
                'sections': [], 'total_chars': 0, 'coverage': None,
                'meta': {}, 'cached': False}
    out = {
        'code': code, 'state': snap['state'], 'elapsed': snap['elapsed'],
        'sections': snap['sections'], 'total_chars': snap['total_chars'],
        'coverage': snap['coverage'], 'meta': snap['meta'],
        'error': snap['error'], 'cached': False,
    }
    if snap['state'] == 'done':
        cached = _ssdeep.get_cached(code)
        if cached:
            out['sections'] = cached.get('sections') or out['sections']
            out['total_chars'] = cached.get('total_chars') or out['total_chars']
            out['meta'] = {
                'contradictions': cached.get('contradictions') or [],
                'critic': cached.get('critic') or {},
                'rewrite_rounds': cached.get('rewrite_rounds') or 0,
                'unresolved': cached.get('unresolved') or [],
                'structure_issues': cached.get('structure_issues') or [],
                'unverified_numbers': cached.get('unverified_numbers') or [],
                'research_reports': cached.get('research_reports') or 0,
                'coverage_note': cached.get('coverage_note') or '',
                'industry': cached.get('industry'),
            }
            out['cached'] = True
    return out


@app.post('/api/stockscore_v3_refresh')
def stockscore_v3_refresh(req: Req):
    """强制刷新某只股票的全部缓存（payload/facts/研报/行业/估值风险块）。

    坑（2026-10-21）：改成日级缓存后，数据更新（换季财报、新研报、
    行业成分调整）不会自动生效 —— 必须有显式刷新入口，否则会出现
    「代码改了线上还是旧数」的困局。
    """
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    cleared = []
    with _CACHE_LOCK:
        for k in list(_CACHE.keys()):
            if k.endswith(':' + code) or k == code:
                _CACHE.pop(k, None)
                cleared.append(k)
    try:
        import stockscore_deep as _ssd
        _ssd.invalidate(code)
        cleared.append('deep')
    except Exception:
        pass
    return {'code': code, 'cleared': cleared, 'count': len(cleared)}


@app.post('/api/stockscore_v3_bundle')
def stockscore_v3_bundle(req: Req):
    """统一数据契约：一次返回总览 + 4 个深度分页所需的全部数据。

    2026-10-21 新增。为什么要它：
    之前 PC 端要打 4 个端点（v3 / modules / deep / summary），
    微信端、小程序、APP 各写一套拼装逻辑，模块边界必然走形。
    bundle 把「一个总览页 + 4 个深度分页」的模块边界固化在服务端：
      overview  —— 总览页：快速判断、核心摘要、关键风险、一句话结论
      quality   —— 质地：Q 组四维 + 业务结构/差异化壁垒两段深度
      price     —— 价格：V 组 + 数字检验/估值与预期两段深度
      momentum  —— 势能：M 组 + 市场空间段深度
      risk      —— 风险：风险与安全段 + 红旗 + 关键矛盾 + 审读意见
    四端拿同一份 JSON，渲染层各自决定长什么样。

    deep 正文只取已缓存的（get_cached），不触发生成 ——
    预热由 /api/stockscore_v3_deep_prewarm 负责，总览页会调。

    坑（2026-10-21 实测）：第一版 bundle 要 58.6s，因为
    facts(9.5s) + modules(12.6s) + industry + research 全串行算，
    而其中 facts/research/industry/modules 都是**当日不变**的确定性数据。
    现在：facts 走日级缓存；research/industry/modules 走日级缓存；
    且 research 与 modules 互不依赖，并行算。
    """
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    payload, fk = _ss_core(code)
    # 日级缓存：确定性层当天算一次就够（facts/research/industry/modules）
    research = _ss_research(code)
    industry_raw, industry_facts = _ss_industry(code)
    cov = _ssres.coverage_level(research, industry_raw)
    vb, kb = _ss_modules(code, research)
    deep = _ssdeep.get_cached(code)

    def _sec(key):
        if not deep:
            return []
        return [s for s in (deep.get('sections') or []) if s.get('key') == key]

    dims_by_key = {d['key']: d for d in (payload.get('dims') or [])}
    groups = payload.get('groups') or {}
    pages = payload.get('pages') or {}
    gate = payload.get('gate') or {}

    def _dim_block(keys):
        return [dims_by_key[k] for k in keys if k in dims_by_key]

    Q_KEYS = ['profit_quality', 'core_competence', 'growth', 'financial_health']
    V_KEYS = ['valuation']
    M_KEYS = ['earnings_revision']

    # 关键风险：红旗 + 黄旗 + 风险模块的 flag，合并去重
    key_risks = []
    for r in (gate.get('red') or []):
        key_risks.append({'level': 'red', 'text': r})
    for r in (gate.get('yellow') or []):
        key_risks.append({'level': 'yellow', 'text': r})
    for f in (kb.get('flags') or []):
        # 坑：flags 的 text 本身常常已经带了 label 前缀
        # （"盈利质量：当前 -1.07倍（阈值 0.60倍…）"），
        # 无脑拼一下会变成"盈利质量：盈利质量：当前…"。
        _lb = (f.get('label') or '已兑现风险').strip()
        _tx = (f.get('text') or '').strip()
        if _tx.startswith(_lb):
            _tx = _tx[len(_lb):].lstrip('：: ')
        key_risks.append({'level': 'flag', 'text': '%s：%s' % (_lb, _tx)})

    overview = {
        'total': payload.get('total'),
        'total_raw': payload.get('total_raw'),
        'tier': payload.get('tier'),
        'tier_note': payload.get('tier_note'),
        # 2026-10-22：去掉松果投资策略的选股最终影响。
        # tag（可投域：域内候选/域外优质/红旗不碰）和 investable_checks
        # （可投性11步）都是"选不选它"的结论，不属于"这只股票质地如何"的范畴，
        # 这里不再下发到前端。保留 groups/gate/key_risks 这些客观事实层。
        'groups': groups,
        'gate': gate,
        'key_risks': key_risks,
        'one_liner': _verdict_overall(payload.get('total'), payload.get('tier'), groups),
        'headline': (pages.get('overview') or {}).get('headline') or '',
        'coverage': cov,
    }

    def _mod(key, title, dim_keys, sec_keys, page_key, extra=None):
        page = pages.get(page_key) or {}
        m = {
            'key': key,
            'title': title,
            'score': (groups.get({'quality': 'Q', 'price': 'V',
                                   'momentum': 'M'}.get(key, '')) or {}).get('score'),
            'headline': page.get('headline') or '',
            # 2026-10-22：总体评价（结论式）。原来只有 headline（维度分数罗列），
            # 用户要的是"先是分数及总体评价，其次才是具体深度分析"，
            # 所以这里补一条带判断和短板的结论句。
            'verdict': _verdict(key, title, m_dims := _dim_block(dim_keys),
                                (groups.get({'quality': 'Q', 'price': 'V',
                                             'momentum': 'M'}.get(key, '')) or {})),
            'blocks': page.get('blocks') or [],
            'dims': m_dims,
            'sections': [s for sk in sec_keys for s in _sec(sk)],
            'section_keys': sec_keys,
            'coverage': cov,
        }
        if extra:
            m.update(extra)
        return m

    modules = {
        'quality': _mod('quality', '质地', Q_KEYS, ['business', 'moat'], 'quality'),
        'price': _mod('price', '价格', V_KEYS, ['numbers', 'valuation'], 'price',
                      extra={'valuation_facts': vb.get('facts') or [],
                             'valuation_gaps': vb.get('gaps') or []}),
        'momentum': _mod('momentum', '势能', M_KEYS, [], 'momentum'),
        'risk': _mod('risk', '风险与安全', [], ['risk'], 'overview',
                     extra={'verdict': _verdict_risk(gate, kb.get('flags') or [],
                                                     kb.get('gaps') or []),
                            'risk_facts': kb.get('facts') or [],
                            'risk_flags': kb.get('flags') or [],
                            'risk_gaps': kb.get('gaps') or [],
                            'contradictions': (deep or {}).get('contradictions') or [],
                            'critic': (deep or {}).get('critic') or {},
                            'unresolved': (deep or {}).get('unresolved') or [],
                            'structure_issues': (deep or {}).get('structure_issues') or []}),
    }

    return {
        'code': code,
        'name': payload.get('name', code),
        'industry': payload.get('industry'),
        'data_asof': payload.get('data_asof'),
        'coverage': cov,
        'deep_ready': deep is not None,
        'deep_cached': deep is not None,
        'research_reports': (research or {}).get('report_count', 0),
        'overview': overview,
        'modules': modules,
        'contract': 'v1',
    }


@app.post('/api/stockscore_v3_bundle_async')
def stockscore_v3_bundle_async(req: Req):
    """小程序专用：bundle + 后台预热 deep。

    同步返回 overview + 4 个模块（含已缓存的 deep 段落，未缓存时 deep 为空）；
    若 deep 未缓存，启动后台作业预热，front端可轮询 /api/stockscore_v3_deep_progress
    拉取已完成段落。首次调用概览 <3s（缓存命中），deep 段落后台异步生成。
    """
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    bundle = stockscore_v3_bundle(Req(code=code))
    deep = _ssdeep.get_cached(code)
    if deep is None:
        started = _ss_start_deep_job(code)
        bundle['deep_state'] = 'started' if started else 'running'
    else:
        bundle['deep_state'] = 'cached'
    return bundle


@app.post('/api/stockscore_v3_summary')
def stockscore_v3_summary(req: Req):
    """元宝总结版：手机端/语音用的口播稿（≤1200字）。"""
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    payload, fk, research, industry_raw, industry_facts, cov = _ss_context(code)
    vb = _ssmod.build_valuation_block(code, research=research)
    kb = _ssmod.build_risk_block(code, research=research)
    deep = None
    try:
        deep = _ssdeep.get_or_build(
            code, payload.get('name', code),
            [fk.get('facts') or [], vb['facts'], kb['facts']],
            research, payload=payload, key=DS_KEY, coverage=cov)
    except Exception:
        deep = None
    try:
        return _sssum.get_or_build(code, payload.get('name', code), payload,
                                    vb, kb, research, fk.get('facts') or [],
                                    DS_KEY, deep=deep, coverage=cov,
                                    industry_facts=industry_facts)
    except Exception as e:
        raise HTTPException(503, f'总结版生成失败: {type(e).__name__}: {e}')


@app.post('/api/stockscore_v3_talk')
def stockscore_v3_talk(req: Req):
    """元宝口播版·快速通道（手机端专用）。

    与 /api/stockscore_v3_summary 的区别：**不等待深度分析生成**。
    坑（2026-10-20 实测）：summary 端点内部会调 deep.get_or_build，
    六段深度分析 + 两轮审读重写要 2-4 分钟，手机上等不起。
    这里的口播稿只用打分卡/估值/风险/研报四类数字源，十几秒出稿。

    deep 已缓存时会用（免费），没缓存就直接跳过——口播稿照样成立。
    """
    code = re.sub(r'\D', '', req.code or '')
    if len(code) != 6:
        raise HTTPException(400, '请输入6位股票代码')
    payload, fk, research, industry_raw, industry_facts, cov = _ss_context(code)
    vb = _ssmod.build_valuation_block(code, research=research)
    kb = _ssmod.build_risk_block(code, research=research)
    # 只取已缓存的 deep，不触发生成
    deep = None
    try:
        deep = _ssdeep.get_cached(code)
    except Exception:
        deep = None
    try:
        return _sssum.get_or_build(code, payload.get('name', code), payload,
                                    vb, kb, research, fk.get('facts') or [],
                                    DS_KEY, deep=deep, coverage=cov,
                                    industry_facts=industry_facts)
    except Exception as e:
        raise HTTPException(503, f'口播版生成失败: {type(e).__name__}: {e}')


# ---------- 匿名工具使用埋点（2026-09-18）----------
# 只记录：工具名/事件/随机sid/停留秒数。不记录IP、不记录用户输入内容。
# 数据按日切 JSONL 存 track/，90 天归档压缩。埋点失败静默，绝不影响主服务。
TRACK_DIR = os.path.join(BASE_DIR, 'track')
TRACK_TOOLS = {'backtest-compare', 'compound', 'daily-insight', 'etf-allocator', 'fund-ranking',
               'fund-scorecard', 'industry-compare', 'industry-report', 'macro-signal', 'stockcheck', 'valuator',
               'stockscore', 'stockscore_v3'}
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


# ---------- 页面级访问采集（自建，替代 51LA · 2026-09-20）----------
# 只记录：路径/来源(剥query)/UTM/视口/屏幕/DPR/语言/时区/设备类别/停留/滚动/性能/机器人标记
# 不记录：IP、Cookie、完整 UA（只存解析后的类别标签）、任何用户输入内容。
# 按日切 JSONL 存 pv/，90 天归档压缩。失败静默，绝不影响主服务。
PV_DIR = os.path.join(BASE_DIR, 'pv')
_PV_LOCK = threading.Lock()
_PV_RATE = {}
PV_RATE_WIN = 600       # 限流窗口（秒）
PV_RATE_MAX = 120       # 单 sid 单个窗口内上限（防刷）
PV_EVENTS = {'pv', 'leave'}
_BOT_RE = re.compile(
    r'bot|crawl|spider|slurp|headless|phantom|python-requests|python-urllib|curl/|wget|'
    r'semrush|ahrefs|mj12|dotbot|petal|bytespider|yandex|facebookexternalhit|'
    r'go-http-client|okhttp|java/|libwww|scrapy|masscan|nmap', re.I)


def _ua_class(ua):
    """UA → 类别标签（不留原串）。返回 (browser, os_name, device, is_bot)。"""
    u = ua or ''
    is_bot = bool(_BOT_RE.search(u))
    if re.search(r'Edg/|EdgA/', u):
        browser = 'Edge'
    elif re.search(r'OPR/|Opera', u):
        browser = 'Opera'
    elif re.search(r'MicroMessenger', u):
        browser = 'WeChat'
    elif re.search(r'Chrome/', u):
        browser = 'Chrome'
    elif re.search(r'Firefox/', u):
        browser = 'Firefox'
    elif re.search(r'Safari/', u):
        browser = 'Safari'
    else:
        browser = 'Other'
    if re.search(r'Android', u):
        os_name = 'Android'
    elif re.search(r'iPhone|iPad|iPod', u):
        os_name = 'iOS'
    elif re.search(r'Windows', u):
        os_name = 'Windows'
    elif re.search(r'Mac OS X', u):
        os_name = 'macOS'
    elif re.search(r'Linux', u):
        os_name = 'Linux'
    else:
        os_name = 'Other'
    if re.search(r'iPad|Tablet', u):
        device = 'tablet'
    elif re.search(r'Mobile|Android|iPhone', u):
        device = 'mobile'
    else:
        device = 'desktop'
    return browser, os_name, device, is_bot


class CollectReq(BaseModel):
    ev: str = Field('pv', max_length=8)
    p: str = Field('/', max_length=120)
    t: str = Field('', max_length=80)
    r: str = Field('', max_length=200)
    u: str = Field('', max_length=120)
    vw: int = Field(0, ge=0, le=10000)
    vh: int = Field(0, ge=0, le=10000)
    sw: int = Field(0, ge=0, le=20000)
    sh: int = Field(0, ge=0, le=20000)
    dpr: float = Field(1.0, ge=0.1, le=10.0)
    lg: str = Field('', max_length=16)
    tz: str = Field('', max_length=48)
    tc: bool = False
    cs: str = Field('', max_length=8)
    rm: bool = False
    cn: str = Field('', max_length=8)
    wd: bool = False
    sid: str = Field('', max_length=32)
    s: int = Field(0, ge=0, le=100)
    dw: float = None
    ph: int = Field(0, ge=0, le=2000000)
    cta: int = Field(-1, ge=-1, le=2000000)
    ttfb: int = Field(0, ge=0, le=600000)
    dom: int = Field(0, ge=0, le=600000)


def _pv_allow(sid):
    """单 sid 窗口限流（内存级，防采集端点被刷）。"""
    now = time.time()
    with _PV_LOCK:
        win, cnt = _PV_RATE.get(sid, (now, 0))
        if now - win > PV_RATE_WIN:
            win, cnt = now, 0
        if cnt >= PV_RATE_MAX:
            return False
        _PV_RATE[sid] = (win, cnt + 1)
        if len(_PV_RATE) > 5000:
            for k, v in list(_PV_RATE.items()):
                if now - v[0] > PV_RATE_WIN:
                    _PV_RATE.pop(k, None)
    return True


@app.post('/api/collect')
def collect(req: CollectReq, request: Request):
    try:
        if req.ev not in PV_EVENTS or not req.sid:
            return {'ok': False}
        if not _pv_allow(req.sid):
            return {'ok': False}
        ua = (request.headers.get('user-agent') or '')[:300]
        browser, os_name, device, is_bot = _ua_class(ua)
        rec = {
            'ts': int(time.time()), 'ev': req.ev, 'p': req.p, 't': req.t,
            'r': req.r, 'u': req.u, 'sid': req.sid,
            'vw': req.vw, 'vh': req.vh, 'sw': req.sw, 'sh': req.sh,
            'dpr': round(req.dpr, 2),
            'lg': req.lg, 'tz': req.tz, 'tc': req.tc, 'cs': req.cs, 'rm': req.rm, 'cn': req.cn,
            'wd': req.wd, 'bot': is_bot, 'br': browser, 'os': os_name, 'dv': device,
            'ph': req.ph, 'cta': req.cta, 'ttfb': req.ttfb, 'dom': req.dom,
        }
        if req.ev == 'leave':
            rec['s'] = req.s
            if req.dw is not None:
                try:
                    rec['dw'] = round(max(0.0, min(float(req.dw), 3600.0)), 1)
                except (TypeError, ValueError):
                    pass
        fname = time.strftime('%Y-%m-%d', time.gmtime(time.time() + 28800)) + '.jsonl'
        os.makedirs(PV_DIR, exist_ok=True)
        with _PV_LOCK:
            with open(os.path.join(PV_DIR, fname), 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:
        pass
    return {'ok': True}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', '8080')))
