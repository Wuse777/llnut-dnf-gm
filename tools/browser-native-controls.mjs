/** Synthetic UI/API fixtures only; never contacts production or a native monitor. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.DNF_GM_BROWSER_URL||'http://127.0.0.1:8766/dnf-gm/';
assert(['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname));
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/native-controls';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
const uid=900001,account={uid,accountname:'合成测试账号',cera:1050,cera_point:0,mileage:0,login_status:1,channel:3011,online:{login_status:1,channel:3011}};
let record=null,n=0,postCount=0;
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.split('/api/v1')[1];calls.push({p,method:request.method()});let d,status=200;
 if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:1,characters:1,online_accounts:1},server:{fresh:true,core_ok:true,mem_available_mib:800,swap_free_mib:4096,services:{}},enabled_writes:[]};
 else if(p==='/accounts')d={items:[account]};
 else if(p==='/accounts/'+uid)d=account;
 else if(p==='/characters')d={items:[{uid,charac_no:900001,charac_name:'合成测试角色',lev:60,delete_flag:0}]};
 else if(p==='/native-controls')d={items:record?[record]:[],page:1};
 else if(p==='/native-controls/preview'){
  const body=request.postDataJSON();n++;
  assert.equal(body.uid,body.action==='native-notice'?null:uid);
  record={operation_id:String(n).repeat(32),action:body.action,status:'preview',expires_at:Date.now()/1000+300,created_at:Date.now()/1000,preview:{...body,target:body.uid?{uid,accountname:account.accountname}:{uid:null,accountname:'全部游戏服务器'}}};d=record;
 }else if(p.endsWith('/confirm')){
  postCount++;assert.equal(p,`/native-controls/${record.operation_id}/confirm`);
  if(n===1){record={...record,status:'dispatching',result:{reason_code:'dispatch_claimed',effect_status:'unknown',ban_status:'not_requested'}};status=503;d={detail:'防重事务结果待确认；请查询原编号'};}
  else {record={...record,status:'not_sent',result:{transport_status:'not_sent',effect_status:'unknown',reason_code:'connection_failed',ban_status:'committed_login_test_pending'}};d=record;}
 }else if(p===`/native-controls/${record?.operation_id}`)d=record;
 else throw Error('Unexpected fixture route '+p);
 await route.fulfill({status,json:d});
});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(base);
 await page.locator('nav').getByRole('button',{name:'游戏内控制',exact:true}).click();
 await page.getByRole('button',{name:'生成控制预览',exact:true}).click();
 await page.locator('#native-reason-error').waitFor();assert.equal(calls.filter(c=>c.p.endsWith('/preview')).length,0);
 await page.locator('#native-message').fill('维护结束，欢迎进入游戏。');await page.locator('#native-reason').fill('合成浏览器验证');
 await page.getByRole('button',{name:'生成控制预览',exact:true}).click();await page.getByRole('checkbox',{name:'我确认发送全服广播，不是单人私信',exact:true}).check();
 await page.screenshot({path:output+'/desktop-notice-preview.png',fullPage:true});
 await page.getByRole('button',{name:'确认执行一次',exact:true}).click();await page.getByText('防重事务结果待确认；请查询原编号',{exact:true}).waitFor();
 assert.equal(postCount,1);assert.equal(await page.getByRole('button',{name:'确认执行一次',exact:true}).count(),0);
 await page.reload();await page.locator('nav').getByRole('button',{name:'游戏内控制',exact:true}).click();
 await page.getByRole('status').filter({hasText:'发送占位已提交'}).waitFor();assert.equal(postCount,1,'Reload must not repeat native confirmation');
 record={...record,status:'sent',result:{transport_status:'sent',effect_status:'unknown',reason_code:'no_application_ack',ban_status:'not_requested'}};
 await page.getByRole('button',{name:'查询原操作结果',exact:true}).click();await page.getByRole('status').filter({hasText:'指令已发送'}).waitFor();
 await page.getByRole('button',{name:'结束查看，返回新操作',exact:true}).click();
 await page.locator('nav').getByRole('button',{name:'账号与角色',exact:true}).click();await page.getByRole('button',{name:'管理 →',exact:true}).click();
 const dismiss=page.getByRole('button',{name:'关闭操作提示',exact:true});if(await dismiss.isVisible())await dismiss.click();
 await page.getByRole('button',{name:'管理此账号的游戏内控制',exact:true}).click();
 assert.equal(await page.locator('#native-action').inputValue(),'native-kick');
 await page.locator('#native-action').selectOption('native-ban-kick');await page.locator('#native-reason').fill('合成封禁联动验证');
 await page.getByRole('button',{name:'生成控制预览',exact:true}).click();await page.getByRole('button',{name:'确认执行一次',exact:true}).click();
 await page.getByText('封禁数据库已提交，重新登录阻断效果未核验；踢下线结果独立显示，不因踢人失败撤销封禁。',{exact:true}).waitFor();
 assert.equal(postCount,2);await page.screenshot({path:output+'/desktop-ban-result.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.locator('.native-controls').scrollIntoViewIfNeeded();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile overflow');
 await page.screenshot({path:output+'/mobile-result.png',fullPage:true});
 await page.getByRole('button',{name:'结束查看，返回新操作',exact:true}).click();await page.locator('#native-action').selectOption('native-notice');
 await page.getByRole('button',{name:'生成控制预览',exact:true}).click();await page.locator('#native-message-error').waitFor();
 await page.screenshot({path:output+'/mobile-validation.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,synthetic:true,confirmation_posts:postCount,reload_did_not_replay:true,desktop_mobile:true,errors}));
}finally{await browser.close()}
