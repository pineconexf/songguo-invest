var e=[[`index`,`总览`,`overview`],[`quality`,`质地`,`quality`],[`price`,`价格`,`price`],[`momentum`,`势能`,`momentum`]],t=e=>String(e??``).replace(/&/g,`&amp;`).replace(/</g,`&lt;`).replace(/>/g,`&gt;`).replace(/"/g,`&quot;`);function n(e,n=2){if(e==null)return`N/A`;if(typeof e!=`number`)return t(e);if(Math.abs(e)>=1e6)return e.toLocaleString(`zh-CN`,{maximumFractionDigits:0});let r=e.toFixed(n);return r.indexOf(`.`)>=0&&(r=r.replace(/0+$/,``).replace(/\.$/,``)),r||`0`}var r=e=>({优:`p-in`,良:`p-in`,中:`p-out`,待观察:`p-red`})[e]||`p-gray`,i=e=>({in:`p-in`,out:`p-out`,red:`p-red`})[e]||`p-gray`,a=e=>e===`valuation`?`v`:[`chain_prosperity`,`earnings_revision`,`capital_momentum`].indexOf(e)>=0?`m`:``,o=[`index`,`quality`,`price`,`momentum`];function s(){let e=null;try{e=new URLSearchParams(location.search).get(`view`)}catch{}if(e&&o.indexOf(e)>=0)return e;let t=location.pathname.match(/\/stockscore(?:\/(index|quality|price|momentum))?\/?$/);return t&&t[1]||`index`}function c(){let e=location.pathname.replace(/\/+$/,``),t=e.match(/^(.*\/stockscore)(?:\/(?:index|quality|price|momentum))?$/);return t?t[1]:e}function l(t,n){let r=c(),i=n||s();return`<div class="nav">`+e.map(([e,n])=>`<a class="${e===i?`on`:``}" href="${r}${e===`index`?``:`/`+e}/?code=${encodeURIComponent(t)}">${n}</a>`).join(``)+`</div>`}function u(e){return`<div class="ident"><h1>${t(e.name)}</h1><span class="code">${t(e.code)}</span><span class="ind">${t(e.industry||`—`)}</span><span class="ind">数据 ${t(e.data_asof)}</span></div>`}function d(e){if(!e.available)return`<div class="dimhead"><h3>${t(e.label)}</h3><div class="sc">N/A<small>权重 ${Math.round(e.weight*100)}%</small></div></div><div class="fl n">${t(e.na_reason||`该维不可用`)}</div>`;let r=e.metrics.map(e=>{let r=e.reliability===`A`?`<br><span class="tagA">A级·真实披露</span>`:e.reliability===`B`?`<br><span class="tagB">B级·大单推算</span>`:``,i=e.note?`<div class="note">${t(e.note)}</div>`:``;return`<tr><td>${t(e.name)}${r}${i}</td><td class="n">${n(e.value)}${t(e.unit||``)}</td><td class="n">${n(e.pctl,0)}</td><td class="n">${Math.round(e.weight*100)}%</td><td class="n">${e.confidence}</td></tr>`}).join(``),i=(e.flags||[]).map(e=>`<div class="fl n">${t(e)}</div>`).join(``),a=e.thresh?`<div class="note">口径：${t(e.thresh)}</div>`:``;return`<div class="dimhead"><h3>${t(e.label)}</h3><div class="sc">${n(e.score,1)}<small>权重 ${Math.round(e.weight*100)}% · 置信 ${e.confidence}</small></div></div><table><thead><tr><th>子指标</th><th style="text-align:right">数值</th><th style="text-align:right">分位/刻度</th><th style="text-align:right">维内权重</th><th style="text-align:right">置信</th></tr></thead><tbody>${r}</tbody></table>${i}${a}`}function f(e,n){return(e.pages[n]&&e.pages[n].blocks||[]).map(e=>`<div class="blk"><div class="h">${t(e.h)}</div><div class="t">${t(e.t)}</div></div>`).join(``)}function p(e){let o=e.groups,s=e.dims.map(e=>{let r=e.score===null?0:Math.max(0,Math.min(100,e.score));return`<div class="row"><div class="nm">${t(e.label)}<em>${Math.round(e.weight*100)}%</em></div><div class="bar ${a(e.key)}${e.score===null?` na`:``}"><i style="width:${r.toFixed(1)}%"></i></div><div class="sc">${n(e.score,1)}</div></div>`}).join(``),c=e.gate.red.map(e=>`<div class="fl r">🔴 ${t(e)}</div>`).join(``)+e.gate.yellow.map(e=>`<div class="fl y">🟡 ${t(e)}</div>`).join(``);!e.gate.red.length&&!e.gate.yellow.length&&(c=`<div class="fl n">✅ 未触发红旗与黄旗</div>`),c+=`<div class="fl n">未接入：${t((e.gate.not_wired||[]).join(`、`))}</div>`;let l=Object.entries(e.investable_checks||{}).map(([e,n])=>`<div class="${n?`ok`:`no`}">${n?`✅`:`❌`} ${t(e)}</div>`).join(``);return`<div class="card"><div class="hero">
    <div><div class="big">${n(e.total,1)}<small>分 · ${t(e.tier)}</small></div>
    <div class="note" style="margin-top:8px">裸分 ${n(e.total_raw,1)}${e.tier_note?`　`+t(e.tier_note):``}</div></div>
    <div class="meta"><span class="pill ${i(e.tag.code)}">${t(e.tag.label)}</span>
      <span class="pill ${r(e.tier)}">档位 ${t(e.tier)}</span>
      <span class="pill p-gray">红旗 ${e.gate.red.length} · 黄旗 ${e.gate.yellow.length}</span>
      <div class="note">${t(e.tag.desc)}</div></div></div>
    <div class="g3">
      <div class="gcard Q"><div class="k">Q · 质地</div><div class="v">${n(o.Q.score,1)}</div><div class="q">${t(o.Q.question)}｜权重 ${o.Q.weight}</div></div>
      <div class="gcard V"><div class="k">V · 价格</div><div class="v">${n(o.V.score,1)}</div><div class="q">${t(o.V.question)}｜权重 ${o.V.weight}</div></div>
      <div class="gcard M"><div class="k">M · 势能</div><div class="v">${n(o.M.score,1)}</div><div class="q">${t(o.M.question)}｜权重 ${o.M.weight}</div></div>
    </div></div>
    <div class="card"><h2 class="s">八维得分<span class="w">权重合计 ${n(e.meta.weights_sum,2)}</span></h2>${s}</div>
    <div class="card"><h2 class="s">闸门</h2>${c}</div>
    <div class="card"><h2 class="s">松果可投性（简化 11 步 + 市值）</h2><div class="chk">${l}</div>
      <div class="note">完整 V35 管线含 VC∈[0.90,0.99]、行业软调节、红旗删票不补位；本卡用可公开验证的简化口径做代理，
      标签含义为「落在射程内与否」，不等于买入建议。</div></div>
    <div class="card"><h2 class="s">一句话结论</h2>${f(e,`overview`)}</div>`}var m={Q:`quality`,V:`price`,M:`momentum`};function h(e,r,i,a){let o=e.groups[r],s=m[r]||String(r).toLowerCase(),c=e.pages[s]||{},l=e.dims.filter(e=>i.indexOf(e.key)>=0),u=`<div class="card"><div class="hero"><div class="big">${n(o.score,1)}<small>${r} · ${t(o.label)}</small></div>
    <div class="meta"><div style="font-size:13.5px;color:var(--ink2)">${t(c.headline||``)}</div>
    <div class="note">${t(o.v35)}</div></div></div></div>`,p=`<div class="card"><h2 class="s">${l.length} 个维度合在一起看</h2>${l.map(d).join(``)}</div>`,h=`<div class="card"><h2 class="s">结论</h2>${f(e,s)}
    ${a?`<div class="note">${a}</div>`:``}</div>`;return u+p+h}var g=`纵向=链条位置与议价力（慢变，结构）；横向=同行地位与技术代差；自身=壁垒类型与持续性。技术代差、毛利溢价为代理指标——真正的护城河（转换成本、网络效应、心智占领）拿不到结构化数据。`,_=`低分位=高分。亏损股 PE 无定义时整维 N/A；金融业只计 PB。松果 FCF 收益率为 FCFF÷市值的代理口径（未扣净债），权重 26%，是这一维里最接近策略排序逻辑的子项。`,v=`资金动能按真实性分三级：A 级=融资余额/龙虎榜（真实披露，占 3.5 分）；B 级=主力净流入（按单笔金额分档推算，<b>主力可拆单规避</b>，占 2.5 分，只读异动不读意图）；C 级=北向资金（2024-09-30 起停止实时披露，永久剔除）。主窗口统一 20 日，与月度调仓同频。`;function y(e,n){let r;r=n===`quality`?h(e,`Q`,[`profit_quality`,`core_competence`,`growth`,`financial_health`],g):n===`price`?h(e,`V`,[`valuation`],_):n===`momentum`?h(e,`M`,[`chain_prosperity`,`earnings_revision`,`capital_momentum`],v):p(e);let i=`<div class="foot">总分 = 0.52×Q + 0.26×V + 0.22×M，再过闸门（🔴封顶59 / 🟡≥2降一档 / 🟡=1仅标注）。
    缺失子项不进分母、整维缺失标 N/A 不填 0；每个分数带置信度，&lt;0.6 进低置信清单。<br>
    本页所有数字由公开数据按页面写明口径计算，数据可能有误、口径有局限，请自行复核。
    结构化读数不构成投资建议，不预测涨跌，不含任何买卖意见。${(e.source_errors||[]).length?`<br>取数告警：`+t(e.source_errors.join(`；`)):``}</div>`;return u(e)+l(e.code,n)+r+i}function b(){return`<div class="card"><h2 class="s">输入股票代码</h2>
    <div class="form"><input id="ss3code" maxlength="6" inputmode="numeric" placeholder="如 600519">
    <button id="ss3go">开始打分</button></div>
    <div class="note">支持 A 股 6 位代码。首次查询需现建全市场横截面宇宙（约 1-2 分钟，期间会自动重试）；10 分钟内同码命中缓存秒回。</div></div>`}async function x(){if(window.__SS_BASE__)return window.__SS_BASE__;if(/\.github\.io$/i.test(location.hostname))return window.__SS_BASE__=`https://pinecone-lab.cn`,window.__SS_BASE__;try{if((await fetch(`http://127.0.0.1:8081/api/health`)).ok)return window.__SS_BASE__=`http://127.0.0.1:8081`,window.__SS_BASE__}catch{}return location.origin}var S=e=>new Promise(t=>setTimeout(t,e));async function C(e,t,n){for(let r=1;r<=6;r++){let i;try{i=await fetch(e+`/api/stockscore_v3`,{method:`POST`,headers:{"Content-Type":`application/json`},body:JSON.stringify({code:t})})}catch(e){if(r===6)throw e;n(r,`网络中断`),await S(2e4);continue}if(i.ok)return i.json();if([500,502,503,504].indexOf(i.status)>=0&&r<6){n(r,`HTTP `+i.status),await S(2e4);continue}let a=await i.text();throw Error(`HTTP `+i.status+`：`+a.slice(0,160))}throw Error(`多次重试仍失败`)}async function w(e){let n=document.getElementById(`ss3-root`);if(!n)return;if(!document.getElementById(`ss3-style`)){let e=document.createElement(`style`);e.id=`ss3-style`,e.textContent=`
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
`,document.head.appendChild(e)}n.className=`ss3`;let r=(new URLSearchParams(location.search).get(`code`)||``).replace(/\D/g,``);if(!r){n.innerHTML=b();let e=()=>{let e=(document.getElementById(`ss3code`).value||``).replace(/\D/g,``);if(e.length!==6){alert(`请输入 6 位 A 股代码`);return}location.search=`?code=${e}`};document.getElementById(`ss3go`).onclick=e,document.getElementById(`ss3code`).addEventListener(`keydown`,t=>{t.key===`Enter`&&e()});return}n.innerHTML=`<div class="card"><div class="note">正在计算（首次约 1-2 分钟建全市场宇宙，之后同码 10 分钟内秒回）…</div></div>`;try{n.innerHTML=y(await C(await x(),r,(e,r)=>{n.innerHTML=`<div class="card"><div class="note">后端正在建全市场横截面宇宙（${t(r)}），已自动重试 ${e}/6 次，请稍候…首次约 1-2 分钟，完成后 10 分钟内同码秒回。</div></div>`}),e)}catch(e){n.innerHTML=`<div class="card"><div class="fl r">查询失败：${t(e.message)}</div>
      <div class="note"><a href="${location.pathname}">重新输入代码</a></div></div>`}}export{w as t};