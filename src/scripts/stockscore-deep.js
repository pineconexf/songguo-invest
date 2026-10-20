// 个股深度分析前端模块（2026-10-20）
// 新增第五个页面 deep：六段深度分析 + 估值与预期 + 风险与安全 + 元宝口播版。
// 数据分别来自三个端点，可各自独立失败（互不拖累）。

const STYLE = `
.sd{--ink:#1a1f26;--ink2:#33404d;--muted:#67737f;--faint:#8d99a4;--line:#e2e6ec;--line2:#eef1f4;
--green:#146b52;--green-l:#e8f2ee;--green-b:#cfe3da;--gold:#a97c2f;--gold-l:#faf3e6;--gold-b:#ecdcbf;
--red:#b3392c;--red-l:#fbeeec;--red-b:#f0cfca;--blue:#2c5f8a;--blue-l:#eaf1f7;--blue-b:#cddcea;
max-width:1000px;margin:0 auto;padding:0 4px 48px;color:var(--ink);font-size:14.5px;line-height:1.75}
.sd .ident{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;margin:4px 0 2px}
.sd .ident h1{margin:0;font-size:25px;font-weight:800;letter-spacing:-.01em}
.sd .ident .code{font-size:13.5px;color:var(--faint);font-variant-numeric:tabular-nums}
.sd .ident .ind{font-size:12.5px;color:var(--muted);background:#fff;border:1px solid var(--line);padding:2px 9px;border-radius:5px}
.sd .nav{display:flex;gap:2px;margin:16px 0 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}
.sd .nav a{padding:9px 16px;font-size:13.5px;font-weight:600;color:var(--muted);text-decoration:none;border-bottom:2px solid transparent;margin-bottom:-1px}
.sd .nav a.on{color:var(--green);border-bottom-color:var(--green)}
.sd .card{background:#fff;border:1px solid var(--line);border-radius:11px;padding:20px 22px;margin-bottom:14px}
.sd h2.s{font-size:15px;font-weight:800;margin:0 0 14px;padding-bottom:9px;border-bottom:1px solid var(--line2)}
.sd h2.s .w{float:right;font-size:12px;font-weight:600;color:var(--faint)}
.sd .note{font-size:12.5px;color:var(--muted);margin-top:10px;line-height:1.6}
.sd .sec{margin-bottom:22px}
.sd h3.sub{font-size:13.5px;color:var(--muted);font-weight:600;margin:18px 0 8px;padding-top:12px;border-top:1px solid var(--border)}
.sd .card h3.sub:first-of-type{margin-top:14px}
.sd .sec:last-child{margin-bottom:0}
.sd .sec h3{font-size:14.5px;font-weight:800;margin:0 0 9px;padding-left:10px;border-left:3px solid var(--green);line-height:1.5}
.sd .sec p{margin:0 0 10px}
.sd .sec p:last-child{margin-bottom:0}
.sd .gap{font-size:13px;color:var(--gold);background:var(--gold-l);border:1px solid var(--gold-b);
  border-radius:7px;padding:8px 11px;margin:6px 0}
.sd .flag{border:1px solid var(--red-b);background:var(--red-l);border-radius:8px;padding:10px 13px;margin-bottom:9px}
.sd .flag .t{font-size:13.5px;font-weight:700;color:var(--red);display:block;margin-bottom:2px}
.sd .flag .d{font-size:13px;color:var(--ink2)}
.sd .ok{border:1px solid var(--green-b);background:var(--green-l);border-radius:8px;padding:10px 13px;font-size:13px;color:var(--green)}
.sd .facts{width:100%;border-collapse:collapse;font-size:13.5px}
.sd .facts td{padding:7px 0;border-bottom:1px solid var(--line2);vertical-align:top}
.sd .facts tr:last-child td{border-bottom:none}
.sd .facts .k{color:var(--muted);width:190px;padding-right:12px}
.sd .facts .v{font-variant-numeric:tabular-nums}
.sd .facts .src{color:var(--faint);font-size:12px}
.sd .talk{background:#fcfcfd;border:1px solid var(--line);border-radius:9px;padding:15px 17px;
  font-size:14.5px;line-height:1.85;white-space:pre-wrap}
.sd .talk p{margin:0 0 11px}
.sd .talk p:last-child{margin-bottom:0}
.sd .talk .cp{float:right;font-size:12px;color:var(--faint);cursor:pointer;user-select:none;
  background:#fff;border:1px solid var(--line);border-radius:5px;padding:2px 9px}
.sd .meta{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.sd .meta span{font-size:12px;font-weight:700;padding:3px 10px;border-radius:5px;background:#f1f3f5;color:var(--muted);border:1px solid var(--line)}
.sd .meta span.A{background:var(--green-l);color:var(--green);border-color:var(--green-b)}
.sd .meta span.B{background:var(--gold-l);color:var(--gold);border-color:var(--gold-b)}
.sd .meta span.C{background:var(--red-l);color:var(--red);border-color:var(--red-b)}
.sd .issues{font-size:13px;color:var(--ink2)}
.sd .issues li{margin-bottom:6px}
.sd .issues .ty{font-size:11.5px;font-weight:700;color:var(--faint);margin-right:6px}
.sd .issues .high{color:var(--red)}
.sd .issues .medium{color:var(--gold)}
.sd .loading{color:var(--muted);font-size:13.5px;padding:14px 0}
.sd .foot{font-size:12px;color:var(--faint);line-height:1.65;margin-top:18px}
.sd a.btn{display:inline-block;font-size:13px;font-weight:600;color:var(--green);
  border:1px solid var(--green-b);background:var(--green-l);border-radius:6px;
  padding:5px 13px;text-decoration:none;margin-top:8px}
@media (max-width:640px){
.sd{padding:0 2px 36px;font-size:15px}
.sd .card{padding:16px 15px}
.sd .ident h1{font-size:21px}
.sd .facts .k{width:auto;display:block;padding-bottom:2px}
.sd .facts td.k{padding-bottom:0}
.sd .sec h3{font-size:15px}
.sd .talk{font-size:15.5px;padding:13px 14px}
}`;

const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const VIEWS = [
  ['index', '总览', 'overview'],
  ['quality', '质地', 'quality'],
  ['price', '价格', 'price'],
  ['momentum', '势能', 'momentum'],
  ['deep', '深度', 'deep'],
];

function routeBase() {
  const p = location.pathname.replace(/\/+$/, '');
  const m = p.match(/^(.*\/stockscore)(?:\/(?:index|quality|price|momentum|deep))?$/);
  return m ? m[1] : p;
}

function navBar(code, active) {
  const base = routeBase();
  return '<div class="nav">' + VIEWS.map(([k, label]) =>
    `<a class="${k === active ? 'on' : ''}" href="${base}${k === 'index' ? '' : '/' + k}/?code=${encodeURIComponent(code)}">${label}</a>`
  ).join('') + '</div>';
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
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch (e) { /* 非 JSON 错误体 */ }
    throw new Error(msg);
  }
  return res.json();
}

/* ---------------------------------------------------------------- 估值与预期 */
function valFactsHtml(vb) {
  if (!vb || !vb.facts || !vb.facts.length) return '';
  const rows = vb.facts.map((f) => `<tr>
    <td class="k">${esc(f.label || f.key)}</td>
    <td class="v">${esc(f.text || f.value)}${f.source ? ` <span class="src">（${esc(f.source)}）</span>` : ''}</td>
  </tr>`).join('');
  const gaps = (vb.gaps || []).length
    ? `<div class="gap">取不到的维度：${esc(gapsText(vb.gaps))}。这些没有可靠公开数据源，页面不做估算。</div>`
    : '';
  return `<div class="card"><h2 class="s">估值与预期<span class="w">分位是刻度，估值方法是锚</span></h2>
    <table class="facts">${rows}</table>${gaps}</div>`;
}

/* ---------------------------------------------------------------- 风险与安全 */
function riskFactsHtml(kb) {
  if (!kb) return '';
  const flags = kb.flags || [];
  const flagHtml = flags.length
    ? flags.map((f) => `<div class="flag"><span class="t">${esc(f.label || '已兑现风险')}</span>
        <span class="d">${esc(f.text || '')}</span></div>`).join('')
    : `<div class="ok">确定性指标未触发任何红旗阈值。注意：这只说明已量化的风险项没越线，不代表没有风险。</div>`;
  const rows = (kb.facts || []).map((f) => `<tr>
    <td class="k">${esc(f.label || f.key)}</td>
    <td class="v">${esc(f.text || f.value)}${f.source ? ` <span class="src">（${esc(f.source)}）</span>` : ''}</td>
  </tr>`).join('');
  const gaps = (kb.gaps || []).length
    ? `<div class="gap">取不到的维度：${esc(gapsText(kb.gaps))}。没有可靠数据源就不估算。</div>`
    : '';
  return `<div class="card"><h2 class="s">风险与安全<span class="w">只报命中的红旗</span></h2>
    ${flagHtml}
    ${rows ? `<table class="facts">${rows}</table>` : ''}
    ${gaps}</div>`;
}

/* gaps 归一化：后端返回 [{key,label,reason}]，页面要显示「标签：原因」而不是 [object Object] */
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

/* ---------------------------------------------------------------- 行业结构 */
function industryHtml(ind) {
  if (!ind) return '';
  const c = ind.concentration || {};
  const g = ind.growth || {};
  const ix = ind.index || {};
  const cls = ind.classification || {};
  const chain = [cls.l1_name, cls.l2_name, cls.l3_name].filter(Boolean).join(' → ');
  const r = (k, v, unit) => (v === undefined || v === null || v === '')
    ? '' : `<tr><td class="k">${esc(k)}</td><td class="v">${esc(v)}${unit ? ' ' + unit : ''}</td></tr>`;
  const concRows = [
    r('成分股样本数', c.sample_n, '只'),
    r('行业集中度 CR3', c.cr3, '%'),
    r('CR5', c.cr5, '%'),
    r('CR10', c.cr10, '%'),
    r('CR20', c.cr20, '%'),
    r('HHI（赫芬达尔指数）', c.hhi, c.hhi_level ? `· ${c.hhi_level}` : ''),
    r('行业 PE 中位数', c.pe_median),
    r('行业 PB 中位数', c.pb_median),
    r('本股市值占行业比重', c.target_mv_share_pct, '%'),
    r('本股 PE(TTM)', c.target_pe_ttm),
    r('本股 PB', c.target_pb),
  ].join('');
  const growRows = [
    r('营收同比中位数', g.or_yoy_median_pct, '%'),
    r('营收同比均值', g.or_yoy_mean_pct, '%'),
    r('营收正增长占比', g.or_yoy_positive_ratio_pct, '%'),
    r('净利同比中位数', g.netprofit_yoy_median_pct, '%'),
    r('净利为正占比', g.netprofit_positive_ratio_pct, '%'),
  ].join('');
  const idxRows = [
    r('近20日涨跌中位数', ix.chg_20d_pct, '%'),
    r('近60日涨跌中位数', ix.chg_60d_pct, '%'),
  ].join('');
  const notes = (ind.notes || []).map((n) => `<div class="gap">${esc(n)}</div>`).join('');
  const cal = [c.caliber, c.method, g.caliber, ix.caliber].filter(Boolean);
  const calHtml = cal.length
    ? `<div class="note">口径说明：${cal.map(esc).join(' ｜ ')}</div>` : '';
  return `<div class="card"><h2 class="s">行业结构<span class="w">${esc(chain || '同业坐标')}</span></h2>
    ${notes}
    <table class="facts">${concRows}</table>
    <h3 class="sub">同业经营景气度</h3>
    <table class="facts">${growRows}</table>
    <h3 class="sub">板块区间表现</h3>
    <table class="facts">${idxRows}</table>
    ${calHtml}</div>`;
}

/* ---------------------------------------------------------------- 深度正文 */
function deepHtml(d) {
  if (!d) return '';
  const secs = (d.sections || []).map((s) => {
    const gap = s.note ? `<div class="gap">${esc(s.note)}</div>` : '';
    return `<div class="sec"><h3>${esc(s.title)}</h3>
      ${(s.text || '').split(/\n{2,}/).filter(Boolean).map((p) => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('')}
      ${gap}</div>`;
  }).join('');

  const issues = (d.critic && d.critic.issues) || [];
  const issueHtml = issues.length
    ? `<div class="card"><h2 class="s">审读意见<span class="w">${issues.length} 条</span></h2>
      <ul class="issues">${issues.map((i) => `<li><span class="ty ${esc(i.severity || '')}">${esc(i.type || '')}</span>
        ${esc(i.problem || '')}${i.fix ? `<br><span class="src">改法：${esc(i.fix)}</span>` : ''}</li>`).join('')}</ul>
      ${d.critic.summary ? `<div class="note">${esc(d.critic.summary)}</div>` : ''}</div>`
    : '';

  const contra = (d.contradictions || []) || [];
  const contraHtml = contra.length
    ? `<div class="card"><h2 class="s">跨段矛盾<span class="w">${contra.length} 处</span></h2>
      <ul class="issues">${contra.map((c) => `<li><span class="ty high">矛盾</span>${esc(c.detail)}
        ${c.a_text ? `<br><span class="src">${esc(c.a)}：${esc(c.a_text)}</span>` : ''}
        ${c.b_text ? `<br><span class="src">${esc(c.b)}：${esc(c.b_text)}</span>` : ''}</li>`).join('')}</ul></div>`
    : '';

  const covCls = d.coverage === 'A' ? 'A' : (d.coverage === 'B' ? 'B' : 'C');
  const meta = `<div class="meta">
    <span class="${covCls}">外部深度数据 ${esc(d.coverage || '—')} 级</span>
    <span>研报 ${esc(d.research_reports || 0)} 篇</span>
    <span>正文 ${esc(d.total_chars || 0)} 字</span>
    ${d.rewrite_rounds ? `<span class="A">审读重写 ${esc(d.rewrite_rounds)} 轮</span>` : ''}
    ${d.unverified_numbers && d.unverified_numbers.length
      ? `<span class="C">${d.unverified_numbers.length} 个数字待核</span>`
      : `<span class="A">数字全部可溯源</span>`}
  </div>`;

  const note = d.coverage_note ? `<div class="note">${esc(d.coverage_note)}</div>` : '';

  return `<div class="card"><h2 class="s">深度分析<span class="w">逐段生成 · 数字回验</span></h2>
    ${meta}${secs}${note}</div>${industryHtml(d.industry)}${contraHtml}${issueHtml}`;
}

/* ---------------------------------------------------------------- 元宝口播版 */
function talkHtml(s) {
  if (!s) return '';
  const paras = (s.text || '').split(/\n{2,}/).filter(Boolean)
    .map((p) => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
  return `<div class="card"><h2 class="s">口播版 · 通勤路上听<span class="w">${esc(s.chars || 0)} 字</span></h2>
    <div class="meta"><span>${esc(s.source === 'llm' ? 'AI 生成' : '规则兜底')}</span>
      <span>覆盖 ${esc(s.coverage || '—')} 级</span></div>
    <div class="talk" id="sd-talk">${paras}</div>
    <div class="note">复制这段可以直接发给元宝或朗读。纯口语、无符号表格，数字与上文同源。</div>
    <a class="btn" id="sd-copy">复制口播稿</a></div>`;
}

/* ---------------------------------------------------------------- 主渲染 */
function identBar(p) {
  return `<div class="ident"><h1>${esc(p.name)}</h1><span class="code">${esc(p.code)}</span>
    ${p.industry ? `<span class="ind">${esc(p.industry)}</span>` : ''}
    ${p.data_asof ? `<span class="ind">数据 ${esc(p.data_asof)}</span>` : ''}</div>`;
}

export async function mountDeep() {
  const root = document.getElementById('ss3-root');
  if (!root) return;
  if (!document.getElementById('sd-style')) {
    const st = document.createElement('style');
    st.id = 'sd-style';
    st.textContent = STYLE;
    document.head.appendChild(st);
  }
  root.className = 'sd';

  const params = new URLSearchParams(location.search);
  const raw = (params.get('code') || '').trim();
  const isCode = /^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(raw);
  const code = isCode ? raw.replace(/\D/g, '') : '';

  if (!code) {
    root.innerHTML = `<div class="card"><h2 class="s">输入股票代码</h2>
      <div class="form"><input id="sdcode" placeholder="如 600519" autocomplete="off" spellcheck="false">
      <button id="sdgo">看深度分析</button></div>
      <div class="note">深度分析需要现抓券商研报并逐段生成，首次约 2-4 分钟，之后当天秒回。</div></div>`;
    const btn = document.getElementById('sdgo');
    const inp = document.getElementById('sdcode');
    const go = () => {
      const v = (inp.value || '').replace(/\D/g, '');
      if (v.length === 6) location.href = routeBase() + '/deep/?code=' + v;
      else if (inp.value) { inp.value = ''; inp.placeholder = '请输入6位股票代码'; }
    };
    btn.addEventListener('click', go);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    return;
  }

  root.innerHTML = `<div class="card"><div class="loading">正在抓取券商研报并逐段生成深度分析（约 2-4 分钟）…</div></div>`;

  let base;
  try {
    base = await apiBase();
  } catch (e) {
    root.innerHTML = `<div class="card"><div class="loading">无法连接后端：${esc(e.message)}</div></div>`;
    return;
  }

  // 先取基本信息和估值/风险模块（快），再取深度正文（慢）
  let payload = null, mods = null;
  try {
    payload = await post(base, '/api/stockscore_v3', code);
  } catch (e) { /* 模块接口会自己再取 */ }
  try {
    mods = await post(base, '/api/stockscore_v3_modules', code);
  } catch (e) {
    mods = null;
  }

  const head = (payload || mods)
    ? identBar(payload || { code, name: code }) + navBar(code, 'deep')
    : navBar(code, 'deep');

  root.innerHTML = head + `<div id="sd-mods"></div><div id="sd-deep"></div><div id="sd-talkbox"></div>`;

  if (mods) {
    document.getElementById('sd-mods').innerHTML =
      valFactsHtml(mods.valuation) + riskFactsHtml(mods.risk);
  }

  try {
    const d = await post(base, '/api/stockscore_v3_deep', code);
    document.getElementById('sd-deep').innerHTML = deepHtml(d);
  } catch (e) {
    document.getElementById('sd-deep').innerHTML =
      `<div class="card"><div class="loading">深度分析生成失败：${esc(e.message)}</div></div>`;
  }

  try {
    const s = await post(base, '/api/stockscore_v3_summary', code);
    document.getElementById('sd-talkbox').innerHTML = talkHtml(s);
    const cp = document.getElementById('sd-copy');
    if (cp) {
      cp.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(s.text || '');
          cp.textContent = '已复制';
          setTimeout(() => { cp.textContent = '复制口播稿'; }, 1800);
        } catch (e) { cp.textContent = '复制失败，手动选中文本'; }
      });
    }
  } catch (e) {
    document.getElementById('sd-talkbox').innerHTML =
      `<div class="card"><div class="loading">口播版生成失败：${esc(e.message)}</div></div>`;
  }

  root.insertAdjacentHTML('beforeend', `<div class="foot">
    深度分析的每个数字都来自可溯源的公开数据或券商研报原文抽取；研报观点仅代表分析师判断，不构成本站观点。
    正文由模型分段生成后做了数字回验与跨段矛盾检测，仍可能存在遗漏或误判，请自行复核。
    本页不预测涨跌，不含任何买卖意见，不构成投资建议。</div>`);
}
