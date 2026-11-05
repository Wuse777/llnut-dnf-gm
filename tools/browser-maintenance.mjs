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
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/maintenance';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const id='a'.repeat(32),fingerprint='b'.repeat(64);let record=null,failLookup=false;
const ready={write_gate:{state:'open'},state:'ok',enabled:true,prepare_supported:true,execute_supported:true,message:'合成完整执行器，仅验证界面，不连接游戏服务器。'};
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const r=route.request(),p=new URL(r.url()).pathname.split('/api/v1')[1];calls.push({path:p,method:r.method()});let d,status=200;
 if(p==='/auth/methods')d={totp_required:false};else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:0,characters:0,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/maintenance')d=ready;
 else if(p==='/maintenance/requests'&&r.method()==='GET')d={items:[],next_cursor:null};
 else if(p==='/maintenance/requests'&&r.method()==='POST'){
  const b=r.postDataJSON();assert.equal(b.request_id,id);assert.equal(JSON.parse(await page.evaluate(()=>sessionStorage.getItem('dnf-gm.maintenance-pending'))).id,id);
  record={operation_id:id,status:'preparing',reason:b.reason,created_at:Date.now()/1000,result:null,can_confirm:false,can_cancel:true,worker_fresh:true,retry_dispatch_allowed:false};d=record;
 }else if(p==='/maintenance/requests/'+id){if(failLookup){await route.abort('failed');return}d=record}
 else if(p==='/maintenance/requests/'+id+'/confirm'){
  const b=r.postDataJSON();assert.equal(b.fingerprint,fingerprint);assert.equal(b.acknowledge_disconnect,true);
  record={...record,status:'queued',can_confirm:false,can_cancel:false};d=record;
 }else if(p==='/maintenance/requests/'+id+'/observe'){record={...record,observation_pending:true};d=record}
 else{errors.push('Unexpected request '+p);status=500;d={detail:'Unexpected fixture request'}}
 await route.fulfill({status,json:d});
});
try{
 await page.addInitScript(()=>{crypto.randomUUID=()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'});
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://127.0.0.1:'+fixture.address().port+'/dnf-gm/');
 await page.locator('nav').getByRole('button',{name:'维护中心',exact:true}).click();await page.getByText(ready.message,{exact:true}).waitFor();
 assert.equal(await page.getByRole('dialog').count(),0);
 await page.getByRole('button',{name:'生成只读维护计划',exact:true}).click();await page.locator('#maintenance-reason-error').waitFor();assert.equal(calls.filter(c=>c.method==='POST').length,0);
 await page.getByLabel('维护原因',{exact:true}).fill('测试角色装备维护（合成界面验收）');await page.getByRole('button',{name:'生成只读维护计划',exact:true}).click();await page.getByRole('heading',{name:'等待只读计划',exact:true}).waitFor();
 record={...record,can_confirm:true,can_observe:true,result:{state:'prepared',fingerprint,expires_at:Date.now()/1000+300,games:['game_fixture'],events:[]}};
 await page.getByRole('button',{name:'只查询原申请',exact:true}).click();await page.getByRole('button',{name:'核对并确认维护',exact:true}).click();
 await page.getByRole('dialog').waitFor();await page.getByRole('button',{name:'确认执行一次',exact:true}).click();await page.locator('#maintenance-ack-error').waitFor();assert.equal(calls.filter(c=>c.method==='POST').length,1);
 await page.screenshot({path:output+'/desktop-confirm.png'});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:output+'/mobile-confirm.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.getByRole('checkbox',{name:'确认断开当前游戏玩家',exact:true}).check();await page.getByRole('button',{name:'确认执行一次',exact:true}).click();
 await page.getByRole('heading',{name:'确认已入队 · 未证明开始',exact:true}).waitFor();assert.equal(calls.filter(c=>c.method==='POST').length,2);
 record={...record,result:{...record.result,state:'game_drained',maintenance_permit:false,events:[{sequence:1,phase:'freeze-intent',at:Date.now()/1000},{sequence:2,phase:'write-gate-frozen',at:Date.now()/1000},{sequence:3,phase:'database-drained',at:Date.now()/1000},{sequence:4,phase:'signal-intent',at:Date.now()/1000,service:'game_fixture'}]}};
 await page.getByRole('button',{name:'只查询原申请',exact:true}).click();await page.getByRole('heading',{name:'游戏退出阶段完成 · 尚非完整维护窗口',exact:true}).waitFor();
 await page.getByText('已记录冻结新写入意向',{exact:true}).waitFor();
 await page.getByText('普通游戏写入已冻结',{exact:true}).waitFor();
 await page.getByText('已核对原数据库普通写事务结束',{exact:true}).waitFor();
 await page.getByRole('button',{name:'核对实际状态（只读）',exact:true}).click();await page.getByText('核对请求已排队；下方如有记录，仅代表上次核对。',{exact:true}).waitFor();
 record={...record,observation_pending:false,result:{...record.result,observation:{state:'observed',collected_at:Date.now()/1000,games:[{service:'game_fixture',state:'down_normal'}]}}};
 await page.getByRole('button',{name:'只查询原申请',exact:true}).click();await page.getByText('game_fixture：进程正常退出（不是存档验收凭据）',{exact:true}).waitFor();
 await page.locator('.maintenance-request-result').scrollIntoViewIfNeeded();await page.screenshot({path:output+'/mobile-result.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 record={...record,result:{...record.result,state:'writers_stopped',events:[...record.result.events,{sequence:5,phase:'writer-stopped',at:Date.now()/1000,service:'auction'}],observation:{state:'observed',collected_at:Date.now()/1000,games:[{service:'game_fixture',state:'down_normal'}],services:[{service:'game_fixture',state:'down_normal'},{service:'auction',state:'down_normal'},{service:'llnut_gate',state:'down_terminated'}]}}};
 await page.getByRole('button',{name:'只查询原申请',exact:true}).click();
 await page.getByText('llnut_gate：组件已按计划由TERM退出（不代表维护完成）',{exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'核对并确认维护',exact:true}).count(),0);
 await page.locator('.maintenance-observation').scrollIntoViewIfNeeded();await page.screenshot({path:output+'/mobile-writers.png'});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 record={...record,result:{...record.result,state:'resuming',events:[...record.result.events,{sequence:6,phase:'window-closed',at:Date.now()/1000},{sequence:7,phase:'restore-start-sent',at:Date.now()/1000,service:'guild'}],observation:{state:'observed',collected_at:Date.now()/1000,services:[{service:'guild',state:'starting'},{service:'channel',state:'restored'}]}}};
 await page.getByRole('button',{name:'只查询原申请',exact:true}).click();
 await page.getByText('guild：组件已启动，正在核对就绪状态',{exact:true}).waitFor();
 await page.getByText('窗口已关闭并完成数据库核对',{exact:true}).waitFor();
 await page.locator('.maintenance-observation').scrollIntoViewIfNeeded();await page.screenshot({path:output+'/mobile-restoring.png'});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 failLookup=true;await page.getByRole('button',{name:'只查询原申请',exact:true}).click();await page.getByText('当前查询尚未确认；下方仅显示上次记录，不代表执行器仍在运行。',{exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'核对并确认维护',exact:true}).count(),0);assert.equal(calls.filter(c=>c.method==='POST').length,3);
 failLookup=false;ready.write_gate={state:'frozen',operation_id:id};await page.reload();await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.locator('nav').getByRole('button',{name:'维护中心',exact:true}).click();await page.getByText('从历史或刷新恢复的申请只做查询，不自动恢复确认按钮。尚未确认的计划可以取消后重新申请。',{exact:true}).waitFor();
 await page.locator('.maintenance-write-gate').getByText('维护冻结中',{exact:true}).waitFor();
 await page.locator('.maintenance-write-gate').scrollIntoViewIfNeeded();await page.screenshot({path:output+'/mobile-write-freeze.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.equal(await page.locator('.maintenance-write-gate button').count(),0);
 assert.equal(calls.filter(c=>c.method==='POST').length,3);assert.equal(errors.length,0,JSON.stringify(errors));
 console.log(JSON.stringify({passed:true,desktop:true,mobile:true,reloadGetOnly:true,databaseAdmissionStages:true,auxiliaryWriterObservation:true,restorationStages:true,postPaths:calls.filter(c=>c.method==='POST').map(c=>c.path),screenshots:output}));
}finally{await browser.close();await new Promise(r=>fixture.close(r))}
