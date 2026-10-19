/* Read-only experiment catalogue. A result link never starts a simulation. */
(function(root){
  'use strict';
  const states={prepared:'已准备，尚未运行',preparing:'正在准备',running:'运行中',completed:'全部完成',failed:'失败，保留已完成部分',interrupted:'已中断',unavailable:'证据不可用',not_started:'尚未运行'};
  const stageNames={baseline:'基线',closure:'封路',alternative:'封路＋替代道路'};
  let revision=0;
  const el=(tag,text)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
  const num=x=>typeof x==='number'&&Number.isFinite(x)?x.toFixed(3):'—';
  async function load(openRun){
    const seq=++revision,host=document.getElementById('planningCases');
    if(!host)return;
    host.hidden=false;host.replaceChildren(el('h2','成组规划实验'),el('p','读取已保存实验，不会启动仿真…'));
    const refresh=el('button','刷新实验记录');refresh.className='secondary-button';refresh.onclick=()=>load(openRun);
    try{
      const response=await fetch('/ifline/planning-cases',{cache:'no-store'});const data=await response.json();
      if(!response.ok)throw Error(data.detail||'无法读取实验记录');if(seq!==revision)return;
      host.replaceChildren(el('h2','成组规划实验'),el('p','固定人口，逐个种子比较：基线 → 封路 → 封路＋替代道路。范围是这些模型运行的描述性差异，不是置信区间或工程批准。'),refresh);
      if(!data.cases.length){host.append(el('p','尚无成组实验记录。仍可在下方自由编辑自己的方案。'));return;}
      for(const c of data.cases){
        const card=el('details');card.className='planning-case';card.open=c.status==='completed'||c.status==='running';
        const region=c.region==='cbd'?'墨尔本 CBD':(c.region||'本地');
        card.append(el('summary',`${region} · 封路与替代道路 · ${states[c.status]||c.status}`));host.append(card);
        if(c.status==='unavailable'){card.append(el('p',c.error));continue;}
        const id=el('p',`记录编号：${c.id}`);id.style.overflowWrap='anywhere';card.append(id);
        card.append(el('p',c.scope==='expanded_network_fixed_population'
          ? '范围：固定原人口，单独扩大路网覆盖。未重新生成需求；空间覆盖不等于交通模型已校准。'
          : '历史小范围实验：存在路网与人口活动范围不一致的已知限制，不能当作可靠的规划收益。'));
        card.append(el('p',`${c.population_count} 个合成代理 · 每次 ${c.total_iterations} 轮 · ${c.rows.length} 个种子。已知建筑冲突：封路 ${c.conflict_count.closure}，替代道路 ${c.conflict_count.alternative}。`));
        if(c.geometry?.alternative_length_m!=null)card.append(el('p',`关闭 ${c.geometry.closure_links?.length??'—'} 条有向机动车路段，替代道路长度约 ${num(c.geometry.alternative_length_m)} 米。实验要求固定输入人口、匹配各组种子与设置；打开工作台时会再次核对实际文件。`));
        if(Object.values(c.conflict_count).some(n=>n>0))card.append(el('p','⚠ 此方案包含建筑冲突，仅保留为概念筛查；不得视为可直接建设的道路。'));
        const table=el('table'),head=el('tr');['种子','基线','封路','封路＋替代道路','两种干预直接对比'].forEach(x=>head.append(el('th',x)));table.append(head);
        for(const row of c.rows){const tr=el('tr');tr.append(el('td',String(row.seed)));
          for(const name of Object.keys(stageNames)){const td=el('td'),stage=row.stages[name];
            if(stage.run){const b=el('button',`打开${stageNames[name]}`);b.onclick=()=>openRun(stage.run);td.append(b);}else td.textContent=states[stage.status]||stage.status;tr.append(td);}
          const td=el('td'),a=row.stages.closure.run,b=row.stages.alternative.run;
          if(a&&b){const compare=el('button','替代道路 vs 封路');compare.onclick=()=>openRun(b,a);td.append(compare);}else td.textContent='等待两侧完成';tr.append(td);table.append(tr);
        }
        const wrap=el('div');wrap.style.overflowX='auto';wrap.append(table);card.append(wrap);
        if(c.aggregate){const agg=c.aggregate;card.append(el('p',`纳入汇总：${agg.completed_seeds.length}/${agg.expected_seeds.length} 个完整三方案组。未完成种子：${agg.incomplete_seeds.join('、')||'无'}。`));
          const names={closure_vs_baseline:'封路 − 基线',alternative_vs_baseline:'替代道路 − 基线',alternative_vs_closure:'替代道路 − 封路'};
          for(const [key,label]of Object.entries(names)){
            const v=agg.descriptive_ranges[key]?.car_mean_travel_time_s;
            if(v)card.append(el('p',`${label}：汽车平均出行耗时差，跨种子均值 ${num(v.mean)} 秒，最小 ${num(v.min)}，最大 ${num(v.max)}（有效 ${v.n}）。`));
          }
          card.append(el('p','上面汇总的是每次运行的汽车出行均值之差，不是逐出行配对估计；点击方案打开工作台查看配对队列、未配对记录及分时段结果。'));
          card.append(el('p',agg.geographic_scope_caveat));
        }else card.append(el('p',c.aggregate_error?`汇总不可用：${c.aggregate_error}。未显示跨种子结论。`:'跨种子汇总尚未生成；已完成单次结果可先打开核对。'));
        const link=el('a','查看实验状态与证据索引');link.href=c.record_url;link.target='_blank';link.rel='noopener';card.append(link,el('p',c.limitations));
      }
    }catch(error){if(seq!==revision)return;host.replaceChildren(el('h2','成组规划实验'),el('p',`读取失败：${error.message}。未显示上次结果。`),refresh);}
  }
  root.PlanningCases={load};
})(window);
