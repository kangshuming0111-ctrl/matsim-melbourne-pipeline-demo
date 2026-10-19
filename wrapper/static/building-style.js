/* Display-only architectural grammar. Colours and window/storefront layouts
 * are schematic, not surveyed facade details or measured floor counts.
 * One palette per scene; shared opaque materials remain batchable. The scene
 * resource lifecycle owns all returned materials and textures. No added solids.
 */
(function(root) {
  'use strict';
  const styles = Object.freeze({
    residential: {wall:'#c7a590',glass:'#526f79',frame:'#e5d8c7',roof:0x9c9b92,bay:4.2},
    office: {wall:'#92aeba',glass:'#537886',frame:'#b4c9ca',roof:0x91a0a3,bay:3.8},
    retail: {wall:'#c9b185',glass:'#597a81',frame:'#e9ddc3',roof:0xa69c88,bay:4.6},
    civic: {wall:'#d2c8af',glass:'#657d83',frame:'#eee7d6',roof:0xa6aaa3,bay:4.4},
    industrial: {wall:'#acb7b0',glass:'#728d93',frame:'#d1d9d2',roof:0x8f9c99,bay:6},
    generic: {wall:'#bbb9ae',glass:'#647f87',frame:'#deded2',roof:0x99a3a2,bay:4.4},
  });
  const floorBands = [2,4,8,16,32,64,96];
  function descriptor(building) {
    const metres=Number(building.height_m), height=Number(building.height);
    if(!(height>0 && Number.isFinite(height)))throw new Error('Building height must be finite and positive');
    const heightM=metres>0&&Number.isFinite(metres)?metres:9;
    const kind=Object.hasOwn(styles,building.kind)?building.kind:'generic';
    const estimate=Math.max(2,heightM/(kind==='industrial'?5:3.5));
    const floors=floorBands.reduce((best,n)=>Math.abs(n-estimate)<Math.abs(best-estimate)?n:best);
    return {kind,floors,bayWidth:styles[kind].bay*height/heightM};
  }
  function facade(THREE, createCanvas, kind, floors) {
    const p=styles[kind], canvas=createCanvas();
    canvas.width=128;
    canvas.height=Math.min(2048,Math.max(256,2**Math.ceil(Math.log2(floors*32))));
    const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,row=h/floors;
    ctx.fillStyle=p.wall;ctx.fillRect(0,0,w,h);
    // An upright, complete elevation tile: bottom is the street, top is the
    // cornice. Vertical clamping prevents a shopfront repeating on every floor.
    for(let r=0;r<floors;r++) {
      const y=h-(r+1)*row;
      const shop=r===0 && (kind==='retail'||kind==='civic');
      const office=kind==='office', industrial=kind==='industrial';
      const left=office?6:industrial?14:21;
      const top=y+row*(shop?.16:.20),wh=row*(office?.68:shop?.78:.56);
      ctx.fillStyle=p.frame;ctx.fillRect(left-3,top-2,w-left*2+6,wh+4);
      const glass=ctx.createLinearGradient(left,top,w-left,top+wh);
      glass.addColorStop(0,p.glass);glass.addColorStop(1,office?'#89a5ad':'#8ba3a3');
      ctx.fillStyle=glass;ctx.fillRect(left,top,w-left*2,wh);
      // Dark recess at head, restrained sky reflection, no emissive night grid.
      ctx.fillStyle='rgba(23,44,53,.22)';ctx.fillRect(left,top,w-left*2,Math.max(1,row*.055));
      ctx.fillStyle='rgba(234,244,237,.25)';ctx.fillRect(left+3,top+wh*.12,3,wh*.70);
      ctx.fillStyle=p.frame;
      if(!industrial)ctx.fillRect(w*.50-1,top,2,wh);
      if(kind==='residential') {
        ctx.fillStyle='rgba(77,73,63,.25)';ctx.fillRect(left-5,top+wh+3,w-left*2+10,Math.max(1,row*.055));
      }
      if(shop) {
        ctx.fillStyle=kind==='retail'?'#59776d':'#b2a485';
        ctx.fillRect(8,top-row*.10,w-16,Math.max(2,row*.10));
        ctx.fillStyle=p.frame;ctx.fillRect(w*.28,top,3,wh);ctx.fillRect(w*.73,top,3,wh);
      }
      if(office) {
        ctx.fillStyle='rgba(207,225,226,.65)';ctx.fillRect(0,y,3,row);ctx.fillRect(w-3,y,3,row);
      }
      ctx.fillStyle='rgba(52,67,68,.12)';ctx.fillRect(0,y+row-2,w,2);
    }
    // Shallow coping and plinth are painted inside the existing building,
    // never giant boxes sitting above its declared roof height.
    ctx.fillStyle=p.frame;ctx.fillRect(0,0,w,Math.max(2,row*.12));
    ctx.fillStyle='rgba(50,64,64,.23)';ctx.fillRect(0,h-Math.max(2,row*.07),w,Math.max(2,row*.07));
    const texture=new THREE.CanvasTexture(canvas);
    texture.wrapS=THREE.RepeatWrapping;texture.wrapT=THREE.ClampToEdgeWrapping;
    texture.encoding=THREE.sRGBEncoding;
    texture.minFilter=THREE.LinearMipmapLinearFilter;texture.magFilter=THREE.LinearFilter;
    texture.anisotropy=4;
    return texture;
  }
  function createPalette(THREE,{createCanvas=()=>document.createElement('canvas')}={}) {
    const walls=new Map(),caps=new Map();
    return function forBuilding(building) {
      const d=descriptor(building),p=styles[d.kind],key=`${d.kind}:${d.floors}`;
      if(!walls.has(key))walls.set(key,new THREE.MeshStandardMaterial({
        color:0xffffff,map:facade(THREE,createCanvas,d.kind,d.floors),
        roughness:d.kind==='office'?.42:.83,metalness:d.kind==='office'?.12:.02,
        side:THREE.DoubleSide,
      }));
      if(!caps.has(d.kind))caps.set(d.kind,new THREE.MeshStandardMaterial({
        color:new THREE.Color(p.roof).convertSRGBToLinear(),
        roughness:.88,metalness:.04,side:THREE.DoubleSide,
      }));
      return {wall:walls.get(key),roof:caps.get(d.kind),crown:caps.get(d.kind),facade:d};
    };
  }
  const api={createPalette,descriptor};
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.SkylineBuildingStyle=api;
})(globalThis);
