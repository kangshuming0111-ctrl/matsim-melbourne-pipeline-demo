/* One depth-tested road solid sampled from the SAME terrain as the viewer.
 * Elevations are relative metres converted by the scene transform, not DEM Y.
 * Does not touch any terrain, land-use, building or render-target geometry. */
(function(root) {
  'use strict';
  function create(THREE,start,end,width,thickness,material,groundY,h0=0,h1=0,offset=0) {
    const dx=end.x-start.x,dz=end.z-start.z,len=Math.hypot(dx,dz);
    if (!Number.isFinite(len) || len<0.01) return null;
    const n=Math.max(1,Math.ceil(len/0.7)), nx=-dz/len*width/2,nz=dx/len*width/2;
    const pos=[],uv=[],indices=[];
    for (let i=0;i<=n;i++) {
      const t=i/n,x=start.x+dx*t,z=start.z+dz*t,h=h0+(h1-h0)*t+offset;
      for (const bottom of [false,true]) {
        for (const sign of [1,-1]) {
          const px=x+nx*sign,pz=z+nz*sign;
          pos.push(px,groundY(px,pz)+h+(bottom ? -thickness/2 : thickness/2),pz);
          uv.push(t,sign===1 ? 0:1);
        }
      }
      if (i<n) {
        const a=i*4,b=a+4;
        indices.push(a,b,b+1,a,b+1,a+1, a+2,b+3,b+2,a+2,a+3,b+3,
          a,a+2,b+2,a,b+2,b, a+1,b+3,a+3,a+1,b+1,b+3);
      }
    }
    indices.push(0,1,3,0,3,2,n*4,n*4+2,n*4+3,n*4,n*4+3,n*4+1);
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));
    geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));
    geometry.setIndex(indices);geometry.computeVertexNormals();geometry.computeBoundingSphere();
    return new THREE.Mesh(geometry,material);
  }
  root.CityRoadMesh={create};
  if (typeof module!=='undefined') module.exports=root.CityRoadMesh;
})(typeof window==='undefined' ? globalThis : window);
