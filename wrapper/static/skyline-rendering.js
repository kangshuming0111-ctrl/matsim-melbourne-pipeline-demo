/* Rendering setup shared by the city viewer and the browser depth regression.
 * Keep the bundled Three.js r128 API here; do not change scene/data geometry.
 */
(function () {
  'use strict';

  function createCamera(aspect) {
    // The closest allowed orbit is 50 units and the terrain clearance is 2.4.
    // A 1-unit near plane preserves close inspection without spending almost
    // all depth precision on the empty space immediately in front of the eye.
    return new THREE.PerspectiveCamera(34, aspect, 1, 1800);
  }

  function createPipeline(renderer, scene, camera) {
    const size = renderer.getSize(new THREE.Vector2());
    // r128's default offscreen target requests DEPTH_COMPONENT16, even when
    // the canvas has 24-bit depth. Packed depth+stencil uses D24S8 on WebGL1/2
    // and avoids the shared DepthTexture ownership in r128 target.clone().
    const target = new THREE.WebGLRenderTarget(size.x, size.y, {
      minFilter: THREE.LinearFilter,
      magFilter: THREE.LinearFilter,
      format: THREE.RGBAFormat,
      depthBuffer: true,
      stencilBuffer: true,
    });
    target.texture.name = 'skyline.sceneColor';
    const composer = new THREE.EffectComposer(renderer, target);
    // With an explicit target, r128 starts at pixelRatio=1, unlike its
    // default constructor. Set this explicitly so retina/resize stay sharp.
    composer.setPixelRatio(renderer.getPixelRatio());
    composer.addPass(new THREE.RenderPass(scene, camera));
    const bloom = new THREE.UnrealBloomPass(size, 0.16, 0.25, 0.82);
    composer.addPass(bloom);

    let disposed = false;
    function dispose() {
      if (disposed) return;
      disposed = true;
      bloom.dispose();
      // r128 does not provide EffectComposer.dispose(), and bloom.dispose()
      // only releases its targets. Release the per-view materials as well.
      for (const material of [bloom.materialHighPassFilter, bloom.compositeMaterial,
        bloom.materialCopy, bloom.basic, ...bloom.separableBlurMaterials,
        composer.copyPass.material]) {
        material.dispose();
      }
      composer.renderTarget1.dispose();
      composer.renderTarget2.dispose();
    }
    return { composer, dispose };
  }

  function keepCameraAboveGround(camera, controls, groundY) {
    if (!groundY) return;
    const minimumY = groundY(camera.position.x, camera.position.z) + 2.4;
    if (camera.position.y >= minimumY) return;
    const rise = minimumY - camera.position.y;
    // Translate eye and target together, preserving the look direction.
    camera.position.y += rise;
    controls.target.y += rise;
  }

  window.SkylineRendering = { createCamera, createPipeline, keepCameraAboveGround };
})();
