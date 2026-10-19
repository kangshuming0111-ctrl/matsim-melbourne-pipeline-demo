const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto(process.argv[2]||'http://127.0.0.1:8000/',{waitUntil:'networkidle'});
 const actual=await page.evaluate(()=>({
   nullDuration:formatDurationValue(null),nullDistance:formatDistanceValue(null),
   nullDelta:formatTimeDelta(null),zeroDuration:formatDurationValue(0),
   nullPercent:relativeDeltaPercent(90,null),zeroPercent:relativeDeltaPercent(0,90),
   neutral:deltaClass(null),
   verdict:comparisonVerdict({mode_changes:[],baseline:{avg_trip_time_seconds:90},proposal:{avg_trip_time_seconds:null}})
 }));
 assert.equal(actual.nullDuration,'无有效数据');assert.equal(actual.nullDistance,'无有效数据');
 assert.equal(actual.nullDelta,'无有效数据');assert.equal(actual.zeroDuration,'0 秒');
 assert.equal(actual.nullPercent,null);assert.equal(actual.zeroPercent,null);
 assert.equal(actual.neutral,'delta-neutral');assert.match(actual.verdict.title,/无法比较/);
 // This is a renderer fixture, not a claimed simulation result. Isolate unrelated
 // 3D/workbench services so the actual production table renderer is exercised.
 await page.evaluate(async()=>{
  renderIfLineComparison=()=>{};ImpactWorkbench.open=()=>{};PlanningCases.open=()=>{};
  await showResult({run_id:'measurement_renderer_fixture',sim_output_subdir:'fixture_sim',
   person_count:2,total_trips:2,num_iterations:1,first_iteration:0,last_iteration:0,first_score:0,last_score:0,
   mode_rows:[{mode:'car',count:2,share:1,avg_time_label:'无有效数据',avg_time_seconds:null,avg_distance_m:null,
    time_quality:{valid:0,missing:1,invalid:1},distance_quality:{valid:0,missing:2,invalid:0}}]});
 });
 const rendered=await page.locator('#modeTableBody').innerText();
 assert.match(rendered,/无有效数据/);assert.match(rendered,/有效 0 \/ 缺失 1 \/ 非法 1/);
 assert.doesNotMatch(rendered,/0 米/);
 console.log(JSON.stringify({status:'passed',formatter_assertions:8,renderer_assertions:3,rendered}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
