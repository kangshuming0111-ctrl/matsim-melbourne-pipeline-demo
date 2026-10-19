/* One building solid and its constrained roof. Same interface in the viewer
 * and regression fixture. Legacy data uses a flat roof, never guessed boxes. */
(function(root) {
  'use strict';
  function create(THREE, building, groundY, materials) {
    const b = building;
    const group = new THREE.Group();
    group.userData.cityBuilding = true;
    group.userData.osmId = b.osm_id;
    const ground = b.points.map(([x,z]) => groundY(x,z));
    const bottom = Math.min(...ground)-0.08, datum = Math.max(...ground);
    const height = Number(b.height);
    const raw = b.architecture;
    const profile = raw && raw.version===1 && raw.total_height===height
      ? raw : {kind:'flat',body_top:height,total_height:height};
    function solid(entry, low, high, mats) {
      const shape = SkylineLanduse.shape(THREE,entry);
      const geom = new THREE.ExtrudeGeometry(shape,{depth:high-low,bevelEnabled:false,curveSegments:1});
      geom.rotateX(Math.PI/2);
      geom.translate(0,high,0);
      if(materials.facade && high>low) {
        // Extrude's world-X/Z UVs stretch windows on diagonal walls. Project
        // each wall onto its own tangent so every orientation has equal bays.
        // Only UVs change: positions, courtyard holes and normals stay intact.
        const bay=materials.facade.bayWidth;
        if(!(bay>0 && Number.isFinite(bay)))throw new Error('Invalid facade bay width');
        const pos=geom.attributes.position,norm=geom.attributes.normal,uv=geom.attributes.uv;
        for(let i=0;i<pos.count;i++)if(Math.abs(norm.getY(i))<.5) {
          const tx=norm.getZ(i),tz=-norm.getX(i);
          uv.setXY(i,(pos.getX(i)*tx+pos.getZ(i)*tz)/bay,(pos.getY(i)-low)/(high-low));
        }
        uv.needsUpdate=true;
      }
      const mesh = new THREE.Mesh(geom,mats);
      mesh.castShadow = false;
      mesh.receiveShadow = true;
      mesh.userData.cityBuilding = true;
      group.add(mesh);
      return mesh;
    }
    const bodyTop = datum+profile.body_top;
    solid(b,bottom,bodyTop,[materials.roof,materials.wall]);
    if (profile.kind==='setback') {
      solid(profile.inset,bodyTop,datum+height,[materials.roof,materials.crown||materials.wall]);
    } else if (profile.kind==='pitched') {
      for (const [vertices, material] of [[profile.faces,materials.roof],[profile.skirts,materials.wall]]) {
        if (!vertices || !vertices.length) continue;
        const geom = new THREE.BufferGeometry();
        geom.setAttribute('position',new THREE.Float32BufferAttribute(vertices.flatMap(
          ([x,y,z]) => [x,bodyTop+y,z]),3));
        geom.computeVertexNormals();
        const mesh = new THREE.Mesh(geom,material);
        mesh.userData.cityBuilding = true;
        group.add(mesh);
      }
    }
    group.userData.roofKind = profile.kind;
    group.userData.topY = datum+height;
    return group;
  }
  root.SkylineBuildings = {create};
})(globalThis);
