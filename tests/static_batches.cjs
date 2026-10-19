/* Deterministic tests against bundled r128, not a mocked geometry engine. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const THREE=require('../wrapper/static/vendor/three/three.min.js');
const Batches=require('../wrapper/static/static-batches.js');
require('../wrapper/static/landuse-geometry.js');
require('../wrapper/static/building-mesh.js');
let checks=0;
function check(value,message){assert.ok(value,message);checks++;}
function triangles(objects,root) {
  root.updateMatrixWorld(true);
  const result=[], inverse=new THREE.Matrix4().copy(root.matrixWorld).invert();
  for(const mesh of objects) {
    const g=mesh.geometry.index?mesh.geometry.toNonIndexed():mesh.geometry.clone();
    g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse,mesh.matrixWorld));
    const mats=Array.isArray(mesh.material)?mesh.material:[mesh.material];
    const parts=Array.isArray(mesh.material)?g.groups:[{start:0,count:g.attributes.position.count,materialIndex:0}];
    for(const part of parts)for(let v=part.start;v<part.start+part.count;v+=3) {
      const signature=[mats[part.materialIndex].uuid,mesh.renderOrder,mesh.castShadow,mesh.receiveShadow];
      for(const name of Object.keys(g.attributes).sort()) {
        const attr=g.attributes[name];signature.push(name);
        for(let k=v*attr.itemSize;k<(v+3)*attr.itemSize;k++)signature.push(Number(attr.array[k].toFixed(4)));
      }
      result.push(JSON.stringify(signature));
    }
    g.dispose();
  }
  return result.sort();
}
{
  const scene=new THREE.Scene(), sources=[];
  // Local coordinates must remain valid under a transformed scene root.
  scene.position.set(10,2,9);scene.rotation.y=.2;
  const materials={roof:new THREE.MeshStandardMaterial({color:0x445566}),wall:new THREE.MeshStandardMaterial({color:0x778899})};
  const fixtures=JSON.parse(fs.readFileSync(require.resolve('./browser/building-fixtures.json'),'utf8'));
  for(const [i,b] of fixtures.entries()) {
    const group=SkylineBuildings.create(THREE,b,(x,z)=>.03*x+.02*z,materials);
    group.position.x=i*23;group.rotation.y=.1*i;scene.add(group);
    group.traverse(obj=>{if(obj.isMesh)sources.push(obj);});
  }
  const road=new THREE.Mesh(new THREE.BoxGeometry(12,.2,3),materials.wall);
  road.position.set(-30,4,0);road.rotation.y=.7;road.scale.set(1.2,1,.9);
  road.userData.iflineLinkId='kept-road';scene.add(road);sources.push(road);
  const expected=triangles(sources,scene), roadGeometry=road.geometry, roadMatrix=road.matrixWorld.clone();
  let materialDisposals=0;materials.wall.addEventListener('dispose',()=>materialDisposals++);
  const batch=Batches.create(THREE,scene,sources,{maxVertices:120});
  assert.deepEqual(triangles(batch.group.children,scene),expected);checks++;
  check(batch.stats.sourceMeshes===sources.length,'All supported building and road solids batched');
  check(batch.group.children.every(m=>m.geometry.attributes.position.count<=120),'Bounded triangle chunks');
  check(sources.every(m=>!m.visible),'No duplicate rendered surfaces');
  check(road.geometry===roadGeometry && road.userData.iflineLinkId==='kept-road','Pick identity and overlay geometry retained');
  const centre=new THREE.Vector3().setFromMatrixPosition(roadMatrix);
  const ray=new THREE.Raycaster(centre.clone().add(new THREE.Vector3(0,50,0)),new THREE.Vector3(0,-1,0));
  check(ray.intersectObject(road).some(hit=>hit.object===road),'Invisible original remains ray-pickable in r128');
  let releases=0;batch.group.children.forEach(m=>m.geometry.addEventListener('dispose',()=>releases++));
  batch.dispose();batch.dispose();
  check(releases===batch.stats.batchDraws,'Exactly once batched geometry disposal');
  check(materialDisposals===0,'Shared material not owned by batch');
  check(sources.every(m=>m.visible)&&!batch.group.parent,'Restores original rendering on disposal');
}
{
  const scene=new THREE.Scene(),material=new THREE.MeshStandardMaterial(),sources=[];
  for(let i=0;i<1000;i++) {
    const m=new THREE.Mesh(new THREE.BoxGeometry(1,2,3),material);
    m.position.set((i%25)*2,0,Math.floor(i/25));scene.add(m);sources.push(m);
  }
  const batch=Batches.create(THREE,scene,sources);
  check(batch.stats.sourceDraws===1000 && batch.stats.batchDraws===1,'1000 shared-material opaque draws become one');
  check(batch.stats.vertices===36000,'All 12000 triangles retained');batch.dispose();
}
{
  const scene=new THREE.Scene(),sources=[];
  const add=m=>{scene.add(m);sources.push(m);return m;};
  const opaque=new THREE.MeshBasicMaterial();
  add(new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial({transparent:true,opacity:.5})));
  add(new THREE.InstancedMesh(new THREE.BoxGeometry(),opaque,2));
  add(new THREE.Mesh(new THREE.BoxGeometry(),opaque)).geometry.attributes.position.setUsage(THREE.DynamicDrawUsage);
  add(new THREE.Mesh(new THREE.BoxGeometry(),opaque)).scale.x=-1;
  add(new THREE.Mesh(new THREE.BoxGeometry(),opaque)).geometry.setDrawRange(0,6);
  add(new THREE.Mesh(new THREE.BoxGeometry(),opaque)).visible=false;
  const hiddenGroup=new THREE.Group();hiddenGroup.visible=false;scene.add(hiddenGroup);
  const hidden=add(new THREE.Mesh(new THREE.BoxGeometry(),opaque));hiddenGroup.add(hidden);
  const badGroups=add(new THREE.Mesh(new THREE.BoxGeometry(),[opaque]));badGroups.geometry.clearGroups();
  const visibility=sources.map(m=>m.visible);
  const batch=Batches.create(THREE,scene,sources);
  check(batch.stats.sourceMeshes===0 && batch.stats.skipped===sources.length,'Unsupported/transparent/dynamic/hidden sources stay unbatched');
  assert.deepEqual(sources.map(m=>m.visible),visibility);checks++;
  batch.dispose();
  assert.throws(()=>Batches.create(THREE,scene,[],{cellSize:0}));checks++;
  assert.throws(()=>Batches.create(THREE,scene,[],{maxVertices:2}));checks++;
}
console.log(`PASS static batching: ${checks} checks (geometry/material/UV parity, picking, bounded chunks, rejection, disposal)`);
