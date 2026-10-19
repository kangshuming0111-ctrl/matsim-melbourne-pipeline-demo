// Production playback, real Three.js matrices; no browser/GPU required.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const THREE=require('../wrapper/static/vendor/three/three.min.js');
const html=fs.readFileSync(require.resolve('../wrapper/static/index.html'),'utf8');
const code=html.slice(html.indexOf('function formatSimClock('),html.lastIndexOf('</script>'));
const controls=Object.fromEntries(['simSlider','simClock','simActiveCars','simPlayPause','simSpeed','simDensity']
  .map(id=>[id,Object.assign(new EventTarget(),{dataset:{}})]));
controls.simSpeed.value='4';
const scope={THREE,document:{getElementById:id=>controls[id]}};
vm.createContext(scope);vm.runInContext(code,scope);
let checks=0;
function equal(actual,expected){assert.deepEqual(actual,expected);checks++;}
function near(a,b){assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);checks++;}
function makeScene(data,ground=()=>0){const s=new THREE.Scene();s.userData={controls:{autoRotate:true},tickCallbacks:[],cleanupCallbacks:[],requestRender(){s.userData.requests=(s.userData.requests||0)+1;}};scope.setupVehicleAnimation(s,data,ground);return s;}
function dispose(s){s.userData.cleanupCallbacks.forEach(f=>f());}
function mode(value){controls.simDensity.value=String(value);controls.simDensity.dispatchEvent(new Event('change'));}
function scrub(t){controls.simSlider.value=String(t);controls.simSlider.dispatchEvent(new Event('input'));controls.simSlider.dispatchEvent(new Event('change'));}
function mesh(s,name){return s.getObjectByName('vehicle-'+name);}
function position(s,name,i=0){const m=new THREE.Matrix4();mesh(s,name).getMatrixAt(i,m);return new THREE.Vector3().setFromMatrixPosition(m);}
function count(real,extra,density){equal({...controls.simActiveCars.dataset},{realCars:String(real),illustrativeCars:String(extra),displayCars:String(real+extra),density:String(density)});}
const trip=[[0,0,999,0,8],[100,100,999,0,8]];
const data={sim_time_range:[0,220],sim_focus_time:42,coordinate_transform:{scene_units_per_metre:.1},
  vehicles:[{trips:[trip,[[150,0,999,0,0],[200,50,999,0,0]]]}]};
const original=JSON.stringify(data),s=makeScene(data,()=>10);
equal(mesh(s,'bodies').count,1);count(1,0,1);
const m=new THREE.Matrix4();mesh(s,'bodies').getMatrixAt(0,m);
near(new THREE.Vector3().setFromMatrixScale(m).x,.5);
near(mesh(s,'bodies').geometry.parameters.depth*.5,1.925);
near(position(s,'bodies').x,42);
near(position(s,'axles').y-.30*.5/2,10+.8+.35); // wheel bottom on deck, not under it
near(position(s,'cabins').y-position(s,'bodies').y,(.82/2+.72/2)*.5);
near(position(s,'axles',0).distanceTo(position(s,'axles',1)),2.36*.5);
equal(s.children.length,4); // bounded draw objects, not one object per vehicle
equal(mesh(s,'roofs').count,mesh(s,'bodies').count);
equal(mesh(s,'roofs').material,mesh(s,'bodies').material);
assert.ok(mesh(s,'bodies').material.metalness<.1);checks++;
assert.ok(mesh(s,'cabins').material.color.g>.3);checks++;
const bodyColor=new THREE.Color(),roofColor=new THREE.Color();
mesh(s,'bodies').getColorAt(0,bodyColor);mesh(s,'roofs').getColorAt(0,roofColor);
equal(mesh(s,'bodies').instanceColor.count,5);
equal(mesh(s,'roofs').instanceColor.count,5);
equal(mesh(s,'bodies').instanceColor.usage,THREE.DynamicDrawUsage);
assert.ok(bodyColor.toArray().every(c=>Number.isFinite(c)&&c>.8));checks++;
equal(bodyColor.toArray(),roofColor.toArray());
const roofBottom=position(s,'roofs').y-.12*.5/2;
const glassTop=position(s,'cabins').y+.72*.5/2;
assert.ok(roofBottom<glassTop && roofBottom>glassTop-.03);checks++;
const cabinVertices=mesh(s,'cabins').geometry.attributes.position;
for(let i=0;i<cabinVertices.count;i++)if(cabinVertices.getY(i)>0){
  assert.ok(Math.abs(cabinVertices.getX(i))<=1.58*.84/2+1e-5);checks++;
  assert.ok(Math.abs(cabinVertices.getZ(i))<=1.85*.72/2+1e-5);checks++;
}
controls.simPlayPause.dispatchEvent(new Event('click'));
equal(s.userData.playbackActive(),false);
mode(3);count(1,2,3);equal(mesh(s,'bodies').count,3);equal(mesh(s,'axles').count,6);
near(position(s,'bodies',1).x,38);near(position(s,'bodies',2).x,34);
equal(s.userData.requests,1);assert.match(controls.simActiveCars.textContent,/仿真 1 · 示意 \+2/);checks++;
mode(5);count(1,4,5);equal(mesh(s,'bodies').count,5);
equal(mesh(s,'roofs').count,5);
for(let i=0;i<5;i++){
  mesh(s,'bodies').getColorAt(i,bodyColor);mesh(s,'roofs').getColorAt(i,roofColor);
  assert.ok(bodyColor.toArray().every(c=>Number.isFinite(c)&&c>0));checks++;
  equal(bodyColor.toArray(),roofColor.toArray());
}
const allPaint=Array.from(mesh(s,'bodies').instanceColor.array);
equal(new Set(Array.from({length:5},(_,i)=>allPaint.slice(i*3,i*3+3).join(','))).size,5);
mode(1);count(1,0,1);equal(mesh(s,'bodies').count,1);
mode(500);count(1,0,1);equal(controls.simDensity.value,'1');
mode(3);scrub(1);count(1,0,3); // no negative-time ghosts
scrub(100);count(0,0,3);equal(mesh(s,'bodies').count,0); // exact trip end
equal(mesh(s,'roofs').count,0);
scrub(120);count(0,0,3); // parking gap
scrub(150);count(1,0,3);near(position(s,'bodies').x,0); // no reuse of earlier trip
scrub(180);count(1,2,3);
scrub(220);count(0,0,3);
equal(JSON.stringify(data),original);
dispose(s);
const staleRequests=s.userData.requests;
const next=makeScene(data);count(1,0,1);equal(controls.simDensity.value,'1');
mode(3);equal(s.userData.requests,staleRequests);equal(next.userData.requests,1);dispose(next);
const empty=makeScene({sim_time_range:[0,100],vehicles:[]});count(0,0,1);
equal(controls.simDensity.disabled,true);equal(empty.children.length,0);dispose(empty);
const stopped=makeScene({sim_time_range:[0,100],sim_focus_time:42,
  vehicles:[{trips:[[[0,0,0,0],[20,20,0,0],[100,20,0,0]]]}]});
mode(5);count(1,0,5);equal(mesh(stopped,'bodies').count,1);dispose(stopped);
// Real car has priority over an illustrative follower at its location.
const crowded=makeScene({sim_time_range:[0,100],sim_focus_time:42,
  vehicles:[{trips:[trip]},{trips:[[[0,-4,0,0,8],[100,96,0,0,8]]]}]});
mode(3);count(2,2,3);equal(mesh(crowded,'bodies').count,4);dispose(crowded);
// Duplicate timestamps choose the outgoing segment, no NaN division.
const p=scope.sampleVehicleTrip([[0,0,0,0],[10,10,0,0],[10,12,0,0],[20,22,0,0]],10);
near(p.x,12);equal(scope.sampleVehicleTrip(trip,100),null);equal(scope.sampleVehicleTrip([],2),null);
// Pure same-input sampling does not carry heading from another vehicle.
const q=scope.sampleVehicleTrip([[0,0,0,0],[10,10,0,0],[30,10,0,0]],20);
near(q.yaw,Math.PI/2);
// Regression: the first frame may have no cars, then several enter at once.
const late=makeScene({sim_time_range:[0,200],sim_focus_time:0,
  vehicles:Array.from({length:8},(_,i)=>({trips:[[[100,i*10,0,0],[200,i*10+20,0,0]]]}))});
equal(mesh(late,'bodies').count,0);equal(mesh(late,'bodies').instanceColor.count,40);
scrub(150);equal(mesh(late,'bodies').count,8);
for(let i=0;i<8;i++){
  mesh(late,'bodies').getColorAt(i,bodyColor);mesh(late,'roofs').getColorAt(i,roofColor);
  assert.ok(bodyColor.toArray().every(c=>Number.isFinite(c)&&c>0));checks++;
  equal(bodyColor.toArray(),roofColor.toArray());
}
dispose(late);
console.log(`PASS vehicle density: ${checks} checks (counts, size, deck clearance, pause/scrub, no parked ghosts, cleanup, immutable input)`);
