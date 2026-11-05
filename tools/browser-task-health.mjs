/** Synthetic loopback-only browser check; no production or webhook traffic. */
import assert from 'node:assert/strict';
import {mkdir,readFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=fileURLToPath(new URL('../web/dist/',import.meta.url));
const fixture=createServer(async(req,res)=>{try{const url=new URL(req.url,'http://127.0.0.1');if(req.method!=='GET'||!url.pathname.startsWith('/dnf-gm/'))throw Error('not fixture');const p=resolve(root,decodeURIComponent(url.pathname.slice('/dnf-gm/'.length)||'index.html'));if(!p.startsWith(root.endsWith(sep)?root:root+sep))throw Error('outside fixture');const body=await readFile(p);res.writeHead(200,{'Content-Type':({'.js':'text/javascript','.css':'text/css','.html':'text/html'})[extname(p)]||'application/octet-stream'});res.end(body)}catch{res.writeHead(404);res.end()}});
await new Promise(r=>fixture.listen(0,'127.0.0.1',r));
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/task-health';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const now=Date.now()/1000;
let mode='attention';const id='a'.repeat(32),other='b'.repeat(32);
await page.context().route('**/dnf-gm/api/v1/**',async route=>{
 const req=route.request(),p=new URL(req.url()).pathname.split('/api/v1')[1];calls.push({path:p,method:req.method()});let d,status=200;
 if(req.method()!=='GET'){errors.push('Unexpected write');status=500;d={detail:'Unexpected write'}}
 else if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:0,characters:0,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/operations-dashboard')d={state:'unavailable',fresh:false,current:{fresh:false},message:'合成夹具',points:[],events:[],storage:null,releases:null,protection:null,application:{version:'fixture',schema_versions:[],schema_state:'unknown'}};
 else if(p==='/release-cleanups')d={enabled:false,state:'disabled'};
 else if(p==='/alerts'||p==='/backup-health')d={state:'unavailable'};
 else if(p==='/task-health'){
  d={write_gate:{state:'frozen'},state:mode,checked_at:now,truncated:mode==='unknown',workers:{rewards:{state:'failing',failures:2},schedules:{state:'disabled',failures:0}},issues:mode==='attention'?[{kind:'reward',id,ordinal:1,code:'uncertain'},{kind:'schedule',id:other,code:'unreconciled'}]:[]};
  if(mode==='error'){status=503;d={detail:'合成任务检查失败'}}
 }
 else if(p.startsWith('/reward-jobs')){
  const job={id,status:'cancelled',counts:{uncertain:1},fingerprint:'f'.repeat(64),target_count:1,account_count:1,reason:'synthetic',request:{targets:{mode:'selected'},account_reward_mode:'once_per_account'},preview:{currency_totals:{},gold_total:'0',rewards:{items:[]}}};
  d=p.includes('/targets')?{items:[],next_after:null}:p==='/reward-jobs'?{items:[job],has_more:false}:job;
 }
 else if(p.startsWith('/schedules')){
  const job={id:other,title:'合成定时计划',status:'active',kind:'reward',next_due:now-130,request:{recurrence:'once',first_due:now-130,reward_job:{targets:{mode:'selected'},account_reward_mode:'once_per_account',reward:{currency_rewards:{}}}},preview:{binding:{reward:{gold:0,rewards:{items:[]}}}},fingerprint:'f'.repeat(64)};
  d=p.endsWith('/runs')?{items:[]}:p==='/schedules'?{items:[job],worker_enabled:false}:job;
 }
 else{errors.push('Unexpected route '+p);status=500;d={detail:'Unexpected route'}}
 await route.fulfill({status,json:d});
});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://127.0.0.1:'+fixture.address().port+'/dnf-gm/');
 async function open(){if(await page.getByRole('button',{name:'打开导航',exact:true}).isVisible())await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.locator('nav').getByRole('button',{name:'运维诊断',exact:true}).click();await page.locator('.task-health').getByRole('button',{name:'刷新任务状态',exact:true}).waitFor()}
 await open();let section=page.locator('.task-health');await section.getByText(/提交结果待核对/).waitFor();await section.getByText(/维护已冻结新奖励和定时触发/).waitFor();await section.scrollIntoViewIfNeeded();await section.screenshot({path:output+'/desktop.png'});
 await page.setViewportSize({width:390,height:844});await section.scrollIntoViewIfNeeded();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await section.screenshot({path:output+'/mobile.png'});
 await section.getByRole('button',{name:'查看原任务',exact:true}).click();await page.getByRole('button',{name:'只核对已取消任务的中断目标（不重发）',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'重新排队未提交目标',exact:true}).count(),0);
 await open();await section.getByRole('button',{name:'查看原计划',exact:true}).click();await page.getByText('合成定时计划',{exact:true}).first().waitFor();assert(calls.some(c=>c.path==='/schedules/'+other));
 await open();mode='unknown';await section.getByRole('button',{name:'刷新任务状态',exact:true}).click();await section.getByText(/列表不完整/).waitFor();assert.equal(await section.getByText(/本次检查未发现/).count(),0);
 mode='error';await section.getByRole('button',{name:'刷新任务状态',exact:true}).click();await section.getByRole('alert').getByText('合成任务检查失败',{exact:true}).waitFor();assert.equal(await section.locator('.task-issues').count(),0);
 assert.deepEqual(errors,[]);assert(calls.every(c=>c.method==='GET'));console.log(JSON.stringify({ok:true,synthetic:true,desktop_mobile:true,only_get:true,original_task_navigation:true,cancelled_no_reissue:true,original_schedule_navigation:true,incomplete_not_clear:true}));
}catch(error){console.error(JSON.stringify({errors,calls,body:await page.locator('body').innerText()}));throw error}finally{await browser.close();await new Promise(r=>fixture.close(r))}
