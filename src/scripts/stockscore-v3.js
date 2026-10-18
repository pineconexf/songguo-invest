// 个股打分卡 V3 前端渲染模块（2026-10-18）
// 四个页面（index/quality/price/momentum）共用本模块，通过 view 参数区分。
// 数据来自 POST /api/stockscore_v3，解说是后端规则生成（非 LLM），前端只做排版。

const STYLE = `
.ss3{--ink:#1a1f26;--ink2:#33404d;--muted:#67737f;--faint:#8d99a4;--line:#e2e6ec;--line2:#eef1f4;
--green:#146b52;--green-l:#e8f2ee;--green-b:#cfe3da;--gold:#a97c2f;--gold-l:#faf3e6;--gold-b:#ecdcbf;
--red:#b3392c;--red-l:#fbeeec;--red-b:#f0cfca;--blue:#2c5f8a;--blue-l:#eaf1f7;--blue-b:#cddcea;
max-width:1000px;margin:0 auto;padding:0 4px 48px;color:var(--ink);font-size:14.5px;line-height:1.7}
.ss3 .ident{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;margin:4px 0 2px}
.ss3 .ident h1{margin:0;font-size:25px;font-weight:800;letter-spacing:-.01em}
.ss3 .ident .code{font-size:13.5px;color:var(--faint);font-variant-numeric:tabular-nums}
.ss3 .ident .ind{font-size:12.5px;color:var(--muted);background:#fff;border:1px solid var(--line);padding:2px 9px;border-radius:5px}
.ss3 .nav{display:flex;gap:2px;margin:16px 0 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.ss3 .nav a{padding:9px 16px;font-size:13.5px;font-weight:600;color:var(--muted);text-decoration:none;border-bottom:2px solid transparent;margin-bottom:-1px}
.ss3 .nav a.on{color:var(--green);border-bottom-color:var(--green)}
.ss3 .card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:20px 22px;margin-bottom:14px}
.ss3 .hero{display:flex;gap:24px;align-items:center;flex-wrap:wrap}
.ss3 .big{font-size:50px;font-weight:800;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.ss3 .big small{font-size:14px;font-weight:600;color:var(--muted);margin-left:8px;letter-spacing:0}
.ss3 .hero .meta{flex:1;min-width:240px}
.ss3 .pill{display:inline-block;font-size:12px;font-weight:700;padding:3px 10px;border-radius:5px;margin:3px 6px 3px 0}
.ss3 .p-in{background:var(--green-l);color:var(--green);border:1px solid var(--green-b)}
.ss3 .p-out{background:var(--gold-l);color:var(--gold);border:1px solid var(--gold-b)}
.ss3 .p-red{background:var(--red-l);color:var(--red);border:1px solid var(--red-b)}
.ss3 .p-gray{background:#f1f3f5;color:var(--muted);border:1px solid var(--line)}
.ss3 .g3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0 2px}
.ss3 .gcard{border:1px solid var(--line);border-radius:9px;padding:14px 16px;background:#fcfcfd}
.ss3 .gcard .k{font-size:11.5px;font-weight:800;letter-spacing:.08em;color:var(--faint)}
.ss3 .gcard .v{font-size:26px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1.25}
.ss3 .gcard .q{font-size:12px;color:var(--muted)}
.ss3 .gcard.Q{border-left:3px solid var(--green)}.ss3 .gcard.V{border-left:3px solid var(--gold)}.ss3 .gcard.M{border-left:3px solid var(--blue)}
.ss3 h2.s{font-size:15px;font-weight:800;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid var(--line2)}
.ss3 h2.s .w{float:right;font-size:12px;font-weight:600;color:var(--faint)}
.ss3 .row{display:grid;grid-template-columns:150px 1fr 56px;gap:12px;align-items:center;margin-bottom:9px}
.ss3 .row .nm{font-size:13px;font-weight:600;color:var(--ink2)}
.ss3 .row .nm em{font-style:normal;font-size:11px;color:var(--faint);margin-left:5px}
.ss3 .bar{height:9px;background:#eef1f4;border-radius:5px;overflow:hidden}
.ss3 .bar i{display:block;height:100%;border-radius:5px;background:var(--green)}
.ss3 .bar.v i{background:var(--gold)}.ss3 .bar.m i{background:var(--blue)}.ss3 .bar.na i{background:#dfe3e8}
.ss3 .row .sc{text-align:right;font-size:13px;font-weight:700;font-variant-numeric:tabular-nums}
.ss3 table{width:100%;border-collapse:collapse;font-size:12.8px}
.ss3 th{text-align:left;padding:8px 10px;background:#f8f9fb;border-bottom:1px solid var(--line);font-size:12px;font-weight:700;white-space:nowrap}
.ss3 td{padding:8px 10px;border-bottom:1px solid var(--line2);color:var(--ink2);vertical-align:top}
.ss3 tr:last-child td{border-bottom:none}
.ss3 td.n{font-variant-numeric:tabular-nums;white-space:nowrap;text-align:right}
.ss3 .tagA,.ss3 .tagB{font-size:10.5px;font-weight:800;padding:1px 5px;border-radius:3px;white-space:nowrap}
.ss3 .tagA{background:var(--green-l);color:var(--green);border:1px solid var(--green-b)}
.ss3 .tagB{background:var(--gold-l);color:var(--gold);border:1px solid var(--gold-b)}
.ss3 .fl{font-size:12.5px;padding:7px 12px;border-radius:6px;margin-bottom:6px;line-height:1.6}
.ss3 .fl.r{background:var(--red-l);border:1px solid var(--red-b);color:#8a4a41}
.ss3 .fl.y{background:var(--gold-l);border:1px solid var(--gold-b);color:#6b5427}
.ss3 .fl.n{background:#f7f8fa;border:1px solid var(--line);color:var(--muted)}
.ss3 .blk{margin-bottom:13px}
.ss3 .blk .h{font-size:12px;font-weight:800;color:var(--green);letter-spacing:.06em;margin-bottom:3px}
.ss3 .blk .t{font-size:13.5px;color:var(--ink2);line-height:1.75}
.ss3 .note{font-size:11.5px;color:var(--faint);line-height:1.7;margin-top:9px}
.ss3 .dimhead{display:flex;justify-content:space-between;align-items:baseline;margin:22px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line2)}
.ss3 .dimhead h3{margin:0;font-size:15px;font-weight:800}
.ss3 .dimhead .sc{font-size:19px;font-weight:800;font-variant-numeric:tabular-nums}
.ss3 .dimhead .sc small{font-size:11.5px;color:var(--faint);font-weight:600;margin-left:6px}
.ss3 .chk{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:7px;margin-top:10px}
.ss3 .chk div{font-size:12.3px;padding:7px 11px;border-radius:6px;border:1px solid var(--line);background:#fcfcfd}
.ss3 .chk div.ok{border-color:var(--green-b);background:var(--green-l);color:var(--green)}
.ss3 .chk div.no{border-color:var(--red-b);background:var(--red-l);color:#8a4a41}
.ss3 .form{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.ss3 .form input{font-size:15px;padding:10px 14px;border:1px solid var(--line);border-radius:8px;width:190px;font-variant-numeric:tabular-nums}
.ss3 .form button{font-size:14px;font-weight:700;padding:10px 20px;border-radius:8px;border:1px solid var(--green);background:var(--green);color:#fff;cursor:pointer}
.ss3 .form button:disabled{opacity:.55;cursor:default}
.ss3 .foot{font-size:11px;color:var(--faint);line-height:1.8;border-top:1px solid var(--line);padding-top:16px;margin-top:24px}
@media(max-width:720px){.ss3 .g3{grid-template-columns:1fr}.ss3 .row{grid-template-columns:110px 1fr 46px}}
`;

const VIEWS = [
  ['index', '总览', 'overview'],
  ['quality', '质地', 'quality'],
  ['price', '价格', 'price'],
  ['momentum', '势能', 'momentum'],
];

const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function num(v, nd = 2) {
  if (v === null || v === undefined) return 'N/A';
  if (typeof v !== 'number') return esc(v);
  if (Math.abs(v) >= 1e6) return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  let s = v.toFixed(nd);
  if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s || '0';
}

const tierCls = (t) => ({ 优: 'p-in', 良: 'p-in', 中: 'p-out', 待观察: 'p-red' }[t] || 'p-gray');
const tagCls = (c) => ({ in: 'p-in', out: 'p-out', red: 'p-red' }[c] || 'p-gray');
const barCls = (k) => (k === 'valuation' ? 'v'
  : ['chain_prosperity', 'earnings_revision', 'capital_momentum'].indexOf(k) >= 0 ? 'm' : '');

function groupOf(key) {
  if (key === 'valuation') return 'V';
  if (['chain_prosperity', 'earnings_revision', 'capital_momentum'].indexOf(key) >= 0) return 'M';
  return 'Q';
}

function navBar(code, active) {
  return '<div class="nav">' + VIEWS.map(([k, label]) =>
    `<a class="${k === active ? 'on' : ''}" href="?code=${encodeURIComponent(code)}&view=${k}">${label}</a>`
  ).join('') + '</div>';
}

function identBar(p) {
  return `<div class="ident"><h1>${esc(p.name)}</h1><span class="code">${esc(p.code)}</span>` +
    `<span class="ind">${esc(p.industry || '—')}</span>` +
    `<span class="ind">数据 ${esc(p.data_asof)}</span></div>`;
}

function dimBlock(d) {
  if (!d.available) {
    return `<div class="dimhead"><h3>${esc(d.label)}</h3>` +
      `<div class="sc">N/A<small>权重 ${Math.round(d.weight * 100)}%</small></div></div>` +
      `<div class="fl n">${esc(d.na_reason || '该维不可用')}</div>`;
  }
  const rows = d.metrics.map((m) => {
    const rel = m.reliability === 'A' ? '<br><span class="tagA">A级·真实披露</span>'
      : m.reliability === 'B' ? '<br><span class="tagB">B级·大单推算</span>' : '';
    const note = m.note ? `<div class="note">${esc(m.note)}</div>` : '';
    return `<tr><td>${esc(m.name)}${rel}${note}</td>` +
      `<td class="n">${num(m.value)}${esc(m.unit || '')}</td>` +
      `<td class="n">${num(m.pctl, 0)}</td>` +
      `<td class="n">${Math.round(m.weight * 100)}%</td>` +
      `<td class="n">${m.confidence}</td></tr>`;
  }).join('');
  const flags = (d.flags || []).map((f) => `<div class="fl n">${esc(f)}</div>`).join('');
  const thresh = d.thresh ? `<div class="note">口径：${esc(d.thresh)}</div>` : '';
  return `<div class="dimhead"><h3>${esc(d.label)}</h3>` +
    `<div class="sc">${num(d.score, 1)}<small>权重 ${Math.round(d.weight * 100)}% · 置信 ${d.confidence}</small></div></div>` +
    '<table><thead><tr><th>子指标</th><th style="text-align:right">数值</th>' +
    '<th style="text-align:right">分位/刻度</th><th style="text-align:right">维内权重</th>' +
    `<th style="text-align:right">置信</th></tr></thead><tbody>${rows}</tbody></table>${flags}${thresh}`;
}

function blocksOf(p, key) {
  const bs = (p.pages[key] && p.pages[key].blocks) || [];
  return bs.map((b) => `<div class="blk"><div class="h">${esc(b.h)}</div><div class="t">${esc(b.t)}</div></div>`).join('');
}

function viewOverview(p) {
  const g = p.groups;
  const bars = p.dims.map((d) => {
    const w = d.score === null ? 0 : Math.max(0, Math.min(100, d.score));
    return `<div class="row"><div class="nm">${esc(d.label)}<em>${Math.round(d.weight * 100)}%</em></div>` +
      `<div class="bar ${barCls(d.key)}${d.score === null ? ' na' : ''}"><i style="width:${w.toFixed(1)}%"></i></div>` +
      `<div class="sc">${num(d.score, 1)}</div></div>`;
  }).join('');
  let fl = p.gate.red.map((r) => `<div class="fl r">🔴 ${esc(r)}</div>`).join('') +
    p.gate.yellow.map((y) => `<div class="fl y">🟡 ${esc(y)}</div>`).join('');
  if (!p.gate.red.length && !p.gate.yellow.length) fl = '<div class="fl n">✅ 未触发红旗与黄旗</div>';
  fl += `<div class="fl n">未接入：${esc((p.gate.not_wired || []).join('、'))}</div>`;
  const chk = Object.entries(p.investable_checks || {}).map(([k, v]) =>
    `<div class="${v ? 'ok' : 'no'}">${v ? '✅' : '❌'} ${esc(k)}</div>`).join('');

  return `<div class="card"><div class="hero">
    <div><div class="big">${num(p.total, 1)}<small>分 · ${esc(p.tier)}</small></div>
    <div class="note" style="margin-top:8px">裸分 ${num(p.total_raw, 1)}${p.tier_note ? '　' + esc(p.tier_note) : ''}</div></div>
    <div class="meta"><span class="pill ${tagCls(p.tag.code)}">${esc(p.tag.label)}</span>
      <span class="pill ${tierCls(p.tier)}">档位 ${esc(p.tier)}</span>
      <span class="pill p-gray">红旗 ${p.gate.red.length} · 黄旗 ${p.gate.yellow.length}</span>
      <div class="note">${esc(p.tag.desc)}</div></div></div>
    <div class="g3">
      <div class="gcard Q"><div class="k">Q · 质地</div><div class="v">${num(g.Q.score, 1)}</div><div class="q">${esc(g.Q.question)}｜权重 ${g.Q.weight}</div></div>
      <div class="gcard V"><div class="k">V · 价格</div><div class="v">${num(g.V.score, 1)}</div><div class="q">${esc(g.V.question)}｜权重 ${g.V.weight}</div></div>
      <div class="gcard M"><div class="k">M · 势能</div><div class="v">${num(g.M.score, 1)}</div><div class="q">${esc(g.M.question)}｜权重 ${g.M.weight}</div></div>
    </div></div>
    <div class="card"><h2 class="s">八维得分<span class="w">权重合计 ${num(p.meta.weights_sum, 2)}</span></h2>${bars}</div>
    <div class="card"><h2 class="s">闸门</h2>${fl}</div>
    <div class="card"><h2 class="s">松果可投性（简化 11 步 + 市值）</h2><div class="chk">${chk}</div>
      <div class="note">完整 V35 管线含 VC∈[0.90,0.99]、行业软调节、红旗删票不补位；本卡用可公开验证的简化口径做代理，
      标签含义为「落在射程内与否」，不等于买入建议。</div></div>
    <div class="card"><h2 class="s">一句话结论</h2>${blocksOf(p, 'overview')}</div>`;
}

// 组键 → 页面键。注意：viewGroup 收到的是 'Q'/'V'/'M'，而 payload.pages 的键是
// 'quality'/'price'/'momentum'，直接 toLowerCase() 会取到 'q'/'v'/'m' → 拿不到 headline 与 blocks。
const PAGE_OF = { Q: 'quality', V: 'price', M: 'momentum' };

function viewGroup(p, key, dimKeys, extraNote) {
  const g = p.groups[key];
  const pageKey = PAGE_OF[key] || String(key).toLowerCase();
  const page = p.pages[pageKey] || {};
  const dims = p.dims.filter((d) => dimKeys.indexOf(d.key) >= 0);
  const head = `<div class="card"><div class="hero"><div class="big">${num(g.score, 1)}<small>${key} · ${esc(g.label)}</small></div>
    <div class="meta"><div style="font-size:13.5px;color:var(--ink2)">${esc(page.headline || '')}</div>
    <div class="note">${esc(g.v35)}</div></div></div></div>`;
  const body = `<div class="card"><h2 class="s">${dims.length} 个维度合在一起看</h2>${dims.map(dimBlock).join('')}</div>`;
  const concl = `<div class="card"><h2 class="s">结论</h2>${blocksOf(p, pageKey)}
    ${extraNote ? `<div class="note">${extraNote}</div>` : ''}</div>`;
  return head + body + concl;
}

const NOTE_Q = '纵向=链条位置与议价力（慢变，结构）；横向=同行地位与技术代差；自身=壁垒类型与持续性。' +
  '技术代差、毛利溢价为代理指标——真正的护城河（转换成本、网络效应、心智占领）拿不到结构化数据。';
const NOTE_V = '低分位=高分。亏损股 PE 无定义时整维 N/A；金融业只计 PB。' +
  '松果 FCF 收益率为 FCFF÷市值的代理口径（未扣净债），权重 26%，是这一维里最接近策略排序逻辑的子项。';
const NOTE_M = '资金动能按真实性分三级：A 级=融资余额/龙虎榜（真实披露，占 3.5 分）；' +
  'B 级=主力净流入（按单笔金额分档推算，<b>主力可拆单规避</b>，占 2.5 分，只读异动不读意图）；' +
  'C 级=北向资金（2024-09-30 起停止实时披露，永久剔除）。主窗口统一 20 日，与月度调仓同频。';

function render(p, view) {
  let inner;
  if (view === 'quality') {
    inner = viewGroup(p, 'Q', ['profit_quality', 'core_competence', 'growth', 'financial_health'], NOTE_Q);
  } else if (view === 'price') {
    inner = viewGroup(p, 'V', ['valuation'], NOTE_V);
  } else if (view === 'momentum') {
    inner = viewGroup(p, 'M', ['chain_prosperity', 'earnings_revision', 'capital_momentum'], NOTE_M);
  } else {
    inner = viewOverview(p);
  }
  const errs = (p.source_errors || []).length
    ? '<br>取数告警：' + esc(p.source_errors.join('；')) : '';
  const foot = `<div class="foot">总分 = 0.52×Q + 0.26×V + 0.22×M，再过闸门（🔴封顶59 / 🟡≥2降一档 / 🟡=1仅标注）。
    缺失子项不进分母、整维缺失标 N/A 不填 0；每个分数带置信度，&lt;0.6 进低置信清单。<br>
    本页所有数字由公开数据按页面写明口径计算，数据可能有误、口径有局限，请自行复核。
    结构化读数不构成投资建议，不预测涨跌，不含任何买卖意见。${errs}</div>`;
  return identBar(p) + navBar(p.code, view) + inner + foot;
}

function formHtml() {
  return `<div class="card"><h2 class="s">输入股票代码</h2>
    <div class="form"><input id="ss3code" maxlength="6" inputmode="numeric" placeholder="如 600519">
    <button id="ss3go">开始打分</button></div>
    <div class="note">支持 A 股 6 位代码。首次查询需现建全市场横截面宇宙，约 30 秒；10 分钟内同码命中缓存秒回。</div></div>`;
}

async function apiBase() {
  if (window.__SS_BASE__) return window.__SS_BASE__;
  try {
    const r = await fetch('http://127.0.0.1:8081/api/health');
    if (r.ok) { window.__SS_BASE__ = 'http://127.0.0.1:8081'; return window.__SS_BASE__; }
  } catch (e) { /* 生产同源 */ }
  return location.origin;
}

export async function mountV3(view) {
  const root = document.getElementById('ss3-root');
  if (!root) return;
  if (!document.getElementById('ss3-style')) {
    const st = document.createElement('style');
    st.id = 'ss3-style';
    st.textContent = STYLE;
    document.head.appendChild(st);
  }
  root.className = 'ss3';

  const params = new URLSearchParams(location.search);
  const code = (params.get('code') || '').replace(/\D/g, '');

  if (!code) {
    root.innerHTML = formHtml();
    const go = () => {
      const v = (document.getElementById('ss3code').value || '').replace(/\D/g, '');
      if (v.length !== 6) { alert('请输入 6 位 A 股代码'); return; }
      location.search = `?code=${v}&view=${view}`;
    };
    document.getElementById('ss3go').onclick = go;
    document.getElementById('ss3code').addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    return;
  }

  root.innerHTML = '<div class="card"><div class="note">正在计算（首次约 30 秒，之后同码秒回）…</div></div>';
  try {
    const base = await apiBase();
    const res = await fetch(base + '/api/stockscore_v3', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });
    if (!res.ok) {
      const t = await res.text();
      root.innerHTML = `<div class="card"><div class="fl r">查询失败：${esc(t.slice(0, 200))}</div>
        <div class="note"><a href="?view=${view}">重新输入代码</a></div></div>`;
      return;
    }
    const p = await res.json();
    root.innerHTML = render(p, view);
  } catch (e) {
    root.innerHTML = `<div class="card"><div class="fl r">网络异常：${esc(e.message)}</div></div>`;
  }
}
