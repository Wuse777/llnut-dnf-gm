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
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/item-cards';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const uid=900001,account={uid,accountname:'合成测试账号',cera:1050,cera_point:0,mileage:0,login_status:0,channel:0,online:{login_status:0,channel:0}};
const character={uid,charac_no:uid,charac_name:'合成测试角色',lev:60,delete_flag:0,job:0,grow_type:1,max_fatigue:156};
const item={id:990001,name:'合成测试 · 勇者长剑',category:'equipment',single_item:true,quantity:1,level:60,sendable:true,policy_state:'trial',policy_reason:'合成浏览器夹具，未实际投递',pvf_sha256:'a'.repeat(64)};
const stored={...item,slot:0,slot_label:'武器',type:1,type_name:'装备',enhancement:3,forge:0,durability:33,amplify_type:0,amplify_value:0,orb_id:0,sealed_raw:0,empty:false};
const role={character,account,profession:{name:'剑魂',base_name:'鬼剑士',note:'合成名称'},account_online:{login_status:0,channel:0},wealth:{state:'ok',gold:10000,revival_coin_raw:3},attributes:[],collected_at:Date.now()/1000,catalog_state:'ok',snapshot_note:'合成浏览器快照，非真实玩家',equipment:{state:'ok',slot_count:12,items:[stored]},backpack:{state:'ok',slot_count:12,items:[]}};
await page.route('**/dnf-gm/api/v1/**',async route=>{
 const r=route.request(),p=new URL(r.url()).pathname.split('/api/v1')[1];calls.push({path:p,method:r.method()});let d,status=200;
 if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:1,characters:1,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/catalog')d={items:[item],metadata:{pvf_sha256:item.pvf_sha256},total:1};
 else if(p==='/accounts')d={items:[account]};
 else if(p==='/accounts/'+uid)d=account;
 else if(p==='/characters')d={items:[character]};
 else if(p==='/characters/'+uid)d=role;
 else{errors.push('Unexpected request '+p);status=500;d={detail:'Unexpected fixture request'}}
 await route.fulfill({status,json:d});
});
async function noOverflow(){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);for(const modal of await page.locator('.modal').all()){assert.equal(await modal.evaluate(el=>el.scrollWidth>el.clientWidth+1),false)}}
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://127.0.0.1:'+fixture.address().port+'/dnf-gm/');
 await page.locator('nav').getByRole('button',{name:'物品索引',exact:true}).click();
 const inspect=page.getByRole('button',{name:'查看物品详情 '+item.id+' '+item.name,exact:true});await inspect.click();
 await page.getByRole('dialog',{name:'物品详情 · #'+item.id}).waitFor();await noOverflow();await page.screenshot({path:output+'/desktop-item.png'});
 await page.keyboard.press('Escape');await inspect.waitFor();assert.equal(await inspect.evaluate(el=>el===document.activeElement),true);
 await page.locator('nav').getByRole('button',{name:'账号与角色',exact:true}).click();await page.getByRole('button',{name:'管理 →',exact:true}).click();await page.getByRole('button',{name:'查看详情',exact:true}).click();await page.getByRole('group',{name:'角色详情分组',exact:true}).getByRole('button',{name:/装备与仓储/}).click();await page.getByRole('tab',{name:/穿戴装备/}).click();await page.getByRole('button',{name:'格子视图',exact:true}).click();
 await page.locator('button.inventory-slot').click();await page.getByRole('region',{name:'选中物品详情',exact:true}).waitFor();await page.screenshot({path:output+'/desktop-inventory.png'});
 await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog',{name:'角色详情',exact:true}).count(),1);assert.equal(await page.getByRole('region',{name:'选中物品详情',exact:true}).count(),0);
 await page.setViewportSize({width:390,height:844});await page.locator('button.inventory-slot').click();
 const drawer=page.getByRole('dialog',{name:'物品详情 · #'+item.id,exact:true});await drawer.waitFor();assert.equal(await page.getByRole('dialog').count(),2);await noOverflow();
 const rect=await drawer.boundingBox();assert(Math.abs(rect.y+rect.height-844)<2,'Drawer must dock to viewport bottom');await page.screenshot({path:output+'/mobile-drawer.png'});
 await page.keyboard.press('Shift+Tab');assert.equal(await drawer.locator('button').last().evaluate(el=>el===document.activeElement),true);await page.keyboard.press('Tab');assert.equal(await drawer.locator('button').first().evaluate(el=>el===document.activeElement),true);
 await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog',{name:'角色详情',exact:true}).count(),1);assert.equal(await page.locator('button.inventory-slot').evaluate(el=>el===document.activeElement),true);
 await page.locator('button.inventory-slot').click();await page.evaluate(()=>document.documentElement.setAttribute('data-theme','dark'));await page.screenshot({path:output+'/mobile-dark.png'});
 await page.setViewportSize({width:1440,height:1000});await page.getByRole('region',{name:'选中物品详情',exact:true}).waitFor();assert.equal(await page.locator('.item-drawer').count(),0);await noOverflow();
 assert.equal(calls.filter(c=>c.method!=='GET').length,0);assert.deepEqual(errors,[]);
 console.log(JSON.stringify({ok:true,synthetic:true,read_only_no_writes:true,nested_escape:true,focus_trap:true,viewport_transition:true,desktop_mobile:true,errors}));
}finally{await browser.close();await new Promise(r=>fixture.close(r))}
