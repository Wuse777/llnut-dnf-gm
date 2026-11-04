/** Loopback-only, read-only synthetic UI/API check; no production data. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.DNF_GM_BROWSER_URL||'http://127.0.0.1:8766/dnf-gm/';assert(['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname));
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/economy';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const uid=900001,op='a'.repeat(32),account={uid,accountname:'合成统计账号',cera:1100,cera_point:0,mileage:0,login_status:0,channel:0};let failSummary=false;
const report={note:'仅GM发放统计，不是全服经济流水',generated_at:1793800000,coverage:{state:'partial',reward_audits:4,projected:3,complete:2,incomplete:1,unprojected:1},totals:[{metric:'cera',issued:'9007199254740993',deducted:'30',net:'9007199254740963'},{metric:'gold',issued:'1000000000',deducted:'0',net:'1000000000'}],daily:[{day:'2026-11-05',metric:'cera',issued:'100',deducted:'30',net:'70'}],targets:[{target_uid:uid,operations:2}],items:[{item_id:990001,pvf_sha256:'a'.repeat(64),item_name:'合成材料',quantity:'4294967294',operations:2}],templates:[{template_id:1,template_version:2,operations:1}],reasons:[{reason:'合成问题补偿',operations:2}],sources:[{source:'manual',operations:1},{source:'schedule',operations:1}]};
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const req=route.request(),url=new URL(req.url()),p=url.pathname.split('/api/v1')[1];calls.push({path:p,method:req.method(),query:url.search});let d,status=200;
 if(req.method()!=='GET'){errors.push('Unexpected mutation');status=500;d={detail:'Unexpected write'}}
 else if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:1,characters:1,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/economy/summary'){d=report;if(failSummary){status=503;d={detail:'合成查询超时，未返回部分总计'}}}
 else if(p==='/economy/operations')d={upper:10,next_before:url.searchParams.get('before')==='0'?8:null,items:[{operation_id:op,audit_id:9,target_uid:uid,charac_no:uid,action:'currency',source:'manual',reason:'合成补偿',complete:1,created_at:'2026-11-04T16:00:00',values:[{metric:'cera',item_id:0,pvf_sha256:'',amount:'100'}]}]};
 else if(p==='/economy/backlog')d={note:'领取仅是数据库标记',coverage:{batches:2,incomplete_batches:1,unrecorded:'2',missing_mail_ledgers:1},states:[{receipt_state:'record_missing',records:1,gold:'0',quantity:'2'},{receipt_state:'unclaimed_marker',records:1,gold:'1000000000',quantity:'2'}],oldest:[{operation_id:op,target_uid:uid,charac_no:uid,character_name:'合成角色',created_at:'2026-11-04T16:00:00',postal_id:1,item_id:990001,quantity:2,gold:1000000000}]};
 else if(p==='/economy/compensation')d={note:'仅为核对线索，不自动撤销奖励',items:[{case_id:'b'.repeat(32),uid,title:'合成问题',compensation_count:2,matches_in_window:1}],has_more:false};
 else if(p==='/operations/'+op)d={operation_id:op,status:'committed',action:'currency',preview:{target:account},result:{before:1000,after:1100,currency:'cera'}};
 else if(p==='/accounts')d={items:[account]};
 else if(p==='/accounts/'+uid)d=account;
 else if(p==='/characters')d={items:[]};
 else if(p==='/support/cases')d={items:[],has_more:false};
 else if(p==='/support/profiles/'+uid)d={uid,revision:0,notes:'',tags:[],target:account};
 else{errors.push('Unexpected '+p);status=500;d={detail:'Unexpected route'}}
 await route.fulfill({status,json:d});
});
const button=name=>page.getByRole('button',{name,exact:true});
async function nav(name){if(page.viewportSize().width<768)await button('打开导航').click();await page.locator('nav').getByRole('button',{name,exact:true}).click()}
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(base);await nav('发放统计');await page.getByText('9,007,199,254,740,993',{exact:true}).waitFor();await page.getByText(/不是所选范围完整总计/).waitFor();
 assert.equal(calls.filter(c=>c.path==='/economy/backlog').length,0);
 await page.getByLabel('统计账号 UID',{exact:true}).fill('bad');await button('查询统计').click();await page.getByText('账号 UID 须为正整数，留空查看全部',{exact:true}).waitFor();assert.equal(calls.filter(c=>c.path==='/economy/summary').length,1);await page.getByLabel('统计账号 UID',{exact:true}).fill('');
 await page.screenshot({path:output+'/desktop-summary.png',fullPage:false});
 await button('物品排行').click();await page.getByText('4,294,967,294 件 · 2 笔',{exact:true}).waitFor();await button('礼包版本').click();await page.getByText('礼包 #1 · v2',{exact:true}).waitFor();await button('操作原因').click();await page.getByText('合成问题补偿',{exact:true}).waitFor();
 await button('操作明细').click();await button('查看原操作').click();await page.locator('#operation-lookup').getByText('余额变更 · 数据库已提交',{exact:true}).waitFor();
 await page.getByLabel('只看大额操作',{exact:true}).check();await page.getByLabel('货币筛选阈值',{exact:true}).fill('12345');await button('刷新操作明细').click();await page.waitForFunction(()=>document.querySelector('.report-body').textContent.includes('12,345'));
 assert(calls.some(c=>c.path==='/economy/operations'&&c.query.includes('currency_threshold=12345')));
 await button('下一页明细').click();await page.getByText('第 2 页',{exact:true}).waitFor();assert(calls.some(c=>c.path==='/economy/operations'&&c.query.includes('before=8&upper=10')));
 const href=await page.getByRole('link',{name:'导出明细（NDJSON）'}).getAttribute('href');assert(href.startsWith('/dnf-gm/api/v1/economy/export?'));assert(!href.includes('large='));
 await button('邮件积压').click();await page.getByText('游戏记录缺失（未知）',{exact:true}).waitFor();await page.setViewportSize({width:390,height:844});await page.screenshot({path:output+'/mobile-backlog.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await button('补偿核对').click();await button('查看玩家问题').click();await page.getByRole('heading',{name:'玩家问题工作台'}).waitFor();await page.getByLabel('账号备注',{exact:true}).waitFor();assert(calls.some(c=>c.path==='/support/profiles/'+uid));
 await nav('发放统计');await button('接收账号').click();const targetResponse=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/accounts/'+uid));await button('查看此玩家').click();await targetResponse;await page.getByRole('heading',{name:'角色与管理历史'}).waitFor();assert(calls.some(c=>c.path==='/accounts/'+uid));
 await nav('发放统计');await page.locator('.metric-cards').waitFor();failSummary=true;await button('查询统计').click();await page.getByText('合成查询超时，未返回部分总计',{exact:true}).waitFor();assert.equal(await page.locator('.metric-cards').count(),0);await page.screenshot({path:output+'/mobile-timeout.png',fullPage:false});
 assert.deepEqual(errors,[]);assert(calls.every(c=>c.method==='GET'));console.log(JSON.stringify({ok:true,synthetic:true,only_get:true,exact_large_numbers:true,partial_coverage:true,trace_links:true,desktop_mobile:true,no_fake_totals_on_error:true}));
}finally{await browser.close()}
