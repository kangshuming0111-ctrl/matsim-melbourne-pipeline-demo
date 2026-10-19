/* Keep the studio inside the visible viewport, including Safari pinch zoom.
 * Geometry and all dimensions here are CSS pixels, never scene coordinates.
 * bind() owns listeners until its returned cleanup is called on studio exit. */
(function (root) {
  function bind(stage, resized, host = window) {
    const viewport = host.visualViewport;
    let frame = null, stopped = false, previousSize = '';
    function update() {
      frame = null;
      if (stopped) return;
      const width = viewport ? viewport.width : host.innerWidth;
      const height = viewport ? viewport.height : host.innerHeight;
      if (!(width > 0 && height > 0)) return;
      stage.style.setProperty('--studio-left', `${viewport ? viewport.offsetLeft : 0}px`);
      stage.style.setProperty('--studio-top', `${viewport ? viewport.offsetTop : 0}px`);
      stage.style.setProperty('--studio-width', `${width}px`);
      stage.style.setProperty('--studio-height', `${height}px`);
      // A layout-viewport media query does not react to pinch zoom.
      stage.classList.toggle('studio-compact', width <= 760);
      const size = `${width}:${height}`;
      if (size !== previousSize) {
        previousSize = size;
        resized();
      }
    }
    function schedule() {
      if (!stopped && frame === null) frame = host.requestAnimationFrame(update);
    }
    host.addEventListener('resize', schedule);
    if (viewport) {
      viewport.addEventListener('resize', schedule);
      viewport.addEventListener('scroll', schedule);
    }
    update();
    return function unbind() {
      stopped = true;
      host.removeEventListener('resize', schedule);
      if (viewport) {
        viewport.removeEventListener('resize', schedule);
        viewport.removeEventListener('scroll', schedule);
      }
      if (frame !== null) host.cancelAnimationFrame(frame);
      for (const name of ['left', 'top', 'width', 'height']) stage.style.removeProperty(`--studio-${name}`);
      stage.classList.remove('studio-compact');
    };
  }
  root.StudioViewport = { bind };
  if (typeof module !== 'undefined') module.exports = root.StudioViewport;
})(typeof window !== 'undefined' ? window : globalThis);
