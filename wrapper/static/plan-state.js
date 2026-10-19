/* Pure, bounded history. No DOM, storage or simulator dependencies. */
(function(root) {
  'use strict';
  const copy = value => JSON.parse(JSON.stringify(value));
  function create(initial = {operations:[],building_labels:{}}) {
    let past=[], future=[], value=copy(initial), revision=0;
    return {
      read:() => copy(value), revision:() => revision,
      canUndo:() => past.length>0, canRedo:() => future.length>0,
      commit(next) {
        if (JSON.stringify(next)===JSON.stringify(value)) return false;
        past.push(value); if (past.length>50) past.shift();
        value=copy(next); future=[]; revision++; return true;
      },
      undo() { if (!past.length) return false; future.push(value); value=past.pop(); revision++; return true; },
      redo() { if (!future.length) return false; past.push(value); value=future.pop(); revision++; return true; },
    };
  }
  root.CityPlanState={create};
  if (typeof module!=='undefined') module.exports=root.CityPlanState;
})(typeof window==='undefined' ? globalThis : window);
