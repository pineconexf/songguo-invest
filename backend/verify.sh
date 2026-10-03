#!/usr/bin/env bash
# ============================================================
# 个股打分卡验收脚本 —— spec.md §7 九条验收项（机器可跑）
# 用法：
#   BASE=http://127.0.0.1:8081 ./verify.sh          # 需后端已在跑
#   默认 BASE=http://127.0.0.1:8081
# 退出码：0 全部通过；1 有失败项
# 依赖：curl、python3（用 backend/.venv 时可 export PY=.../python.exe）
# ============================================================
set -u
BASE="${BASE:-http://127.0.0.1:8081}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PY:-$SCRIPT_DIR/.venv/Scripts/python.exe}"
[ -x "$PY" ] || PY="$(command -v python3 || command -v python)"
PAGE_SRC="$SCRIPT_DIR/../src/pages/tools/stockscore.astro"
cd "$SCRIPT_DIR" || exit 2
OUT="_verify_out"          # 相对路径：git-bash、Windows curl、Windows python 三方一致
rm -rf "$OUT" && mkdir -p "$OUT"
# 结果保留在 _verify_out/ 供审计（重跑时自动清空重建）

# 10 只样本：正常 / 对照 / 银行 / 保险 / 医药 / 半导体 / 亏损 / ST亏损 / 中小创
CODES="600519 000001 300750 002415 300496 600276 601318 688981 001211 002883"

echo "== 验收开始 BASE=$BASE PY=$PY OUT=$OUT =="
FAIL=0

# ---------- 第 1 项：10 只票全部 200 且 JSON 可解析 ----------
for c in $CODES; do
  code=$(curl -s -o "$OUT/$c.json" -w '%{http_code}' --max-time 120 \
         -X POST "$BASE/api/stockscore" \
         -H 'Content-Type: application/json' -d "{\"code\":\"$c\"}")
  if [ "$code" != "200" ]; then echo "[1][FAIL] $c HTTP $code"; FAIL=1; fi
done
[ $FAIL -eq 0 ] && echo "[1][PASS] 10 只票全部 HTTP 200"

# ---------- 第 2~9 项交给 python 断言 ----------
"$PY" - "$OUT" "$CODES" "$PAGE_SRC" <<'PYEOF'
import json, re, sys, os
out_dir, codes_arg, page_src = sys.argv[1], sys.argv[2], sys.argv[3]
codes = codes_arg.split()
fails = []

BANNED = ['买入', '卖出', '加仓', '减仓', '目标价', '必涨', '稳赚', '推荐']
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')

def check(item, cond, msg):
    if not cond:
        fails.append(f"[{item}][FAIL] {msg}")

datas = {}
for c in codes:
    p = os.path.join(out_dir, f'{c}.json')
    try:
        with open(p, encoding='utf-8') as f:
            datas[c] = json.load(f)
    except Exception as e:
        check(1, False, f'{c} JSON 解析失败 {e}')

# ---- 2. dims==6，权重和==1.0（1e-9） ----
for c, d in datas.items():
    dims = d.get('dims') or []
    check(2, len(dims) == 6, f'{c} dims 长度 {len(dims)} != 6')
    ws = sum(x['weight'] for x in dims)
    check(2, abs(ws - 1.0) < 1e-9, f'{c} 权重和 {ws}')

# ---- 3. 每维 score∈[0,100]、weighted_score∈[0,100*weight/w_eff]；available=false 必在 excluded ----
# （§7-3 字面"score∈[0,100*weight]"与 §6 样例矛盾：样例 weight=0.22 的维 score=78.4。
#   以 §6 契约为准：score=维内原始分 0-100，weighted_score=对总分贡献。此矛盾已上报。）
for c, d in datas.items():
    w_eff = sum(x['weight'] for x in d['dims'] if x['available'])
    ex_keys = {e['key'] for e in d.get('excluded') or []}
    for x in d['dims']:
        if x['available']:
            check(3, x['score'] is not None and -1e-9 <= x['score'] <= 100 + 1e-9,
                  f"{c} {x['key']} score {x['score']} 越界 [0,100]")
            check(3, x['weighted_score'] <= 100 * x['weight'] / w_eff + 1e-6,
                  f"{c} {x['key']} weighted_score 贡献越界")
        else:
            check(3, x['key'] in ex_keys, f"{c} {x['key']} available=false 但未进 excluded")
            check(3, x['score'] is None, f"{c} {x['key']} 不可用却有分数 {x['score']}")

# ---- 4. total==Σweighted_score（1e-6）；基本面=①②④(55%)、市场=③⑤⑥(45%) 块内加权复算一致 ----
# 审计 B3 修正：③估值输入为逐日 PE/PB 序列（属日频），原口径把它漏在两个小计之外，
# 导致「日频合计」被低估为 25%（实为 45%）、且本断言按旧口径恒不成立。
FUND = {'profit_quality', 'growth', 'financial_health'}
MKT = {'valuation', 'capital_momentum', 'concept_heat'}
for c, d in datas.items():
    avail = [x for x in d['dims'] if x['available']]
    sw = sum(x['weighted_score'] for x in avail)
    check(4, abs(sw - d['total']) < 1e-6, f'{c} total {d["total"]} != Σweighted {sw}')
    # 小计恒等式（同一批 round 后 float 可复算）：total*w_eff == fund*fw + tr*tw
    fw = sum(x['weight'] for x in avail if x['key'] in FUND)
    tw = sum(x['weight'] for x in avail if x['key'] in MKT)
    sf = sum(x['score'] * x['weight'] for x in avail if x['key'] in FUND)
    st = sum(x['score'] * x['weight'] for x in avail if x['key'] in MKT)
    if fw:
        check(4, abs(sf / fw - d['fundamental_score']) < 1e-6,
              f'{c} fundamental {d["fundamental_score"]} != 块内加权 {sf / fw}')
    if tw:
        check(4, abs(st / tw - d['market_score']) < 1e-6,
              f'{c} market {d["market_score"]} != 块内加权 {st / tw}')
    w_eff = fw + tw
    check(4, abs((sf + st) - d['total'] * w_eff) < 1e-3,
          f'{c} (fund*fw+mkt*mw) {sf + st} != total*w_eff {d["total"] * w_eff}')
    # 维内权重归一（available 维的 metrics 权重和 == 1；权重存 float 未舍入，容差 1e-9）
    for x in d['dims']:
        if x['available'] and x['metrics']:
            mw = sum(m['weight'] for m in x['metrics'])
            check(4, abs(mw - 1.0) < 1e-6, f"{c} {x['key']} 维内权重和 {mw} != 1")

# ---- 5. 指标值非 None；excluded 维的分数为显式 null ----
for c, d in datas.items():
    for x in d['dims']:
        for m in x.get('metrics') or []:
            check(5, m['value'] is not None, f"{c} {x['key']} 指标 {m['name']} value=None")
            check(5, m['pctl'] is not None, f"{c} {x['key']} 指标 {m['name']} pctl=None")
    for e in d.get('excluded') or []:
        dim = next((x for x in d['dims'] if x['key'] == e['key']), None)
        check(5, dim is not None and dim['score'] is None,
              f"{c} excluded 维 {e['key']} 分数不是显式 null")

# ---- 6. 亏损/银行/医药：估值维口径已切换或 available=false ----
def val_dim(d): return next(x for x in d['dims'] if x['key'] == 'valuation')
for c in ('001211', '002883'):                       # 亏损股
    d = datas.get(c)
    if d:
        v = val_dim(d)
        check(6, (not v['available']) or any('亏损' in f or 'PE 无定义' in f for f in v['flags']),
              f'{c} 亏损股估值维未降级')
        check(6, not v['available'], f'{c} 亏损股估值维应 available=false')
for c in ('000001', '601318'):                       # 银行/保险：PE/PEG 不计分
    d = datas.get(c)
    if d:
        v = val_dim(d)
        names = ' '.join(m['name'] for m in v['metrics'])
        check(6, ('金融' in ' '.join(v['flags'])) and ('PE_TTM' not in names) and ('PEG' not in names),
              f'{c} 金融估值维未切换 PB 口径: {names[:80]}')
for c in ('600276', '688981'):                       # 医药/半导体（样本当期盈利为正）
    d = datas.get(c)
    if d:
        v = val_dim(d)
        fl = ' '.join(v['flags'])
        names = ' '.join(m['name'] for m in v['metrics'])
        # spec §1③：亏损期整维不计分；盈利期必须带行业相对口径（行业中位分位）
        check(6, (not v['available']) or
                  (('医药' in fl) or ('半导体' in fl)) or
                  ('行业中位分位' in names),
              f'{c} 医药/半导体估值维既未降级、亦无行业相对口径')

# ---- 7. 禁词扫描：页面源文件 + 所有 AI 报告文本，命中数==0 ----
scan_targets = []
if os.path.exists(page_src):
    scan_targets.append(('page', open(page_src, encoding='utf-8').read()))
for c, d in datas.items():
    scan_targets.append((f'report:{c}', json.dumps(d.get('report') or {}, ensure_ascii=False)))
for label, text in scan_targets:
    for w in BANNED:
        check(7, w not in text, f'{label} 命中禁词「{w}」')

# ---- 8. confidence<0.6 的维/指标全部进 low_confidence ----
for c, d in datas.items():
    lc = {x['key']: x for x in d.get('low_confidence') or []}
    for x in d['dims']:
        bad_metrics = [m['name'] for m in (x.get('metrics') or [])
                       if m.get('confidence') is not None and m['confidence'] < 0.6]
        if x.get('confidence') is not None and x['confidence'] < 0.6:
            check(8, x['key'] in lc, f'{c} 维 {x["key"]} conf={x["confidence"]}<0.6 未进 low_confidence')
        if bad_metrics:
            check(8, x['key'] in lc and set(bad_metrics) <= set(lc[x['key']].get('metrics_below_0.6') or []),
                  f'{c} 指标低置信未披露: {x["key"]} {bad_metrics}')

# ---- 9. data_asof 非空且 YYYY-MM-DD ----
for c, d in datas.items():
    check(9, bool(d.get('data_asof')) and bool(DATE_RE.match(d['data_asof'] or '')),
          f'{c} data_asof 异常: {d.get("data_asof")!r}')
    # 附加契约：dupont 三分解必带（盈利质量维）
    pq = next(x for x in d['dims'] if x['key'] == 'profit_quality')
    if pq['available']:
        dp = pq.get('dupont') or {}
        check(9, all(k in dp and dp[k] is not None for k in ('margin', 'turnover', 'equity_mult')),
              f'{c} 盈利质量维缺 dupont 三分解')

if fails:
    for f in fails:
        print(f)
    print(f"\n== 断言失败 {len(fails)} 项 ==")
    sys.exit(1)
print('== 第 2~9 项断言全部通过（10 票 × 全部维度）==')
PYEOF
[ $? -eq 0 ] || FAIL=1

# ---------- 汇总 ----------
if [ $FAIL -eq 0 ]; then
  echo "VERIFY: ALL 9 ITEMS PASS"
else
  echo "VERIFY: FAILED"
fi
exit $FAIL
