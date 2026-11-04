/** Local synthetic schedules. Never sends a real announcement or reward. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.DNF_GM_BROWSER_URL||'http://127.0.0.1:8766/dnf-gm/';
assert(['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname));
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/schedules';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1050},timezoneId:'America/New_York'}),calls=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
const id='d'.repeat(32);let record=null,posts=0,previewCount=0;
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.split('/api/v1')[1];calls.push({p,method:request.method()});let d,status=200;
 if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:1,characters:1,online_accounts:1},server:{fresh:true,core_ok:true,mem_available_mib:800,swap_free_mib:4096,services:{}},enabled_writes:[]};
 else if(p==='/schedules')d={items:record?[record]:[],page:1,worker_enabled:true};
 else if(p==='/schedules/preview'){
  previewCount++;const body=request.postDataJSON();record={id,title:body.title,kind:body.kind,request:body,preview:{binding:{reward:{gold:100,rewards:{items:[{id:990002,name:'测试材料',quantity:2147483647}]}}},estimate:{target_count:3,account_count:2},note:'预览仅估算；到期实际触发时冻结名单。超过5分钟的期次跳过，不补发。'},fingerprint:'f'.repeat(64),worker_enabled:true,status:'preview',next_due:body.first_due};d=record;
 }else if(p===`/schedules/${id}/activate`){
  posts++;record={...record,status:'active'};status=503;d={detail:'激活结果待确认；请查询原计划'};
 }else if(p===`/schedules/${id}`)d=record;
 else if(p===`/schedules/${id}/runs`)d={items:record.status==='active'?[{id:'1',status:'skipped',due_at:record.next_due-86400,started_at:record.next_due-86000,last_due_at:record.next_due-86400,skipped_count:1,error_message:'错过超过5分钟的期次，没有补发'}]:[],page:1};
 else if(p===`/schedules/${id}/control`){const {action}=request.postDataJSON();record={...record,status:action==='pause'?'paused':action==='resume'?'active':'cancelled'};d=record;}
 else throw Error('Unexpected synthetic route '+p);
 await route.fulfill({status,json:d});
});
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(base);await page.locator('nav').getByRole('button',{name:'定时运营',exact:true}).click();
 await page.getByLabel('计划类型',{exact:true}).selectOption('notice');await page.getByRole('button',{name:'预览定时公告计划',exact:true}).click();
 await page.getByText('请填写公告原因',{exact:true}).waitFor();assert.equal(previewCount,0);
 await page.getByLabel('计划名称',{exact:true}).fill('周末活动开放公告');await page.getByLabel('定时公告文字',{exact:true}).fill('周末活动即将开始，请前往活动频道。');await page.getByLabel('定时公告原因',{exact:true}).fill('合成界面验收，不连接游戏');
 await page.getByLabel('执行周期',{exact:true}).selectOption('weekly');const first=await page.getByLabel('首次北京时间',{exact:true}).inputValue();
 await page.getByRole('button',{name:'预览定时公告计划',exact:true}).click();
 assert.equal(record.request.first_due,Date.parse(first+':00+08:00')/1000,'Browser timezone must not change Beijing input');
 await page.getByLabel('定时全服确认',{exact:true}).fill('全服公告');await page.getByRole('checkbox',{name:'我确认按此周期重复执行，直到截止、暂停或取消',exact:true}).check();
 await page.screenshot({path:output+'/desktop-preview.png',fullPage:true});await page.getByRole('button',{name:'确认启用计划',exact:true}).click();
 await page.getByText('激活结果待确认。请只查询这个计划编号，不要另建重复计划。',{exact:true}).waitFor();assert.equal(posts,1);
 await page.reload();await page.locator('nav').getByRole('button',{name:'定时运营',exact:true}).click();await page.getByRole('button',{name:'暂停后续期次',exact:true}).waitFor();assert.equal(posts,1);assert.equal(await page.getByRole('button',{name:'确认启用计划',exact:true}).count(),0);
 await page.getByRole('button',{name:'暂停后续期次',exact:true}).click();await page.getByRole('button',{name:'继续后续期次',exact:true}).waitFor();
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:output+'/mobile-plan.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile overflow');
 await page.getByRole('button',{name:'复制为新计划草稿',exact:true}).click();await page.getByLabel('计划类型',{exact:true}).selectOption('reward');await page.getByLabel('角色编号名单',{exact:true}).fill('900001');await page.getByLabel('批量点券',{exact:true}).fill('100');await page.getByLabel('批量发放原因',{exact:true}).fill('合成奖励计划');
 await page.getByRole('button',{name:'预览定时奖励计划',exact:true}).click();await page.getByText('预览时估算 3 个角色、2 个账号；不是本次实际名单。',{exact:true}).waitFor();await page.screenshot({path:output+'/mobile-reward-preview.png',fullPage:true});
 assert.equal(record.request.reward_job.reward.currency_rewards.cera,100);assert.equal(calls.filter(c=>c.p.startsWith('/reward-jobs')).length,0);assert.equal(posts,1);assert.deepEqual(errors,[]);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 console.log(JSON.stringify({ok:true,synthetic:true,activation_posts:posts,preview_posts:previewCount,reload_did_not_replay:true,beijing_in_new_york_browser:true,desktop_mobile:true,errors}));
}finally{await browser.close()}
