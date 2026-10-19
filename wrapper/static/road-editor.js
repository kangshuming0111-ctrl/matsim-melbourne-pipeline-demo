/* Direct manipulation adapter. Only draft geometry is owned here; terrain,
 * buildings, simulation results and the renderer's depth setup are untouched. */
(function() {
  'use strict';
  const history=RoadDesign.history(),ns='http://www.w3.org/2000/svg';
  let ghost=null,tooltip=null,profileDrag=null,profileLayout=null,cancelMapDrag=null;
  const byId=id=>document.getElementById(id);
  const points=()=>iflineNewRoadPoints;
  const editable=()=>iflineStudioOpen && iflineStudioMode==='new_road' && activeViewer &&
    !activeViewer.userData.isDifferenceScene && !cityPlanBusy();
  function message(text) {byId('roadEditorReadout').textContent=text;}
  function clearHover() {
    if(ghost){ghost.parent?.remove(ghost);ghost.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});ghost=null;}
    if(tooltip)tooltip.hidden=true;
  }
  function remember() {
    clearHover();history.remember(points());
    // Freeze the displayed XY before a vertical edit. Legacy raw positions
    // must not reappear when an elevated point crosses height zero.
    points().forEach(p=>{if(Number.isFinite(p.x)){p.raw_x=p.x;p.raw_y=p.y;}});
  }
  function reset() {clearHover();history.clear();profileDrag=null;}
  function undo() {
    if(!editable())return;
    const previous=history.undo(points());if(previous){iflineNewRoadPoints=previous;clearHover();renderNewRoadDraft();}
  }
  function redo() {
    if(!editable())return;
    const next=history.redo(points());if(next){iflineNewRoadPoints=next;clearHover();renderNewRoadDraft();}
  }
  function freezeHeight(index,value,record=true) {
    if(!editable())return;
    if(record)remember();
    iflineNewRoadPoints=RoadDesign.setHeight(points(),index,value);
    resnapNewRoadPoints();renderNewRoadOverlay();refreshStudioRunButton();refresh();
  }
  function bridge() {
    if(!editable())return;
    try {
      const suggestion=RoadDesign.bridge(points(),Number(byId('roadBridgeHeight').value));
      remember();iflineNewRoadPoints=suggestion;iflineNewRoadDrawing=false;renderNewRoadDraft();
      message('已生成相对地形的高架草案。拖动下方蓝点调高度，或拖动地图蓝点改走向；请再做建筑冲突检查。');
      view('side');
    } catch(e){message(e.message);}
  }
  function flatten() {
    if(!editable()||!points().length)return;
    remember();points().forEach(p=>p.height_m=0);renderNewRoadDraft();
  }
  function svg(tag,attrs,text) {
    const el=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))el.setAttribute(k,v);
    if(text!==undefined)el.textContent=text;return el;
  }
  function refresh() {
    const target=byId('roadProfile');if(!target)return;
    byId('roadEditUndo').disabled=!editable()||!history.canUndo;
    byId('roadEditRedo').disabled=!editable()||!history.canRedo;
    byId('roadMakeBridge').disabled=!editable()||points().length<2;
    target.replaceChildren();
    if(!activeViewer?.userData.groundY||points().length<2){
      profileLayout=null;target.append(svg('text',{x:20,y:88,fill:'#a1bac8','font-size':12},'画出起点和终点后，在这里调整高度'));
      byId('roadProfileHint').textContent='地图拖点改走向；纵断面拖点改高度。端点锁定地面。';return;
    }
    const scale=currentSceneTransform().scene_units_per_metre;
    const ground=(x,y)=>{const p=networkToScenePoint(x,y);return activeViewer.userData.groundY(p.x,p.z)/scale;};
    const data=RoadDesign.profile(points(),ground);
    const origin=data.handles[0].ground;
    const values=data.samples.flatMap(s=>[s.ground-origin,s.road-origin]);
    const lo=Math.min(0,...values)-4,hi=Math.max(12,...values)+8;
    const layout=profileDrag?profileDrag.layout:{lo,hi,total:Math.max(1,data.total),origin};
    const X=s=>28+s/layout.total*278,Y=h=>145-(h-layout.origin-layout.lo)/(layout.hi-layout.lo)*119;
    profileLayout={...layout,data,X,Y};
    for(let i=0;i<=3;i++){
      const y=26+i*119/3;
      target.append(svg('line',{x1:28,x2:306,y1:y,y2:y,stroke:'#2b4556','stroke-width':1}));
    }
    const path=key=>data.samples.map((p,i)=>`${i?'L':'M'}${X(p.station).toFixed(2)},${Y(p[key]).toFixed(2)}`).join(' ');
    target.append(svg('path',{d:path('ground')+` L306,145 L28,145 Z`,fill:'#375747',opacity:.65}));
    target.append(svg('path',{d:path('ground'),stroke:'#92b991','stroke-width':2,fill:'none'}));
    target.append(svg('path',{d:path('road'),stroke:'#6cc8ff','stroke-width':3,fill:'none'}));
    target.append(svg('text',{x:28,y:15,fill:'#b1cbd9','font-size':10},'场景纵断面 · 地形展示有夸张，非工程高程'));
    target.append(svg('text',{x:28,y:166,fill:'#b1cbd9','font-size':10},'0 m'));
    target.append(svg('text',{x:306,y:166,fill:'#b1cbd9','font-size':10,'text-anchor':'end'},Math.round(data.total)+' m'));
    data.handles.forEach((p,i)=>{
      const locked=i===0||i===data.handles.length-1;
      const circle=svg('circle',{cx:X(p.station),cy:Y(p.ground+p.height),r:locked?5:7,
        fill:locked?'#93b996':'#53bafa',stroke:'#0c202c','stroke-width':2,
        'data-point':i,role:'slider',tabindex:locked?-1:0,'aria-disabled':locked||!editable(),
        'aria-label':`控制点${i+1}离地高度`,'aria-valuemin':0,'aria-valuemax':50,'aria-valuenow':p.height});
      circle.append(svg('title',{},`点${i+1} · 抬高 ${p.height.toFixed(1)} m${locked?' · 端点锁定':' · 拖动或上下方向键'}`));
      target.append(circle);
    });
    byId('roadProfileHint').textContent=`${data.handles.length} 个点 · 路线 ${Math.round(data.total)} m · 最大相对抬高坡率 ${(data.maxOffsetGrade*100).toFixed(1)}%`+
      (data.maxOffsetGrade>.12?' · 超过原型 12% 上限，请延长过渡段或降低高度。':' · 蓝点可上下拖动；两端绿色点保持接地。');
  }
  function view(mode) {
    if(!activeViewer?.userData.groundY)return;
    const {camera,controls,groundY}=activeViewer.userData;
    const ps=points().map(p=>networkToScenePoint(p.x,p.y));
    const bounds=new THREE.Box3().setFromPoints(ps.length?ps.map(p=>new THREE.Vector3(p.x,groundY(p.x,p.z),p.z)):
      [new THREE.Vector3(-110,0,-110),new THREE.Vector3(110,0,110)]);
    const center=bounds.getCenter(new THREE.Vector3()),span=Math.max(50,bounds.getSize(new THREE.Vector3()).length());
    const distance=Math.min(650,Math.max(95,span*1.55));
    controls.autoRotate=false;camera.fov=48;camera.updateProjectionMatrix();controls.target.copy(center);
    if(mode==='plan')camera.position.copy(center).add(new THREE.Vector3(0,distance,0.05));
    else if(mode==='side'&&ps.length>1){
      const dx=ps[ps.length-1].x-ps[0].x,dz=ps[ps.length-1].z-ps[0].z,len=Math.hypot(dx,dz)||1;
      camera.position.copy(center).add(new THREE.Vector3(-dz/len*distance,distance*.36,dx/len*distance));
    } else camera.position.copy(center).add(new THREE.Vector3(distance*.68,distance*.58,distance*.68));
    camera.lookAt(center);controls.update();
  }
  function attach(scene) {
    const {renderer,camera,controls,terrainMesh,groundY}=scene.userData,canvas=renderer.domElement;
    const ray=new THREE.Raycaster(),mouse=new THREE.Vector2();let down=null,raf=0,lastEvent=null,disposed=false;
    if(!tooltip){tooltip=document.createElement('div');tooltip.id='roadLiveReadout';tooltip.hidden=true;document.body.append(tooltip);}
    function surface(e){
      const r=canvas.getBoundingClientRect();mouse.set((e.clientX-r.left)/r.width*2-1,1-(e.clientY-r.top)/r.height*2);
      ray.setFromCamera(mouse,camera);return terrainMesh?ray.intersectObject(terrainMesh,false)[0]?.point:null;
    }
    function project(x,z,height=0){
      const r=canvas.getBoundingClientRect(),v=new THREE.Vector3(x,groundY(x,z)+1.5+height*currentSceneTransform().scene_units_per_metre,z).project(camera);
      return {x:r.left+(v.x+1)*r.width/2,y:r.top+(1-v.y)*r.height/2,visible:v.z>-1&&v.z<1};
    }
    function handle(e){
      let found=null,best=17;
      points().forEach((p,i)=>{const xy=networkToScenePoint(p.x,p.y),v=project(xy.x,xy.z,p.height_m||0),d=Math.hypot(v.x-e.clientX,v.y-e.clientY);
        if(v.visible&&d<best){found=i;best=d;}});return found;
    }
    function resolve(e,height=0,offset=null){
      const hit=surface(e);if(!hit)return null;
      const raw=sceneToNetworkPoint(hit.x,hit.z);
      if(offset){raw.x+=offset.x;raw.y+=offset.y;}
      const nearest=nearestIfLineNode(raw.x,raw.y);
      let snap=false;
      if(!height&&!e.shiftKey&&byId('roadSnapEnabled').checked&&nearest&&nearest.distance<=currentNewRoadSnapTolerance()){
        const p=networkToScenePoint(nearest.x,nearest.y),screen=project(p.x,p.z);
        snap=screen.visible&&Math.hypot(screen.x-e.clientX,screen.y-e.clientY)<=22;
      }
      const x=snap?nearest.x:raw.x,y=snap?nearest.y:raw.y,p=networkToScenePoint(x,y);
      return {raw_x:x,raw_y:y,x,y,scene_x:p.x,scene_z:p.z,height_m:height,snap_enabled:snap,
        snapped:snap||Boolean(nearest&&nearest.distance<1e-5),node_id:snap?nearest.id:null};
    }
    function preview(e){
      clearHover();if(!editable()||!iflineNewRoadDrawing||down)return;
      const p=resolve(e);if(!p)return;
      const scale=currentSceneTransform().scene_units_per_metre,prev=points()[points().length-1];
      ghost=new THREE.Group();ghost.userData.roadHoverPreview=true;
      const color=p.snapped?0x71e2b5:0x73cfff;
      const marker=new THREE.Mesh(new THREE.SphereGeometry(1.4,12,8),new THREE.MeshBasicMaterial({color,depthTest:true,toneMapped:false}));
      marker.position.set(p.scene_x,groundY(p.scene_x,p.scene_z)+1.5,p.scene_z);ghost.add(marker);
      let text=p.snapped?`吸附路口 ${p.node_id} · 点击确定`:'自由位置 · 点击确定';
      if(prev){
        const width=(Number(byId('iflineNewRoadLanes').value)*3.5*(byId('iflineNewRoadBidirectional').checked?2:1)+2)*scale;
        const mat=new THREE.MeshBasicMaterial({color,transparent:true,opacity:.62,depthTest:true,depthWrite:false,toneMapped:false});
        const mesh=CityRoadMesh.create(THREE,{x:prev.scene_x,z:prev.scene_z},{x:p.scene_x,z:p.scene_z},width,.12,mat,groundY,(prev.height_m||0)*scale,0,.72);
        if(mesh)ghost.add(mesh);else mat.dispose();
        const length=Math.hypot(p.x-prev.x,p.y-prev.y),grade=length?Math.abs(prev.height_m||0)/length*100:0;
        text+=`\n本段 ${length.toFixed(0)} m · 相对抬高坡率 ${grade.toFixed(1)}%`;
        if(grade>12)text+=' · 过陡';
      }
      scene.add(ghost);tooltip.textContent=text;tooltip.hidden=false;
      tooltip.style.left=Math.max(8,Math.min(window.innerWidth-270,e.clientX+16))+'px';
      tooltip.style.top=Math.max(8,Math.min(window.innerHeight-95,e.clientY+18))+'px';
    }
    function finish(cancel=false){
      if(!down)return;const old=down;down=null;
      if(old.index!==null){
        if(cancel)iflineNewRoadPoints=old.before;
        else if(old.max>2)history.remember(old.before);
        controls.enabled=old.controlsEnabled;
        if(canvas.hasPointerCapture(old.id))canvas.releasePointerCapture(old.id);
        renderNewRoadDraft();
      }
      clearHover();canvas.style.cursor='crosshair';
    }
    cancelMapDrag=()=>finish(true);
    function pointerDown(e){
      if(!editable()||down||![0,2].includes(e.button))return;
      const index=e.button===0?handle(e):null;
      down={x:e.clientX,y:e.clientY,max:0,index,id:e.pointerId,button:e.button,
        before:JSON.parse(JSON.stringify(points())),controlsEnabled:controls.enabled};
      controls.autoRotate=false;clearHover();
      if(index!==null){
        const hit=surface(e),raw=hit&&sceneToNetworkPoint(hit.x,hit.z);
        down.offset=raw?{x:points()[index].x-raw.x,y:points()[index].y-raw.y}:null;
        e.preventDefault();e.stopImmediatePropagation();controls.enabled=false;canvas.setPointerCapture(e.pointerId);canvas.style.cursor='grabbing';
      }
    }
    function pointerMove(e){
      if(!editable())return;
      if(down){
        if(e.pointerId!==down.id)return;
        down.max=Math.max(down.max,Math.hypot(e.clientX-down.x,e.clientY-down.y));
        if(down.index!==null){
          e.preventDefault();e.stopImmediatePropagation();
          const p=resolve(e,down.before[down.index].height_m||0,down.offset);if(!p)return;
          iflineNewRoadPoints[down.index]=p;resnapNewRoadPoints();renderNewRoadOverlay();refreshStudioRunButton();refresh();
        }return;
      }
      canvas.style.cursor=handle(e)!==null?'grab':iflineNewRoadDrawing?'crosshair':'grab';
      lastEvent={clientX:e.clientX,clientY:e.clientY,shiftKey:e.shiftKey};
      if(!raf)raf=requestAnimationFrame(()=>{raf=0;if(!disposed)preview(lastEvent);});
    }
    function pointerUp(e){
      if(!down||e.pointerId!==down.id)return;
      down.max=Math.max(down.max,Math.hypot(e.clientX-down.x,e.clientY-down.y));
      if(down.index!==null){e.preventDefault();e.stopImmediatePropagation();finish();return;}
      const old=down;down=null;clearHover();
      if(!editable()||old.max>7)return;
      if(old.button===2){undoNewRoadPoint();return;}
      if(!iflineNewRoadDrawing)return;
      const p=resolve(e);if(!p)return;
      if(points().length>=32){message('最多 32 个控制点，请先撤销一点。');return;}
      const last=points()[points().length-1];
      if(last&&Math.hypot(last.x-p.x,last.y-p.y)<2){message('本次位置离上一点不足 2 米，请移远一些。');return;}
      remember();
      if(cityPlanMoveIndex!==null){points()[cityPlanMoveIndex]=Object.assign(p,{height_m:points()[cityPlanMoveIndex].height_m||0});cityPlanMoveIndex=null;}
      else points().push(p);
      renderNewRoadDraft();message('已放置控制点。继续画路，或暂停后拖动蓝点编辑；两端接回路网后，可直接检查冲突。');
    }
    function cancel(){finish(true);clearHover();}
    function releaseOutside(){if(down)finish(true);}
    function leave(){if(!down)clearHover();}
    function context(e){if(editable())e.preventDefault();}
    function key(e){
      if(!editable()||e.target.closest?.('input,textarea,select,[role=slider],[contenteditable=true]'))return;
      if(e.code==='Escape'){e.preventDefault();finish(true);iflineNewRoadDrawing=false;renderNewRoadDraft();clearHover();}
      if((e.ctrlKey||e.metaKey)&&e.code==='KeyZ'){e.preventDefault();e.stopImmediatePropagation();e.shiftKey?redo():undo();}
    }
    const bindings=[['pointerdown',pointerDown],['pointermove',pointerMove],['pointerup',pointerUp],['pointercancel',cancel],['lostpointercapture',cancel],['pointerleave',leave],['contextmenu',context]];
    bindings.forEach(([name,fn])=>canvas.addEventListener(name,fn,true));
    window.addEventListener('keydown',key,true);window.addEventListener('blur',cancel);
    window.addEventListener('pointerup',releaseOutside);
    refresh();
    return ()=>{disposed=true;cancel();cancelAnimationFrame(raf);bindings.forEach(([n,f])=>canvas.removeEventListener(n,f,true));window.removeEventListener('keydown',key,true);window.removeEventListener('blur',cancel);window.removeEventListener('pointerup',releaseOutside);cancelMapDrag=null;};
  }
  document.addEventListener('DOMContentLoaded',()=>{
    const target=byId('roadProfile');
    target.addEventListener('pointerdown',e=>{
      const item=e.target.closest('[data-point]');if(!editable()||!item||!profileLayout)return;
      const index=Number(item.dataset.point);if(!index||index===points().length-1)return;
      e.preventDefault();cancelMapDrag?.();clearHover();
      profileDrag={index,id:e.pointerId,before:JSON.parse(JSON.stringify(points())),layout:profileLayout};
      points().forEach(p=>{p.raw_x=p.x;p.raw_y=p.y;});
      target.setPointerCapture(e.pointerId);
    });
    target.addEventListener('pointermove',e=>{
      if(!profileDrag||e.pointerId!==profileDrag.id)return;
      const rect=target.getBoundingClientRect(),y=(e.clientY-rect.top)/rect.height*180,l=profileDrag.layout;
      const relative=l.origin+l.lo+(145-y)/119*(l.hi-l.lo)-l.data.handles[profileDrag.index].ground;
      freezeHeight(profileDrag.index,relative,false);
    });
    const finish=cancel=>{
      if(!profileDrag)return;const old=profileDrag;profileDrag=null;
      if(cancel)iflineNewRoadPoints=old.before;else history.remember(old.before);
      if(target.hasPointerCapture(old.id))target.releasePointerCapture(old.id);
      renderNewRoadDraft();
    };
    target.addEventListener('pointerup',()=>finish(false));target.addEventListener('pointercancel',()=>finish(true));
    target.addEventListener('lostpointercapture',()=>finish(true));window.addEventListener('blur',()=>finish(true));
    target.addEventListener('keydown',e=>{
      const item=e.target.closest('[data-point]');if(!item||!['ArrowUp','ArrowDown'].includes(e.code))return;
      e.preventDefault();e.stopPropagation();const i=Number(item.dataset.point);
      freezeHeight(i,(points()[i].height_m||0)+(e.code==='ArrowUp'?1:-1));
      target.querySelector(`[data-point="${i}"]`)?.focus();
    });
    byId('roadSnapEnabled').addEventListener('change',clearHover);refresh();
  });
  window.RoadEditor={attach,refresh,remember,reset,clearHover,undo,redo,bridge,flatten,view,freezeHeight};
})();
