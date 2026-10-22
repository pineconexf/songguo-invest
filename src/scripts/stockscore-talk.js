// 个股打分卡 · 元宝口播版（手机端专用页）
// 2026-10-20
// 设计要点：
//  1) 只调 /api/stockscore_v3_summary，不触发 deep 生成——手机上秒回，不等 2-4 分钟。
//  2) 排版按手机改：字号放大、段落间距加大、按钮做到底部拇指区。
//  3) 提供复制 + 系统分享（可直接分享到元宝/微信）。
//  4) 纯口语、无 Markdown、无符号列表、不含操作建议。

const STYLE = `
.tk{--ink:#1a1f26;--ink2:#33404d;--muted:#67737f;--faint:#8d99a4;--line:#e2e6ec;
--green:#146b52;--green-l:#e8f2ee;--green-b:#cfe3da;--gold:#a97c2f;--gold-l:#faf3e6;--gold-b:#ecdcbf;
max-width:720px;margin:0 auto;padding:0 18px 120px;color:var(--ink);
font-size:17px;line-height:1.95;-webkit-text-size-adjust:100%}
.tk .ident{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin:2px 0 4px}
.tk .ident h1{margin:0;font-size:26px;font-weight:800;letter-spacing:-.01em}
.tk .ident .code{font-size:15px;color:var(--faint);font-variant-numeric:tabular-nums}
.tk .ident .ind{font-size:13px;color:var(--muted);background:#fff;border:1px solid var(--line);padding:2px 9px;border-radius:5px}
.tk .nav{display:flex;gap:2px;margin:14px 0 18px;border-bottom:1px solid var(--line);overflow-x:auto;-webkit-overflow-scrolling:touch}
.tk .nav a{padding:10px 14px;font-size:14px;font-weight:600;color:var(--muted);text-decoration:none;
  border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tk .nav a.on{color:var(--green);border-bottom-color:var(--green)}
.tk .meta{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}
.tk .meta span{font-size:12.5px;font-weight:700;padding:4px 11px;border-radius:5px;background:#f1f3f5;color:var(--muted);border:1px solid var(--line)}
.tk .talk{background:#fff;border:1px solid var(--line);border-radius:11px;padding:20px 18px}
.tk .talk p{margin:0 0 15px}
.tk .talk p:last-child{margin-bottom:0}
.tk .note{font-size:13.5px;color:var(--muted);margin-top:12px;line-height:1.75}
.tk .gap{font-size:14px;color:var(--gold);background:var(--gold-l);border:1px solid var(--gold-b);
  border-radius:8px;padding:9px 13px;margin:0 0 16px}
.tk .loading{background:#fff;border:1px solid var(--line);border-radius:11px;padding:22px 18px;color:var(--muted);font-size:15.5px}
.tk .form{background:#fff;border:1px solid var(--line);border-radius:11px;padding:18px}
.tk .form input{width:100%;box-sizing:border-box;padding:12px 13px;font-size:16px;
  border:1px solid var(--line);border-radius:8px;margin-bottom:10px}
.tk .form button{width:100%;padding:13px;font-size:16px;font-weight:700;border:0;border-radius:8px;
  background:var(--green);color:#fff;cursor:pointer}
.tk .acts{position:fixed;left:0;right:0;bottom:0;z-index:50;background:rgba(255,255,255,.96);
  backdrop-filter:saturate(1.6) blur(8px);border-top:1px solid var(--line);
  padding:10px 18px calc(10px + env(safe-area-inset-bottom));display:flex;gap:10px}
.tk .acts button{flex:1;padding:13px;font-size:15.5px;font-weight:700;border-radius:9px;cursor:pointer}
.tk .acts .cp{background:var(--green);color:#fff;border:0}
.tk .acts .sh{background:#fff;color:var(--green);border:1px solid var(--green-b)}
.tk .foot{font-size:12.5px;color:var(--faint);line-height:1.75;margin-top:26px}
.tk .rule{background:var(--gold-l);border:1px solid var(--gold-b);border-radius:9px;
  padding:11px 14px;font-size:14px;color:var(--ink2);margin:0 0 18px}
.tk .rule b{color:var(--gold)}
@media (max-width:420px){
  .tk{font-size:16.5px;padding:0 14px 116px}
  .tk .ident h1{font-size:23px}
}
`;

const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// 2026-10-21：导航与打分卡主结构对齐（总览 + 质地/价格/势能/风险），
// 去掉已废弃的 deep 页，避免出现点进去是重定向的空 tab。
const VIEWS = [
  ['index', '总览', 'overview'],
  ['quality', '质地', 'quality'],
  ['price', '价格', 'price'],
  ['momentum', '势能', 'momentum'],
  ['risk', '风险', 'risk'],
];

function routeBase() {
  // 坑（2026-10-20 修）：原来这里用 /\/tools\/stockscore(\/[^/]*)?/ 去 pathname 里找片段，
  // 拼出来的 base 丢了子路径前缀。线上 base 是 /songguo-invest（GitHub Pages 子路径），
  // 丢前缀 → 导航 href 指向根路径 /tools/... → 线上一点就 404；
  // 本地 serve_dist 剥掉前缀后反而"能用"，所以本地测不出来，只有线上炸。
  // 现在和 stockscore-v3.js 用同一套写法：保留前缀。
  const p = location.pathname.replace(/\/+$/, '');
  const m = p.match(/^(.*\/stockscore)(?:\/(?:index|quality|price|momentum|risk|talk))?$/);
  return m ? m[1] : p;
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
    } catch (e) { /* 落到部署域名 */ }
  }
  window.__SS_BASE__ = location.origin;
  return window.__SS_BASE__;
}

async function post(base, path, code) {
  const r = await fetch(base + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.success === false) {
    throw new Error(j.error || j.detail || ('接口返回 ' + r.status));
  }
  return j;
}

function navBar(code, active) {
  const base = routeBase();
  return '<div class="nav">' + VIEWS.map(([k, label]) =>
    `<a class="${k === active ? 'on' : ''}" href="${base}${k === 'index' ? '' : '/' + k}/?code=${encodeURIComponent(code)}">${label}</a>`
  ).join('') + '</div>';
}

/* 口播稿正文。纯口语，段落即停顿点。 */
function talkHtml(s) {
  const paras = (s.text || '').split(/\n{2,}/).filter(Boolean)
    .map((p) => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`).join('');
  const meta = `<div class="meta">
    <span>${esc(s.source === 'llm' ? 'AI 生成' : '规则兜底')}</span>
    <span>${esc(s.chars || 0)} 字</span>
    <span>数据覆盖 ${esc(s.coverage || '—')} 级</span>
  </div>`;
  return `<div class="talk">${paras}</div>
    <div class="note">纯口语稿，无 Markdown、无符号列表、无操作建议。数字与网页深度分析同源。
    复制后直接发到元宝或朗读都可以。</div>`;
}

export async function mountTalk() {
  const root = document.getElementById('ss3-root');
  if (!root) return;
  if (!document.getElementById('tk-style')) {
    const st = document.createElement('style');
    st.id = 'tk-style';
    st.textContent = STYLE;
    document.head.appendChild(st);
  }
  root.className = 'tk';

  const params = new URLSearchParams(location.search);
  const raw = (params.get('code') || '').trim();
  const isCode = /^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(raw);
  const code = isCode ? raw.replace(/\D/g, '') : '';

  if (!code) {
    root.innerHTML = `<div class="rule"><b>口播版</b>：≤1200 字纯口语稿，可直接发到元宝或朗读。</div>
      <div class="form"><input id="tkcode" placeholder="如 688508" inputmode="numeric" autocomplete="off" spellcheck="false">
      <button id="tkgo">生成口播版</button></div>
      <div class="note" style="margin-top:12px">只需要数字源，不需要跑完整深度分析，通常十几秒出稿。</div>`;
    const btn = document.getElementById('tkgo');
    const inp = document.getElementById('tkcode');
    const go = () => {
      const v = (inp.value || '').replace(/\D/g, '');
      if (v.length === 6) location.href = routeBase() + '/talk/?code=' + v;
      else if (inp.value) { inp.value = ''; inp.placeholder = '请输入6位股票代码'; }
    };
    btn.addEventListener('click', go);
    inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    return;
  }

  root.innerHTML = `<div class="card loading">正在生成口播版…</div>`;

  let base;
  try {
    base = await apiBase();
  } catch (e) {
    root.innerHTML = `<div class="loading">无法连接后端：${esc(e.message)}</div>`;
    return;
  }

  // 先取基本信息（快），口播稿与基本信息并行等
  const headP = post(base, '/api/stockscore_v3', code).catch(() => null);
  const sumP = post(base, '/api/stockscore_v3_talk', code);

  const payload = await headP;
  const head = (payload
    ? `<div class="ident"><h1>${esc(payload.name)}</h1><span class="code">${esc(payload.code)}</span>
       ${payload.industry ? `<span class="ind">${esc(payload.industry)}</span>` : ''}</div>`
    : '') + navBar(code, 'index');

  root.innerHTML = head + `<div id="tk-box"></div>`;

  let s;
  try {
    s = await sumP;
  } catch (e) {
    document.getElementById('tk-box').innerHTML =
      `<div class="loading">口播版生成失败：${esc(e.message)}</div>`;
    return;
  }

  const gaps = (s.gaps && s.gaps.length)
    ? `<div class="gap">数据缺口：${esc(s.gaps.slice(0, 4).join('；'))}</div>` : '';

  document.getElementById('tk-box').innerHTML =
    `<div class="rule"><b>口播版</b>：≤1200 字，纯口语，无操作建议。</div>` +
    gaps + talkHtml(s);

  // 底部固定操作条：复制 + 系统分享（手机上可直接分享到元宝/微信）
  const acts = document.createElement('div');
  acts.className = 'acts';
  acts.innerHTML = `<button class="cp" id="tk-cp">复制口播稿</button>
    <button class="sh" id="tk-sh">分享到元宝</button>`;
  document.body.appendChild(acts);

  const cp = document.getElementById('tk-cp');
  cp.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(s.text || '');
      cp.textContent = '已复制';
      setTimeout(() => { cp.textContent = '复制口播稿'; }, 1800);
    } catch (e) {
      cp.textContent = '复制失败，手动选中文本';
    }
  });

  const sh = document.getElementById('tk-sh');
  const title = `${payload ? payload.name : code}（${code}）深度分析口播版`;
  sh.addEventListener('click', async () => {
    if (navigator.share) {
      try {
        await navigator.share({ title, text: s.text || '' });
        return;
      } catch (e) {
        if (e && e.name === 'AbortError') return;
      }
    }
    // 没有系统分享能力（桌面浏览器）→ 退回复制
    try {
      await navigator.clipboard.writeText(s.text || '');
      sh.textContent = '已复制，去元宝粘贴';
      setTimeout(() => { sh.textContent = '分享到元宝'; }, 2200);
    } catch (e) {
      sh.textContent = '请手动复制上方文字';
    }
  });

  root.insertAdjacentHTML('beforeend', `<div class="foot">
    口播稿由个股打分卡 V3 的数字源生成，经数字回验与措辞过滤（无涨跌预测、无价格预期、无买卖建议）。
    数据缺口在正文中直接说明，不做补白。研报观点仅代表分析师判断，不构成本站观点。
    本页不构成投资建议。</div>`);
}
