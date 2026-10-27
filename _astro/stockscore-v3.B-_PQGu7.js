var e=[[`index`,`总览`,`overview`],[`quality`,`质地`,`quality`],[`price`,`价格`,`price`],[`momentum`,`势能`,`momentum`],[`risk`,`风险`,`risk`]],t=e=>String(e??``).replace(/&/g,`&`).replace(/</g,`<`).replace(/>/g,`>`).replace(/\"/g,`"`);function n(e,n=2){if(e==null)return`N/A`;if(typeof e!=`number`)return t(e);if(Math.abs(e)>=1e6)return e.toLocaleString(`zh-CN`,{maximumFractionDigits:0});let r=e.toFixed(n);return r.indexOf(`.`)>=0&&(r=r.replace(/0+$/,``).replace(/\.$/,``)),r||`0`}var r={元:1e8,万元:1e4};function i(e,i,a=2){if(e==null)return`N/A`;if(typeof e!=`number`)return t(e);let o=(i||``).trim();if(!Object.prototype.hasOwnProperty.call(r,o))return n(e,a)+(o?` `+t(o):``);let s=e/r[o];return Math.abs(s)>=.01?n(s,a)+` 亿元`:n(s,4)+` 亿元`}var a=[[/二审/g,`二次修订`],[/三审/g,`复核`],[/审读/g,`复核`],[/仍未解/g,`仍待确认`],[/未解问题/g,`待确认项`],[/改法/g,`修订方式`],[/自检/g,`检查`],[/审稿/g,`复核`],[/审校/g,`复核`],[/仍有审读意见未解/g,`仍有待确认项`],[/critic/gi,`复核`],[/pipeline/gi,`流程`]],o=[/目标价/,/上涨空间/,/上行空间/,/下行空间/,/合理价位/,/价格中枢/,/估值区间/,/估值带/,/预期回报/,/回归中位空间/,/回归中位幅度/,/涨跌空间/,/空间测算/];function s(e){return e?String(e).split(/(?<=[。；;！!？?])/).filter(e=>!o.some(t=>t.test(e))).join(``).trim():``}function c(e){if(!e)return`待确认`;let t=String(e);return a.forEach(([e,n])=>{t=t.replace(e,n)}),t=t.replace(/[\s·・\-_—:：]+/g,` `).trim(),!t||t.length>12?`待确认`:t}function l(e){if(!e)return``;let t=String(e);return a.forEach(([e,n])=>{t=t.replace(e,n)}),t=s(t),t||``}var u=e=>({优:`p-in`,良:`p-in`,中:`p-out`,待观察:`p-red`})[e]||`p-gray`;function d(){let e=location.pathname.replace(/\/+$/,``),t=e.match(/^(.*\/stockscore)(?:\/(?:index|quality|price|momentum|risk))?$/);return t?t[1]:e}function f(t,n){let r=d();return`<div class="nav">`+e.map(([e,i])=>`<a class="${e===n?`on`:``}" href="${r}${e===`index`?``:`/`+e}/?code=${encodeURIComponent(t)}">${i}</a>`).join(``)+`</div>`}function p(e){return`<div class="ident"><h1>${t(e.name)}</h1><span class="code">${t(e.code)}</span>`+(e.industry?`<span class="ind">${t(e.industry)}</span>`:``)+(e.data_asof?`<span class="ind">数据 ${t(e.data_asof)}</span>`:``)+`</div>`}async function m(){if(window.__SS_BASE__)return window.__SS_BASE__;if(/\.github\.io$/i.test(location.hostname))return window.__SS_BASE__=`https://pinecone-lab.cn`,window.__SS_BASE__;if(/^(localhost|127\.0\.0\.1|\[::1\])$/i.test(location.hostname))try{if((await fetch(`http://127.0.0.1:8081/api/health`)).ok)return window.__SS_BASE__=`http://127.0.0.1:8081`,window.__SS_BASE__}catch{}return location.origin}async function h(e,t,n){let r=await fetch(e+t,{method:`POST`,headers:{"Content-Type":`application/json`},body:JSON.stringify({code:n})});if(!r.ok){let e=`HTTP `+r.status;try{let t=await r.json();t.detail&&(e=t.detail)}catch{}throw Error(e)}return r.json()}var g=e=>new Promise(t=>setTimeout(t,e));function _(e){if(!e.available)return`<div class="dimhead"><h3>${t(e.label)}</h3><div class="sc">N/A<small>权重 ${Math.round(e.weight*100)}%</small></div></div><div class="fl n">${t(e.na_reason||`该维不可用`)}</div>`;let r=(e.tags||[]).slice(0,2).map(e=>`<span class="tagC" data-ss3-jump="${t(e.anchor)}">${t(e.text)}</span>`).join(` `),a=r?`<div class="tags" style="margin-top:4px">${r}</div>`:``,o=(e.metrics||[]).map(e=>{let r=e.reliability===`A`?`<br><span class="tagA">A级·真实披露</span>`:e.reliability===`B`?`<br><span class="tagB">B级·大单推算</span>`:``,a=e.note?`<div class="note">${t(e.note)}</div>`:``;return`<tr><td>${t(e.name)}${r}${a}</td><td class="n">${i(e.value,e.unit)}</td><td class="n">${n(e.pctl,0)}</td><td class="n">${Math.round(e.weight*100)}%</td><td class="n">${e.confidence}</td></tr>`}).join(``),s=(e.flags||[]).map(e=>`<div class="fl n">${t(e)}</div>`).join(``),c=e.thresh?`<div class="note">口径：${t(e.thresh)}</div>`:``,l=e.dupont,u=l?`<div class="note">杜邦拆解（ROE = 净利率 × 周转率 × 权益乘数）：净利率 ${n(l.margin,1)}% × 总资产周转率 ${n(l.turnover,2)} 次 × 权益乘数 ${n(l.equity_mult,2)}</div>`:``;return`<div class="dimhead"><h3>${t(e.label)}</h3><div class="sc">${n(e.score,1)}<small>权重 ${Math.round(e.weight*100)}% · 置信 ${e.confidence}</small></div></div>${a}<table><thead><tr><th>子指标</th><th style="text-align:right">数值</th><th style="text-align:right">分位/刻度</th><th style="text-align:right">维内权重</th><th style="text-align:right">置信</th></tr></thead><tbody>${o}</tbody></table>${u}${s}${c}`}function v(e){return(e||[]).map(e=>`<div class="blk"><div class="h">${t(e.h)}</div><div class="t">${t(e.t)}</div></div>`).join(``)}function y(e){return(e||[]).map(e=>{if(e==null)return``;if(typeof e==`string`)return e;let t=e.label||e.key||``,n=e.reason||e.text||``;return t&&n?t+`：`+n:t||n||String(e)}).filter(Boolean).join(`；`)}function b(e,n){let r=(e||[]).map(e=>`<tr>
      <td class="k">${t(e.label||e.key)}</td>
      <td class="v">${t(e.text||e.value)}${e.source?` <span class="src">（${t(e.source)}）</span>`:``}</td>
    </tr>`).join(``),i=(n||[]).length?`<div class="deepnote">取不到的维度：${t(y(n))}。没有可靠公开数据源，页面不做估算。</div>`:``;return!r&&!i?``:`<table class="facts">${r}</table>${i}`}function x(e){let n=l(e.text||``).split(/\n{2,}/).filter(Boolean).map(e=>`<p>${t(e).replace(/\n/g,`<br>`)}</p>`).join(``),r=e.note?`<div class="deepnote">${t(e.note)}</div>`:``;return`<div class="deep"><h3>${t(e.title)}</h3>${n}${r}</div>`}function S(e){let r=e.overview||{},i=r.gate||{},a=[`quality`,`price`,`momentum`,`risk`].map(r=>{let i=(e.modules||{})[r]||{},a=r===`quality`?`Q`:r===`price`?`V`:r===`momentum`?`M`:``,o=i.score===null||i.score===void 0?`—`:n(i.score,1),s=i.score===null||i.score===void 0?i.verdict||`不参与打分，只做风险核查`:i.headline||``;return`<a class="gcard ${a}" href="${d()}/${r}/?code=${encodeURIComponent(e.code)}">
      <div class="k">${t(i.title||r)}</div>
      <div class="v">${o}</div>
      <div class="q">${t(s)}</div></a>`}).join(``),o=`<div class="card"><h2 class="s">分数总览<span class="w">三个切面打分 + 一个风险核查</span></h2>
    <div class="hero">
      <div><div class="big">${n(r.total,1)}<small>分 · ${t(r.tier)}</small></div>
        <div class="note" style="margin-top:8px">裸分 ${n(r.total_raw,1)}${r.tier_note?`　`+t(r.tier_note):``}</div></div>
      <div class="meta"><span class="pill ${u(r.tier)}">档位 ${t(r.tier)}</span>
        <span class="pill p-gray">风险项 ${(i.red||[]).length} · 关注项 ${(i.yellow||[]).length}</span></div></div>
    <div class="g3">${a}</div></div>`,s=e._v4_neutral||{},c=[];s.fcf_ev_pct!=null&&c.push(`<div class="ck"><div class="cl">自由现金流÷企业价值</div><div class="cv">${s.fcf_ev_pct}<small>%</small></div><div class="cn">FCF/EV · 独立指标</div></div>`),s.price_to_fair_pct!=null&&c.push(`<div class="ck"><div class="cl">现价÷估算合理价</div><div class="cv">${s.price_to_fair_pct}<small>%</small></div><div class="cn">中性参照，非买卖提示</div></div>`);let l=c.length?`<div class="card"><h2 class="s">四张核心卡<span class="w">独立指标，非策略阀门</span></h2><div class="cgrid">${c.join(``)}</div></div>`:``,f=(r.key_risks||[]).map(e=>`<div class="fl ${e.level===`red`?`r`:e.level===`yellow`?`y`:`f`}">${e.level===`red`?`🔴 `:e.level===`yellow`?`🟡 `:`⚑ `}${t(e.text)}</div>`).join(``),p=(e._v4_neutral||{}).growth_hint||``,m=p?`<div class="fl y">⚠ 增长提示：${t(p)}（客观事实陈述，不提策略动作）</div>`:``,h=(i.not_wired||[]).length?`<div class="fl n">未接入：${t((i.not_wired||[]).join(`、`))}（如实标注，不填 0）</div>`:``,g=`<h2 class="s" style="margin-top:16px">已量化的风险</h2>`+(f||`<div class="fl n">未触发风险项、关注项或已兑现风险标记。</div>`)+h,_=`<div class="card"><h2 class="s">总体描述评价结果<span class="w">先读这一段</span></h2>
    ${v([{h:`总体评价`,t:r.one_liner||r.headline||`（暂无）`}])}
    ${m}
    ${g}</div>`,y=`<div class="card"><h2 class="s">松果个股打分卡的结构特点<span class="w">这套分数是怎么算出来的</span></h2>
    <div class="note">打分卡把一只股票拆成三个打分切面（质地/价格/势能）加一个风险闸门，每个切面由若干有明确数据来源的指标加权得出，
      指标带口径说明和历史分位，三个切面合成总分，风险闸门只做封顶/降档、不进加权。四个页面各自独立，页内数字与本页同源。</div>
    <table class="facts">
      <tr><td class="v">质地（Q·权重 52%）</td><td>业务结构、差异化壁垒、盈利质量、核心竞争力、成长质量、财务健康</td></tr>
      <tr><td class="v">价格（V·权重 26%）</td><td>数字检验、估值与预期——看价格与经营事实的匹配度</td></tr>
      <tr><td class="v">势能（M·权重 22%）</td><td>市场空间、行业景气与需求端的变化</td></tr>
      <tr><td class="v">风险（权重 0）</td><td>已兑现风险项、安全边际、跨段矛盾检测——只做闸门，不进加权</td></tr>
    </table>
    <div class="note">指标口径、权重、可靠性分级（A 级真实披露 / B 级大单推算）和历史分位
      在各深度页的「评分卡支撑数据」里逐条列出，未接入的指标如实标注，不填 0。
      风险项只报命中的，未命中不等于没有风险。</div>
    <a class="btn" href="${d()}/quality/?code=${encodeURIComponent(e.code)}">从质地开始看 →</a></div>`;return o+l+_+y}function C(e,r){let i=(e.modules||{})[r]||{},a=(i.dims||[]).map(_).join(``),o=(i.sections||[]).map(x).join(``),s=v(i.blocks),u=i.verdict?`<div class="verdict"><b>总体评价</b>${t(i.verdict)}</div>`:`<div class="note" style="margin-top:8px">${t(i.headline||``)}</div>`,d=`<div class="card"><div class="hero">
      <div><div class="big">${i.score===null||i.score===void 0?`—`:n(i.score,1)}<small>${t(i.title||``)}</small></div>
        ${u}</div>
      <div class="meta"><span class="pill p-gray">外部深度数据 ${t(e.coverage||`—`)} 级</span>
        <span class="pill p-gray">研报 ${t(e.research_reports||0)} 篇</span>
        ${(function(){let t=e._v4_neutral||{};return t.price_to_fair_pct==null?``:`<span class="pill p-gray">现价/合理价 ${t.price_to_fair_pct}%</span>`})()}</div></div></div>`,f=a?`<div class="card"><h2 class="s">评分卡支撑数据<span class="w">这一页的维度</span></h2>${a}</div>`:``,p=``;if(r===`price`)p=b(i.valuation_facts,i.valuation_gaps),p&&=`<div class="card"><h2 class="s">估值事实<span class="w">可溯源数字</span></h2>${p}</div>`;else if(r===`momentum`){let e=i.industry_facts||[];e.length&&(p=`<div class="card"><h2 class="s">行业结构数据<span class="w">申万成分股实算</span></h2>
        <table class="facts">${e.map(e=>`<tr><td class="v">${t(e)}</td></tr>`).join(``)}</table></div>`)}else if(r===`risk`){let e=(i.risk_flags||[]).map(e=>`<div class="fl r"><b>${t(e.label||`已兑现风险`)}</b>　${t(e.text||``)}</div>`).join(``)||`<div class="fl n">确定性指标未触发任何风险阈值。只说明已量化的风险项没越线，不代表没有风险。</div>`,n=b(i.risk_facts,i.risk_gaps),r=i.contradictions||[],a=r.length?`<div class="card"><h2 class="s">跨段数据差异<span class="w">${r.length} 处</span></h2>
        <ul class="issues">${r.map(e=>`<li><span class="ty high">差异</span>${t(e.detail)}
          ${e.a_text?`<br><span class="src">${t(e.a)}：${t(e.a_text)}</span>`:``}
          ${e.b_text?`<br><span class="src">${t(e.b)}：${t(e.b_text)}</span>`:``}</li>`).join(``)}</ul></div>`:``,o=i.critic&&i.critic.issues||[],s=o.length?`<div class="card"><h2 class="s">这段分析的薄弱点<span class="w">${o.length} 条</span></h2>
        <ul class="issues">${o.map(e=>`<li><span class="ty ${t(e.severity||``)}">${t(c(e.type))}</span>
          ${t(l(e.problem))}</li>`).join(``)}</ul>
        ${i.critic.summary?`<div class="note">${t(l(i.critic.summary))}</div>`:``}</div>`:``,u=(i.unresolved||[]).length?`<div class="card"><h2 class="s">数据缺口<span class="w">如实披露</span></h2>
        <ul class="issues">${i.unresolved.map(e=>`<li><span class="ty high">${t(e.severity||`high`)}</span>
          ${t(l(e.problem))}</li>`).join(``)}</ul></div>`:``;p=`<div class="card"><h2 class="s">风险与安全<span class="w">只报命中的风险项</span></h2>${e}
        ${n?`<h2 class="s" style="margin-top:16px">风险事实</h2>${n}`:``}</div>`+a+s+u}let m=`<div class="card"><h2 class="s">深度分析<span class="w" id="ss3-prog"></span></h2>
    <div id="ss3-deep">${o||`<div class="waiting">深度分析正在生成中…</div>`}</div></div>`,h=s?`<div class="card">${s}</div>`:``,g={quality:`质地（Q）在松果策略中用于评估公司内在质量是否扎实：包含盈利质量、核心竞争力、成长质量、财务健康四个子维度。策略只把质地达标的股票纳入候选池，不达标的直接排除，不参与后续打分。质地分高低本身不构成买入或卖出信号，只回答「这家公司生意本身是否经得起看」。`,price:`价格（V）在松果策略中用于判断当前价格相对公司自身估值历史是否偏贵或偏便宜：包含估值分位、预期修正两个子维度。策略把估值分位作为仓位微调的参考之一，不作为独立买卖依据。估值低不等于一定会涨，估值高不等于一定会跌，只是说明当前价格在历史区间中的相对位置。`,momentum:`势能（M）在松果策略中用于跟踪行业景气与需求端的变化：包含行业景气度、需求端趋势两个子维度。策略用它来确认公司质地和价格的优势是否有行业景气的配合，没有配合的会被降档处理。势能是滞后确认指标，不用于预测，只用于验证。`},y={quality:`quality`,price:`price`,momentum:`momentum`}[r]||r,S=r===`quality`?` open`:``,C=`<div class="card" id="ss3-l3-${t(y)}">
    <h2 class="s">松果投资策略怎么用这些指标</h2>
    <details class="ss3-l3"${S}><summary>展开策略视角说明（不影响上方打分，仅供理解）</summary>
      <div class="note" style="margin-top:8px">${t(g[y]||`该维度说明暂未接入。`)}</div>
    </details></div>`;return d+m+f+p+h+C}async function w(e,n,r,i){let a=document.getElementById(`ss3-deep`),o=document.getElementById(`ss3-prog`);if(!a)return;let s=0;for(let c=0;c<400;c++){let c;try{c=await h(e,`/api/stockscore_v3_deep_progress`,n)}catch{o&&(o.textContent=`（连接中断，重试中）`),await g(3e3);continue}let l=c.sections||[],u=i?l.filter(e=>i.indexOf(e.key)>=0):l;if(u.length!==s&&(s=u.length,a.innerHTML=u.map(x).join(``)||`<div class="waiting">深度分析正在生成中…</div>`,o&&(o.textContent=c.state===`done`?`已完成 ${l.length} 段 · ${c.total_chars||0} 字`:`已出 ${u.length} 段 · ${c.total_chars||0} 字 · 用时 ${c.elapsed||0}s`)),c.state===`done`){try{r(await h(e,`/api/stockscore_v3_bundle`,n))}catch{}return}if(c.state===`error`){a.innerHTML=`<div class="fl r">深度分析生成失败：${t(c.error||`未知错误`)}</div>`;return}await g(2e3)}}function T(){return`<div class="card"><h2 class="s">输入股票代码或名称</h2>
    <div class="form"><input id="ss3code" placeholder="如 600519 或 贵州茅台" autocomplete="off" spellcheck="false">
    <button id="ss3go">开始打分</button></div>
    <div id="ss3hint" class="note">支持 6 位代码、股票全称或简称（贵州茅台 / 茅台 / 农行）。
      首次查询需现建全市场横截面宇宙（约 1-2 分钟，期间会自动重试）；10 分钟内同码命中缓存秒回。</div></div>`}function E(e){return`<div class="card"><h2 class="s">找到 ${e.length} 只，请选择</h2>
    <div class="cands">${e.map(e=>`<button class="cand" data-code="${t(e.code)}">
      <span class="cd">${t(e.code)}</span><span class="cn">${t(e.name)}</span>
      <span class="cm">${t(e.market||``)}</span></button>`).join(``)}</div>
    <div class="note"><a href="${location.pathname}">← 重新输入</a>　也可以直接输入 6 位代码精确定位。</div></div>`}function D(e,n){let r=document.getElementById(`ss3code`),i=document.getElementById(`ss3go`),a=document.getElementById(`ss3hint`),o=a.innerHTML,s=e=>{i.disabled=!1,r.disabled=!1,a.innerHTML=e||o,r.focus()},c=async()=>{let n=(r.value||``).trim();if(!n){r.focus();return}if(/^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(n)){location.search=`?code=`+n.replace(/\D/g,``);return}i.disabled=!0,r.disabled=!0,a.innerHTML=`正在识别「`+t(n)+`」…`;try{let r=await m(),i=await fetch(r+`/api/stockscore_resolve?q=`+encodeURIComponent(n));if(!i.ok)throw Error(`HTTP `+i.status);let a=await i.json(),o=a.candidates||[];if(!o.length){s(a.hint===`latin`?`暂只支持中文名称或 6 位代码（拼音暂不支持）。`:`未找到「`+t(n)+`」，换个写法试试，或直接输入 6 位代码。`);return}if(o.length===1||a.exact){location.search=`?code=`+o[0].code;return}e.innerHTML=E(o),Array.prototype.forEach.call(e.querySelectorAll(`.cand`),e=>{e.onclick=()=>{location.search=`?code=`+e.dataset.code}})}catch(e){s(`识别服务暂时不可用（`+t(e.message)+`），请直接输入 6 位代码。`)}};i.onclick=c,r.addEventListener(`keydown`,e=>{e.key===`Enter`&&c()}),n?(r.value=n,c()):r.focus()}function O(e){let t=e.dims||[],n=e.groups||{},r=e.gate||{},i={profit_quality:`Q`,core_competence:`Q`,growth:`Q`,financial_health:`Q`,valuation:`V`,earnings_revision:`V`,chain_prosperity:`M`,capital_momentum:`M`},a={Q:[],V:[],M:[]};t.forEach(e=>{let t=i[e.key];t&&a[t].push(e)});let o=(e,t,r,i={})=>{let o=n[r]||{};return{key:e,title:t,score:o.score??null,weight:o.weight??0,headline:o.headline||``,verdict:``,dims:a[r]||[],sections:[],blocks:[],...i}};return{quality:o(`quality`,`质地`,`Q`),price:o(`price`,`价格`,`V`,{valuation_facts:[],valuation_gaps:[]}),momentum:o(`momentum`,`势能`,`M`,{industry_facts:[]}),risk:{key:`risk`,title:`风险`,score:null,weight:0,headline:``,verdict:`不参与打分，只做风险核查`,dims:[],sections:[],blocks:[],risk_facts:[],risk_flags:[],risk_gaps:[],contradictions:[],critic:{issues:[],summary:``},unresolved:[],gate:r}}}async function k(e){let n=document.getElementById(`ss3-root`);if(!n)return;if(!document.getElementById(`ss3-style`)){let e=document.createElement(`style`);e.id=`ss3-style`,e.textContent=`
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
.ss3 .tagA,.ss3 .tagB,.ss3 .tagC{font-size:10.5px;font-weight:800;padding:1px 5px;border-radius:3px;white-space:nowrap}
.ss3 .tagA{background:var(--green-l);color:var(--green);border:1px solid var(--green-b)}
.ss3 .tagB{background:var(--gold-l);color:var(--gold);border:1px solid var(--gold-b)}
/* 第2层角标（V4 中性口径）：棕底金字，≤2项，点击跳第三层锚点 */
.ss3 .tagC{background:var(--brown-l,#f5efe6);color:var(--brown,#7a5a37);border:1px solid var(--brown-b,#d9c4a3);cursor:pointer}
.ss3 .tagC:hover{background:var(--brown-b,#d9c4a3)}
.ss3 .fl{font-size:12.5px;padding:7px 12px;border-radius:6px;margin-bottom:6px;line-height:1.6}
.ss3 .fl.r{background:var(--red-l);border:1px solid var(--red-b);color:#8a4a41}
.ss3 .fl.y{background:var(--gold-l);border:1px solid var(--gold-b);color:#6b5427}
.ss3 .fl.f{background:var(--blue-l);border:1px solid var(--blue-b);color:#2c5f8a}
.ss3 .fl.n{background:#f7f8fa;border:1px solid var(--line);color:var(--muted)}
.ss3 .blk{margin-bottom:13px}
.ss3 .blk .h{font-size:12px;font-weight:800;color:var(--green);letter-spacing:.06em;margin-bottom:3px}
.ss3 .blk .t{font-size:13.5px;color:var(--ink2);line-height:1.75}
.ss3 .note{font-size:11.5px;color:var(--faint);line-height:1.7;margin-top:9px}
/* 2026-10-22：总体评价块。用户要求先看分数及总体评价、再看深度分析，
   所以总体评价要比 note 醒目一点，但不能抢分数的位置。 */
.ss3 .verdict{margin-top:10px;font-size:13px;line-height:1.75;color:var(--fg)}
.ss3 .verdict b{display:inline-block;margin-right:8px;font-size:11px;font-weight:600;
  color:var(--gold);border:1px solid var(--gold);border-radius:3px;padding:1px 6px;
  vertical-align:1.5px;letter-spacing:.5px}
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
`,document.head.appendChild(e)}n.className=`ss3`;let r=new URLSearchParams(location.search),i=(r.get(`code`)||r.get(`q`)||``).trim(),a=/^(sh|sz|bj)?\d{6}(\.(sh|sz|bj))?$/i.test(i)?i.replace(/\D/g,``):``;if(!a){n.innerHTML=T(),D(n,i);return}let o=e===`index`;n.innerHTML=`<div class="card"><div class="note">${o?`正在计算（首次约 1-2 分钟建全市场宇宙，之后同码 10 分钟内秒回）…`:`正在取数…`}</div></div>`;let s;try{s=await m()}catch(e){n.innerHTML=`<div class="card"><div class="fl r">无法连接后端：${t(e.message)}</div></div>`;return}let c=null;for(let e=1;e<=6;e++)try{c=await h(s,`/api/stockscore_v3_core`,a);break}catch(r){if(e===6){n.innerHTML=`<div class="card"><div class="fl r">查询失败：${t(r.message)}</div>
            <div class="note"><a href="${location.pathname}">重新输入代码</a></div></div>`;return}n.innerHTML=`<div class="card"><div class="note">后端正在建全市场横截面宇宙，已自动重试 ${e}/6 次…</div></div>`,await g(2e4)}if(!c)return;c.modules=O(c);let l=()=>{let r=p(c)+f(c.code,e),i=o?S(c):C(c,e),a=(c.source_errors||[]).length?`<br>取数告警：`+t(c.source_errors.join(`；`)):``,s=`<div class="foot">总分 = 0.52×Q + 0.26×V + 0.22×M，再过闸门（🔴封顶59 / 🟡≥2降一档 / 🟡=1仅标注）。${c.contract===`core_v1`?` <span class="pill p-gray">核心层已返回 · 深度正文增量中</span>`:``}
      缺失子项不进分母、整维缺失标 N/A 不填 0；每个分数带置信度，<0.6 进低置信清单。<br>
      深度分析的每个数字都来自可溯源的公开数据或券商研报原文抽取；研报观点仅代表分析师判断，不构成本站观点。
      本页所有数字由公开数据按页面写明口径计算，数据可能有误、口径有局限，请自行复核。<br>
      结构化读数不构成投资建议，不预测涨跌，不含任何买卖意见。${a}</div>`;n.innerHTML=r+i+s};l();try{let e=await h(s,`/api/stockscore_v3_modules`,a),t=!1;if(e&&c.modules){if(e.valuation){let n=c.modules.price||{};n.valuation_facts=e.valuation.facts,n.valuation_gaps=e.valuation.gaps,t=!0}if(e.risk){let n=c.modules.risk||{};n.risk_facts=e.risk.facts,n.risk_flags=e.risk.flags,n.risk_gaps=e.risk.gaps,t=!0}}t&&l()}catch{}if(o)try{await h(s,`/api/stockscore_v3_deep_prewarm`,a)}catch{}else{let t={quality:[`business`,`moat`],price:[`numbers`,`valuation`],momentum:[`market`],risk:[`risk`]}[e]||null;w(s,a,l,t)}}typeof document<`u`&&document.addEventListener(`click`,e=>{let t=e.target.closest&&e.target.closest(`.tagC[data-ss3-jump]`);if(!t)return;let n=t.getAttribute(`data-ss3-jump`),r=document.getElementById(`ss3-l3-`+n);if(!r)return;let i=r.querySelector(`details.ss3-l3`);i&&(i.open=!0),r.scrollIntoView({behavior:`smooth`,block:`start`})});export{k as t};