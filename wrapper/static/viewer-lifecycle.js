/* Visibility owns scheduling, not simulation/domain state. A disposed loader
 * can never publish an old scene, even if its transport ignores abort. */
(function(root) {
  'use strict';
  function deferred({load,ready,failed,release}) {
    const controller=new AbortController();
    let cancelled=false,pending=null,value=null;
    function ensure() {
      if(cancelled)return Promise.resolve(null);
      if(pending)return pending;
      pending=Promise.resolve().then(()=>load(controller.signal)).then(result=>{
        if(cancelled){if(result)release(result);return null;}
        value=result;ready(result);return result;
      }).catch(error=>{
        if(!cancelled&&error.name!=='AbortError')failed(error);
        pending=null;return null;
      });
      return pending;
    }
    return {ensure,dispose(){if(cancelled)return;cancelled=true;controller.abort();if(value)release(value);value=null;}};
  }
  function frameLoop({request,cancel,draw,state=()=>{}}) {
    let visible=false,disposed=false,frame=null,last=null;
    function invalidate() {
      if(disposed||!visible||frame!==null)return;
      state('running');frame=request(tick);
    }
    function tick(time) {
      frame=null;if(disposed||!visible)return;
      const dt=last===null?0:Math.min(.1,Math.max(0,(time-last)/1000));last=time;
      const moving=draw(dt)!==false;
      if(moving)invalidate();
      else if(frame===null&&visible&&!disposed){last=null;state('idle');}
    }
    function setVisible(next) {
      if(disposed||visible===next)return;visible=next;last=null;
      if(visible)invalidate();
      else {if(frame!==null)cancel(frame);frame=null;state('suspended');}
    }
    return {setVisible,invalidate,dispose(){if(disposed)return;setVisible(false);disposed=true;state('disposed');}};
  }
  function observeVisibility(element,changed) {
    const doc=element.ownerDocument,win=doc.defaultView;
    let last=null;
    const check=()=>{
      const r=element.getBoundingClientRect();
      const visible=!doc.hidden&&r.width>0&&r.height>0&&r.bottom>0&&r.right>0&&r.top<win.innerHeight&&r.left<win.innerWidth;
      if(last!==visible){last=visible;changed(visible);}
    };
    const observer=win.IntersectionObserver?new win.IntersectionObserver(check):null;
    observer?.observe(element);
    doc.addEventListener('visibilitychange',check);
    // Also covers fixed-position studio opening/closing and layout resize.
    win.addEventListener('scroll',check,{passive:true});win.addEventListener('resize',check);
    check();
    return {check,dispose(){observer?.disconnect();doc.removeEventListener('visibilitychange',check);win.removeEventListener('scroll',check);win.removeEventListener('resize',check);}};
  }
  const api={deferred,frameLoop,observeVisibility};
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.ViewerLifecycle=api;
})(typeof window==='object'?window:globalThis);
