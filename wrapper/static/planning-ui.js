/* Browser adapter for the pure plan store and server-side topology compiler.
 * A checked plan is immutable for submission; edits always invalidate its token. */
let cityPlanStore=null,cityPlanBaseline='',cityPlanVerified=null,cityPlanEditing=null;
let cityPlanMoveIndex=null,cityPlanSubmitting=false,cityPlanHighlight=null;
let cityPlanChecking=false,cityPlanCheckSequence=0;
const cityPlanSessions=new Map();
function toggleCityPlanPanel() {
  const collapsed=document.body.classList.toggle('studio-tools-collapsed');
  document.getElementById('studioPanelToggle').setAttribute('aria-expanded',String(!collapsed));
  if(activeViewer?.userData.resize)requestAnimationFrame(activeViewer.userData.resize);
}
function cityPlanBusy() {
  return cityPlanChecking || cityPlanSubmitting || Boolean(localStorage.getItem('matsimIfLineJob'));
}
function cityPlanEnsure() {
  const baseline=document.getElementById('iflineBaselineSelect').value;
  if (!cityPlanStore || baseline!==cityPlanBaseline) {
    cityPlanBaseline=baseline;
    cityPlanStore=cityPlanSessions.get(baseline) || CityPlanState.create();
    cityPlanSessions.set(baseline,cityPlanStore);
    cityPlanVerified=null;cityPlanEditing=null;cityPlanMoveIndex=null;
    cityPlanCheckSequence++;cityPlanChecking=false;
    cityPlanClearReport();
    cityPlanMessage('当前基线尚未检查方案。画好路线后即可检查。');
    if(window.RoadEditor)RoadEditor.reset();
  }
  return cityPlanStore;
}
function cityPlanMessage(text) { document.getElementById('planReport').textContent=text; }
function cityPlanClearReport() {
  document.getElementById('planConflicts').replaceChildren();
  document.getElementById('planConflictSummary').textContent='建筑冲突：尚未检查';
  document.getElementById('planAcknowledgement').hidden=true;
  document.getElementById('planAck').checked=false;
}
function cityPlanClearHighlight() {
  if (!cityPlanHighlight) return;
  cityPlanHighlight.parent?.remove(cityPlanHighlight);
  cityPlanHighlight.geometry.dispose();cityPlanHighlight.material.dispose();
  cityPlanHighlight=null;
}
function cityPlanInvalidate() {
  cityPlanVerified=null;cityPlanClearHighlight();
  cityPlanClearReport();
  cityPlanMessage('方案已变化，需重新检查连接与建筑冲突。');
}
function cityPlanDescription(op) {
  if (op.type==='new_road') return `${op.heights.some(h=>h>0)?'高架 / 匝道':'地面道路'} · ${op.points.length} 点 · ${op.speed_kph} km/h · ${op.lanes} 车道/方向`;
  return `${{speed_limit:'限速',capacity_scale:'容量',road_closure:'封路'}[op.type]} · link ${op.link_id} ${op.value===null?'':op.value+(op.type==='capacity_scale'?'%':' km/h')}`;
}
function cityPlanRefresh() {
  const store=cityPlanEnsure(),list=document.getElementById('planOperations');
  list.replaceChildren();
  store.read().operations.forEach((op,i)=>{
    const li=document.createElement('li');li.style.margin='8px 0';
    const label=document.createElement('span');label.textContent=cityPlanDescription(op)+' ';
    li.append(label);
    for (const [text,action] of [['编辑',()=>cityPlanEdit(i)],['移除',()=>{
      if (cityPlanBusy()) return;
      const next=store.read();next.operations.splice(i,1);store.commit(next);
      cityPlanEditing=null;cityPlanInvalidate();cityPlanRefresh();renderNewRoadOverlay();
    }]]) {
      const button=document.createElement('button');button.type='button';button.textContent=text;
      button.style.cssText='width:auto;display:inline-block;padding:4px 8px;margin:2px';
      button.disabled=cityPlanBusy();button.onclick=action;li.append(button);
    }
    list.append(li);
  });
  document.getElementById('planAdd').textContent=cityPlanEditing===null?'将当前修改加入方案':`更新第 ${cityPlanEditing+1} 项`;
  document.getElementById('planAdd').disabled=cityPlanBusy();
  document.getElementById('planUndo').disabled=cityPlanBusy()||!store.canUndo();
  document.getElementById('planRedo').disabled=cityPlanBusy()||!store.canRedo();
  refreshStudioRunButton();
}
// The plan store owns committed operations; the draft and checked report retain
// their existing owners. Only this decision selects the next action. A run
// decision carries the checked request, so UI and submission cannot disagree.
function cityPlanPending() {
  return iflineNewRoadPoints.length>0 || cityPlanEditing!==null;
}
function cityPlanFlow() {
  const result=(canCheck,action,label,hint,request)=>({canCheck,action,label,hint,request});
  const run='运行 MATSim 并与基线比较';
  if(iflineStudioLoading)return result(false,'blocked',run,'正在载入基线，请稍候。');
  if(cityPlanChecking)return result(false,'blocked','正在检查方案…','正在核对连接与建筑轮廓；尚未启动仿真。');
  if(cityPlanBusy())return result(false,'blocked','方案运行中…','已有方案正在提交或运行，请等待任务状态更新。');
  if(activeViewer?.userData.isDifferenceScene)return result(false,'blocked',run,'当前是结果视图，请先返回基线继续编辑。');
  if(!cityPlanStore || !cityPlanBaseline || cityPlanBaseline!==document.getElementById('iflineBaselineSelect').value)
    return result(false,'blocked',run,'请先选择基线并打开规划沙盘。');
  if(iflineNewRoadPoints.length && iflineStudioMode!=='new_road')
    return result(false,'blocked',run,'还有未提交的画路草案，请切回“自由画路”后检查或清空，避免遗漏路线。');
  if(iflineNewRoadPoints.length===1)return result(false,'blocked',run,'当前路线只有 1 个点；请再放置终点，或清空草案。');
  const operations=cityPlanStore.read().operations;
  const pending=cityPlanPending();
  const selected=iflineStudioMode==='existing_road' && linkSupportsCar(selectedIfLineLink());
  if(!operations.length && !pending && !selected)
    return result(false,'blocked',run,'请画出至少两个控制点，或选择一条可修改的机动车道路。');
  const verified=cityPlanVerified && cityPlanVerified.revision===cityPlanStore.revision()
    && cityPlanVerified.baseline_run===cityPlanBaseline && !pending;
  if(!verified)return result(true,'check','检查方案以继续比较',pending
    ?'点击检查会自动加入或更新当前路线，并显示冲突数量；这一步不会运行仿真。'
    :'先检查方案，确认连接与冲突后再运行比较。');
  if(cityPlanVerified.conflicts.length && !document.getElementById('planAck').checked)
    return result(true,'blocked',run,`请先查看并勾选上方风险确认：共 ${cityPlanVerified.conflicts.length} 个建筑轮廓冲突。`);
  const name=document.getElementById('iflineStudioName').value.trim();
  if(name.length<2 || name.length>80)return result(true,'blocked',run,'请填写 2–80 个字符的方案名称。');
  return result(true,'run',run,`已检查 ${operations.length} 项修改；点击后才会启动独立 MATSim 分支并与基线比较。`,{
    baseline_run:cityPlanBaseline,name,plan:cityPlanVerified.plan,check_token:cityPlanVerified.token,
    acknowledge_conflicts:document.getElementById('planAck').checked,
  });
}
function cityPlanRefreshActions() {
  const flow=cityPlanFlow(),button=document.getElementById('iflineStudioRun');
  button.disabled=flow.action==='blocked';button.textContent=flow.label;button.title=flow.hint;
  document.getElementById('planRunHint').textContent=flow.hint;
  const check=document.getElementById('planCheck');
  check.disabled=!flow.canCheck;
  check.textContent=cityPlanChecking?'正在检查连接与建筑冲突…':'检查当前路线与方案的冲突';
  check.title=flow.hint;
  if(cityPlanVerified)document.getElementById('planConflictSummary').textContent=cityPlanPending()
    ?`上次检查：${cityPlanVerified.conflicts.length} 个冲突；当前草案尚未检查`
    :`建筑冲突：${cityPlanVerified.conflicts.length} 个（${cityPlanVerified.plan.operations.length} 项修改已检查）`;
}
function cityPlanDraft() {
  return {type:'new_road',points:iflineNewRoadPoints.map(p=>[p.x,p.y]),
    heights:iflineNewRoadPoints.map(p=>Number(p.height_m??0)),
    snap_points:iflineNewRoadPoints.map(p=>p.snap_enabled!==false),
    speed_kph:Number(document.getElementById('iflineNewRoadSpeed').value),
    lanes:Number(document.getElementById('iflineNewRoadLanes').value),
    capacity_per_hour:Number(document.getElementById('iflineNewRoadCapacity').value),
    snap_tolerance_m:currentNewRoadSnapTolerance(),
    bidirectional:document.getElementById('iflineNewRoadBidirectional').checked,
    modes:['car',...['bike','walk'].filter(m=>document.getElementById('iflineNewRoad'+m[0].toUpperCase()+m.slice(1)).checked)]};
}
function cityPlanAdd() {
  if (cityPlanBusy()) return false;
  const store=cityPlanEnsure(), next=store.read(); let op;
  if (iflineStudioMode==='new_road') {
    if (iflineNewRoadPoints.length<2) {cityPlanMessage('请先画至少两个控制点。');return false;}
    op=cityPlanDraft();
  } else {
    const link=selectedIfLineLink();
    if (!linkSupportsCar(link)) {cityPlanMessage('请选择可修改的机动车道路。');return false;}
    op={type:document.getElementById('iflineType').value,link_id:String(link.id),
      value:Number(document.getElementById('iflineStudioValue').value),
      include_reverse:document.getElementById('iflineStudioReverse').checked};
    if (op.type==='road_closure') op.value=null;
  }
  if (cityPlanEditing!==null) next.operations[cityPlanEditing]=op;
  else { if (next.operations.length>=12) {cityPlanMessage('一个方案最多 12 项修改。');return false;} next.operations.push(op); }
  store.commit(next);cityPlanEditing=null;cityPlanMoveIndex=null;
  iflineNewRoadPoints=[];iflineNewRoadDrawing=false;cityPlanInvalidate();
  if(window.RoadEditor)RoadEditor.reset();
  renderNewRoadDraft();cityPlanRefresh();
  return true;
}
function cityPlanRestoreDraft(op) {
  for (const [key,id] of [['speed_kph','Speed'],['lanes','Lanes'],['capacity_per_hour','Capacity'],['snap_tolerance_m','Snap']])
    document.getElementById('iflineNewRoad'+id).value=op[key];
  document.getElementById('iflineNewRoadBidirectional').checked=op.bidirectional;
  for (const m of ['bike','walk']) document.getElementById('iflineNewRoad'+m[0].toUpperCase()+m.slice(1)).checked=op.modes.includes(m);
  if(window.RoadEditor)RoadEditor.reset();
  iflineNewRoadPoints=op.points.map(([x,y],i)=>({raw_x:x,raw_y:y,x,y,height_m:op.heights[i],snap_enabled:op.snap_points?.[i]!==false}));
  renderNewRoadDraft();
}
function cityPlanEdit(i) {
  if (cityPlanBusy()) return;
  const op=cityPlanEnsure().read().operations[i]; cityPlanEditing=i;cityPlanInvalidate();
  if (op.type==='new_road') {setIfLineStudioMode('new_road');cityPlanRestoreDraft(op);}
  else { iflineNewRoadPoints=[];setIfLineStudioMode('existing_road');selectIfLineLink(op.link_id);
    setStudioIntervention(op.type);if(op.value!==null)updateStudioValue(op.value,true);
    document.getElementById('iflineStudioReverse').checked=op.include_reverse;
  }
  iflineNewRoadDrawing=false;cityPlanRefresh();
}
function cityPlanHistory(direction) {
  if (cityPlanBusy()) return;
  cityPlanEnsure()[direction]();cityPlanEditing=null;cityPlanMoveIndex=null;iflineNewRoadPoints=[];
  cityPlanInvalidate();renderNewRoadDraft();cityPlanRefresh();
}
function cityPlanSave() {
  const store=cityPlanEnsure();
  try {
    localStorage.setItem('matsimCityPlan:'+cityPlanBaseline,JSON.stringify({version:1,
      baseline_run:cityPlanBaseline,name:document.getElementById('iflineStudioName').value,
      plan:store.read(),draft:iflineNewRoadPoints.length?cityPlanDraft():null,editing:cityPlanEditing}));
    document.getElementById('planSaveStatus').textContent='已保存到当前浏览器（含未加入的画路草案）。运行后服务器另存方案与检查记录。';
  } catch(error) {document.getElementById('planSaveStatus').textContent='保存失败：'+error.message;}
}
function cityPlanLoad() {
  if (cityPlanBusy()) return;
  const store=cityPlanEnsure();
  try {
    const saved=JSON.parse(localStorage.getItem('matsimCityPlan:'+cityPlanBaseline));
    if (!saved || saved.version!==1 || saved.baseline_run!==cityPlanBaseline || !Array.isArray(saved.plan.operations))
      throw Error('当前基线没有兼容的已保存草案');
    store.commit(saved.plan);cityPlanEditing=saved.editing;cityPlanMoveIndex=null;
    document.getElementById('iflineStudioName').value=saved.name;
    document.getElementById('iflineStudioName').dataset.userEdited='true';
    iflineNewRoadPoints=[];cityPlanInvalidate();
    if (saved.draft) {setIfLineStudioMode('new_road');cityPlanRestoreDraft(saved.draft);}
    else renderNewRoadDraft();
    cityPlanRefresh();cityPlanMessage('草案已读取；必须重新检查后才能运行。');
  } catch(error) {cityPlanMessage('读取失败：'+error.message);}
}
function cityPlanPoints() {
  const list=document.getElementById('planPoints');if(!list)return;list.replaceChildren();
  iflineNewRoadPoints.forEach((p,i)=>{
    const row=document.createElement('div');row.style.cssText='display:flex;align-items:center;gap:5px;margin:5px 0';
    const label=document.createElement('label');label.textContent=`点${i+1} 高度 m`;
    const input=document.createElement('input');input.type='number';input.min=0;input.max=50;input.step=1;
    input.style.width='70px';input.value=p.height_m||0;input.setAttribute('aria-label',`点${i+1}高度`);
    // Do not rebuild the focused input on blur: doing so can discard a
    // just-entered height before the user's "update" click is delivered.
    input.disabled=cityPlanBusy()||i===0||i===iflineNewRoadPoints.length-1;
    input.onfocus=()=>RoadEditor.remember();
    input.oninput=()=>RoadEditor.freezeHeight(i,Number(input.value),false);
    const move=document.createElement('button');move.type='button';move.textContent='移动此点';
    move.style.cssText='width:auto;padding:5px';move.disabled=cityPlanBusy();
    move.onclick=()=>{if(cityPlanBusy())return;cityPlanMoveIndex=i;iflineNewRoadDrawing=true;
      cityPlanMessage(`下一次点击地图将移动点${i+1}，保留其高度。`);};
    row.append(label,input,move);list.append(row);
    if(i<iflineNewRoadPoints.length-1){
      const insert=document.createElement('button');insert.type='button';insert.textContent=`在点${i+1}与${i+2}之间插点`;
      insert.style.cssText='width:auto;padding:5px;margin:2px 0';insert.disabled=cityPlanBusy();
      insert.onclick=()=>{const q=iflineNewRoadPoints[i+1];
        if(cityPlanBusy())return;
        if(iflineNewRoadPoints.length>=32)return cityPlanMessage('最多 32 个控制点。');
        RoadEditor.remember();
        iflineNewRoadPoints.splice(i+1,0,{raw_x:(p.x+q.x)/2,raw_y:(p.y+q.y)/2,
          snap_enabled:false,height_m:((p.height_m||0)+(q.height_m||0))/2});renderNewRoadDraft();};
      list.append(insert);
    }
  });
}
async function cityPlanCheck() {
  if (cityPlanBusy()) return;
  cityPlanEnsure();
  const flow=cityPlanFlow();
  if(!flow.canCheck){cityPlanMessage(flow.hint);return false;}
  // Flush the visible draft once (or replace the edited operation). Rechecking
  // a canonical plan never appends a duplicate road.
  if(cityPlanPending() || !cityPlanStore.read().operations.length){
    if(!cityPlanAdd())return false;
  }
  const store=cityPlanEnsure(),revision=store.revision(),baseline=cityPlanBaseline;
  const sequence=++cityPlanCheckSequence;
  cityPlanInvalidate();cityPlanMessage('正在检查实际道路宽度、连接及建筑轮廓…');
  document.getElementById('planConflictSummary').textContent='建筑冲突：检查中（尚无结论）';
  cityPlanChecking=true;cityPlanRefresh();cityPlanPoints();
  try {
    const report=await apiJson('/ifline/plan/check',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({baseline_run:baseline,plan:store.read()})});
    if(sequence!==cityPlanCheckSequence)return false;
    if (baseline!==document.getElementById('iflineBaselineSelect').value || baseline!==cityPlanBaseline ||
        store!==cityPlanStore || revision!==store.revision() || cityPlanPending()) {
      cityPlanInvalidate();cityPlanMessage('检查期间方案已变化，请重试。');return false;
    }
    store.commit(report.plan);cityPlanVerified={...report,revision:store.revision()};
    cityPlanRefresh();cityPlanMessage(`检查完成：${report.plan.operations.length} 项修改，${report.conflicts.length} 个建筑轮廓冲突。`);
    document.getElementById('planConflictSummary').textContent=`建筑冲突：${report.conflicts.length} 个（${report.plan.operations.length} 项修改已检查）`;
    const reportBox=document.getElementById('planConflicts');
    if(report.building_screen?.status==='completed'){
      const p=document.createElement('p');
      p.textContent=`数据范围：已校验 ${report.building_screen.counts.validated_features} 个建筑源要素；本次新路占地筛查不受 3D 显示数量限制。已知源数据仍可能缺漏。`;
      reportBox.append(p);
    }
    report.conflicts.forEach(hit=>{
      const button=document.createElement('button');button.type='button';
      button.textContent=`${hit.label}${hit.name?' · '+hit.name:''}（修改 ${hit.operation_ids.join('、')}）`;
      button.style.cssText='text-align:left;margin:4px 0;padding:8px';
      button.onclick=()=>cityPlanFocus(hit);reportBox.append(button);
    });
    for (const warning of report.warnings) {const p=document.createElement('p');p.textContent=warning;reportBox.append(p);}
    document.getElementById('planAcknowledgement').hidden=!report.conflicts.length;
    renderNewRoadOverlay();refreshStudioRunButton();
    return true;
  } catch(error) {
    if(sequence===cityPlanCheckSequence){cityPlanClearReport();
      document.getElementById('planConflictSummary').textContent='建筑冲突：未完成检查（不是 0 个）';
      cityPlanMessage('检查未通过：'+error.message);}
    return false;
  } finally {
    if(sequence===cityPlanCheckSequence){cityPlanChecking=false;cityPlanRefresh();cityPlanPoints();}
  }
}
function cityPlanFocus(hit) {
  if(!activeViewer || !activeViewer.userData.groundY) return;
  cityPlanClearHighlight();const ground=activeViewer.userData.groundY;
  const points=hit.points.map(([x,z])=>new THREE.Vector3(x,ground(x,z)+0.2,z));
  const box=new THREE.Box3().setFromPoints(points);box.max.y+=Number(hit.height)||3;
  cityPlanHighlight=new THREE.Box3Helper(box,0x28b3ff);cityPlanHighlight.material.depthTest=true;
  activeViewer.add(cityPlanHighlight);
  const c=box.getCenter(new THREE.Vector3());const radius=Math.max(38,box.getSize(new THREE.Vector3()).length()*1.7);
  activeViewer.userData.setCameraFocus(c.x,c.y,c.z,radius);
}
function cityPlanOverlayRoads() {
  if (!cityPlanStore) return [];
  if (cityPlanVerified && cityPlanVerified.revision===cityPlanStore.revision()) return cityPlanVerified.roads;
  return cityPlanStore.read().operations.flatMap((op,i)=>op.type!=='new_road'||i===cityPlanEditing?[]:[{
    width_m:op.lanes*3.5*(op.bidirectional?2:1)+2,
    segments:op.points.slice(1).map((p,j)=>[[...op.points[j],op.heights[j]],[...p,op.heights[j+1]]])}]);
}
async function cityPlanRun() {
  cityPlanEnsure();
  const flow=cityPlanFlow();
  if(flow.action==='check'){await cityPlanCheck();return;}
  if(flow.action!=='run'){cityPlanMessage(flow.hint);return;}
  cityPlanSubmitting=true;cityPlanRefresh();
  clearDisplayedResult({preserveStudio:true});setIfLineStatusMessage('方案提交中；此时仍是基线，不是新结果。');
  try {
    const data=await apiJson('/ifline/plan/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(flow.request)});
    const startedAt=Date.now();
    localStorage.setItem('matsimIfLineJob',JSON.stringify({id:data.job_id,runId:data.run_id,startedAt,interventionType:'plan'}));
    cityPlanSubmitting=false;
    document.getElementById('iflineStudioBaselineLabel').textContent='方案运行中 · 仍显示基线与概念草案';
    pollIfLineJob(data.job_id,data.run_id,startedAt);
  } catch(error) {cityPlanSubmitting=false;cityPlanMessage('方案未启动：'+error.message);cityPlanRefresh();}
}
document.addEventListener('DOMContentLoaded',()=>{cityPlanRefresh();cityPlanPoints();});
