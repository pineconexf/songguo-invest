import"./charts.Deit_MZj.js";var e=JSON.parse(document.getElementById(`__V34_PICKS__`)?.textContent??`{"months":[]}`),t=JSON.parse(document.getElementById(`__HISTORY_DATA__`)?.textContent??`{"months":[]}`),n=JSON.parse(document.getElementById(`__STRATEGY_META__`)?.textContent??`{}`),r=document.getElementById(`rec-search`),i=document.getElementById(`rec-results`),a=`v34`,o=document.getElementById(`tab-v34`),s=document.getElementById(`tab-v31`);o?.addEventListener(`click`,()=>{a=`v34`,c(),u(r?.value??``)}),s?.addEventListener(`click`,()=>{a=`v31`,c(),u(r?.value??``)});function c(){let e=e=>{e&&(e.style.borderColor=`var(--gold,#d9a441)`,e.style.background=`rgba(217,164,65,0.12)`,e.style.color=`var(--gold,#b8860b)`,e.style.fontWeight=`700`)},t=e=>{e&&(e.style.borderColor=`var(--border-strong)`,e.style.background=`transparent`,e.style.color=`var(--text-3)`,e.style.fontWeight=`600`)};a===`v34`?(e(o),t(s)):(e(s),t(o))}function l(e){let t=e.replace(/[^0-9]/g,``);return t.length===6?t:t.length===7?t.slice(0,4)+t.slice(5):t}function u(r){let o=l(r??``);if(!o||o.length!==6){i.innerHTML=`<p style="color:var(--text-3);font-size:14px;">请输入 6 位月份，如 202607</p>`;return}let s=a===`v34`,c=s?e.months?.find(e=>e.ym===o):t.months?.find(e=>e.ym===o),u=n.months?.indexOf(o),d=u>=0?s?n.monthly_compare?.v34?.[u]:n.monthly_compare?.v31?.[u]:null,f=u>=0?n.monthly_compare?.hs300?.[u]:null;if(!c&&d==null){i.innerHTML=`<p style="color:var(--red);font-size:14px;">未找到 ${o} 的数据</p>`;return}let p=``;if(d!=null&&(p+=`
          <div style="background:var(--surface-alt);border-radius:10px;padding:16px;margin-bottom:14px;">
            <b style="font-size:15px;color:var(--navy-800);">${o.slice(0,4)} 年 ${o.slice(4)} 月 · 策略表现（${s?`V34 基础版`:`V31 沿革`}）</b>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px;">
              <div style="text-align:center;"><div style="font-size:18px;font-weight:700;color:${d>=0?`var(--green)`:`var(--red)`};">${d>=0?`+`:``}${d.toFixed(2)}%</div><div style="font-size:11px;color:var(--text-3);">策略收益</div></div>
              <div style="text-align:center;"><div style="font-size:18px;font-weight:700;color:${f>=0?`var(--green)`:`var(--red)`};">${f>=0?`+`:``}${f.toFixed(2)}%</div><div style="font-size:11px;color:var(--text-3);">沪深300</div></div>
              <div style="text-align:center;"><div style="font-size:18px;font-weight:700;color:${d-f>=0?`var(--green)`:`var(--red)`};">${d-f>=0?`+`:``}${(d-f).toFixed(2)}pp</div><div style="font-size:11px;color:var(--text-3);">超额</div></div>
            </div>
          </div>`),c){let e=[];s?c.drops&&c.drops.length&&e.push(`<span style="font-size:11px;padding:2px 10px;border-radius:999px;background:var(--red-bg);color:var(--red);font-weight:600;">红旗删除 ${c.drops.length} 只</span>`):(c.is_empty&&e.push(`<span style="font-size:11px;padding:2px 10px;border-radius:999px;background:var(--red-bg);color:var(--red);font-weight:600;">空仓保险月</span>`),c.bull_mode&&e.push(`<span style="font-size:11px;padding:2px 10px;border-radius:999px;background:var(--green-bg);color:var(--green);font-weight:600;">牛市增强月</span>`));let t=c.picks??[];p+=`
          <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px;">
              <b style="font-size:15px;color:var(--navy-800);">${o.slice(0,4)} 年 ${o.slice(4)} 月 · 选股名单（${t.length} 只）${s?` · V34`:` · V31`}</b>
              ${e.join(``)}
            </div>
            <p style="font-size:12.5px;color:var(--text-3);margin:6px 0 10px;">
              ${s?`<b style="color:var(--navy-700);">FCF/EV Top4 + 帕伯莱红旗审查</b>（删票满仓集中于保留票；2012-2015 段红旗不亮 = V31 原版）`:`报告期 ${c.report_qe} · 候选 ${c.candidate_count} 只 · ${c.bull_mode?`<b style="color:var(--green);">牛市增强：价值Top1 + 成长Top2</b>`:`<b style="color:var(--navy-700);">普通月 Top4</b>`} · FCF/EV 排名加权（不等权）`}
            </p>
            <table class="data-table"><thead><tr><th>代码</th><th>${s?`当月收益`:`行业`}</th><th>${s?`状态`:`FCF/EV`}</th><th>${s?``:`权重`}</th><th>${s?``:`VC估值`}</th><th>投前月</th><th>投后月</th></tr></thead><tbody>
            ${(s?c.picks:c.picks??[]).map(e=>{if(s){let t=c.stock_rets?.[e];return`
                  <tr>
                    <td>${e}</td>
                    <td class="${t!=null&&t<0?`neg`:`pos`}">${t==null?`—`:(t>0?`+`:``)+t.toFixed(2)+`%`}</td>
                    <td>${c.drops?.includes(e)?`<b style="color:var(--red);">红旗删除</b>`:`<span style="color:var(--green);">保留</span>`}</td>
                    <td></td><td></td>
                    <td>—</td>
                    <td>—</td>
                  </tr>`}return`
                <tr>
                  <td>${e.ts_code}</td>
                  <td>${e.industry??`—`}</td>
                  <td>${e.fcf_ev??`—`}</td>
                  <td><b style="color:var(--navy-700);">${e.weight==null?`—`:(e.weight*100).toFixed(1)+`%`}</b></td>
                  <td>${e.vc??`—`}</td>
                  <td class="${e.prev_ret!=null&&e.prev_ret<0?`neg`:`pos`}">${e.prev_ret==null?`—`:(e.prev_ret>0?`+`:``)+e.prev_ret.toFixed(2)+`%`}</td>
                  <td class="${e.next_ret!=null&&e.next_ret<0?`neg`:`pos`}">${e.next_ret==null?`—`:(e.next_ret>0?`+`:``)+e.next_ret.toFixed(2)+`%`}</td>
                </tr>`}).join(``)}
            </tbody></table>
            <p style="font-size:12px;color:var(--text-3);margin-top:8px;">
              ${s?`V34 档案：当月收益 = 个股在持仓月实际收益（%）。红旗删除 = 帕伯莱审查命中被剔除的股票。投前/投后明细见回测系统原始 CSV（v34_picks.json 仅含精简字段）。`:`权重 = FCF/EV 排名加权（rank+0.5 归一化），非等权。投前月 = 选股时点上一月收益（止损过滤依据）；投后月 = 持仓月实际收益。`}
            </p>
          </div>`}i.innerHTML=p}r?.addEventListener(`input`,()=>{u(r.value)});