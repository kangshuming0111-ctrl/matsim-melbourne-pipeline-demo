const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const url=process.argv[2]||'http://127.0.0.1:8765/portfolio/index.html';
 await page.goto(url,{waitUntil:'networkidle'});
 await page.waitForFunction(()=>window.scrollY===0);
 await page.getByRole('button',{name:'Experiment',exact:true}).click();
 assert.equal(await page.locator('#seedRows tr').count(),3);
 assert.equal(await page.locator('#closureDelta').innerText(),'+7.530 s');
 await page.getByLabel('Experiment seed').selectOption('4711');
 assert.equal(await page.locator('#seedRows tr').count(),1);
 assert.equal(await page.locator('#alternativeDelta').innerText(),'+0.117 s');
 await page.getByRole('button',{name:'Data quality',exact:true}).click();
 for(const [selection,expected] of [['missing','90 s'],['zero','45 s'],['invalid','90 s'],['all','Unavailable']]){
  await page.locator('#measurement').selectOption(selection);assert.equal(await page.locator('#mean').innerText(),expected);
 }
 await page.getByRole('button',{name:'SQL analysis',exact:true}).click();
 for(const [seed,net] of [['4711','+109'],['4712','+91'],['4713','+74']]){
  await page.getByLabel('SQL analysis seed').selectOption(seed);
  assert.equal(await page.locator('#sql-users').innerText(),'6 / 934');
  assert((await page.locator('#sql-net').innerText()).includes(net+' trip-seconds'));
  assert.equal(await page.locator('#sql-existing-value').innerText(),'20.88 s');
  assert.equal(await page.locator('#sql-new-value').innerText(),'42.74 s');
 }
 for(const width of [390,768,1440]){
  await page.setViewportSize({width,height:1000});
  for(const tab of ['Overview','Architecture','Experiment','Data quality','SQL analysis','AI assistant','Evidence']){
   await page.getByRole('button',{name:tab,exact:true}).click();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),`Horizontal overflow: ${tab} at ${width}`);
  }
 }
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',seed_and_metric_checks:4,quality_states:4,sql_seed_checks:12,responsive_sections:21,page_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
