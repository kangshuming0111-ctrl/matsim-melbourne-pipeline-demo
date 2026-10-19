/* Presentation-only contract: physical facade spacing without changing solids. */
const assert=require('node:assert/strict'),fs=require('node:fs');
const THREE=require('../wrapper/static/vendor/three/three.min.js');
const Style=require('../wrapper/static/building-style.js');
require('../wrapper/static/landuse-geometry.js');require('../wrapper/static/building-mesh.js');
let canvases=0,checks=0;
const createCanvas=()=>{canvases++;return {width:0,height:0,getContext:()=>({
  fillRect(){},createLinearGradient(){return {addColorStop(){}};},
})};};
const palette=Style.createPalette(THREE,{createCanvas});
const b={points:[[0,0],[8,0],[8,4],[0,4]],height:8,height_m:80,kind:'office'};
const original=JSON.stringify(b),m=palette(b);
assert.equal(m.wall,palette(b).wall);assert.equal(m.roof,palette(b).roof);checks+=2;
assert.equal(canvases,1);assert.equal(JSON.stringify(b),original);checks+=2;
assert.equal(m.wall.transparent,false);assert.equal(m.wall.map.wrapT,THREE.ClampToEdgeWrapping);
assert.equal(m.wall.map.encoding,THREE.sRGBEncoding);assert.equal(m.wall.emissiveIntensity,1);checks+=4;
assert.equal(m.wall.emissive.getHex(),0);checks++;
for(const kind of ['residential','office','retail','civic','industrial','unknown']) {
  for(const height_m of [9,15,28,55,110,220,320])palette({...b,kind,height_m});
}
assert.ok(canvases<=42,'Bounded shared textures, not one per building');checks++;
assert.equal(Style.descriptor({...b,kind:'unknown'}).kind,'generic');checks++;
assert.throws(()=>Style.descriptor({...b,height:NaN}));checks++;
const fixtures=JSON.parse(fs.readFileSync(require.resolve('./browser/building-fixtures.json'),'utf8'));
for(const f of fixtures) {
  const styled=palette({...f,height_m:f.height_m||80,kind:'office'});
  const originalGroup=SkylineBuildings.create(THREE,f,()=>2,{wall:styled.wall,roof:styled.roof});
  const group=SkylineBuildings.create(THREE,f,()=>2,styled);
  assert.equal(group.children.length,originalGroup.children.length);checks++;
  group.children.forEach((obj,j)=>{
    assert.deepEqual(obj.geometry.attributes.position.array,originalGroup.children[j].geometry.attributes.position.array);
    assert.deepEqual(obj.geometry.attributes.normal.array,originalGroup.children[j].geometry.attributes.normal.array);
    assert.ok([...obj.geometry.attributes.uv?.array||[]].every(Number.isFinite));checks+=3;
  });
  const geom=group.children[0].geometry,p=geom.attributes.position,n=geom.attributes.normal,uv=geom.attributes.uv;
  // Diagonal and axis-aligned walls must have identical metres per bay.
  for(let i=0;i<p.count;i+=3)if(Math.abs(n.getY(i))<.5) {
    for(const [a,c] of [[i,i+1],[i+1,i+2],[i,i+2]]) {
      if(Math.abs(p.getY(a)-p.getY(c))<1e-5) {
        const world=Math.hypot(p.getX(a)-p.getX(c),p.getZ(a)-p.getZ(c));
        assert.ok(Math.abs(Math.abs(uv.getX(a)-uv.getX(c))*styled.facade.bayWidth-world)<1e-4);
      }
      assert.ok(uv.getY(a)>=-1e-5&&uv.getY(a)<=1.00001);
    }
  }
  checks++;
}
console.log(`PASS building style: ${checks} checks; unchanged solids, upright physical-bay UVs, shared opaque materials, bounded textures`);
