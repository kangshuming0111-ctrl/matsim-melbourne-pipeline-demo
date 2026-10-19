/* Shared, testable ring handling. Never join separate OSM polygon parts. */
(function (root) {
  'use strict';
  function inRing(x, z, points) {
    let inside = false;
    for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
      const [xi, zi] = points[i], [xj, zj] = points[j];
      if (((zi > z) !== (zj > z)) && x < (xj - xi) * (z - zi) / (zj - zi) + xi) inside = !inside;
    }
    return inside;
  }
  function contains(entry, x, z) {
    return inRing(x, z, entry.points || []) && !(entry.holes || []).some(r => inRing(x, z, r));
  }
  function paint(ctx, entry, project) {
    if (!entry.points || entry.points.length < 3) return;
    ctx.beginPath();
    for (const ring of [entry.points, ...(entry.holes || [])]) {
      ring.forEach((p, i) => {
        const [x, y] = project(p);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.closePath();
    }
    ctx.fill('evenodd');
  }
  function shape(THREE, entry) {
    const outer = entry.points.map(p => new THREE.Vector2(p[0], p[1]));
    if (!THREE.ShapeUtils.isClockWise(outer)) outer.reverse();
    const result = new THREE.Shape(outer);
    for (const ring of entry.holes || []) {
      const points = ring.map(p => new THREE.Vector2(p[0], p[1]));
      if (THREE.ShapeUtils.isClockWise(points)) points.reverse();
      result.holes.push(new THREE.Path(points));
    }
    return result;
  }
  root.SkylineLanduse = { contains, paint, shape };
})(globalThis);
