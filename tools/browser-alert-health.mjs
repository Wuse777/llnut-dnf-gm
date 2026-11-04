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
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/alert-health';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const now=Date.now()/1000;
let mode='ok';
const data={state:'ok',updated_at:now,notification:{state:'retrying',last_attempt:now,last_accepted:null,next_attempt:now+60},pending_count:2,rules:[['collector','状态采集失效'],['gm','GM接口不可用'],['core','游戏或核心服务异常'],['memory','可用内存不足'],['swap','Swap剩余不足'],['disk','磁盘剩余不足']].map(([key,label])=>({key,label,active:['gm','memory'].includes(key),observed:key==='core'?'unknown':(['gm','memory'].includes(key)?'bad':'healthy'),pending_confirmation:false,changed_at:now,started_at:now})),history:[{id:'a'.repeat(32),key:'memory',label:'可用内存不足',state:'firing',occurred_at:now}]};
await page.context().route('**/dnf-gm/api/v1/**',async route=>{const req=route.request(),url=new URL(req.url()),p=url.pathname.split('/api/v1')[1];calls.push({path:p,method:req.method()});let d,status=200;
 if(req.method()!=='GET'){errors.push('Unexpected write');status=500;d={detail:'Unexpected write'}}
 else if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:0,characters:0,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/operations-dashboard')d={state:'unavailable',fresh:false,current:{fresh:false},message:'合成夹具：未启用资源历史',points:[],events:[],storage:null,releases:null,protection:null,application:{version:'fixture',schema_versions:[],schema_state:'unknown'}};
 else if(p==='/release-cleanups')d={enabled:false,state:'disabled',message:'合成夹具：清理未启用'};
 else if(p==='/alerts'){d={...data,state:mode};if(mode==='error'){status=503;d={detail:'合成告警读取失败'}}if(mode==='unavailable')d={state:'unavailable'}}
 else{errors.push('Unexpected route '+p);status=500;d={detail:'Unexpected route'}}
 await route.fulfill({status,json:d});
});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://127.0.0.1:'+fixture.address().port+'/dnf-gm/');await page.locator('nav').getByRole('button',{name:'运维诊断',exact:true}).click();
 const section=page.locator('.alert-health');await section.getByText('通知失败或未确认，等待重试',{exact:false}).waitFor();await section.scrollIntoViewIfNeeded();await page.screenshot({path:output+'/desktop.png',fullPage:false});
 await page.setViewportSize({width:390,height:844});await section.getByText('最近变化记录（最多100条）',{exact:true}).click();await section.scrollIntoViewIfNeeded();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await section.screenshot({path:output+'/mobile.png'});
 mode='stale';await section.getByRole('button',{name:'刷新告警',exact:true}).click();await section.getByText(/告警报告已过期/).waitFor();assert.equal(await section.getByText('最近观测正常',{exact:true}).count(),0);await section.screenshot({path:output+'/mobile-stale.png'});
 mode='error';await section.getByRole('button',{name:'刷新告警',exact:true}).click();await section.getByRole('alert').getByText('合成告警读取失败',{exact:true}).waitFor();assert.equal(await section.locator('article').count(),0);
 mode='unavailable';await section.getByRole('button',{name:'刷新告警',exact:true}).click();await section.getByText(/观察器未启用或报告不可读/).waitFor();
 assert.deepEqual(errors,[]);assert(calls.every(x=>x.method==='GET'));console.log(JSON.stringify({ok:true,synthetic:true,desktop_mobile:true,only_get:true,stale_not_healthy:true,error_clears_old:true}));
}finally{await browser.close();await new Promise(r=>fixture.close(r))}
