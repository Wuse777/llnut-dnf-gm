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
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/capabilities';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const choices=[['currency','余额调整'],['mail','物品／金币邮件'],['ban','封禁'],['unban','解封'],['equipment-unlock','装备提前解锁'],['reward','组合奖励'],['batch-reward','批量奖励'],['item-edit','装备编辑'],['item-reclaim','物品回收'],['item-restore','快照恢复'],['native-monitor','原生会话查询'],['native-notice','公告'],['native-kick','踢下线'],['batch-worker','批量执行器'],['schedule-worker','定时执行器'],['release-cleanup','旧GM产物清理']].map(([id,label])=>({id,label}));
const data={checked_at:Date.now()/1000,application:{version:'fixture',source_revision:'abcdef123456',source_state:'recorded'},schema:{state:'ok',versions:Array.from({length:12},(_,i)=>i+1)},policy:{state:'legacy',revision:0,enabled:['mail'],choices,account_scope:'legacy'},scope:{test_only:true},binding:{pvf_sha256:'a'.repeat(64),image_digest:'sha256:'+'b'.repeat(64)},catalog:{state:'matched'},assets:{state:'not_installed'},runtime:{fresh:true,collected_at:Date.now()/1000},note:'配置开关、运行前提与人工验收分开展示，非游戏效果保证。',items:choices.map(c=>({id:c.id,label:c.label,group:'已实现功能',state:'disabled',checks:[{code:'disabled',message:'配置开关未启用'}],verification:{state:'not_recorded'},note:'合成数据：不连接游戏服务器。',destination:'mail'}))};
let receipt=null,dropResponse=false;
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const r=route.request(),p=new URL(r.url()).pathname.split('/api/v1')[1];calls.push({path:p,method:r.method()});let d,status=200;
 if(p==='/auth/methods')d={totp_required:false};else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:0,characters:0,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/capabilities')d=data;
 else if(p==='/capabilities/policy'){
  const b=r.postDataJSON();assert.equal(b.expected_revision,data.policy.revision);receipt={status:'committed',request_id:b.request_id,revision:data.policy.revision+1,enabled:b.enabled};data.policy={...data.policy,state:'managed',revision:receipt.revision,enabled:b.enabled,account_scope:'all'};data.scope.test_only=false;
  data.items=data.items.map(i=>({...i,state:b.enabled.includes(i.id)?'configured':'disabled',checks:[]}));d=receipt;
  if(dropResponse){dropResponse=false;await route.abort('failed');return}
 }else if(p==='/capabilities/policy/requests/'+receipt?.request_id)d=receipt;
 else{errors.push('Unexpected request '+p);status=500;d={detail:'Unexpected fixture request'}}
 await route.fulfill({status,json:d});
});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://127.0.0.1:'+fixture.address().port+'/dnf-gm/');await page.locator('nav').getByRole('button',{name:'功能与版本',exact:true}).click();
 await page.getByRole('button',{name:'全部开放',exact:true}).click();assert.equal(calls.filter(c=>c.method==='POST').length,0);
 await page.getByRole('checkbox',{name:'原生会话查询',exact:true}).uncheck();assert.equal(await page.getByRole('checkbox',{name:'公告',exact:true}).isChecked(),false);assert.equal(await page.getByRole('checkbox',{name:'踢下线',exact:true}).isChecked(),false);
 await page.getByRole('checkbox',{name:'批量奖励',exact:true}).uncheck();assert.equal(await page.getByRole('checkbox',{name:'批量执行器',exact:true}).isChecked(),false);
 await page.getByRole('button',{name:'全部开放',exact:true}).click();assert.equal(calls.filter(c=>c.method==='POST').length,0);
 await page.getByRole('button',{name:'核对并保存权限',exact:true}).click();await page.locator('#capability-reason-error').waitFor();assert((await page.locator('#capability-reason-error').innerText()).includes('至少2'));assert.equal(calls.filter(c=>c.method==='POST').length,0);
 await page.getByLabel('权限调整原因',{exact:true}).fill('合成网页管理员全部开放');await page.getByRole('button',{name:'核对并保存权限',exact:true}).click();await page.getByRole('dialog').waitFor();await page.screenshot({path:output+'/desktop-confirm.png'});
 await page.getByRole('button',{name:'确认保存权限',exact:true}).click();await page.getByText(/权限版本 1 已保存/).waitFor();assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.deepEqual(data.policy.enabled,choices.map(c=>c.id));
 await page.setViewportSize({width:390,height:844});await page.locator('.capability-permissions').scrollIntoViewIfNeeded();await page.screenshot({path:output+'/mobile-permissions.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.getByRole('checkbox',{name:'余额调整',exact:true}).uncheck();await page.getByLabel('权限调整原因',{exact:true}).fill('合成响应丢失测试');await page.getByRole('button',{name:'核对并保存权限',exact:true}).click();dropResponse=true;await page.getByRole('button',{name:'确认保存权限',exact:true}).click();await page.getByText(/结果待确认，请查询原编号/).waitFor();
 await page.reload();await page.getByRole('button',{name:'打开导航',exact:true}).click();await page.locator('nav').getByRole('button',{name:'功能与版本',exact:true}).click();await page.getByRole('button',{name:'查询原权限请求',exact:true}).click();await page.getByText(/已按原编号确认权限版本 2/).waitFor();assert.equal(calls.filter(c=>c.method==='POST').length,2);
 await page.evaluate(()=>document.documentElement.setAttribute('data-theme','dark'));await page.screenshot({path:output+'/mobile-result.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,synthetic:true,web_permissions:true,explicit_confirmation:true,no_write_on_select:true,response_loss_get_only:true,desktop_mobile:true,posts:2}));
}finally{await browser.close();await new Promise(r=>fixture.close(r))}
