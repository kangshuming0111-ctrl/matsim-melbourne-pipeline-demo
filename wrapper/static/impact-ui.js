/* Read-only planning workbench. One request snapshot owns every map, number,
 * and export. No simulation or editor state is owned here. */
(function (root) {
  'use strict';
  const NS = 'http://www.w3.org/2000/svg';
  const labels = {comparable:'两侧均有完整通行观测',no_data:'缺少一侧或两侧完整通行观测',
    new:'新增路段，无基线同段',removed:'已移除路段',split:'拆分路段，不作整段对比',
    geometry_changed:'几何变化，不直接比较',unavailable:'此方式没有路段通行数据'};
  const number = (x, digits=2) => x === null || x === undefined || !Number.isFinite(Number(x)) ? '—' : Number(x).toLocaleString('zh-CN',{maximumFractionDigits:digits});
  const signed = x => x === null || x === undefined ? '—' : `${x>0?'+':''}${number(x,3)}`;
  const esc = text => String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rgb = values => `rgb(${values.map(x=>Math.round(x*255)).join(',')})`;
  const absoluteColor = value => value==null ? '#706e96' : value>=60?'#9c1221':value>=15?'#e0513b':value>=1?'#fab37a':'#81bda1';
  const rankedLinks = rows => [...rows].sort((a,b)=>{
    const av=a.delta.mean_travel_time_s,bv=b.delta.mean_travel_time_s;
    if(av==null||bv==null)return (av==null)-(bv==null);
    return Math.abs(bv)-Math.abs(av)||a.id.localeCompare(b.id,undefined,{numeric:true});
  });
  let session = null;
  function close() {
    if (session) { session.abort?.abort(); session.seq++; session = null; }
    const host = document.getElementById('impactWorkbench');
    if (host) { host.replaceChildren(); host.hidden=true; }
  }
  function element(tag, text, className) {
    const el=document.createElement(tag); if(text!=null)el.textContent=text; if(className)el.className=className; return el;
  }
  function button(text, action, className) { const el=element('button',text,className); el.type='button'; el.onclick=action; return el; }
  async function json(url, signal) {
    const res=await fetch(url,{signal,cache:'no-store'}); const body=await res.json();
    if(!res.ok)throw Error(body.detail||`请求失败 (${res.status})`); return body;
  }
  function save(content,type,name) {
    const url=URL.createObjectURL(new Blob([content],{type})); const a=element('a');
    a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function markDirty(s) {
    if(session!==s)return; s.seq++;s.abort?.abort();s.dirty=true;
    s.exportHTML.disabled=s.exportJSON.disabled=true;
    s.status.className='impact-status';
    s.status.textContent='筛选条件已改变，尚未重新分析。下面若仍有图表，它们属于上次已应用的条件；导出已锁定。';
    s.apply.disabled=false; scopeText(s);
  }
  function scopeText(s) {
    s.scope.textContent=s.selected.size ? `待应用走廊：${s.selected.size} 条有向路段（${[...s.selected].join('、')}）。点击地图添加/移除；再次应用分析后统计才会更新。`
      : '范围：全网。开启“选走廊”后可在地图上选多条路段；走廊队列为任一方案中实际完整经过所选路段的出行。';
  }
  function addSelect(parent,label,options) {
    const wrap=element('label',label);const select=element('select');
    options.forEach(([value,text])=>{const o=element('option',text);o.value=value;select.append(o);});
    wrap.append(select);parent.append(wrap);return select;
  }
  function open(data, adapters={}) {
    close(); const comp=data.ifline_comparison;if(!comp)return;
    const host=document.getElementById('impactWorkbench');host.hidden=false;
    const s={seq:0,abort:null,selected:new Set(),view:'delta',pickScope:false,adapters,displayedRun:comp.proposal_run,
      data:null,coverage:null,dirty:true,box:null,focusId:null};session=s;
    const head=element('div',null,'impact-head');head.append(element('span','IF LINE / 方案影响工作台','impact-kicker'),
      element('h2','改动发生在哪里，影响了哪些出行？'),
      element('p','已完成结果的只读分析 · 固定色标 · 同人口 / 同参数核对 · 不会启动新的仿真。统计时段与下方车辆播放时间相互独立。'));
    const body=element('div',null,'impact-body');host.append(head,body);s.body=body;
    const pairs=element('div',null,'impact-controls');body.append(pairs);
    const initialBaseline=adapters.initialBaseline||comp.baseline_run;
    s.base=addSelect(pairs,'参照方案 A',[[initialBaseline,initialBaseline]]);
    s.proposal=addSelect(pairs,'比较方案 B',[[comp.proposal_run,comp.scenario_name||comp.proposal_run]]);
    for(const select of [s.base,s.proposal])select.onchange=()=>{s.selected.clear();s.box=null;markDirty(s);};
    json('/ifline/baselines').then(catalog=>{
      if(session!==s)return;
      for(const select of [s.base,s.proposal])for(const run of catalog.baselines||[]) {
        if([...select.options].some(o=>o.value===run.id))continue;
        const o=element('option',`${run.label} · ${run.id}`);o.value=run.id;select.append(o);
      }
    }).catch(()=>{}); // Optional catalogue failure never changes current pair.
    const period=element('div',null,'impact-period');body.append(period);
    const preset=addSelect(period,'观察时段', [['0,108000','全仿真日（0–30时）'],['25200,32400','早高峰（7–9时）'],['57600,64800','晚高峰（16–18时）'],['custom','自定义']]);
    function hour(label,value){const l=element('label',label),input=element('input');input.type='number';input.min=0;input.max=48;input.step=.25;input.value=value;l.append(input);period.append(l);input.oninput=()=>{preset.value='custom';markDirty(s);};return input;}
    s.start=hour('开始（小时）',0);s.end=hour('结束（小时，不含）',30);
    s.mode=addSelect(period,'基线出行方式',[['car','汽车'],['bike','骑行'],['walk','步行'],['pt','公共交通'],['all','所有方式']]);s.mode.onchange=()=>markDirty(s);
    preset.onchange=()=>{if(preset.value!=='custom'){const t=preset.value.split(',').map(Number);s.start.value=t[0]/3600;s.end.value=t[1]/3600;}markDirty(s);};
    const actions=element('div',null,'impact-actions');body.append(actions);
    s.apply=button('应用条件并分析',()=>refresh(s),'primary');
    s.exportHTML=button('下载讨论报告 HTML',()=>exportReport(s));
    s.exportJSON=button('下载核对数据 JSON',()=>save(JSON.stringify({analysis:s.data,coverage:s.coverage},null,2),'application/json','ifline-impact.json'));
    s.exportHTML.disabled=s.exportJSON.disabled=true;actions.append(s.apply,s.exportHTML,s.exportJSON);
    s.status=element('div','正在读取已完成结果…','impact-status');s.status.setAttribute('role','status');body.append(s.status);
    s.scope=element('p',null,'impact-scope');body.append(s.scope);scopeText(s);
    s.result=element('div');body.append(s.result);
    refresh(s);
  }
  async function refresh(s) {
    if(session!==s)return; s.abort?.abort(); const abort=new AbortController();s.abort=abort;const seq=++s.seq;
    s.data=null;s.coverage=null;s.dirty=true;s.apply.disabled=true;s.exportHTML.disabled=s.exportJSON.disabled=true;
    s.result.replaceChildren();s.status.className='impact-status';s.status.textContent='核对两侧输入与配置，按已选时段重算事件和出行…';
    try {
      const start=Number(s.start.value)*3600,end=Number(s.end.value)*3600;
      if(s.start.value===''||s.end.value===''||!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>172800)throw Error('时间范围必须满足 0 ≤ 开始 < 结束 ≤ 48 小时。');
      const p=new URLSearchParams({baseline:s.base.value,proposal:s.proposal.value,start_s:start,end_s:end,mode:s.mode.value,links:[...s.selected].join(',')});
      const result=await json(`/ifline/impact?${p}`,abort.signal);
      if(session!==s||s.seq!==seq)return;s.data=result;s.dirty=false;s.apply.disabled=false;
      s.status.textContent=`已应用：${number(start/3600)}–${number(end/3600)} 时 · ${s.mode.selectedOptions[0].textContent} · ${s.selected.size?'所选走廊':'全网'}。配置与输入人口核对通过；不是模型校准证明。`;
      s.exportHTML.disabled=s.exportJSON.disabled=false;render(s);
      try {
        const coverage=await json(`/ifline/coverage/${encodeURIComponent(s.base.value)}`,abort.signal);
        if(session!==s||s.seq!==seq)return;s.coverage=coverage;renderQuality(s);
      } catch(e) {if(e.name!=='AbortError'&&session===s&&s.seq===seq)s.quality.append(element('p',`覆盖审计不可用：${e.message}`));}
    } catch(e) {
      if(e.name==='AbortError'||session!==s||s.seq!==seq)return;
      s.status.className='impact-status error';s.status.textContent=`分析未完成，未显示任何旧结论：${e.message}`;s.apply.disabled=false;
    }
  }
  function metric(parent,label,value,note) {const box=element('div',null,'impact-metric');box.append(element('small',label),element('strong',value),element('span',note));parent.append(box);}
  function render(s) {
    const d=s.data,t=d.trips,metrics=element('div',null,'impact-metrics');s.result.append(metrics);
    metric(metrics,'配对出行平均耗时变化',`${signed(t.delta_s.mean)} 秒`,`${number(t.baseline.mean_s)} → ${number(t.proposal.mean_s)} 秒；B − A`);
    metric(metrics,'配对出行 / 基线队列',`${t.paired_count} / ${t.cohort_count}`,'同一合成代理与出行序号，不等于同一路线');
    metric(metrics,'变快 / 变慢 / 变化不足 1 秒',`${t.faster_count} / ${t.slower_count} / ${t.within_1s_count}`,'1 秒是展示容差，不是统计显著性');
    metric(metrics,'配对出行 P95 耗时',`${number(t.baseline.p95_s)} → ${number(t.proposal.p95_s)} 秒`,'95% 分位；不是置信区间');
    s.result.append(element('p','灰色路段不等于方案没有影响：封路可能让车辆绕行、改变整趟出行耗时，而仍被使用的同一路段速度变化很小。先看配对出行，再看路段和缺失观测；不要只凭颜色判断效果。','impact-notes'));
    const layout=element('div',null,'impact-map-layout'),shell=element('div',null,'impact-map-shell');
    const bar=element('div',null,'impact-mapbar');shell.append(bar);
    s.viewButtons=[];for(const [v,label]of[['baseline','A 延误'],['proposal','B 延误'],['delta','B − A 耗时差']]){
      const b=button(label,()=>{s.view=v;drawMap(s);});b.dataset.view=v;s.viewButtons.push(b);bar.append(b);
    }
    const pick=button(`选走廊：${s.pickScope?'开':'关'}`,()=>{s.pickScope=!s.pickScope;pick.textContent=`选走廊：${s.pickScope?'开':'关'}`;pick.setAttribute('aria-pressed',s.pickScope);});pick.setAttribute('aria-pressed',s.pickScope);bar.append(pick);
    bar.append(button('清空范围',()=>{s.selected.clear();markDirty(s);updateHighlights(s);}),button('复位地图',()=>{s.box=[...s.fullBox];s.svg.setAttribute('viewBox',s.box.join(' '));}));
    s.svg=document.createElementNS(NS,'svg');s.svg.classList.add('impact-map');s.svg.setAttribute('aria-label','方案影响地图：拖动平移，滚轮缩放，点击道路查看，选走廊模式可多选');shell.append(s.svg);
    s.legend=element('div',null,'impact-legend');shell.append(s.legend);
    s.detail=element('div',null,'impact-detail');layout.append(shell,s.detail);s.result.append(layout);
    s.detail.append(element('h3','点击一条道路'),element('p','查看有向路段两侧的观测数和通行时间。紫灰色虚线表示不能直接比较，不是“严重拥堵”。'));
    attachPan(s);drawMap(s);
    s.result.append(element('p','路段表按通行时间差绝对值排序。未观测、新增和拆分路段保留为空值；不会当成改善。','impact-notes'));
    const tableWrap=element('div',null,'impact-table-wrap'),table=element('table'),thead=element('thead'),tr=element('tr');
    ['有向路段','状态','A 完整通行','B 完整通行','A 均耗时（秒）','B 均耗时（秒）','耗时差（秒）'].forEach(x=>tr.append(element('th',x)));thead.append(tr);table.append(thead);
    const tbody=element('tbody');table.append(tbody);tableWrap.append(table);s.result.append(tableWrap);
    const rows=rankedLinks(d.network.links.filter(r=>!d.filters.link_ids.length||r.selected));
    for(const row of rows.slice(0,100)){const tr=element('tr'),td=element('td');td.append(button(row.id,()=>inspect(s,row)));tr.append(td);
      [labels[row.state]||row.state,number(row.baseline?.complete_traversal_count),number(row.proposal?.complete_traversal_count),number(row.baseline?.mean_travel_time_s),number(row.proposal?.mean_travel_time_s),signed(row.delta.mean_travel_time_s)].forEach(x=>tr.append(element('td',x)));tbody.append(tr);}
    const newLinks=rows.filter(r=>r.state==='new');
    const newEntries=d.network.available&&newLinks.every(r=>r.proposal?.entered_count!=null)
      ? newLinks.reduce((sum,r)=>sum+r.proposal.entered_count,0) : null;
    s.result.append(element('p',`表格显示 ${Math.min(100,rows.length)} / ${rows.length} 条；JSON 含全部路段。${d.filters.link_ids.length?'所选走廊':'全网'}新增路段进入次数合计：${newEntries==null?'不可用':number(newEntries)}（不等于独立车辆数）。`,'impact-notes'));
    s.quality=element('div',null,'impact-quality');s.result.append(s.quality);renderQuality(s);
    const notes=element('details',null,'impact-notes');notes.append(element('summary','口径、来源与限制'));const list=element('ul');
    ['出行队列按 A 的出发时间和主方式筛选；B 的同序号出行可能改变时间、方式或目的地。',
      '路段统计按进入时间分桶，只使用完整通过该路段的观测；停车、出发部分路段和未完成通行不填成零。',
      'A/B 延误各自减去该方案的自由流耗时；修改限速会改变参考值。差异地图比较实际通行耗时，不混淆两个指标。',
      '地图可显示范围外其他路段，不能把它们直接称为住宅区，也没有据此推算排放、安全或经济收益。',
      '缺少实测校准、工程净空及造价核验。本页单对结果不证明收敛、长期发展或真实因果效应。',
      ...d.limitations].forEach(x=>list.append(element('li',x)));notes.append(list);s.result.append(notes);
    s.result.append(element('p',`A: ${d.baseline_run}\nB: ${d.proposal_run}\n种子 ${d.comparability.random_seed}；迭代 ${d.comparability.first_iteration}–${d.comparability.last_iteration}`,'impact-source'));
  }
  function renderQuality(s) {
    s.quality.replaceChildren(element('strong','可信范围 / 数据质量'));
    const d=s.data,t=d.trips,u=t.unmatched;
    s.quality.append(element('p',`无法配对：A 中缺失于 B ${u.baseline_missing_in_proposal}；B 重复键 ${u.proposal_duplicate_keys_in_cohort}；无效配对 ${u.invalid_pairs_in_cohort}；B 独有出行 ${u.proposal_only_in_own_window}；配对中改变方式 ${t.mode_switch_count}。未配对出行不当成零耗时或受益。`));
    for(const [side,label]of [['baseline','A'],['proposal','B']]){
      const q=t.quality[side];
      s.quality.append(element('p',`${label} 源出行表：总行 ${q.rows}，无效行 ${q.invalid_rows}，重复键 ${q.duplicate_keys}；无效标识 ${q.invalid_key_rows}、出发时间 ${q.invalid_departure_rows}、耗时 ${q.invalid_travel_time_rows}、方式 ${q.invalid_mode_rows}。各项可能重叠；这些是全表诊断，并非筛选后队列。`));
    }
    const outside=d.network.outside_selection;
    if(d.filters.link_ids.length)s.quality.append(element('p',`所选走廊外：${outside.comparable_link_count} 条可比路段，路段平均耗时差 ${signed(outside.delta.mean_link_travel_time_s)} 秒（路段等权，非居民福利）。`));
    if(!d.network.available)s.quality.append(element('p','步行 / 公共交通在此模型中为传送模式，没有可用的道路拥堵观测；出行耗时仍可比较。'));
    s.quality.append(element('p','到达、出发与卡住事件按所选时间窗独立计数，不能用跨时段的到达/出发比直接当完成率。'));
    const events=element('table'),header=element('tr');
    ['方式','A 出发 / 到达 / 卡住','B 出发 / 到达 / 卡住'].forEach(x=>header.append(element('th',x)));events.append(header);
    const modeNames={car:'汽车',bike:'骑行',walk:'步行',pt:'公共交通',other:'其他'};
    for(const [mode,label]of Object.entries(modeNames)){
      const row=element('tr');row.append(element('td',label));
      for(const side of ['baseline','proposal']){const counts=d.completion[side][mode];row.append(element('td',counts?`${counts.departures} / ${counts.arrivals} / ${counts.stuck}`:'—'));}events.append(row);
    }s.quality.append(events);
    if(s.coverage){const a=s.coverage.activities;
      const percent=a.inside_node_bbox_fraction_of_finite;
      s.quality.append(element('p',`输入活动点在路网节点矩形内：${number(percent==null?null:percent*100,1)}%；矩形外 ${a.outside_node_bbox} 个。矩形覆盖不等于可达性或校准；不自动删除外部需求。`));
      const entries=Object.entries(s.coverage.by_activity_type).filter(([,v])=>v.outside_node_bbox>0);
      if(entries.length)s.quality.append(element('p',`矩形外活动：${entries.map(([type,v])=>`${type} ${v.outside_node_bbox}`).join('；')}`));
    }else s.quality.append(element('p','覆盖审计加载中或不可用；缺失审计不表示覆盖正常。'));
  }
  function geometry(row,view){return view==='baseline'?row.baseline_geometry:view==='proposal'?row.proposal_geometry:row.proposal_geometry||row.baseline_geometry;}
  function drawMap(s) {
    const rows=s.data.network.links;
    let xmin=Infinity,xmax=-Infinity,ymin=Infinity,ymax=-Infinity;
    // Avoid argument-count limits from spreading a city-sized coordinate array.
    for(const r of rows)for(const g of [r.baseline_geometry,r.proposal_geometry]){
      if(!g)continue;
      xmin=Math.min(xmin,g.x1,g.x2);xmax=Math.max(xmax,g.x1,g.x2);
      ymin=Math.min(ymin,g.y1,g.y2);ymax=Math.max(ymax,g.y1,g.y2);
    }
    if(!Number.isFinite(xmin))return;
    const scale=940/Math.max(xmax-xmin,ymax-ymin,1);s.project=(x,y)=>[30+(x-xmin)*scale,30+(ymax-y)*scale];
    s.fullBox=[0,0,1000,60+(ymax-ymin)*scale];if(!s.box)s.box=[...s.fullBox];
    s.svg.replaceChildren();s.svg.setAttribute('viewBox',s.box.join(' '));
    s.mapLines=new Map();s.rowsById=new Map(rows.map(row=>[row.id,row]));
    const fragment=document.createDocumentFragment();
    const mapValue=row=>s.view==='delta'?row.delta.mean_travel_time_s:row[s.view]?.mean_delay_s;
    // Missing observations remain selectable context, not the dominant colour.
    // Paint observed roads last so their wider hit targets remain usable.
    const ordered=[...rows].sort((a,b)=>Number(mapValue(b)==null)-Number(mapValue(a)==null));
    for(const row of ordered){const g=geometry(row,s.view);if(!g)continue;
      const [x1,y1]=s.project(g.x1,g.y1),[x2,y2]=s.project(g.x2,g.y2),len=Math.hypot(x2-x1,y2-y1)||1;
      // Small directed offsets separate opposite carriageways without changing
      // their model geometry or pretending to represent physical lane widths.
      const ox=-(y2-y1)/len*1.2,oy=(x2-x1)/len*1.2;
      function line(color,width){const l=document.createElementNS(NS,'line');
        Object.entries({x1:x1+ox,y1:y1+oy,x2:x2+ox,y2:y2+oy,stroke:color,'stroke-width':width,'vector-effect':'non-scaling-stroke'}).forEach(([k,v])=>l.setAttribute(k,v));return l;}
      const value=mapValue(row),context=value==null&&['no_data','unavailable'].includes(row.state);
      const l=line(s.view==='delta'?rgb(row.color):absoluteColor(value),context ? 0.8 : 2.5);
      if(value==null)l.setAttribute('stroke-dasharray','3 4');
      if(context)l.setAttribute('opacity','.3');
      const title=document.createElementNS(NS,'title');title.textContent=`${row.id}: ${s.view==='delta'?signed(value):number(value)} 秒；${labels[row.state]}`;l.append(title);fragment.append(l);
      const hit=line('transparent',10);hit.dataset.linkId=row.id;hit.setAttribute('pointer-events','stroke');fragment.append(hit);
      s.mapLines.set(row.id,l);
    }
    s.svg.append(fragment);
    s.highlightLayer=document.createElementNS(NS,'g');s.highlightLayer.setAttribute('pointer-events','none');s.svg.append(s.highlightLayer);
    updateHighlights(s);
    s.viewButtons.forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===s.view));
    s.legend.textContent=s.view==='delta'?'固定耗时差（B − A）：深绿 ≤ −60秒 · 绿 −60至−15 · 浅绿 −15至−1 · 灰 |差|<1 · 橙 1至15 · 红 15至60 · 深红 ≥60。紫灰虚线=不可比较；蓝边=选中。'
      :'固定延误刻度：绿 <1秒（含负值）· 橙 1–15秒 · 红 15–60秒 · 深红 ≥60秒；紫灰虚线=未观测/不存在。沿用相同地图范围。';
    const modeScope={all:'路段指标仅含汽车与骑行；步行和公共交通没有网络路段观测。',car:'路段指标仅含汽车。',bike:'路段指标仅含骑行。',walk:'步行没有网络路段观测。',pt:'公共交通为传送模式，没有网络路段观测。'};
    s.legend.textContent+=` ${modeScope[s.data.filters.mode]} 地图为模型有向线段，细微侧移仅用于区分方向；不是车道或施工图。`;
  }
  function updateHighlights(s) {
    // Selection is a small overlay, never a rebuild of the city-sized base map.
    const fragment=document.createDocumentFragment();
    const ids=new Set(s.selected);if(s.focusId)ids.add(s.focusId);
    for(const id of ids){const source=s.mapLines.get(id);if(!source)continue;
      const line=source.cloneNode(false);line.setAttribute('stroke','#2c83cb');line.setAttribute('stroke-width',7);
      line.removeAttribute('stroke-dasharray');line.removeAttribute('opacity');fragment.append(line);
    }
    s.highlightLayer.replaceChildren(fragment);
  }
  function attachPan(s) {
    let down=null;
    s.svg.onpointerdown=e=>{if(e.button!==0)return;down={x:e.clientX,y:e.clientY,box:[...s.box],id:e.target.dataset.linkId};s.svg.setPointerCapture(e.pointerId);};
    s.svg.onpointermove=e=>{if(!down)return;const r=s.svg.getBoundingClientRect(),units=Math.max(down.box[2]/r.width,down.box[3]/r.height);
      s.box=[down.box[0]-(e.clientX-down.x)*units,down.box[1]-(e.clientY-down.y)*units,down.box[2],down.box[3]];s.svg.setAttribute('viewBox',s.box.join(' '));};
    s.svg.onpointerup=e=>{if(!down)return;const click=Math.hypot(e.clientX-down.x,e.clientY-down.y)<5,id=down.id;down=null;
      if(s.svg.hasPointerCapture(e.pointerId))s.svg.releasePointerCapture(e.pointerId);
      if(click&&id){const row=s.rowsById.get(id);if(!row)return;if(s.pickScope)toggleScope(s,row,false);inspect(s,row);}};
    s.svg.onpointercancel=()=>{down=null;};
    s.svg.onwheel=e=>{e.preventDefault();const f=e.deltaY>0?1.18:.85,w=Math.max(50,Math.min(s.fullBox[2]*3,s.box[2]*f)),h=w*s.fullBox[3]/s.fullBox[2];s.box=[s.box[0]+(s.box[2]-w)/2,s.box[1]+(s.box[3]-h)/2,w,h];s.svg.setAttribute('viewBox',s.box.join(' '));};
  }
  function toggleScope(s,row,paint=true){if(s.selected.has(row.id))s.selected.delete(row.id);else if(s.selected.size<100)s.selected.add(row.id);else {s.status.textContent='走廊最多选择 100 条有向路段。';return;}markDirty(s);if(paint)updateHighlights(s);}
  function inspect(s,row) {
    s.focusId=row.id;updateHighlights(s);s.detail.replaceChildren(element('h3',`有向路段 ${row.id}`),element('p',labels[row.state]||row.state));
    const dl=element('dl');
    for(const [label,key]of[['进入次数','entered_count'],['完整通行次数','complete_traversal_count'],['平均通行耗时（秒）','mean_travel_time_s'],['相对本方案自由流延误（秒）','mean_delay_s']]){
      dl.append(element('dt',label),element('dd',`${number(row.baseline?.[key])} → ${number(row.proposal?.[key])}`));}
    s.detail.append(dl,element('p',`通行耗时差：${signed(row.delta.mean_travel_time_s)} 秒。箭头为 A → B，空值不是零。`),button('加入 / 移出走廊',()=>toggleScope(s,row)));
    const focus=button('在下方 3D 中定位',async()=>{document.getElementById('skylineContainer').scrollIntoView({block:'center',behavior:'smooth'});
      focus.disabled=true;const scene=await (s.adapters.ensureScene?.()||s.adapters.getScene?.());
      if(session!==s)return;focus.disabled=false;if(!scene)return;
      const tr=scene?.userData.coordinateTransform,g=row.proposal_geometry||row.baseline_geometry;if(!tr||!g)return;
      const x=((g.x1+g.x2)/2-tr.center_x)*tr.scene_units_per_metre,z=((g.y1+g.y2)/2-tr.center_y)*tr.scene_units_per_metre;
      scene.userData.setCameraFocus?.(x,scene.userData.groundY(x,z)+2,z,70);document.getElementById('skylineContainer').scrollIntoView({block:'center',behavior:'smooth'});});
    focus.disabled=(!s.adapters.ensureScene&&!s.adapters.getScene?.())||s.data.proposal_run!==s.displayedRun;s.detail.append(focus);
    const same=s.data.network.links.filter(r=>r.id!==row.id&&Math.hypot(r.x1-row.x2,r.y1-row.y2)<.01&&Math.hypot(r.x2-row.x1,r.y2-row.y1)<.01);
    if(same.length){s.detail.append(element('p','同位置反向路段：'));same.forEach(r=>s.detail.append(button(r.id,()=>inspect(s,r))));}
  }
  function exportReport(s) {
    if(!s.data||s.dirty)return;const d=s.data,t=d.trips;
    const rows=rankedLinks(d.network.links.filter(r=>!d.filters.link_ids.length||r.selected));
    // Quality nodes are constructed with textContent, never untrusted HTML.
    // Preserve their table structure so A/B event counts remain unambiguous.
    const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>IF Line 方案讨论报告</title><style>body{font:15px system-ui;max-width:1080px;margin:40px auto;padding:0 20px;color:#193442}h1{border-bottom:4px solid #176b74;padding-bottom:16px}table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #ccd9df;padding:8px;text-align:left}svg{width:100%;height:550px;background:#e5eceb}pre{white-space:pre-wrap;word-break:break-all}p{line-height:1.7}</style><h1>IF Line · 方案讨论报告</h1><p>已有仿真结果分析，不是施工许可或已校准预测。</p><p>A：${esc(d.baseline_run)}<br>B：${esc(d.proposal_run)}<br>时段 ${number(d.filters.start_s/3600)}–${number(d.filters.end_s/3600)} 时；基线方式 ${esc(d.filters.mode)}；走廊 ${esc(d.filters.link_ids.join(', ')||'全网')}</p><p>同人口与配置核对通过；种子 ${d.comparability.random_seed}，迭代 ${d.comparability.first_iteration}–${d.comparability.last_iteration}。</p><h2>配对出行</h2><p>可配对 ${t.paired_count}/${t.cohort_count}；平均耗时 ${number(t.baseline.mean_s)} → ${number(t.proposal.mean_s)} 秒（变化 ${signed(t.delta_s.mean)} 秒）。变快 ${t.faster_count}，变慢 ${t.slower_count}，变化不足1秒 ${t.within_1s_count}；不代表统计显著性。</p><h2>当前地图视图：${esc(s.view)}</h2>${s.svg.outerHTML}<p>${esc(s.legend.textContent)}</p><h2>走廊路段明细（前100条；完整值见 JSON）</h2><table><tr><th>ID</th><th>状态</th><th>A耗时/s</th><th>B耗时/s</th><th>差值/s</th></tr>${rows.slice(0,100).map(r=>`<tr><td>${esc(r.id)}</td><td>${esc(labels[r.state])}</td><td>${number(r.baseline?.mean_travel_time_s)}</td><td>${number(r.proposal?.mean_travel_time_s)}</td><td>${signed(r.delta.mean_travel_time_s)}</td></tr>`).join('')}</table><h2>质量与限制</h2>${s.quality.outerHTML}<ul>${d.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><details><summary>来源文件与哈希</summary><pre>${esc(JSON.stringify(d.sources,null,2))}</pre></details></html>`;
    save(html,'text/html;charset=utf-8','ifline-discussion-report.html');
  }
  root.ImpactWorkbench={open,close};
})(window);
