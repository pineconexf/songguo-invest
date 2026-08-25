import"./charts.Deit_MZj.js";var e=JSON.parse(document.getElementById(`__MACRO_DATA__`)?.textContent??`[]`),t=document.getElementById(`macro-search`),n=document.getElementById(`macro-results`);function r(t){let r=t.trim().toUpperCase();if(!r){n.innerHTML=`<p style="color:var(--text-3);font-size:14px;">输入关键词开始搜索</p>`;return}let i=e.filter(e=>e.week.toUpperCase().includes(r));if(i.length===0){n.innerHTML=`<p style="color:var(--red);font-size:14px;">未找到匹配的周</p>`;return}n.innerHTML=i.slice(0,50).map(e=>`
          <div style="padding:12px 14px;border-bottom:1px solid var(--border);font-size:14px;">
            <b>${e.week}</b> · Shibor ${e.shibor}% · 环比 ${e.diff_bp??`—`}bp ·
            <span style="color:${e.signal===`宽松`?`var(--green)`:`var(--red)`};font-weight:600;">${e.signal}</span>
            ${e.hs300_ret==null?``:` · HS300周 ${(e.hs300_ret*100).toFixed(2)}%`}
            ${e.zz500_ret==null?``:` · 中证500周 ${(e.zz500_ret*100).toFixed(2)}%`}
          </div>`).join(``)+(i.length>50?`<p style="color:var(--text-3);font-size:12px;padding:8px;">…共 ${i.length} 条，仅显示前 50 条</p>`:``)}t?.addEventListener(`input`,()=>r(t.value));