/* Opt-in static, opaque triangle batching for bundled Three.js r128.
 * Sources remain in the scene as hidden pick proxies, with original IDs and
 * geometry. No ownership of their geometry/materials/textures is transferred.
 * Moving sources requires rebuilding the batch. Transparent/dynamic objects
 * must stay on their original render path (sorting/animation is not equivalent).
 */
(function(root) {
  'use strict';
  function create(THREE, scene, sources, {cellSize=64, maxVertices=60000}={}) {
    if (!(cellSize>0 && Number.isFinite(cellSize)) || !Number.isInteger(maxVertices) || maxVertices<3)
      throw new Error('Invalid static batch limits');
    const group=new THREE.Group(); group.name='city.staticBatches';
    const buckets=new Map(), accepted=[];
    const stats={sourceMeshes:0, sourceDraws:0, batchDraws:0, vertices:0, skipped:0};
    scene.updateMatrixWorld(true);
    // Batch coordinates are local to scene, not the global world: scene/root
    // transforms are retained exactly once, including raycast proxy transforms.
    const inverse=new THREE.Matrix4().copy(scene.matrixWorld).invert();
    function inspect(mesh) {
      const g=mesh.geometry;
      if (!mesh.isMesh || mesh.isInstancedMesh || mesh.isSkinnedMesh || !mesh.visible ||
          !g?.isBufferGeometry || Object.keys(g.morphAttributes).length ||
          mesh.children.length || mesh.matrixWorld.determinant()<=0 ||
          mesh.layers.mask!==1 || mesh.customDepthMaterial || mesh.customDistanceMaterial) return null;
      let attached=false;
      for(let p=mesh.parent;p;p=p.parent) {
        if(!p.visible || (p.isGroup && p.renderOrder!==0))return null;
        if(p===scene){attached=true;break;}
      }
      if(!attached || mesh.onBeforeRender!==THREE.Object3D.prototype.onBeforeRender ||
          mesh.onAfterRender!==THREE.Object3D.prototype.onAfterRender)return null;
      const attrs=g.attributes;
      if(!attrs.position || Object.keys(attrs).some(k=>!['position','normal','uv'].includes(k)) ||
          Object.values(attrs).some(a=>a.isInterleavedBufferAttribute || a.normalized ||
            !(a.array instanceof Float32Array) || a.count!==attrs.position.count || a.usage!==THREE.StaticDrawUsage)) return null;
      const mats=Array.isArray(mesh.material)?mesh.material:[mesh.material];
      if(mats.some(m=>!m || !m.visible || m.transparent || m.opacity!==1 || !m.depthWrite ||
          m.wireframe || m.alphaTest || m.isShaderMaterial || m.blending!==THREE.NormalBlending))return null;
      const count=g.index?g.index.count:attrs.position.count;
      if(g.drawRange.start!==0 || g.drawRange.count<count || count%3)return null;
      const parts=Array.isArray(mesh.material)?g.groups:[{start:0,count,materialIndex:0}];
      // Do not guess how incomplete/overlapping material groups should render.
      let covered=0;
      for(const part of parts) {
        if(part.start!==covered || part.count%3 || !mats[part.materialIndex])return null;
        covered+=part.count;
      }
      if(covered!==count || count===0)return null;
      return {g,mats,parts};
    }
    try {
      for(const mesh of new Set(sources)) {
        const info=inspect(mesh);
        if(!info){stats.skipped++;continue;}
        const local=new THREE.Matrix4().multiplyMatrices(inverse,mesh.matrixWorld);
        const geometry=info.g.index?info.g.toNonIndexed():info.g.clone();
        geometry.applyMatrix4(local); geometry.computeBoundingBox();
        const centre=geometry.boundingBox.getCenter(new THREE.Vector3());
        if(![centre.x,centre.y,centre.z].every(Number.isFinite)) {
          geometry.dispose();stats.skipped++;continue;
        }
        const names=Object.keys(geometry.attributes).sort();
        const signature=names.map(n=>`${n}:${geometry.attributes[n].itemSize}`).join(',');
        const tile=`${Math.floor(centre.x/cellSize)},${Math.floor(centre.z/cellSize)}`;
        for(const part of info.parts) {
          const material=info.mats[part.materialIndex];
          const key=[tile,material.uuid,signature,mesh.castShadow,mesh.receiveShadow,mesh.renderOrder].join('|');
          let bucket=buckets.get(key);
          if(!bucket) {
            bucket={material,names,arrays:Object.fromEntries(names.map(n=>[n,[]])),
              sizes:Object.fromEntries(names.map(n=>[n,geometry.attributes[n].itemSize])),
              count:0,castShadow:mesh.castShadow,receiveShadow:mesh.receiveShadow,renderOrder:mesh.renderOrder};
            buckets.set(key,bucket);
          }
          for(let i=part.start;i<part.start+part.count;i+=3) {
            if(bucket.count+3>maxVertices)flush(bucket);
            for(const name of names) {
              const attr=geometry.attributes[name], out=bucket.arrays[name];
              for(let k=i*attr.itemSize;k<(i+3)*attr.itemSize;k++)out.push(attr.array[k]);
            }
            bucket.count+=3;
          }
          stats.sourceDraws++;
          stats.vertices+=part.count;
        }
        geometry.dispose();accepted.push(mesh);
      }
      for(const bucket of buckets.values())flush(bucket);
    } catch(error) {
      group.traverse(obj=>obj.geometry?.dispose());
      throw error; // no sources have been hidden yet: publication is atomic
    }
    stats.sourceMeshes=accepted.length; stats.batchDraws=group.children.length;
    scene.add(group);
    accepted.forEach(mesh=>{mesh.visible=false;});
    let disposed=false;
    function dispose() {
      if(disposed)return;disposed=true;
      accepted.forEach(mesh=>{mesh.visible=true;});
      if(group.parent)group.parent.remove(group);
      group.traverse(obj=>obj.geometry?.dispose());
    }
    function flush(bucket) {
      if(!bucket.count)return;
      const geometry=new THREE.BufferGeometry();
      for(const name of bucket.names) {
        geometry.setAttribute(name,new THREE.Float32BufferAttribute(bucket.arrays[name],bucket.sizes[name]));
        bucket.arrays[name]=[];
      }
      geometry.computeBoundingBox();geometry.computeBoundingSphere();
      const mesh=new THREE.Mesh(geometry,bucket.material);
      mesh.castShadow=bucket.castShadow;mesh.receiveShadow=bucket.receiveShadow;mesh.renderOrder=bucket.renderOrder;
      group.add(mesh);bucket.count=0;
    }
    return {group,stats:Object.freeze(stats),dispose};
  }
  const api={create};
  if(typeof module==='object'&&module.exports)module.exports=api;
  root.SkylineStaticBatches=api;
})(globalThis);
