// Synthetic local-browser regression. Never connect this harness to production.
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=new URL(process.env.DNF_GM_E2E_BASE||'http://127.0.0.1:8766');
if(base.protocol!=='http:'||!['127.0.0.1','localhost','[::1]'].includes(base.hostname))throw Error('Loopback-only fixture URL required');
await mkdir('outputs',{recursive:true});
const browser=await chromium.launch({...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),headless:true,args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
const id='a'.repeat(32),old='20261001-synthetic-old-package-0123456789abcdef0123456789abcdef';let state='preview',lost=true;
const preview={operation_id:id,expires_at:Date.now()/1000+240,preview:{items:[{name:old,allocated_bytes:120*2**20,entries:15}],reason:'清理合成旧版本',atomic:false,note:'仅删除所选旧GM产物，多目录可能部分完成；不会清理游戏、备份或日志。'}};
await page.route('**/*',route=>new URL(route.request().url()).origin===base.origin?route.continue():route.abort());
await page.route('**/dnf-gm/api/v1/**',async route=>{const req=route.request(),p=new URL(req.url()).pathname.split('/api/v1')[1];calls.push({method:req.method(),path:p});let d;
if(p==='/auth/methods')d={totp_required:false};else if(p==='/auth/me')d={csrf:'fixture',username:'admin'};else if(p==='/overview')d={counts:{accounts:2,characters:2,online_accounts:1},server:{fresh:true,services:{}},enabled_writes:[]};
else if(p==='/operations-dashboard'){await route.fulfill({status:503,json:{detail:'本次仅测试合成清理界面，不连接生产'}});return}
else if(p==='/audit')d={items:[],page:1};
else if(p===`/operations/${id}`)d={operation_id:id,action:'cleanup-release',status:'queued',preview:preview.preview,result:{state:'queued'},cleanup:{result:{state:'needs_review',items:[{name:old,state:'partial_or_unknown'}]}}};
else if(p==='/release-cleanups')d={state:'ok',items:[{name:old,eligible:true,allocated_bytes:120*2**20,entries:15},{name:'20261104-current-fixture',eligible:false,reason:'protected_release'},{name:'20261103-rollback-fixture',eligible:false,reason:'protected_release'}]};
else if(p==='/release-cleanups/preview'){if(req.postDataJSON().names.join()!==old)throw Error('wrong targets');d=preview}
else if(p===`/release-cleanups/${id}/confirm`){if(req.postDataJSON().confirmation!=='删除旧GM产物')throw Error('wrong phrase');state='queued';if(lost){lost=false;await route.abort('connectionfailed');return}throw Error('unexpected duplicate confirmation')}
else if(p===`/release-cleanups/${id}`)d={...preview,status:state==='preview'?'preview':'queued',result:state==='queued'?null:{state:'needs_review',reason:'deletion_failed',items:[{name:old,state:'partial_or_unknown'}]},dispatch_present:true,retry_dispatch_allowed:false};
else throw Error('Unexpected mock route '+p);
await route.fulfill({json:d});});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(new URL('/dnf-gm/',base).href);await page.locator('nav').getByRole('button',{name:'运维诊断',exact:true}).click();
 const area=page.locator('.release-cleanup');await area.getByRole('heading',{name:'受控旧GM产物清理'}).waitFor();
 await area.getByRole('button',{name:'预览所选旧版本清理',exact:true}).click();await area.locator('#cleanup-reason-error').waitFor();
 if(!await area.getByRole('checkbox',{name:'清理版本 20261104-current-fixture',exact:true}).isDisabled())throw Error('current selectable');
 await area.evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));await page.screenshot({path:'outputs/DNF-GM-受控清理-桌面-20261104.png',fullPage:false});
 await page.setViewportSize({width:390,height:844});await area.evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));await page.waitForTimeout(100);await page.screenshot({path:'outputs/DNF-GM-受控清理-手机-20261104.png',fullPage:false});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('mobile overflow');
 await area.getByRole('checkbox',{name:'清理版本 '+old,exact:true}).check();await area.locator('#cleanup-reason').fill('清理合成旧版本');await area.getByRole('button',{name:'预览所选旧版本清理',exact:true}).click();
 await area.getByRole('button',{name:'确认清理一次',exact:true}).click();await area.getByRole('alert').filter({hasText:'请输入“删除旧GM产物”'}).waitFor();
 await area.locator('#cleanup-confirmation').fill('删除旧GM产物');await area.getByRole('button',{name:'确认清理一次',exact:true}).click();await area.getByText('入队结果待确认；',{exact:false}).waitFor();
 await area.getByRole('button',{name:'查询原清理结果',exact:true}).click();await area.getByText('已审计入队，不代表目录已经删除。',{exact:false}).waitFor();
 state='review';await page.reload();await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.locator('nav').getByRole('button',{name:'运维诊断',exact:true}).click();await area.getByText('可能部分完成，需要人工核对',{exact:false}).waitFor();
 await area.evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));await page.screenshot({path:'outputs/DNF-GM-清理中断恢复-手机-20261104.png',fullPage:false});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('result overflow');
 await page.setViewportSize({width:1440,height:1000});await page.locator('nav').getByRole('button',{name:'操作审计',exact:true}).click();await page.getByLabel('操作编号',{exact:true}).fill(id);await page.getByRole('button',{name:'只查询，不重放',exact:true}).click();await page.locator('.lookup-result').getByText('已审计入队，不代表执行完成',{exact:false}).waitFor();await page.getByRole('button',{name:'前往运维诊断核对清理',exact:true}).click();await page.getByRole('heading',{name:'运行诊断',exact:true}).waitFor();
 const writes=calls.filter(c=>c.method!=='GET');if(writes.length!==2||errors.length)throw Error(JSON.stringify({writes,errors}));console.log(JSON.stringify({ok:true,api_calls:calls.length,synthetic_writes:writes,errors,real_deletions:0,desktop_and_mobile:true}));
}finally{await browser.close()}
