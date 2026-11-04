/** Synthetic UI QA only. Does not contact any production game/API. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.DNF_GM_BROWSER_URL||'http://127.0.0.1:8766/dnf-gm/';
assert(['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname),'Loopback fixture server required');
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/native-session';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
const uid=900001,account={uid,accountname:'合成测试账号',cera:1050,cera_point:0,mileage:0,login_status:1,channel:3011,online:{login_status:1,channel:3011}};
let mode='online';
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.split('/api/v1')[1];calls.push({p,method:request.method()});
 assert.equal(request.method(),'GET','No writes expected');let d;
 if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:1,characters:1,online_accounts:1},server:{fresh:true,core_ok:true,mem_available_mib:800,swap_free_mib:4096,services:{}},enabled_writes:[]};
 else if(p==='/accounts')d={items:[account]};
 else if(p==='/accounts/'+uid)d=account;
 else if(p==='/characters')d={items:[{uid,charac_no:900001,charac_name:'合成测试角色',lev:60,delete_flag:0}]};
 else if(p==='/online/'+uid+'/live')d={uid,database:{record:{login_status:1,channel:3011}},native:{uid,state:mode,observed_at:mode==='unknown'?null:await page.evaluate(()=>Date.now()/1000),reason:mode==='unknown'?'原生查询超时；不能据此判断离线':'原生服务返回有效会话状态'}};
 else throw Error('Unexpected fixture route '+p);
 await route.fulfill({json:d});
});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.clock.install();await page.goto(base);
 await page.locator('nav').getByRole('button',{name:'账号与角色',exact:true}).click();await page.getByRole('button',{name:'管理 →',exact:true}).click();
 const dismiss=page.getByRole('button',{name:'关闭操作提示',exact:true});if(await dismiss.isVisible())await dismiss.click();
 const section=page.getByRole('region',{name:'原生在线会话核对'});
 await section.waitFor();assert.equal(calls.filter(c=>c.p.endsWith('/live')).length,0);
 await section.getByRole('button',{name:'查询实时状态',exact:true}).click();await section.getByText('原生会话在线',{exact:true}).waitFor();
 await page.screenshot({path:output+'/desktop.png',fullPage:true});
 await page.clock.fastForward(16000);await section.getByText('实时状态未知',{exact:true}).waitFor();
 assert.equal(calls.filter(c=>c.p.endsWith('/live')).length,1,'No background query allowed');
 mode='offline';await section.getByRole('button',{name:'查询实时状态',exact:true}).click();await section.getByText('原生会话离线',{exact:true}).waitFor();await section.getByText('登录表记录为在线',{exact:true}).waitFor();
 await page.setViewportSize({width:390,height:844});await section.scrollIntoViewIfNeeded();await page.screenshot({path:output+'/mobile.png',fullPage:true});await section.screenshot({path:output+'/mobile-panel.png'});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile viewport overflow');
 mode='unknown';await section.getByRole('button',{name:'查询实时状态',exact:true}).click();await section.getByText('实时状态未知',{exact:true}).waitFor();await section.getByText('原生查询超时；不能据此判断离线',{exact:true}).waitFor();
 assert.equal(await section.getByText('原生会话离线',{exact:true}).count(),0);
 assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,synthetic:true,live_query_gets:calls.filter(c=>c.p.endsWith('/live')).length,writes:0,desktop_mobile:true,errors}));
}finally{await browser.close()}
