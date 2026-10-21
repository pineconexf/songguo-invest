var e=[[`index`,`总览`,`overview`],[`quality`,`质地`,`quality`],[`price`,`价格`,`price`],[`momentum`,`势能`,`momentum`],[`risk`,`风险`,`risk`]],t=e=>String(e??``).replace(/&/g,`&amp;`).replace(/</g,`&lt;`).replace(/>/g,`&gt;`).replace(/"/g,`&quot;`);function n(e,n=2){if(e==null)return`N/A`;if(typeof e!=`number`)return t(e);if(Math.abs(e)>=1e6)return e.toLocaleString(`zh-CN`,{maximumFractionDigits:0});let r=e.toFixed(n);return r.indexOf(`.`)>=0&&(r=r.replace(/0+$/,``).replace(/\.$/,``)),r||`0`}var r=e=>({优:`p-in`,良:`p-in`,中:`p-out`,待观察:`p-red`})[e]||`p-gray`,i=e=>({in:`p-in`,out:`p-out`,red:`p-red`})[e]||`p-gray`;function a(){let e=location.pathname.replace(/\/+$/,``),t=e.match(/^(.*\/stockscore)(?:\/(?:index|quality|price|momentum|risk))?$/);return t?t[1]:e}function o(t,n){let r=a();return`<div class="nav">`+e.map(([e,i])=>`<a class="${e===n?`on`:``}" href="${r}${e===`index`?``:`/`+e}/?code=${encodeURIComponent(t)}">${i}</a>`).join(``)+`</div>`}function s(e){return`<div class="ident"><h1>${t(e.name)}</h1><span class="code">${t(e.code)}</span>`+(e.industry?`<span class="ind">${t(e.industry)}</span>`:``)+(e.data_asof?`<span class="ind">数据 ${t(e.data_asof)}</span>`:``)+`</div>`}async function c(){if(window.__SS_BASE__)return window.__SS_BASE__;if(/\.github\.io$/i.test(location.hostname))return window.__SS_BASE__=`https://pinecone-lab.cn`,window.__SS_BASE__;if(/^(localhost|127\.0\.0\.1|\[::1\])$/i.test(location.hostname))try{if((await fetch(`http://127.0.0.1:8081/api/health`)).ok)return window.__SS_BASE__=`http://127.0.0.1:8081`,window.__SS_BASE__}catch{}return location.origin}async function l(e,t,n){let r=await fetch(e+t,{method:`POST`,headers:{"Content-Type":`application/json`},body:JSON.stringify({code:n})});if(!r.ok){let e=`HTTP `+r.status;try{let t=await r.json();t.detail&&(e=t.detail)}catch{}throw Error(e)}return r.json()}var u=e=>new Promise(t=>setTimeout(t,e));function d(e){if(!e.available)return`<div class="dimhead"><h3>${t(e.label)}</h3><div class="sc">N/A<small>权重 ${Math.round(e.weight*100)}%</small></div></div><div class="fl n">${t(e.na_reason||`该维不可用`)}</div>`;let r=(e.metrics||[]).map(e=>{let r=e.reliability===`A`?`<br><span class="tagA">A级·真实披露</span>`:e.reliability===`B`?`<br><span class="tagB">B级·大单推算</span>`:``,i=e.note?`<div class="note">${t(e.note)}</div>`:``;return`<tr><td>${t(e.name)}${r}${i}</td><td class="n">${n(e.value)}${t(e.unit||``)}</td><td class="n">${n(e.pctl,0)}</td><td class="n">${Math.round(e.weight*100)}%</td><td class="n">${e.confidence}</td></tr>`}).join(``),i=(e.flags||[]).map(e=>`<div class="fl n">${t(e)}</div>`).join(``),a=e.thresh?`<div class="note">口径：${t(e.thresh)}</div>`:``,o=e.dupont,s=o?`<div class="note">杜邦拆解（ROE = 净利率 × 周转率 × 权益乘数）：净利率 ${n(o.margin,1)}% × 总资产周转率 ${n(o.turnover,2)} 次 × 权益乘数 ${n(o.equity_mult,2)}</div>`:``;return`<div class="dimhead"><h3>${t(e.label)}</h3><div class="sc">${n(e.score,1)}<small>权重 ${Math.round(e.weight*100)}% · 置信 ${e.confidence}</small></div></div><table><thead><tr><th>子指标</th><th style="text-align:right">数值</th><th style="text-align:right">分位/刻度</th><th style="text-align:right">维内权重</th><th style="text-align:right">置信</th></tr></thead><tbody>${r}</tbody></table>${s}${i}${a}`}function f(e){return(e||[]).map(e=>`<div class="blk"><div class="h">${t(e.h)}</div><div class="t">${t(e.t)}</div></div>`).join(``)}function p(e){return(e||[]).map(e=>{if(e==null)return``;if(typeof e==`string`)return e;let t=e.label||e.key||``,n=e.reason||e.text||``;return t&&n?t+`：`+n:t||n||String(e)}).filter(Boolean).join(`；`)}function m(e,n){let r=(e||[]).map(e=>`<tr>
      <td class="k">${t(e.label||e.key)}</td>
      <td class="v">${t(e.text||e.value)}${e.source?` <span class="src">（${t(e.source)}）</span>`:``}</td>
    </tr>`).join(``),i=(n||[]).length?`<div class="deepnote">取不到的维度：${t(p(n))}。没有可靠公开数据源，页面不做估算。</div>`:``;return!r&&!i?``:`<table class="facts">${r}</table>${i}`}function h(e){let n=(e.text||``).split(/\n{2,}/).filter(Boolean).map(e=>`<p>${t(e).replace(/\n/g,`<br>`)}</p>`).join(``),r=e.note?`<div class="deepnote">${t(e.note)}</div>`:``;return`<div class="deep"><h3>${t(e.title)}</h3>${n}${r}</div>`}function g(e){let o=e.overview||{};o.groups;let s=o.tag||{},c=o.gate||{},l=(o.key_risks||[]).map(e=>`<div class="fl ${e.level===`red`?`r`:e.level===`yellow`?`y`:`f`}">${e.level===`red`?`🔴 `:e.level===`yellow`?`🟡 `:`⚑ `}${t(e.text)}</div>`).join(``)||`<div class="fl n">未触发红旗、黄旗或已兑现风险标记。</div>`,u=(c.not_wired||[]).length?`<div class="fl n">未接入：${t((c.not_wired||[]).join(`、`))}（如实标注，不填 0）</div>`:``,d=Object.entries(o.investable_checks||{}).map(([e,n])=>`<div class="${n?`ok`:`no`}">${n?`✅`:`❌`} ${t(e)}</div>`).join(``),p=[`quality`,`price`,`momentum`,`risk`].map(r=>{let i=(e.modules||{})[r]||{},o=r===`quality`?`Q`:r===`price`?`V`:r===`momentum`?`M`:``,s=i.score===null||i.score===void 0?`—`:n(i.score,1);return`<a class="gcard ${o}" href="${a()}/${r}/?code=${encodeURIComponent(e.code)}">
      <div class="k">${t(i.title||r)}</div>
      <div class="v">${s}</div>
      <div class="q">${t(i.headline||``)}</div></a>`}).join(``);return`<div class="card"><div class="hero">
      <div><div class="big">${n(o.total,1)}<small>分 · ${t(o.tier)}</small></div>
        <div class="note" style="margin-top:8px">裸分 ${n(o.total_raw,1)}${o.tier_note?`　`+t(o.tier_note):``}</div></div>
      <div class="meta"><span class="pill ${i(s.code)}">${t(s.label)}</span>
        <span class="pill ${r(o.tier)}">档位 ${t(o.tier)}</span>
        <span class="pill p-gray">红旗 ${(c.red||[]).length} · 黄旗 ${(c.yellow||[]).length}</span>
        <div class="note">${t(s.desc||``)}</div></div></div>
    </div>
    <div class="g3">${p}</div></div>
    <div class="card"><h2 class="s">一句话结论<span class="w">先读这一句</span></h2>
      ${f([{h:`结论`,t:o.one_liner||o.headline||`（暂无）`}])}
      <div class="note">${t(o.headline||``)}</div></div>
    <div class="card"><h2 class="s">关键风险<span class="w">${(o.key_risks||[]).length} 条</span></h2>${l}${u}</div>
    <div class="card"><h2 class="s">松果可投性（简化 11 步 + 市值）</h2><div class="chk">${d}</div>
      <div class="note">完整 V35 管线含 VC∈[0.90,0.99]、行业软调节、红旗删票不补位；
        本卡用可公开验证的简化口径做代理，标签含义为「落在射程内与否」，不等于买入建议。</div></div>
    <div class="card"><h2 class="s">四个深度分页<span class="w">同一份数据，不同切面</span></h2>
      <div class="note">质地（业务结构＋差异化壁垒）、价格（数字检验＋估值与预期）、
        势能（市场空间）、风险（风险与安全＋关键矛盾＋审读意见）。
        每页都带对应的评分卡支撑数据与事实证据，数字与本页同源。</div>
      <a class="btn" href="${a()}/quality/?code=${encodeURIComponent(e.code)}">从质地开始看 →</a></div>`}function _(e,r){let i=(e.modules||{})[r]||{},a=(i.dims||[]).map(d).join(``),o=(i.sections||[]).map(h).join(``),s=f(i.blocks),c=`<div class="card"><div class="hero">
      <div><div class="big">${i.score===null||i.score===void 0?`—`:n(i.score,1)}<small>${t(i.title||``)}</small></div>
        <div class="note" style="margin-top:8px">${t(i.headline||``)}</div></div>
      <div class="meta"><span class="pill p-gray">外部深度数据 ${t(e.coverage||`—`)} 级</span>
        <span class="pill p-gray">研报 ${t(e.research_reports||0)} 篇</span></div></div></div>`,l=a?`<div class="card"><h2 class="s">评分卡支撑数据<span class="w">这一页的维度</span></h2>${a}</div>`:``,u=``;if(r===`price`)u=m(i.valuation_facts,i.valuation_gaps),u&&=`<div class="card"><h2 class="s">估值事实<span class="w">可溯源数字</span></h2>${u}</div>`;else if(r===`momentum`){let e=i.industry_facts||[];e.length&&(u=`<div class="card"><h2 class="s">行业结构数据<span class="w">申万成分股实算</span></h2>
        <table class="facts">${e.map(e=>`<tr><td class="v">${t(e)}</td></tr>`).join(``)}</table></div>`)}else if(r===`risk`){let e=(i.risk_flags||[]).map(e=>`<div class="fl r"><b>${t(e.label||`已兑现风险`)}</b>　${t(e.text||``)}</div>`).join(``)||`<div class="fl n">确定性指标未触发任何红旗阈值。只说明已量化的风险项没越线，不代表没有风险。</div>`,n=m(i.risk_facts,i.risk_gaps),r=i.contradictions||[],a=r.length?`<div class="card"><h2 class="s">跨段矛盾<span class="w">${r.length} 处</span></h2>
        <ul class="issues">${r.map(e=>`<li><span class="ty high">矛盾</span>${t(e.detail)}
          ${e.a_text?`<br><span class="src">${t(e.a)}：${t(e.a_text)}</span>`:``}
          ${e.b_text?`<br><span class="src">${t(e.b)}：${t(e.b_text)}</span>`:``}</li>`).join(``)}</ul></div>`:``,o=i.critic&&i.critic.issues||[],s=o.length?`<div class="card"><h2 class="s">审读意见<span class="w">${o.length} 条</span></h2>
        <ul class="issues">${o.map(e=>`<li><span class="ty ${t(e.severity||``)}">${t(e.type||``)}</span>
          ${t(e.problem||``)}${e.fix?`<br><span class="src">改法：${t(e.fix)}</span>`:``}</li>`).join(``)}</ul>
        ${i.critic.summary?`<div class="note">${t(i.critic.summary)}</div>`:``}</div>`:``,c=(i.unresolved||[]).length?`<div class="card"><h2 class="s">未解问题<span class="w">如实披露</span></h2>
        <ul class="issues">${i.unresolved.map(e=>`<li><span class="ty high">${t(e.severity||`high`)}</span>
          ${t(e.problem||``)}${e.fix?`　改法：${t(e.fix)}`:``}</li>`).join(``)}</ul></div>`:``;u=`<div class="card"><h2 class="s">风险与安全<span class="w">只报命中的红旗</span></h2>${e}
        ${n?`<h2 class="s" style="margin-top:16px">风险事实</h2>${n}`:``}</div>`+a+s+c}let p=`<div class="card"><h2 class="s">深度分析<span class="w" id="ss3-prog"></span></h2>
    <div id="ss3-deep">${o||`<div class="waiting">深度分析正在生成中…</div>`}</div></div>`,g=s?`<div class="card"><h2 class="s">结论</h2>${s}</div>`:``;return c+p+l+u+g}async function v(e,n,r,i){let a=document.getElementById(`ss3-deep`),o=document.getElementById(`ss3-prog`);if(!a)return;let s=0;for(let c=0;c<400;c++){let c;try{c=await l(e,`/api/stockscore_v3_deep_progress`,n)}catch{o&&(o.textContent=`（连接中断，重试中）`),await u(3e3);continue}let d=c.sections||[],f=i?d.filter(e=>i.indexOf(e.key)>=0):d;if(f.length!==s&&(s=f.length,a.innerHTML=f.map(h).join(``)||`<div class="waiting">深度分析正在生成中…</div>`,o&&(o.textContent=c.state===`done`?`已完成 ${d.length} 段 · ${c.total_chars||0} 字`:`已出 ${f.length} 段 · ${c.total_chars||0} 字 · 用时 ${c.elapsed||0}s`)),c.state===`done`){try{r(await l(e,`/api/stockscore_v3_bundle`,n))}catch{}return}if(c.state===`error`){a.innerHTML=`<div class="fl r">深度分析生成失败：${t(c.error||`未知错误`)}</div>`;return}await u(2e3)}}function y(){return`<div class="card"><h2 class="s">输入股票代码或名称</h2>
    <div class="form"><input id="ss3code" placeholder="如 600519 或 贵州茅台" autocomplete="off" spellcheck="false">
    <button id="ss3go">开始打分</button></div>
    <div id="ss3hint" class="note">支持 6 位代码、股票全称或简称（贵州茅台 / 茅台 / 农行）。
      首次查询需现建全市场横截面宇宙（约 1-2 分钟，期间会自动重试）；10 分钟内同码命中缓存秒回。</div></div>`}function b(e){return`<div class="card"><h2 class="s">找到 ${e.length} 只，请选择</h2>
    <div class="cands">${e.map(e=>`<button class="cand" data-code="${t(e.code)}">
      <span class="cd">${t(e.code)}</span><span class="cn">${t(e.name)}</span>
      <span class="cm">${t(e.market||``)}</span></button>`).join(``)}</div>
    <div class="note"><a href="${location.pathname}">← 重新输入</a>　也可以直接输入 6 位代码精确定位。</div></div>`}function x(e,n){let r=document.getElementById(`ss3code`),i=document.getElementById(`ss3go`),a=document.getElementById(`ss3hint`),o=a.innerHTML,s=e=>{i.disabled=!1,r.disabled=!1,a.innerHTML=e||o,r.focus()},l=async()=>{let n=(r.value||``).trim();if(!n){r.focus();return}if(/^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(n)){location.search=`?code=`+n.replace(/\D/g,``);return}i.disabled=!0,r.disabled=!0,a.innerHTML=`正在识别「`+t(n)+`」…`;try{let r=await c(),i=await fetch(r+`/api/stockscore_resolve?q=`+encodeURIComponent(n));if(!i.ok)throw Error(`HTTP `+i.status);let a=await i.json(),o=a.candidates||[];if(!o.length){s(a.hint===`latin`?`暂只支持中文名称或 6 位代码（拼音暂不支持）。`:`未找到「`+t(n)+`」，换个写法试试，或直接输入 6 位代码。`);return}if(o.length===1||a.exact){location.search=`?code=`+o[0].code;return}e.innerHTML=b(o),Array.prototype.forEach.call(e.querySelectorAll(`.cand`),e=>{e.onclick=()=>{location.search=`?code=`+e.dataset.code}})}catch(e){s(`识别服务暂时不可用（`+t(e.message)+`），请直接输入 6 位代码。`)}};i.onclick=l,r.addEventListener(`keydown`,e=>{e.key===`Enter`&&l()}),n?(r.value=n,l()):r.focus()}async function S(e){let n=document.getElementById(`ss3-root`);if(!n)return;if(!document.getElementById(`ss3-style`)){let e=document.createElement(`style`);e.id=`ss3-style`,e.textContent=`
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
`,document.head.appendChild(e)}n.className=`ss3`;let r=new URLSearchParams(location.search),i=(r.get(`code`)||r.get(`q`)||``).trim(),a=/^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(i)?i.replace(/\D/g,``):``;if(!a){n.innerHTML=y(),x(n,i);return}let d=e===`index`;n.innerHTML=`<div class="card"><div class="note">${d?`正在计算（首次约 1-2 分钟建全市场宇宙，之后同码 10 分钟内秒回）…`:`正在取数…`}</div></div>`;let f;try{f=await c()}catch(e){n.innerHTML=`<div class="card"><div class="fl r">无法连接后端：${t(e.message)}</div></div>`;return}let p=null;for(let e=1;e<=6;e++)try{p=await l(f,`/api/stockscore_v3_bundle`,a);break}catch(r){if(e===6){n.innerHTML=`<div class="card"><div class="fl r">查询失败：${t(r.message)}</div>
          <div class="note"><a href="${location.pathname}">重新输入代码</a></div></div>`;return}n.innerHTML=`<div class="card"><div class="note">后端正在建全市场横截面宇宙，已自动重试 ${e}/6 次…</div></div>`,await u(2e4)}if(!p)return;let m=()=>{let r=s(p)+o(p.code,e),i=d?g(p):_(p,e),a=`<div class="foot">总分 = 0.52×Q + 0.26×V + 0.22×M，再过闸门（🔴封顶59 / 🟡≥2降一档 / 🟡=1仅标注）。
      缺失子项不进分母、整维缺失标 N/A 不填 0；每个分数带置信度，&lt;0.6 进低置信清单。<br>
      深度分析的每个数字都来自可溯源的公开数据或券商研报原文抽取；研报观点仅代表分析师判断，不构成本站观点。
      本页所有数字由公开数据按页面写明口径计算，数据可能有误、口径有局限，请自行复核。<br>
      结构化读数不构成投资建议，不预测涨跌，不含任何买卖意见。${(p.source_errors||[]).length?`<br>取数告警：`+t(p.source_errors.join(`；`)):``}</div>`;n.innerHTML=r+i+a};if(m(),d)try{await l(f,`/api/stockscore_v3_deep_prewarm`,a)}catch{}else{let t={quality:[`business`,`moat`],price:[`numbers`,`valuation`],momentum:[`market`],risk:[`risk`]}[e]||null;v(f,a,m,t)}}export{S as t};