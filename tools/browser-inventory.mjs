/** Synthetic local browser/API contract test, never production/player writes. */
import assert from 'node:assert/strict';
import {mkdir} from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
const base=process.env.DNF_GM_BROWSER_URL||'http://127.0.0.1:8766/dnf-gm/';
assert(['127.0.0.1','localhost','[::1]'].includes(new URL(base).hostname));
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/inventory';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],calls=[];
page.on('pageerror',e=>errors.push(e.message));
const uid=900001,account={uid,accountname:'合成测试账号',cera:1050,cera_point:0,mileage:0,login_status:0,channel:0,online:{login_status:0,channel:0}};
const character={uid,charac_no:900001,charac_name:'合成测试角色',lev:60,delete_flag:0,job:0,grow_type:1,max_fatigue:156};
const item={slot:0,slot_label:'武器',id:990001,name:'合成测试装备',type:1,type_name:'装备',quantity:1,level:60,enhancement:3,forge:0,durability:33,amplify_type:0,amplify_value:0,orb_id:0,sealed_raw:0,quality_raw:4294967295,editable:true,empty:false,lock_key:0};
const role={character,account,profession:{name:'剑魂',base_name:'鬼剑士',note:'合成名称'},account_online:{login_status:0,channel:0},wealth:{state:'ok',gold:10000,revival_coin_raw:3},attributes:[],collected_at:Date.now()/1000,catalog_state:'ok',snapshot_note:'合成浏览器快照，非真实玩家',equipment:{state:'ok',slot_count:12,items:[item]},backpack:{state:'ok',slot_count:12,items:[]}};
let record=null,postCount=0,serial=0;
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const request=route.request(),p=new URL(request.url()).pathname.split('/api/v1')[1];calls.push({p,method:request.method()});let d,status=200;
 if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:1,characters:1,online_accounts:0},server:{fresh:true,core_ok:true,mem_available_mib:800,swap_free_mib:4096,services:{}},enabled_writes:[]};
 else if(p==='/accounts')d={items:[account]};
 else if(p==='/accounts/'+uid)d=account;
 else if(p==='/characters')d={items:[character]};
 else if(p==='/characters/'+uid)d=role;
 else if(p==='/inventory/characters/'+uid+'/equipment/0')d={uid,charac_no:uid,container:'equipment',slot:0,reference:'f'.repeat(64),target:{uid,accountname:account.accountname,character},item,maintenance:{available:true},enabled_actions:['item-edit','item-reclaim','item-restore']};
 else if(p==='/inventory/operations')d={items:record?[record]:[],has_more:false,page:1};
 else if(p==='/inventory/preview'){
  const body=request.postDataJSON();assert.equal(body.uid,uid);assert.equal(body.charac_no,uid);assert.equal(body.container,'equipment');assert.deepEqual(body.changes,{enhancement:12});
  serial++;record={operation_id:String(serial).repeat(32),action:body.action,status:'preview',request:body,preview:{...body,target:{uid,accountname:account.accountname,character},item_name:item.name,before:item,after:{...item,enhancement:12}}};d=record;
 }else if(p.endsWith('/confirm')){
  assert.equal(p,`/inventory/operations/${record.operation_id}/confirm`);postCount++;
  record={...record,status:'executing'};status=503;d={detail:'合成提交结果待确认，请查询原操作编号'};
 }else if(p===`/inventory/operations/${record?.operation_id}`)d=record;
 else {errors.push('Unexpected route '+p);status=500;d={detail:'Unknown synthetic route'}}
 await route.fulfill({status,json:d});
});
async function openRole(){await page.locator('nav').getByRole('button',{name:'账号与角色',exact:true}).click();await page.getByRole('button',{name:'管理 →',exact:true}).click();await page.getByRole('button',{name:'查看详情',exact:true}).click();await page.getByRole('group',{name:'角色详情分组',exact:true}).getByRole('button',{name:/装备与仓储/}).click();await page.getByRole('tab',{name:/穿戴装备/}).click();await page.getByRole('button',{name:'列表视图',exact:true}).click()}
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(base);await openRole();
 await page.locator('.character-items').getByRole('button',{name:'维护此物品',exact:true}).click();
 const panel=page.getByRole('tabpanel',{name:'装备维护',exact:true});await panel.getByRole('heading',{name:'装备与道具维护'}).waitFor();
 await page.getByRole('button',{name:'生成装备操作预览',exact:true}).click();await page.getByText('请填写操作原因',{exact:true}).waitFor();assert.equal(calls.filter(c=>c.p==='/inventory/preview').length,0);
 await page.getByRole('textbox',{name:'强化',exact:true}).fill('12');await page.getByRole('textbox',{name:'装备维护原因',exact:true}).fill('合成属性纠正');
 await page.getByRole('button',{name:'生成装备操作预览',exact:true}).click();await page.getByRole('button',{name:'确认执行装备操作',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'刷新角色存档',exact:true}).isDisabled(),true);
 await page.screenshot({path:output+'/desktop-preview.png',fullPage:false});
 await page.getByRole('button',{name:'确认执行装备操作',exact:true}).click();await page.getByText(/合成提交结果待确认/).waitFor();assert.equal(postCount,1);
 await page.reload();await openRole();await page.getByRole('group',{name:'角色详情分组',exact:true}).getByRole('button',{name:/维护与排查/}).click();await page.getByRole('tab',{name:'装备维护',exact:true}).click();
 await page.getByRole('heading',{name:/执行意向已记录/}).waitFor();assert.equal(postCount,1);assert.equal(await page.getByRole('button',{name:'确认执行装备操作',exact:true}).count(),0);
 record={...record,status:'committed',result:{snapshot_id:record.operation_id}};await page.getByRole('button',{name:'查询原操作结果',exact:true}).click();await page.getByText(/下方角色资料仍是旧快照/).waitFor();
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:output+'/mobile-result.png',fullPage:false});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Mobile document overflow');
 const overflowing=await page.locator('.modal-body').evaluate(el=>el.scrollWidth>el.clientWidth+1);assert.equal(overflowing,false,'Mobile modal overflow');
 await page.getByRole('button',{name:'结束查看',exact:true}).click();await page.getByRole('group',{name:'角色详情分组',exact:true}).getByRole('button',{name:/装备与仓储/}).click();await page.getByRole('tab',{name:/穿戴装备/}).click();await page.getByRole('button',{name:'刷新角色存档',exact:true}).click();
 await page.getByRole('button',{name:'格子视图',exact:true}).click();
 const tiles=page.locator('.inventory-grid button');if(await tiles.count())await tiles.first().click();
 await page.screenshot({path:output+'/mobile-grid.png',fullPage:true});
 assert.equal(postCount,1);assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,synthetic:true,confirmations:postCount,reload_no_replay:true,parent_panel:true,nearby_errors:true,desktop_mobile:true,errors}));
}finally{await browser.close()}
