var e=e=>String(e??``).replace(/&/g,`&amp;`).replace(/</g,`&lt;`).replace(/>/g,`&gt;`).replace(/"/g,`&quot;`),t=[[`index`,`总览`,`overview`],[`quality`,`质地`,`quality`],[`price`,`价格`,`price`],[`momentum`,`势能`,`momentum`],[`deep`,`深度`,`deep`]];function n(){let e=location.pathname.match(/\/tools\/stockscore(\/[^/]*)?/);if(!e)return`/tools/stockscore`;let t=(e[1]||``).replace(/\/+$/,``);return t===``||t===`/index`?`/tools/stockscore`:`/tools/stockscore`+t}async function r(){if(window.__SS_BASE__)return window.__SS_BASE__;if(/\.github\.io$/i.test(location.hostname))return window.__SS_BASE__=`https://pinecone-lab.cn`,window.__SS_BASE__;if(/^(localhost|127\.0\.0\.1|\[::1\])$/i.test(location.hostname))try{if((await fetch(`http://127.0.0.1:8081/api/health`)).ok)return window.__SS_BASE__=`http://127.0.0.1:8081`,window.__SS_BASE__}catch{}return window.__SS_BASE__=location.origin,window.__SS_BASE__}async function i(e,t,n){let r=await fetch(e+t,{method:`POST`,headers:{"Content-Type":`application/json`},body:JSON.stringify({code:n})}),i=await r.json().catch(()=>({}));if(!r.ok||i.success===!1)throw Error(i.error||i.detail||`接口返回 `+r.status);return i}function a(e,r){let i=n();return`<div class="nav">`+t.map(([t,n])=>`<a class="${t===r?`on`:``}" href="${i}${t===`index`?``:`/`+t}/?code=${encodeURIComponent(e)}">${n}</a>`).join(``)+`</div>`}function o(t){let n=(t.text||``).split(/\n{2,}/).filter(Boolean).map(t=>`<p>${e(t).replace(/\n/g,`<br>`)}</p>`).join(``);return`${e(t.source===`llm`?`AI 生成`:`规则兜底`)}${e(t.chars||0)}${e(t.coverage||`—`)}`,`<div class="talk">${n}</div>
    <div class="note">纯口语稿，无 Markdown、无符号列表、无操作建议。数字与网页深度分析同源。
    复制后直接发到元宝或朗读都可以。</div>`}async function s(){let t=document.getElementById(`ss3-root`);if(!t)return;if(!document.getElementById(`tk-style`)){let e=document.createElement(`style`);e.id=`tk-style`,e.textContent=`
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
`,document.head.appendChild(e)}t.className=`tk`;let s=(new URLSearchParams(location.search).get(`code`)||``).trim(),c=/^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(s)?s.replace(/\D/g,``):``;if(!c){t.innerHTML=`<div class="rule"><b>口播版</b>：≤1200 字纯口语稿，可直接发到元宝或朗读。</div>
      <div class="form"><input id="tkcode" placeholder="如 688508" inputmode="numeric" autocomplete="off" spellcheck="false">
      <button id="tkgo">生成口播版</button></div>
      <div class="note" style="margin-top:12px">只需要数字源，不需要跑完整深度分析，通常十几秒出稿。</div>`;let e=document.getElementById(`tkgo`),r=document.getElementById(`tkcode`),i=()=>{let e=(r.value||``).replace(/\D/g,``);e.length===6?location.href=n()+`/talk/?code=`+e:r.value&&(r.value=``,r.placeholder=`请输入6位股票代码`)};e.addEventListener(`click`,i),r.addEventListener(`keydown`,e=>{e.key===`Enter`&&i()});return}t.innerHTML=`<div class="card loading">正在生成口播版…</div>`;let l;try{l=await r()}catch(n){t.innerHTML=`<div class="loading">无法连接后端：${e(n.message)}</div>`;return}let u=i(l,`/api/stockscore_v3`,c).catch(()=>null),d=i(l,`/api/stockscore_v3_talk`,c),f=await u;t.innerHTML=(f?`<div class="ident"><h1>${e(f.name)}</h1><span class="code">${e(f.code)}</span>
       ${f.industry?`<span class="ind">${e(f.industry)}</span>`:``}</div>`:``)+a(c,`index`)+`<div id="tk-box"></div>`;let p;try{p=await d}catch(t){document.getElementById(`tk-box`).innerHTML=`<div class="loading">口播版生成失败：${e(t.message)}</div>`;return}let m=p.gaps&&p.gaps.length?`<div class="gap">数据缺口：${e(p.gaps.slice(0,4).join(`；`))}</div>`:``;document.getElementById(`tk-box`).innerHTML=`<div class="rule"><b>口播版</b>：≤1200 字，纯口语，无操作建议。</div>`+m+o(p);let h=document.createElement(`div`);h.className=`acts`,h.innerHTML=`<button class="cp" id="tk-cp">复制口播稿</button>
    <button class="sh" id="tk-sh">分享到元宝</button>`,document.body.appendChild(h);let g=document.getElementById(`tk-cp`);g.addEventListener(`click`,async()=>{try{await navigator.clipboard.writeText(p.text||``),g.textContent=`已复制`,setTimeout(()=>{g.textContent=`复制口播稿`},1800)}catch{g.textContent=`复制失败，手动选中文本`}});let _=document.getElementById(`tk-sh`),v=`${f?f.name:c}（${c}）深度分析口播版`;_.addEventListener(`click`,async()=>{if(navigator.share)try{await navigator.share({title:v,text:p.text||``});return}catch(e){if(e&&e.name===`AbortError`)return}try{await navigator.clipboard.writeText(p.text||``),_.textContent=`已复制，去元宝粘贴`,setTimeout(()=>{_.textContent=`分享到元宝`},2200)}catch{_.textContent=`请手动复制上方文字`}}),t.insertAdjacentHTML(`beforeend`,`<div class="foot">
    口播稿由个股打分卡 V3 的数字源生成，经数字回验与禁词过滤（无涨跌预测、无目标价、无买卖建议）。
    数据缺口在正文中直接说明，不做补白。研报观点仅代表分析师判断，不构成本站观点。
    本页不构成投资建议。</div>`)}s();