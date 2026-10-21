// 个股打分卡 V3 · 模块化前端（2026-10-21 重构）
//
// 页面结构（总计 6 页 = 1 总览 + 4 深度分页 + 1 口播）：
//   总览   /tools/stockscore/            快速判断、核心摘要、关键风险、一句话结论
//   质地   /tools/stockscore/quality/    业务结构 + 差异化壁垒 + Q 组四维支撑
//   价格   /tools/stockscore/price/      数字检验 + 估值与预期 + V 组支撑
//   势能   /tools/stockscore/momentum/   市场空间 + M 组支撑
//   风险   /tools/stockscore/risk/       风险与安全 + 红旗 + 关键矛盾 + 审读意见
//   口播   /tools/stockscore/talk/       手机端口播稿
//
// 数据契约：POST /api/stockscore_v3_bundle（overview + modules，一次拉全）
// 深度正文：POST /api/stockscore_v3_deep_progress（轮询，首段 8-10s 可见）
// 预热：    POST /api/stockscore_v3_deep_prewarm（总览页后台触发，点深度页近 0s 读缓存）
//
// 坑（2026-10-21）：不能用 ?view= 同页切 tab —— 深度分页是独立路由，
// tab 必须真跳路由，否则 URL 与内容不一致，收藏/分享会错位。

const STYLE = `
.ss3{--ink:#1a1f26;--ink2:#33404d;--muted:#67737f;--faint:#8d99a4;--line:#e2e6ec;--line2:#eef1f4;
--green:#146b52;--green-l:#e8f2ee;--green-b:#cfe3da;--gold:#a97c2f;--gold-l:#faf3e6;--gold-b:#ecdcbf;
--red:#b3392c;--red-l:#fbeeec;--red-b:#f0cfca;--blue:#2c5f8a;--blue-l:#eaf1f7;--blue-b:#cddcea;
max-width:1000px;margin:0 auto;padding:0 4px 48px;color:var(--ink);font-size:14.5px;line-height:1.75}
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
.ss3 .gcard{border:1px solid var(--line);border-radius:9px;padding:14px 16px;background:#fcfcfd;text-decoration:none;display:block}
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
.ss3 .fl.f{background:var(--blue-l);border:1px solid var(--blue-b);color:#2c5f8a}
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
.ss3 .form input{font-size:15px;padding:10px 14px;border:1px solid var(--line);border-radius:8px;width:250px;font-variant-numeric:tabular-nums}
.ss3 .form button{font-size:14px;font-weight:700;padding:10px 20px;border-radius:8px;border:1px solid var(--green);background:var(--green);color:#fff;cursor:pointer}
.ss3 .form button:disabled{opacity:.55;cursor:default}
.ss3 .say{background:linear-gradient(180deg,#fcfdfc,#f6faf8);border-color:var(--green-b);border-left:3px solid var(--green)}
.ss3 .say .k{font-size:11.5px;font-weight:800;letter-spacing:.1em;color:var(--green);margin-bottom:10px}
.ss3 .say .v{font-size:15px;line-height:1.95;color:var(--ink);margin:0 0 10px}
.ss3 .say .v.lead{font-size:15.5px;font-weight:600}
.ss3 .say .v.loading{color:var(--faint);font-weight:400}
.ss3 .scale{margin-top:8px;padding-top:11px;border-top:1px dashed var(--line);font-size:12.5px;color:var(--ink2)}
.ss3 .scale span{display:block;margin-top:4px;font-size:11.5px;color:var(--faint)}
.ss3 .cands{display:flex;flex-direction:column;gap:8px;margin-top:4px}
.ss3 .cand{display:grid;grid-template-columns:84px 1fr auto;gap:12px;align-items:center;text-align:left;
padding:12px 16px;border:1px solid var(--line);border-radius:9px;background:#fff;cursor:pointer;font:inherit;font-size:14px;color:var(--ink)}
.ss3 .cand:hover,.ss3 .cand:focus{border-color:var(--green);background:var(--green-l);outline:none}
.ss3 .cand .cd{font-variant-numeric:tabular-nums;font-weight:700;color:var(--ink2)}
.ss3 .cand .cn{font-weight:600}
.ss3 .cand .cm{font-size:12px;color:var(--faint)}
.ss3 .foot{font-size:11px;color:var(--faint);line-height:1.8;border-top:1px solid var(--line);padding-top:16px;margin-top:24px}
/* 深度正文 */
.ss3 .deep{margin-bottom:20px}
.ss3 .deep h3{font-size:15px;font-weight:800;margin:0 0 10px;padding-left:10px;border-left:3px solid var(--green);line-height:1.5}
.ss3 .deep p{margin:0 0 10px}
.ss3 .deep p:last-child{margin-bottom:0}
.ss3 .deepnote{font-size:13px;color:var(--gold);background:var(--gold-l);border:1px solid var(--gold-b);
  border-radius:7px;padding:8px 11px;margin:6px 0}
.ss3 .waiting{font-size:13px;color:var(--muted);padding:10px 0;line-height:1.7}
.ss3 .waiting b{color:var(--green)}
.ss3 .facts{width:100%;border-collapse:collapse;font-size:13px}
.ss3 .facts td{padding:7px 0;border-bottom:1px solid var(--line2);vertical-align:top}
.ss3 .facts tr:last-child td{border-bottom:none}
.ss3 .facts .k{color:var(--muted);width:190px;padding-right:12px}
.ss3 .facts .v{font-variant-numeric:tabular-nums}
.ss3 .facts .src{color:var(--faint);font-size:12px}
.ss3 .issues{font-size:13px;color:var(--ink2)}
.ss3 .issues li{margin-bottom:6px}
.ss3 .issues .ty{font-size:11.5px;font-weight:700;color:var(--faint);margin-right:6px}
.ss3 .issues .high{color:var(--red)}
.ss3 .issues .medium{color:var(--gold)}
.ss3 .meta{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.ss3 .meta span{font-size:12px;font-weight:700;padding:3px 10px;border-radius:5px;background:#f1f3f5;color:var(--muted);border:1px solid var(--line)}
.ss3 .meta span.A{background:var(--green-l);color:var(--green);border-color:var(--green-b)}
.ss3 .meta span.B{background:var(--gold-l);color:var(--gold);border-color:var(--gold-b)}
.ss3 .meta span.C{background:var(--red-l);color:var(--red);border-color:var(--red-b)}
.ss3 a.btn{display:inline-block;font-size:13px;font-weight:600;color:var(--green);
  border:1px solid var(--green-b);background:var(--green-l);border-radius:6px;
  padding:5px 13px;text-decoration:none;margin-top:8px}
@media(max-width:720px){.ss3 .g3{grid-template-columns:1fr}.ss3 .row{grid-template-columns:110px 1fr 46px}
.ss3 .facts .k{width:auto;display:block;padding-bottom:2px}}
`;

const VIEWS = [
  ['index', '总览', 'overview'],
  ['quality', '质地', 'quality'],
  ['price', '价格', 'price'],
  ['momentum', '势能', 'momentum'],
  ['risk', '风险', 'risk'],
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

function routeBase() {
  const p = location.pathname.replace(/\/+$/, '');
  const m = p.match(/^(.*\/stockscore)(?:\/(?:index|quality|price|momentum|risk))?$/);
  return m ? m[1] : p;
}

function navBar(code, active) {
  const base = routeBase();
  return '<div class="nav">' + VIEWS.map(([k, label]) =>
    `<a class="${k === active ? 'on' : ''}" href="${base}${k === 'index' ? '' : '/' + k}/?code=${encodeURIComponent(code)}">${label}</a>`
  ).join('') + '</div>';
}

function identBar(b) {
  return `<div class="ident"><h1>${esc(b.name)}</h1><span class="code">${esc(b.code)}</span>` +
    (b.industry ? `<span class="ind">${esc(b.industry)}</span>` : '') +
    (b.data_asof ? `<span class="ind">数据 ${esc(b.data_asof)}</span>` : '') + '</div>';
}

async function apiBase() {
  if (window.__SS_BASE__) return window.__SS_BASE__;
  if (/\.github\.io$/i.test(location.hostname)) {
    window.__SS_BASE__ = 'https://pinecone-lab.cn';
    return window.__SS_BASE__;
  }
  if (/^(localhost|127\.0\.0\.1|\[::1\])$/i.test(location.hostname)) {
    try {
      const r = await fetch('http://127.0.0.1:8081/api/health');
      if (r.ok) { window.__SS_BASE__ = 'http://127.0.0.1:8081'; return window.__SS_BASE__; }
    } catch (e) { /* 生产同源 */ }
  }
  return location.origin;
}

async function post(base, path, code) {
  const res = await fetch(base + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    let msg = 'HTTP ' + res.status;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch (e) { /* 非 JSON */ }
    throw new Error(msg);
  }
  return res.json();
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------------------ 通用块 */
function dimBlock(d) {
  if (!d.available) {
    return `<div class="dimhead"><h3>${esc(d.label)}</h3>` +
      `<div class="sc">N/A<small>权重 ${Math.round(d.weight * 100)}%</small></div></div>` +
      `<div class="fl n">${esc(d.na_reason || '该维不可用')}</div>`;
  }
  const rows = (d.metrics || []).map((m) => {
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
  // 杜邦三因子（ROE = 净利率 × 总资产周转率 × 权益乘数）
  // 只有盈利质量维有：它把 ROE 拆开，读者能看出「ROE 低是利润率低还是周转低」。
  const dp = d.dupont;
  const dpHtml = dp
    ? `<div class="note">杜邦拆解（ROE = 净利率 × 周转率 × 权益乘数）：净利率 ${num(dp.margin, 1)}%`
      + ` × 总资产周转率 ${num(dp.turnover, 2)} 次 × 权益乘数 ${num(dp.equity_mult, 2)}</div>`
    : '';
  return `<div class="dimhead"><h3>${esc(d.label)}</h3>` +
    `<div class="sc">${num(d.score, 1)}<small>权重 ${Math.round(d.weight * 100)}% · 置信 ${d.confidence}</small></div></div>` +
    '<table><thead><tr><th>子指标</th><th style="text-align:right">数值</th>' +
    '<th style="text-align:right">分位/刻度</th><th style="text-align:right">维内权重</th>' +
    `<th style="text-align:right">置信</th></tr></thead><tbody>${rows}</tbody></table>${dpHtml}${flags}${thresh}`;
}

function blocksHtml(list) {
  return (list || []).map((b) => `<div class="blk"><div class="h">${esc(b.h)}</div><div class="t">${esc(b.t)}</div></div>`).join('');
}

function gapsText(list) {
  return (list || []).map((g) => {
    if (g == null) return '';
    if (typeof g === 'string') return g;
    const label = g.label || g.key || '';
    const reason = g.reason || g.text || '';
    if (label && reason) return label + '：' + reason;
    return label || reason || String(g);
  }).filter(Boolean).join('；');
}

function factsHtml(facts, gaps) {
  const rows = (facts || []).map((f) => `<tr>
      <td class="k">${esc(f.label || f.key)}</td>
      <td class="v">${esc(f.text || f.value)}${f.source ? ` <span class="src">（${esc(f.source)}）</span>` : ''}</td>
    </tr>`).join('');
  const gapHtml = (gaps || []).length
    ? `<div class="deepnote">取不到的维度：${esc(gapsText(gaps))}。没有可靠公开数据源，页面不做估算。</div>` : '';
  if (!rows && !gapHtml) return '';
  return `<table class="facts">${rows}</table>${gapHtml}`;
}

/* ------------------------------------------------------------ 深度正文 */
function sectionHtml(s) {
  const paras = (s.text || '').split(/\n{2,}/).filter(Boolean)
    .map((p) => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
  const note = s.note ? `<div class="deepnote">${esc(s.note)}</div>` : '';
  return `<div class="deep"><h3>${esc(s.title)}</h3>${paras}${note}</div>`;
}

/* ------------------------------------------------------------ 总览页 */
function renderOverview(b) {
  const o = b.overview || {};
  const g = o.groups || {};
  const tag = o.tag || {};
  const gate = o.gate || {};

  const risks = (o.key_risks || []).map((r) => {
    const cls = r.level === 'red' ? 'r' : (r.level === 'yellow' ? 'y' : 'f');
    const mark = r.level === 'red' ? '🔴 ' : (r.level === 'yellow' ? '🟡 ' : '⚑ ');
    return `<div class="fl ${cls}">${mark}${esc(r.text)}</div>`;
  }).join('') || '<div class="fl n">未触发红旗、黄旗或已兑现风险标记。</div>';

  const gateNote = (gate.not_wired || []).length
    ? `<div class="fl n">未接入：${esc((gate.not_wired || []).join('、'))}（如实标注，不填 0）</div>` : '';

  const chk = Object.entries(o.investable_checks || {}).map(([k, v]) =>
    `<div class="${v ? 'ok' : 'no'}">${v ? '✅' : '❌'} ${esc(k)}</div>`).join('');

  const cards = ['quality', 'price', 'momentum', 'risk'].map((k) => {
    const m = (b.modules || {})[k] || {};
    const cls = k === 'quality' ? 'Q' : (k === 'price' ? 'V' : (k === 'momentum' ? 'M' : ''));
    const score = m.score === null || m.score === undefined ? '—' : num(m.score, 1);
    return `<a class="gcard ${cls}" href="${routeBase()}/${k}/?code=${encodeURIComponent(b.code)}">
      <div class="k">${esc(m.title || k)}</div>
      <div class="v">${score}</div>
      <div class="q">${esc(m.headline || '')}</div></a>`;
  }).join('');

  return `<div class="card"><div class="hero">
      <div><div class="big">${num(o.total, 1)}<small>分 · ${esc(o.tier)}</small></div>
        <div class="note" style="margin-top:8px">裸分 ${num(o.total_raw, 1)}${o.tier_note ? '　' + esc(o.tier_note) : ''}</div></div>
      <div class="meta"><span class="pill ${tagCls(tag.code)}">${esc(tag.label)}</span>
        <span class="pill ${tierCls(o.tier)}">档位 ${esc(o.tier)}</span>
        <span class="pill p-gray">红旗 ${(gate.red || []).length} · 黄旗 ${(gate.yellow || []).length}</span>
        <div class="note">${esc(tag.desc || '')}</div></div></div>
    </div>
    <div class="g3">${cards}</div></div>
    <div class="card"><h2 class="s">一句话结论<span class="w">先读这一句</span></h2>
      ${blocksHtml([{ h: '结论', t: o.one_liner || o.headline || '（暂无）' }])}
      <div class="note">${esc(o.headline || '')}</div></div>
    <div class="card"><h2 class="s">关键风险<span class="w">${(o.key_risks || []).length} 条</span></h2>${risks}${gateNote}</div>
    <div class="card"><h2 class="s">松果可投性（简化 11 步 + 市值）</h2><div class="chk">${chk}</div>
      <div class="note">完整 V35 管线含 VC∈[0.90,0.99]、行业软调节、红旗删票不补位；
        本卡用可公开验证的简化口径做代理，标签含义为「落在射程内与否」，不等于买入建议。</div></div>
    <div class="card"><h2 class="s">四个深度分页<span class="w">同一份数据，不同切面</span></h2>
      <div class="note">质地（业务结构＋差异化壁垒）、价格（数字检验＋估值与预期）、
        势能（市场空间）、风险（风险与安全＋关键矛盾＋审读意见）。
        每页都带对应的评分卡支撑数据与事实证据，数字与本页同源。</div>
      <a class="btn" href="${routeBase()}/quality/?code=${encodeURIComponent(b.code)}">从质地开始看 →</a></div>`;
}

/* ------------------------------------------------------------ 深度分页 */
function renderModule(b, key) {
  const m = (b.modules || {})[key] || {};
  const dims = (m.dims || []).map(dimBlock).join('');
  const secs = (m.sections || []).map(sectionHtml).join('');
  const blocks = blocksHtml(m.blocks);

  const head = `<div class="card"><div class="hero">
      <div><div class="big">${m.score === null || m.score === undefined ? '—' : num(m.score, 1)}<small>${esc(m.title || '')}</small></div>
        <div class="note" style="margin-top:8px">${esc(m.headline || '')}</div></div>
      <div class="meta"><span class="pill p-gray">外部深度数据 ${esc(b.coverage || '—')} 级</span>
        <span class="pill p-gray">研报 ${esc(b.research_reports || 0)} 篇</span></div></div></div>`;

  const dimCard = dims
    ? `<div class="card"><h2 class="s">评分卡支撑数据<span class="w">这一页的维度</span></h2>${dims}</div>` : '';

  let extra = '';
  if (key === 'price') {
    extra = factsHtml(m.valuation_facts, m.valuation_gaps);
    if (extra) extra = `<div class="card"><h2 class="s">估值事实<span class="w">可溯源数字</span></h2>${extra}</div>`;
  } else if (key === 'momentum') {
    const ind = (m.industry_facts || []);
    if (ind.length) {
      extra = `<div class="card"><h2 class="s">行业结构数据<span class="w">申万成分股实算</span></h2>
        <table class="facts">${ind.map((t) => `<tr><td class="v">${esc(t)}</td></tr>`).join('')}</table></div>`;
    }
  } else if (key === 'risk') {
    const flags = (m.risk_flags || []).map((f) => `<div class="fl r"><b>${esc(f.label || '已兑现风险')}</b>　${esc(f.text || '')}</div>`).join('')
      || '<div class="fl n">确定性指标未触发任何红旗阈值。只说明已量化的风险项没越线，不代表没有风险。</div>';
    const rf = factsHtml(m.risk_facts, m.risk_gaps);
    const contra = (m.contradictions || []);
    const contraHtml = contra.length
      ? `<div class="card"><h2 class="s">跨段矛盾<span class="w">${contra.length} 处</span></h2>
        <ul class="issues">${contra.map((c) => `<li><span class="ty high">矛盾</span>${esc(c.detail)}
          ${c.a_text ? `<br><span class="src">${esc(c.a)}：${esc(c.a_text)}</span>` : ''}
          ${c.b_text ? `<br><span class="src">${esc(c.b)}：${esc(c.b_text)}</span>` : ''}</li>`).join('')}</ul></div>` : '';
    const issues = (m.critic && m.critic.issues) || [];
    const issueHtml = issues.length
      ? `<div class="card"><h2 class="s">审读意见<span class="w">${issues.length} 条</span></h2>
        <ul class="issues">${issues.map((i) => `<li><span class="ty ${esc(i.severity || '')}">${esc(i.type || '')}</span>
          ${esc(i.problem || '')}${i.fix ? `<br><span class="src">改法：${esc(i.fix)}</span>` : ''}</li>`).join('')}</ul>
        ${m.critic.summary ? `<div class="note">${esc(m.critic.summary)}</div>` : ''}</div>` : '';
    const unres = (m.unresolved || []).length
      ? `<div class="card"><h2 class="s">未解问题<span class="w">如实披露</span></h2>
        <ul class="issues">${m.unresolved.map((i) => `<li><span class="ty high">${esc(i.severity || 'high')}</span>
          ${esc(i.problem || '')}${i.fix ? `　改法：${esc(i.fix)}` : ''}</li>`).join('')}</ul></div>` : '';
    extra = `<div class="card"><h2 class="s">风险与安全<span class="w">只报命中的红旗</span></h2>${flags}
        ${rf ? `<h2 class="s" style="margin-top:16px">风险事实</h2>${rf}` : ''}</div>`
      + contraHtml + issueHtml + unres;
  }

  const deepBox = `<div class="card"><h2 class="s">深度分析<span class="w" id="ss3-prog"></span></h2>
    <div id="ss3-deep">${secs || '<div class="waiting">深度分析正在生成中…</div>'}</div></div>`;

  const concl = blocks ? `<div class="card"><h2 class="s">结论</h2>${blocks}</div>` : '';

  return head + deepBox + dimCard + extra + concl;
}

/* ------------------------------------------------------------ 深度正文增量轮询 */
async function pollDeep(base, code, mount, expectKeys) {
  const box = document.getElementById('ss3-deep');
  const prog = document.getElementById('ss3-prog');
  if (!box) return;
  let seen = 0;
  for (let i = 0; i < 400; i++) {
    let d;
    try {
      d = await post(base, '/api/stockscore_v3_deep_progress', code);
    } catch (e) {
      if (prog) prog.textContent = '（连接中断，重试中）';
      await sleep(3000);
      continue;
    }
    const secs = d.sections || [];
    const mine = expectKeys
      ? secs.filter((s) => expectKeys.indexOf(s.key) >= 0)
      : secs;
    if (mine.length !== seen) {
      seen = mine.length;
      box.innerHTML = mine.map(sectionHtml).join('') ||
        '<div class="waiting">深度分析正在生成中…</div>';
      if (prog) {
        prog.textContent = d.state === 'done'
          ? `已完成 ${secs.length} 段 · ${d.total_chars || 0} 字`
          : `已出 ${mine.length} 段 · ${d.total_chars || 0} 字 · 用时 ${d.elapsed || 0}s`;
      }
    }
    if (d.state === 'done') {
      // 完成后再拉一次 bundle，把矛盾/审读等终态信息补上
      try {
        const b = await post(base, '/api/stockscore_v3_bundle', code);
        mount(b);
      } catch (e) { /* 保留已有内容 */ }
      return;
    }
    if (d.state === 'error') {
      box.innerHTML = `<div class="fl r">深度分析生成失败：${esc(d.error || '未知错误')}</div>`;
      return;
    }
    await sleep(2000);
  }
}

/* ------------------------------------------------------------ 表单 */
function formHtml() {
  return `<div class="card"><h2 class="s">输入股票代码或名称</h2>
    <div class="form"><input id="ss3code" placeholder="如 600519 或 贵州茅台" autocomplete="off" spellcheck="false">
    <button id="ss3go">开始打分</button></div>
    <div id="ss3hint" class="note">支持 6 位代码、股票全称或简称（贵州茅台 / 茅台 / 农行）。
      首次查询需现建全市场横截面宇宙（约 1-2 分钟，期间会自动重试）；10 分钟内同码命中缓存秒回。</div></div>`;
}

function candidateHtml(cs) {
  return `<div class="card"><h2 class="s">找到 ${cs.length} 只，请选择</h2>
    <div class="cands">${cs.map((c) => `<button class="cand" data-code="${esc(c.code)}">
      <span class="cd">${esc(c.code)}</span><span class="cn">${esc(c.name)}</span>
      <span class="cm">${esc(c.market || '')}</span></button>`).join('')}</div>
    <div class="note"><a href="${location.pathname}">← 重新输入</a>　也可以直接输入 6 位代码精确定位。</div></div>`;
}

function mountForm(root, prefill) {
  const input = document.getElementById('ss3code');
  const btn = document.getElementById('ss3go');
  const hint = document.getElementById('ss3hint');
  const defaultHint = hint.innerHTML;
  const reset = (msg) => {
    btn.disabled = false; input.disabled = false;
    hint.innerHTML = msg || defaultHint; input.focus();
  };
  const go = async () => {
    const v = (input.value || '').trim();
    if (!v) { input.focus(); return; }
    if (/^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(v)) {
      location.search = '?code=' + v.replace(/\D/g, '');
      return;
    }
    btn.disabled = true; input.disabled = true;
    hint.innerHTML = '正在识别「' + esc(v) + '」…';
    try {
      const base = await apiBase();
      const res = await fetch(base + '/api/stockscore_resolve?q=' + encodeURIComponent(v));
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const d = await res.json();
      const cs = d.candidates || [];
      if (!cs.length) {
        reset(d.hint === 'latin' ? '暂只支持中文名称或 6 位代码（拼音暂不支持）。'
          : '未找到「' + esc(v) + '」，换个写法试试，或直接输入 6 位代码。');
        return;
      }
      if (cs.length === 1 || d.exact) { location.search = '?code=' + cs[0].code; return; }
      root.innerHTML = candidateHtml(cs);
      Array.prototype.forEach.call(root.querySelectorAll('.cand'), (b) => {
        b.onclick = () => { location.search = '?code=' + b.dataset.code; };
      });
    } catch (e) {
      reset('识别服务暂时不可用（' + esc(e.message) + '），请直接输入 6 位代码。');
    }
  };
  btn.onclick = go;
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  if (prefill) { input.value = prefill; go(); }
  else input.focus();
}

/* ------------------------------------------------------------ 入口 */
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
  const raw = (params.get('code') || params.get('q') || '').trim();
  const isCode = /^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(raw);
  const code = isCode ? raw.replace(/\D/g, '') : '';

  if (!code) {
    root.innerHTML = formHtml();
    mountForm(root, raw);
    return;
  }

  const isOverview = view === 'index';
  root.innerHTML = `<div class="card"><div class="note">${isOverview
    ? '正在计算（首次约 1-2 分钟建全市场宇宙，之后同码 10 分钟内秒回）…'
    : '正在取数…'}</div></div>`;

  let base;
  try {
    base = await apiBase();
  } catch (e) {
    root.innerHTML = `<div class="card"><div class="fl r">无法连接后端：${esc(e.message)}</div></div>`;
    return;
  }

  // bundle 失败重试（冷启动可能 504）
  let bundle = null;
  for (let i = 1; i <= 6; i++) {
    try {
      bundle = await post(base, '/api/stockscore_v3_bundle', code);
      break;
    } catch (e) {
      if (i === 6) {
        root.innerHTML = `<div class="card"><div class="fl r">查询失败：${esc(e.message)}</div>
          <div class="note"><a href="${location.pathname}">重新输入代码</a></div></div>`;
        return;
      }
      root.innerHTML = `<div class="card"><div class="note">后端正在建全市场横截面宇宙，已自动重试 ${i}/6 次…</div></div>`;
      await sleep(20000);
    }
  }
  if (!bundle) return;

  const render = () => {
    const head = identBar(bundle) + navBar(bundle.code, view);
    const body = isOverview ? renderOverview(bundle) : renderModule(bundle, view);
    const errs = (bundle.source_errors || []).length
      ? '<br>取数告警：' + esc(bundle.source_errors.join('；')) : '';
    const foot = `<div class="foot">总分 = 0.52×Q + 0.26×V + 0.22×M，再过闸门（🔴封顶59 / 🟡≥2降一档 / 🟡=1仅标注）。
      缺失子项不进分母、整维缺失标 N/A 不填 0；每个分数带置信度，&lt;0.6 进低置信清单。<br>
      深度分析的每个数字都来自可溯源的公开数据或券商研报原文抽取；研报观点仅代表分析师判断，不构成本站观点。
      本页所有数字由公开数据按页面写明口径计算，数据可能有误、口径有局限，请自行复核。<br>
      结构化读数不构成投资建议，不预测涨跌，不含任何买卖意见。${errs}</div>`;
    root.innerHTML = head + body + foot;
  };

  render();

  // 总览页后台预热深度分析 → 用户点进深度页时近 0 秒读缓存
  // 顺序要点：必须等 bundle 拿到（v3 payload 已进后端 10 分钟内存缓存），
  // 预热线程再算时 v3 就是秒回，否则预热自己要重跑 45s 全市场横截面。
  if (isOverview) {
    try {
      await post(base, '/api/stockscore_v3_deep_prewarm', code);
    } catch (e) { /* 预热失败不影响总览 */ }
  } else {
    // 深度分页：轮询增量，先出首段
    const expect = { quality: ['business', 'moat'], price: ['numbers', 'valuation'],
                     momentum: ['market'], risk: ['risk'] }[view] || null;
    pollDeep(base, code, render, expect);
  }
}
