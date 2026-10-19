const assert = require('node:assert/strict');
const {bind} = require('../wrapper/static/studio-viewport.js');

function fixture(withViewport = true) {
  const host = Object.assign(new EventTarget(), {innerWidth:1200, innerHeight:800});
  if (withViewport) host.visualViewport = Object.assign(new EventTarget(), {
    width:600, height:420, offsetLeft:170, offsetTop:140
  });
  const frames = new Map(), styles = new Map(), classes = new Set();
  let next = 0, resizes = 0;
  host.requestAnimationFrame = fn => {frames.set(++next, fn); return next;};
  host.cancelAnimationFrame = id => frames.delete(id);
  const stage = {
    style:{setProperty:(k,v)=>styles.set(k,v),removeProperty:k=>styles.delete(k)},
    classList:{toggle:(k,on)=>on?classes.add(k):classes.delete(k),remove:k=>classes.delete(k)}
  };
  const cleanup = bind(stage, () => resizes++, host);
  const flush = () => {const pending = [...frames.values()];frames.clear();pending.forEach(fn=>fn());};
  return {host, styles, classes, frames, cleanup, flush, resizes:()=>resizes};
}
const f = fixture();
assert.equal(f.styles.get('--studio-width'), '600px');
assert.equal(f.styles.get('--studio-top'), '140px');
assert(f.classes.has('studio-compact'));
assert.equal(f.resizes(), 1);
f.host.visualViewport.width = 950;
for (let i=0;i<5;i++) f.host.visualViewport.dispatchEvent(new Event('resize'));
assert.equal(f.frames.size, 1, 'Coalesce viewport events into one frame');
f.flush();
assert.equal(f.styles.get('--studio-width'), '950px');
assert(!f.classes.has('studio-compact'));
assert.equal(f.resizes(), 2);
f.host.visualViewport.offsetLeft = 250;
f.host.visualViewport.dispatchEvent(new Event('scroll')); f.flush();
assert.equal(f.styles.get('--studio-left'), '250px');
assert.equal(f.resizes(), 2, 'Pan changes position without resizing the scene');
f.host.visualViewport.height = 0;
f.host.visualViewport.dispatchEvent(new Event('resize')); f.flush();
assert.equal(f.styles.get('--studio-height'), '420px', 'Ignore transient zero viewport');
f.host.visualViewport.height = 300;
f.host.visualViewport.dispatchEvent(new Event('resize'));
f.cleanup(); f.cleanup(); f.flush();
assert.equal(f.frames.size, 0);
assert.equal(f.styles.size, 0);
assert.equal(f.classes.size, 0);
f.host.visualViewport.dispatchEvent(new Event('resize'));
f.host.dispatchEvent(new Event('resize'));
assert.equal(f.frames.size, 0, 'Exit removes all listeners, including a pending update');
assert.equal(f.resizes(), 2);
const fallback = fixture(false);
assert.equal(fallback.styles.get('--studio-width'), '1200px');
assert.equal(fallback.styles.get('--studio-left'), '0px');
fallback.host.innerWidth = 375;
fallback.host.dispatchEvent(new Event('resize')); fallback.flush();
assert(fallback.classes.has('studio-compact'));
assert.equal(fallback.styles.get('--studio-width'), '375px');
fallback.cleanup();
console.log('Studio viewport: lifecycle, resize, pan, cleanup and fallback passed');
