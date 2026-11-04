/** Loopback-only synthetic UI/API contract checks. Never production game writes. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.DNF_GM_BROWSER_URL||'http://127.0.0.1:8766/dnf-gm/';
assert(['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname));
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/support';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],calls=[];
page.on('pageerror',e=>errors.push(e.message));
const uid=900001,cid='a'.repeat(32),op='b'.repeat(32);
const account={uid,accountname:'合成测试账号',cera:1050,cera_point:0,mileage:0,login_status:0,channel:0};
const character={uid,charac_no:uid,charac_name:'合成测试角色',lev:60,delete_flag:0};
let profile={uid,revision:0,notes:'',tags:[],target:account},record=null,events=[],links=[],lost=false,lastReceipt=null;
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const r=route.request(),u=new URL(r.url()),p=u.pathname.split('/api/v1')[1],method=r.method(),body=method==='GET'?null:r.postDataJSON();calls.push({p,method,body});let d,status=200;
 const receipt=(kind)=>({request_id:body.idempotency_key,kind,state:'management_committed',uid,...(kind==='player-profile'?{}:{case_id:cid,revision:record.revision})});
 if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:1,characters:1,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:['currency','mail','reward']};
 else if(p==='/accounts')d={items:[account]};
 else if(p==='/accounts/'+uid)d=account;
 else if(p==='/characters')d={items:[character]};
 else if(p==='/support/profiles/'+uid){
  if(method==='PUT'){assert.equal(body.expected_revision,profile.revision);profile={...profile,...body,revision:profile.revision+1};lastReceipt=receipt('player-profile');d=lastReceipt;if(lost){status=503;d={detail:'合成提交响应中断，请查询原编号'}}}else d=profile;
 }else if(p==='/support/cases'&&method==='GET')d={items:record?[record]:[],has_more:false,page:1};
 else if(p==='/support/cases'&&method==='POST'){
  assert.equal(body.uid,uid);assert.equal(body.charac_no,uid);record={...body,case_id:cid,target:{...account,character},status:'open',revision:1,compensation_count:0,updated_at:Date.now()/1000};d=receipt('case-create');
 }else if(p==='/support/cases/'+cid&&method==='GET')d={case:record,events,links,events_has_more:false,links_has_more:false};
 else if(p==='/support/cases/'+cid&&method==='PUT'){
  assert.equal(body.expected_revision,record.revision);record={...record,...body,revision:record.revision+1};d=receipt('case-update');
 }else if(p==='/support/cases/'+cid+'/entries'){
  assert.equal(body.expected_revision,record.revision);record.revision++;events.unshift({revision:record.revision,kind:'case-comment',note:body.note,details:{},created_at:Date.now()/1000});d=receipt('case-comment');
 }else if(p==='/support/cases/'+cid+'/links'){
  assert.equal(body.operation_id,op);assert.equal(body.relation,'reference');assert.equal(body.expected_revision,record.revision);record.revision++;links.push({operation_id:op,relation:'reference',status:'committed',action:'mail'});d=receipt('case-link');
 }else if(p.startsWith('/support/requests/')){assert.equal(p,'/support/requests/'+lastReceipt.request_id);d=lastReceipt;}
 else if(p==='/operations/preview'){
  assert.equal(body.support_case_id,cid);assert.equal(body.uid,uid);assert.equal(body.charac_no,uid);assert.equal(body.delta,100);d={operation_id:op,write_enabled:true,preview:{action:'currency',target:{...account,character},before:1050,after:1150,support_case:record}};
 }else{errors.push('Unexpected '+method+' '+p);status=500;d={detail:'Unexpected synthetic route'}}
 await route.fulfill({status,json:d});
});
const button=(name)=>page.getByRole('button',{name,exact:true});
async function workbench(){if(page.viewportSize().width<768)await button('打开导航').click();await page.locator('nav').getByRole('button',{name:'玩家问题',exact:true}).click();await page.getByRole('heading',{name:'玩家问题工作台'}).waitFor()}
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(base);
 await page.locator('nav').getByRole('button',{name:'账号与角色',exact:true}).click();await button('管理 →').click();await button('备注与问题记录').click();await page.getByLabel('账号备注',{exact:true}).fill('仅合成问题，无真实玩家');await page.getByLabel('玩家标签',{exact:true}).fill('待核查，测试');await button('保存账号备注与标签').click();await page.getByText(/管理记录已保存/).waitFor();
 await button('建立问题记录').click();await button('保存新问题').click();await page.getByText('请填写问题标题',{exact:true}).waitFor();assert.equal(calls.filter(c=>c.p==='/support/cases'&&c.method==='POST').length,0);
 await page.getByLabel('问题标题',{exact:true}).fill('合成邮件排查');await page.getByLabel('问题描述',{exact:true}).fill('仅检查界面与接口');await page.getByLabel('问题角色编号',{exact:true}).fill(String(uid));await button('保存新问题').click();await button('创建余额纠正草稿').waitFor();
 await page.getByLabel('处理记录',{exact:true}).fill('已核对原操作');await button('追加处理记录').click();await page.locator('.support-entry').getByText('已核对原操作',{exact:true}).waitFor();
 await page.getByText('关联已有操作（不会重新执行）',{exact:true}).click();await page.getByLabel('关联操作编号',{exact:true}).fill(op);await page.getByLabel('关联说明',{exact:true}).fill('原投递参考，不是补偿');await button('关联原操作').click();await button('查询此原操作').waitFor();
 await page.getByText('编辑问题内容或处理状态',{exact:true}).click();await page.getByLabel('修改问题状态',{exact:true}).selectOption('in_progress');await page.getByLabel('状态修改说明',{exact:true}).fill('正在排查');await button('保存问题修改').click();await page.waitForFunction(()=>document.querySelector('[aria-label="状态修改说明"]').value==='');
 await page.getByLabel('账号备注',{exact:true}).fill('未保存的合成草稿');await page.locator('nav').getByRole('button',{name:'服务器概览',exact:true}).click();await page.getByText('还有未保存的账号备注或新问题草稿，请先保存或放弃修改再离开工作台',{exact:true}).waitFor();assert.equal(await page.getByRole('heading',{name:'玩家问题工作台'}).count(),1);await button('放弃备注修改').click();
 await page.screenshot({path:output+'/desktop.png',fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:output+'/mobile.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile overflow');
 assert.equal(calls.filter(c=>c.method==='POST'&&c.p.startsWith('/operations')).length,0,'Workbench must not grant rewards');
 await button('创建余额纠正草稿').click();await page.locator('#operation-delta').fill('100');await button('生成预览 →').click();await page.getByText(/关联问题/).first().waitFor();assert.equal(calls.filter(c=>c.p==='/operations/preview').length,1);assert.equal(calls.filter(c=>c.p.endsWith('/confirm')).length,0);
 await button('返回修改').click();await page.getByRole('dialog',{name:'确认操作预览'}).waitFor({state:'hidden'});await workbench();await page.getByLabel('账号备注',{exact:true}).fill('合成响应丢失');lost=true;await button('保存账号备注与标签').click();await page.getByText('保存结果待确认',{exact:true}).waitFor();const writes=calls.filter(c=>c.method!=='GET').length;
 await page.reload();await workbench();await page.getByText(/管理记录已保存/).waitFor();assert.equal(calls.filter(c=>c.method!=='GET').length,writes,'Reload must not replay save');assert.deepEqual(errors,[]);
 console.log(JSON.stringify({ok:true,synthetic:true,profile_case_comment_link_status:true,compensation_preview:true,no_reward_confirm:true,reload_no_replay:true,desktop_mobile:true}));
}finally{await browser.close()}
