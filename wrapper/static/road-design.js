/* Pure road-draft operations. Coordinates and heights are metres; no DOM,
 * renderer, terrain writes or simulator calls. Hover never enters the draft. */
(function(root) {
  'use strict';
  const copy = value => JSON.parse(JSON.stringify(value));
  function stations(points) {
    const out=[0];
    for(let i=1;i<points.length;i++)out.push(out[i-1]+Math.hypot(points[i].x-points[i-1].x,points[i].y-points[i-1].y));
    return points.length?out:[];
  }
  function bridge(points,height) {
    if(points.length<2)throw Error('先画出至少两个点，再生成高架草案。');
    if(!Number.isFinite(height)||height<=0||height>50)throw Error('抬高值须在 0–50 米之间。');
    const s=stations(points),total=s[s.length-1],ramp=Math.max(20,height/0.08);
    if(total<ramp*2+20)throw Error(`路线太短：此抬高值建议至少 ${Math.ceil(ramp*2+20)} 米（含两端过渡段）。请延长路线或降低高度。`);
    const cuts=[...s,ramp,total-ramp].sort((a,b)=>a-b).filter((v,i,a)=>!i||v-a[i-1]>0.01);
    if(cuts.length>32)throw Error('控制点过多，请先删减到 30 个以内。');
    return cuts.map(d=>{
      const existing=s.findIndex(v=>Math.abs(v-d)<0.01);
      let p;
      if(existing>=0)p=copy(points[existing]);
      else {
        const i=s.findIndex(v=>v>d),t=(d-s[i-1])/(s[i]-s[i-1]);
        p={x:points[i-1].x+(points[i].x-points[i-1].x)*t,y:points[i-1].y+(points[i].y-points[i-1].y)*t,snap_enabled:false};
      }
      p.raw_x=p.x;p.raw_y=p.y;
      p.height_m=Math.round(Math.min(1,d/ramp,(total-d)/ramp)*height*100)/100;
      if(d>0&&d<total)p.snap_enabled=false;
      return p;
    });
  }
  function setHeight(points,index,height) {
    if(!Number.isInteger(index)||index<0||index>=points.length||!Number.isFinite(height))throw Error('控制点或高度无效');
    const out=copy(points);
    out[index].height_m=index===0||index===points.length-1?0:Math.round(Math.max(0,Math.min(50,height))*10)/10;
    return out;
  }
  function profile(points,ground) {
    const s=stations(points),samples=[],handles=[];let maxOffsetGrade=0;
    points.forEach((p,i)=>handles.push({station:s[i],ground:ground(p.x,p.y),height:p.height_m||0}));
    for(let i=1;i<points.length;i++) {
      const a=points[i-1],b=points[i],length=s[i]-s[i-1],n=Math.max(1,Math.min(128,Math.ceil(length/10)));
      maxOffsetGrade=Math.max(maxOffsetGrade,length?Math.abs((b.height_m||0)-(a.height_m||0))/length:Infinity);
      for(let j=i===1?0:1;j<=n;j++) {
        const t=j/n,g=ground(a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t),h=(a.height_m||0)+((b.height_m||0)-(a.height_m||0))*t;
        samples.push({station:s[i-1]+length*t,ground:g,road:g+h});
      }
    }
    return {samples,handles,total:s[s.length-1]||0,maxOffsetGrade};
  }
  function history() {
    const undo=[],redo=[];
    return {
      remember(points) {undo.push(copy(points));if(undo.length>50)undo.shift();redo.length=0;},
      undo(points) {if(!undo.length)return null;redo.push(copy(points));return undo.pop();},
      redo(points) {if(!redo.length)return null;undo.push(copy(points));return redo.pop();},
      clear(){undo.length=0;redo.length=0;},
      get canUndo(){return !!undo.length;},get canRedo(){return !!redo.length;}
    };
  }
  root.RoadDesign={stations,bridge,setHeight,profile,history};
  if(typeof module!=='undefined')module.exports=root.RoadDesign;
})(typeof window==='undefined'?globalThis:window);
