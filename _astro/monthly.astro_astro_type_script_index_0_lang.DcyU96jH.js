import"./charts.Deit_MZj.js";var e=JSON.parse(document.getElementById(`__HISTORY_DATA__`)?.textContent??`{"months":[]}`),t=JSON.parse(document.getElementById(`__STRATEGY_META__`)?.textContent??`{}`),n=document.getElementById(`rec-search`),r=document.getElementById(`rec-results`);function i(e){let t=e.replace(/[^0-9]/g,``);return t.length===6?t:t.length===7?t.slice(0,4)+t.slice(5):t}function a(n){if(!n||n.length!==6){r.innerHTML=`<p style="color:var(--text-3);font-size:14px;">请输入 6 位月份，如 202607</p>`;return}let i=e.months?.find(e=>e.ym===n),a=t.months?.indexOf(n),o=a>=0?t.monthly_compare?.v31?.[a]:null,s=a>=0?t.monthly_compare?.hs300?.[a]:null;if(!i&&o==null){r.innerHTML=`<p style="color:var(--red);font-size:14px;">未找到 ${n} 的数据</p>`;return}let c=``;if(o!=null&&(c+=`
          <div style="background:var(--surface-alt);border-radius:10px;padding:16px;margin-bottom:14px;">
            <b style="font-size:15px;color:var(--navy-800);">${n.slice(0,4)} 年 ${n.slice(4)} 月 · 策略表现</b>
            <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px;">
              <div style="text-align:center;"><div style="font-size:18px;font-weight:700;color:${o>=0?`var(--green)`:`var(--red)`};">${o>=0?`+`:``}${o.toFixed(2)}%</div><div style="font-size:11px;color:var(--text-3);">V31 基金版</div></div>
              <div style="text-align:center;"><div style="font-size:18px;font-weight:700;color:${s>=0?`var(--green)`:`var(--red)`};">${s>=0?`+`:``}${s.toFixed(2)}%</div><div style="font-size:11px;color:var(--text-3);">沪深300</div></div>
              <div style="text-align:center;"><div style="font-size:18px;font-weight:700;color:${o-s>=0?`var(--green)`:`var(--red)`};">${o-s>=0?`+`:``}${(o-s).toFixed(2)}pp</div><div style="font-size:11px;color:var(--text-3);">超额</div></div>
            </div>
          </div>`),i){let e=[];i.is_empty&&e.push(`<span style="font-size:11px;padding:2px 10px;border-radius:999px;background:var(--red-bg);color:var(--red);font-weight:600;">空仓保险月</span>`),i.bull_mode&&e.push(`<span style="font-size:11px;padding:2px 10px;border-radius:999px;background:var(--green-bg);color:var(--green);font-weight:600;">牛市增强月</span>`),c+=`
          <div style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:14px;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px;">
              <b style="font-size:15px;color:var(--navy-800);">${n.slice(0,4)} 年 ${n.slice(4)} 月 · 选股名单（${i.picks?.length??0} 只）</b>
              ${e.join(``)}
            </div>
            <p style="font-size:12.5px;color:var(--text-3);margin:6px 0 10px;">
              报告期 ${i.report_qe} · 候选 ${i.candidate_count} 只 ·
              ${i.bull_mode?`<b style="color:var(--green);">牛市增强：价值Top1 + 成长Top2</b>`:`<b style="color:var(--navy-700);">普通月 Top4</b>`}
              · FCF/EV 排名加权（不等权）
            </p>
            <table class="data-table"><thead><tr><th>代码</th><th>行业</th><th>FCF/EV</th><th>权重</th><th>VC估值</th><th>投前月</th><th>投后月</th></tr></thead><tbody>
            ${(i.picks??[]).map(e=>`
              <tr>
                <td>${e.ts_code}</td>
                <td>${e.industry??`—`}</td>
                <td>${e.fcf_ev??`—`}</td>
                <td><b style="color:var(--navy-700);">${e.weight==null?`—`:(e.weight*100).toFixed(1)+`%`}</b></td>
                <td>${e.vc??`—`}</td>
                <td class="${e.prev_ret!=null&&e.prev_ret<0?`neg`:`pos`}">${e.prev_ret==null?`—`:(e.prev_ret>0?`+`:``)+e.prev_ret.toFixed(2)+`%`}</td>
                <td class="${e.next_ret!=null&&e.next_ret<0?`neg`:`pos`}">${e.next_ret==null?`—`:(e.next_ret>0?`+`:``)+e.next_ret.toFixed(2)+`%`}</td>
              </tr>`).join(``)}
            </tbody></table>
            <p style="font-size:12px;color:var(--text-3);margin-top:8px;">权重 = FCF/EV 排名加权（rank+0.5 归一化），非等权。投前月 = 选股时点上一月收益（止损过滤依据）；投后月 = 持仓月实际收益。</p>
          </div>`}r.innerHTML=c}n?.addEventListener(`input`,()=>{let e=i(n.value);e.length===6?a(e):r.innerHTML=``});