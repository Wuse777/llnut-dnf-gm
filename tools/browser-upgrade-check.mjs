/** Loopback-only synthetic browser verification. Never contacts production. */
import assert from 'node:assert/strict';
import {mkdir,readFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {fileURLToPath} from 'node:url';
import {resolve,sep,extname} from 'node:path';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright');
// Download links can bypass Chromium's Playwright route interception. Serve
// that one synthetic download locally; all other APIs remain intercepted.
const root=fileURLToPath(new URL('../web/dist/',import.meta.url));
const fixture=createServer(async(req,res)=>{
 const url=new URL(req.url,'http://127.0.0.1');
 if(url.pathname==='/dnf-gm/api/v1/compatibility/export'){
  calls.push({path:'/compatibility/export',method:req.method,query:url.search});
  if(req.method!=='GET'||url.searchParams.get('fingerprint')!==fp){res.writeHead(400);res.end();return}
  res.writeHead(200,{'Content-Type':'application/x-ndjson','Content-Disposition':'attachment; filename="gm-upgrade-check.ndjson"'});
  res.end(JSON.stringify({type:'metadata',synthetic:true})+'\n'+JSON.stringify({type:'complete',count:1,can_deploy:false})+'\n');return;
 }
 try{
  if(req.method!=='GET'||!url.pathname.startsWith('/dnf-gm/'))throw Error('not fixture');
  const pathname=resolve(root,decodeURIComponent(url.pathname.slice('/dnf-gm/'.length)||'index.html'));
  if(!pathname.startsWith(root.endsWith(sep)?root:root+sep))throw Error('outside fixture');
  const contents=await readFile(pathname);res.writeHead(200,{'Content-Type':({'.js':'text/javascript','.css':'text/css','.html':'text/html'})[extname(pathname)]||'application/octet-stream'});res.end(contents);
 }catch{res.writeHead(404);res.end()}
});
await new Promise(resolve=>fixture.listen(0,'127.0.0.1',resolve));
const base='http://127.0.0.1:'+fixture.address().port+'/dnf-gm/';
const output=process.env.DNF_GM_BROWSER_OUTPUT||'outputs/upgrade-check';await mkdir(output,{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{}),args:process.env.DNF_GM_BROWSER_NO_SANDBOX==='1'?['--no-sandbox']:[]});
const page=await browser.newPage({viewport:{width:1440,height:1000}}),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
const fp='a'.repeat(64),op='b'.repeat(32);let fail=false,configured=true;
const info={state:'ready',fingerprint:fp,note:'合成升级检查，仅查询，不激活候选版本',current:{pvf_sha256:'c'.repeat(64),configured_image:'sha256:'+'d'.repeat(64),live_aligned:false},candidate:{pvf_sha256:'e'.repeat(64),declared_image:'sha256:'+'f'.repeat(64),image_verified:false},assets:{current:{state:'matched'},candidate:{state:'not_installed'}},recheck:[{capability:'baseline',reason:'实时指纹尚未确认一致'},{capability:'schedules',reason:'需要核对冻结版本，检查不会暂停任务'}],sources:['templates','preferences','policies','schedules','jobs','previews','images','portraits'],scope:'仅静态引用，未验证游戏效果',can_deploy:false};
const row={id:'1:1',label:'合成升级礼包',status:'active',needs_review:true,issues:['pvf_bound_reference'],items:[{id:990002,before:{name:'旧材料',category:'material',stack_limit:99},after:{name:'候选新材料',category:'equipment',stack_limit:0},changes:['name_changed','category_changed','mail_kind_changed','stack_limit_changed'],candidate_image_state:'missing'}],note:'索引堆叠信息不限制发放数量'};
await page.context().route('**/dnf-gm/api/v1/**',async route=>{
 const req=route.request(),url=new URL(req.url()),p=url.pathname.split('/api/v1')[1];calls.push({path:p,method:req.method(),query:url.search});let d,status=200;
 if(req.method()!=='GET'){errors.push('Unexpected write');status=500;d={detail:'Unexpected write'}}
 else if(p==='/auth/methods')d={totp_required:false};
 else if(p==='/auth/me')d={csrf:'synthetic',username:'admin'};
 else if(p==='/overview')d={counts:{accounts:0,characters:0,online_accounts:0},server:{fresh:true,core_ok:true,services:{}},enabled_writes:[]};
 else if(p==='/compatibility')d=configured?info:{state:'not_configured',message:'合成场景：尚未配置候选索引'};
 else if(p==='/compatibility/references'){
  const kind=url.searchParams.get('kind');d={kind,fingerprint:fp,items:[kind==='portraits'?{...row,id:'0:1:0',label:'职业0 · 转职1 · 性别0',status:'ready',items:[],issues:['portrait_mapping_missing']}:{...row,id:kind==='previews'?op:'1:1'}],next_cursor:url.searchParams.get('cursor')?'': 'synthetic.cursor',scope_note:'跨页不是同一个数据库快照'};
  if(fail){status=409;d={detail:'检查目标已变化，请重新检查基线'}}
 }
 else if(p==='/compatibility/export'){
  assert.equal(url.searchParams.get('fingerprint'),fp);
  await route.fulfill({status:200,contentType:'application/x-ndjson',headers:{'Content-Disposition':'attachment; filename="gm-upgrade-check.ndjson"'},body:JSON.stringify({type:'metadata',synthetic:true})+'\n'+JSON.stringify({type:'complete',count:1,can_deploy:false})+'\n'});return;
 }
 else if(p==='/operations/'+op)d={operation_id:op,status:'preview',action:'mail',preview:{target:{uid:900001,accountname:'合成账号'}},result:null};
 else if(p==='/gift-templates')d={items:[]};
 else{errors.push('Unexpected route '+p);status=500;d={detail:'Unexpected route'}}
 await route.fulfill({status,json:d});
});
const button=name=>page.getByRole('button',{name,exact:true});
async function nav(name){if(page.viewportSize().width<768)await button('打开导航').click();await page.locator('nav').getByRole('button',{name,exact:true}).click()}
try{
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto(base);await nav('升级检查');await page.getByText('合成升级礼包',{exact:true}).waitFor();await page.getByText(/当前运行指纹未确认一致/).waitFor();
 await page.getByText('堆叠元数据变化（不限制发放数量）',{exact:true}).waitFor();await page.screenshot({path:output+'/desktop-check.png',fullPage:false});
 await button('下一页引用').click();await page.getByText(/第 2 页/).waitFor();assert(calls.some(c=>c.path==='/compatibility/references'&&c.query.includes('cursor=synthetic.cursor')));
 await button('定时运营').last().click();await page.getByText(/第 1 页/).waitFor();assert(calls.some(c=>c.query.includes('kind=schedules')&&c.query.endsWith('cursor=')));
 await button('未提交预览').click();await button('查询原操作，不执行').click();await page.locator('#operation-lookup').getByText(op,{exact:false}).first().waitFor();assert(calls.some(c=>c.path==='/operations/'+op));
 await button('礼包全部版本').click();await button('前往对应管理页面').click();await page.getByRole('heading',{name:'礼包模板',exact:true}).first().waitFor();assert(calls.some(c=>c.path==='/gift-templates'));
 await nav('升级检查');await page.getByText('合成升级礼包',{exact:true}).waitFor();
 const downloadEvent=page.waitForEvent('download');await page.getByRole('link',{name:'导出全部引用报告（NDJSON）'}).click();const download=await downloadEvent;await download.saveAs(output+'/synthetic-report.ndjson');assert.equal(JSON.parse((await readFile(output+'/synthetic-report.ndjson','utf8')).trim().split('\n').at(-1)).type,'complete');
 await page.setViewportSize({width:390,height:844});await button('职业头像映射').click();await page.getByText(/候选包缺少这一精确职业/).waitFor();await page.screenshot({path:output+'/mobile-portraits.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 fail=true;await button('当前图片映射').click();await page.getByText(/检查目标已变化，请重新检查基线/).waitFor();assert.equal(await page.locator('.upgrade-reference').count(),0);await page.screenshot({path:output+'/mobile-changed.png',fullPage:false});
 configured=false;fail=false;await button('重新检查基线').click();await page.getByText(/合成场景：尚未配置候选索引/).waitFor();assert.equal(await page.locator('a[download]').count(),0);
 assert.deepEqual(errors,[]);assert(calls.every(c=>c.method==='GET'));console.log(JSON.stringify({ok:true,synthetic:true,only_get:true,bound_pagination:true,export:true,trace_navigation:true,desktop_mobile:true,stale_results_cleared:true}));
}finally{await browser.close();await new Promise(resolve=>fixture.close(resolve))}
