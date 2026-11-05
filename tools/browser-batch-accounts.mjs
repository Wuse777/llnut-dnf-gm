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
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/batch-accounts';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const now=Date.now()/1000;
const id='a'.repeat(32);let job=null;
await page.context().route('**/dnf-gm/api/v1/**',async route=>{
 const req=route.request(),p=new URL(req.url()).pathname.split('/api/v1')[1];calls.push({path:p,method:req.method(),body:req.method()==='POST'?req.postDataJSON():null});let d,status=200;
 if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:0,characters:0,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/reward-jobs')d={items:job?[job]:[],has_more:false};
 else if(p==='/reward-jobs/preview'){
  const b=req.postDataJSON(),list=b.targets.account_uids||b.targets.account_names;
  if(list.includes('missing')){status=422;d={detail:'名单包含不存在或名称不唯一的账号；请核对账号名单，没有创建任务'}}
  else{const count=new Set(list).size;job={id,status:'preview',worker_enabled:true,write_enabled:true,fingerprint:'f'.repeat(64),target_count:count*2,account_count:count,reason:b.reason,request:b,counts:{pending:count*2},preview:{currency_totals:{cera:String(count*100)},gold_total:'0',rewards:{items:[]},account_selection:{requested_accounts:count,duplicates_removed:list.length-count,input_kind:b.targets.account_uids?'account_uids':'account_names'},note:'合成夹具：不发放游戏奖励'}};d=job}
 }
 else if(p==='/reward-jobs/'+id)d=job;
 else if(p==='/reward-jobs/'+id+'/targets')d={items:[],next_after:null};
 else{errors.push('Unexpected request '+p);status=500;d={detail:'Unexpected request'}}
 await route.fulfill({status,json:d});
});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://127.0.0.1:'+fixture.address().port+'/dnf-gm/');
 await page.locator('nav').getByRole('button',{name:'批量奖励',exact:true}).click();
 await page.getByLabel('目标模式',{exact:true}).selectOption('accounts');await page.getByLabel('批量点券',{exact:true}).fill('100');await page.getByLabel('批量发放原因',{exact:true}).fill('合成账号名单验收');
 await page.getByRole('button',{name:'生成批量预览',exact:true}).click();await page.getByText(/请填写1至5000个账号/).waitFor();assert.equal(calls.filter(c=>c.method==='POST').length,0);
 await page.getByLabel('导入账号名单',{exact:true}).setInputFiles({name:'accounts.txt',mimeType:'text/plain',buffer:Buffer.from('900001\n900001\n900002','utf8')});
 await page.getByRole('status').getByText(/账号名单已读入草稿/).waitFor();assert.equal(calls.filter(c=>c.method==='POST').length,0);
 await page.getByRole('button',{name:'生成批量预览',exact:true}).click();await page.getByText(/账号名单：2 个账号，已去除 1 条重复输入/).waitFor();
 assert.deepEqual(calls.find(c=>c.method==='POST').body.targets,{mode:'accounts',account_uids:[900001,900001,900002]});
 await page.locator('.reward-jobs').screenshot({path:output+'/desktop.png'});
 await page.setViewportSize({width:390,height:844});await page.getByLabel('账号名单类型',{exact:true}).selectOption('name');await page.getByLabel('账号名单',{exact:true}).fill('missing');
 await page.getByRole('button',{name:'生成批量预览',exact:true}).click();await page.getByRole('alert').getByText(/名单包含不存在或名称不唯一/).first().waitFor();
 await page.getByLabel('账号名单',{exact:true}).fill('123\n测试账号');await page.getByRole('button',{name:'生成批量预览',exact:true}).click();await page.getByText(/账号名单：2 个账号，已去除 0 条重复输入/).waitFor();
 assert.deepEqual(calls.filter(c=>c.method==='POST').at(-1).body.targets,{mode:'accounts',account_names:['123','测试账号']});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.locator('.reward-jobs').screenshot({path:output+'/mobile.png'});
 assert.deepEqual(errors,[]);assert(calls.filter(c=>c.method==='POST').every(c=>c.path==='/reward-jobs/preview'));
 console.log(JSON.stringify({ok:true,synthetic:true,desktop_mobile:true,local_import_no_write:true,missing_list_nearby:true,numeric_names_preserved:true,preview_only_no_awards:true}));
}finally{await browser.close();await new Promise(r=>fixture.close(r))}
