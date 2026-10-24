// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import App from './App.vue'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
it('shows password-only login and hides all factor/recovery inputs',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url)=>url.toString().endsWith('/auth/methods')?new Response('{"totp_required":false}'):new Response('{"detail":"请登录"}',{status:401})))
 const w=mount(App);await flushPromises();expect(w.text()).toContain('管理员密码');expect(w.text()).not.toContain('动态验证码');expect(w.find('input[type=password]').exists()).toBe(true);w.unmount()
})
it('escapes player names and shows unknown instead of fabricated healthy state',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url)=>{
  if(url.toString().endsWith('/auth/methods'))return new Response('{"totp_required":false}')
  if(url.toString().endsWith('/auth/me'))return new Response('{"csrf":"fixture","public":true}')
  if(url.toString().endsWith('/overview'))return new Response(JSON.stringify({counts:{accounts:3,characters:2,online_accounts:1},server:{fresh:false,services:{}},enabled_writes:[],test_uids:[]}))
  return new Response('{}')
 }))
 const w=mount(App);await flushPromises();expect(w.text()).toContain('未知');expect(w.text()).toContain('未经完整游戏客户端验收');expect(w.find('aside').exists()).toBe(true);w.unmount()
})

function testApp(){
 const calls:{path:string,method:string,body:any}[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url,opts:any={})=>{
  const path=url.toString().replace('/dnf-gm/api/v1','');const body=opts.body?JSON.parse(opts.body):null;calls.push({path,method:opts.method||'GET',body})
  let d:any={}
  if(path==='/auth/methods')d={totp_required:false}
  else if(path==='/auth/me')d={csrf:'fixture'}
  else if(path==='/overview')d={counts:{accounts:3,characters:2,online_accounts:0},server:{fresh:false},enabled_writes:[],test_uids:[]}
  else if(path.startsWith('/accounts?'))d={items:[{uid:3,accountname:'gm',cera:1050,cera_point:0,login_status:0}]}
  else if(path==='/accounts/3')d={uid:3,accountname:'gm',cera:1050,cera_point:0}
  else if(/^\/characters\/\d+$/.test(path))d={character:{charac_no:Number(path.split('/').pop()),uid:3,charac_name:'示例角色',lev:1},account:{accountname:'gm'},profession:{name:'格斗家',base_name:'格斗家'},wealth:{state:'missing',gold:null},attributes:[],collected_at:1,catalog_state:'ok',equipment:{state:'missing',items:[]},backpack:{state:'missing',items:[]}}
  else if(path.startsWith('/characters?uid='))d={items:[{uid:3,charac_no:4,charac_name:'示例角色',delete_flag:0,lev:1}]}
  else if(path.startsWith('/characters?q='))d={items:[{uid:1,charac_no:2,charac_name:'deleted',delete_flag:1}]}
  else if(path==='/operations/preview')d={operation_id:'a'.repeat(32),write_enabled:true,preview:{target:{uid:3,accountname:'gm'},action:'currency',before:1050,after:1051}}
  else if(path.endsWith('/confirm'))d={operation_id:'a'.repeat(32),state:'database_committed_refresh_client',before:1050,after:1051}
  else if(path==='/operations/'+ 'a'.repeat(32))d={operation_id:'a'.repeat(32),status:'committed',action:'currency',preview:{target:{uid:3}},result:{currency:'cera',before:1050,after:1051}}
  else if(path.startsWith('/catalog?'))d={items:[{id:1000,name:'野草莓',category:'consumable',stack_limit:1000,allowed:1,reviewed:1}]}
  else if(path==='/gift-templates'&&opts.method==='POST')d={id:9,version:1,enabled:true}
  else if(path==='/gift-templates/9'&&opts.method==='PUT')d={id:9,version:2,enabled:true}
  else if(path.startsWith('/gift-templates?'))d={items:[{id:9,name:'测试礼包',enabled:true,current_version:1,rewards:{items:[{id:1000,name:'野草莓',quantity:2,stack_limit:1000,category:'consumable'}]}}]}
  else if(path.startsWith('/audit?'))d={items:[]}
  return new Response(JSON.stringify(d))
 }))
 return {calls,w:mount(App,{attachTo:document.body})}
}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>(b.text()===text||b.find('.nav-text').exists()&&b.find('.nav-text').text()===text));expect(b,'button '+text).toBeTruthy();await b!.trigger('click');const form=b!.element.form;if(form&&b!.element.type==='submit')form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));await flushPromises()}
async function target(w:any){await flushPromises();await click(w,'账号与角色');await click(w,'管理 →')}
it('invalidates preview on amount change and retains original result lookup',async()=>{
 const {w}=testApp();await target(w);await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试');await click(w,'生成预览 →');expect(w.text()).toContain('确认操作预览');await w.find('input[step="1"]').setValue(2);expect(w.text()).not.toContain('确认操作预览');expect(w.text()).toContain('旧预览已失效');w.unmount()
})
it('does not expose another account role as recipient after global role search',async()=>{
 const {w}=testApp();await target(w);await click(w,'按角色搜索');expect(w.text()).toContain('已删除（不可操作）');await click(w,'邮件发放');const role=w.find('select[aria-label="收件角色"]');expect(role!.text()).toContain('示例角色');expect(role!.text()).not.toContain('deleted');w.unmount()
})
it('sends audit UID filter to the documented API instead of unused q',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'操作审计');await w.find('input[aria-label="筛选 UID"]').setValue('3');await click(w,'查询');expect(calls.at(-1)?.path).toBe('/audit?page=1&uid=3');w.unmount()
})
it('rejects blank reason and zero amount before making preview requests',async()=>{
 const {w,calls}=testApp();await target(w);await click(w,'生成预览 →');expect(w.text()).toContain('请填写操作原因');await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('验证');await w.find('input[step="1"]').setValue(0);await click(w,'生成预览 →');expect(w.text()).toContain('非零整数');expect(calls.some(x=>x.path==='/operations/preview')).toBe(false);w.unmount()
})
it('updates template identity after create so next save edits rather than duplicates',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'邮件发放');await click(w,'加入清单');await click(w,'另存为礼包模板');await w.findAll('input').find(i=>i.element.parentElement?.textContent?.includes('模板名称'))!.setValue('测试礼包');await click(w,'创建礼包模板');await click(w,'保存为新版本');expect(calls.filter(x=>x.path==='/gift-templates'&&x.method==='POST')).toHaveLength(1);expect(calls.find(x=>x.path==='/gift-templates/9'&&x.method==='PUT')?.body.expected_version).toBe(1);w.unmount()
})
it('selecting template shows its actual items and editing detaches immutable binding',async()=>{
 const {w}=testApp();await target(w);await click(w,'礼包模板');await click(w,'用于发放');expect(w.text()).toContain('绑定模板 #9 v1');expect(w.text()).toContain('野草莓');expect(w.text()).toContain('#1000');await w.find('input[aria-label="物品数量 1000"]').setValue(3);expect(w.text()).not.toContain('绑定模板 #9 v1');w.unmount()
})
it('shows session restoration rather than flashing the login form',async()=>{
 const {w}=testApp();expect(w.text()).toContain('正在恢复安全会话');expect(w.text()).not.toContain('管理员密码');await flushPromises();expect(w.find('aside').exists()).toBe(true);w.unmount()
})
it('clears old success after changing the next operation draft',async()=>{
 const {w}=testApp();await target(w);await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试');await click(w,'生成预览 →');await click(w,'确认执行一次');expect(w.text()).toContain('最新变更：1,050 → 1,051');await w.find('input[step="1"]').setValue(3);expect(w.text()).not.toContain('最新变更：');w.unmount()
})
it('keeps historical result lookup read-only and logout clears all target data',async()=>{
 const {w,calls}=testApp();await target(w);await click(w,'操作审计');const input=w.find('input[placeholder="32位操作编号；用于断线、重登后核对"]');await input.setValue('a'.repeat(32));await click(w,'只查询，不重放');expect(w.text()).toContain('数据库已提交');expect(calls.at(-1)?.method).toBe('GET');await click(w,'退出登录');expect(w.text()).toContain('管理员密码');expect(w.text()).not.toContain('gm');expect(w.text()).not.toContain('示例角色');w.unmount()
})
it('a rejected reauth request does not incorrectly label the write uncertain',async()=>{
 const {w}=testApp();await target(w);await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试');await click(w,'生成预览 →')
 const mock=vi.mocked(fetch);const original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>url.toString().endsWith('/confirm')?new Response('{"detail":"请先重新认证"}',{status:403}):original(url,opts))
 await click(w,'确认执行一次');expect(w.text()).toContain('敏感操作重新认证');expect(w.text()).not.toContain('提交结果待确认');expect(w.find('[role="dialog"][aria-label="敏感操作重新认证"]').exists()).toBe(true);expect(w.findAll('button').some(b=>b.text()==='确认执行一次')).toBe(false);w.unmount()
})
it('an uncertain network commit blocks replacement previews, without replay',async()=>{
 const {w,calls}=testApp();await target(w);await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试');await click(w,'生成预览 →')
 const mock=vi.mocked(fetch);const original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>{if(url.toString().endsWith('/confirm'))throw new Error('network lost');return original(url,opts)})
 await click(w,'确认执行一次');expect(w.text()).toContain('提交结果待确认');await w.find('input[step="1"]').setValue(8);await click(w,'生成预览 →');expect(w.text()).toContain('禁止新建替代操作');expect(calls.filter(c=>c.path==='/operations/preview')).toHaveLength(1);w.unmount()
})
it('template-only audit entries do not offer an invalid game operation endpoint',async()=>{
 const {w}=testApp();await flushPromises();const mock=vi.mocked(fetch);const original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>url.toString().includes('/audit?')?new Response(JSON.stringify({items:[{id:1,action:'gift-template',operation_id:'b'.repeat(32),created_at:'2026-10-24 01:00:00',reason:'模板版本变更'}]})):original(url,opts));await click(w,'操作审计');expect(w.text()).toContain('礼包模板');expect(w.text()).not.toContain('查询结果 / 邮件领取标记');w.unmount()
})

it('overview has no unrelated operation forms or result lookup',async()=>{
 const {w}=testApp();await flushPromises();expect(w.find('[data-testid="account-operations"]').exists()).toBe(false);expect(w.find('#operation-lookup').exists()).toBe(false);expect(w.find('.queue-panel').exists()).toBe(false);w.unmount()
})
it('mail workbench searches recipient and requires explicit owned role',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'邮件发放');await w.find('[aria-label="查找收件账号"]').setValue('gm');await click(w,'查找账号');expect(calls.at(-1)?.path).toBe('/accounts?q=gm&page=1');await click(w,'gm · UID 3');expect((w.find('select[aria-label="收件角色"]').element as HTMLInputElement).value).toBe('0');await click(w,'加入清单');await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试邮件');await click(w,'生成预览 →');expect(w.text()).toContain('请选择当前账号下未删除的收件角色');expect(calls.some(c=>c.path==='/operations/preview')).toBe(false);await w.find('[aria-label="收件角色"]').setValue('4');await click(w,'生成预览 →');const req=calls.find(c=>c.path==='/operations/preview');expect(req?.body).toMatchObject({action:'mail',uid:3,charac_no:4,items:[{id:1000,quantity:1}],template_id:null});w.unmount()
})
it('mail draft survives visiting template editor and templates never replace recipient draft',async()=>{
 const {w}=testApp();await flushPromises();await click(w,'邮件发放');await click(w,'加入清单');await w.find('[aria-label="物品数量 1000"]').setValue(7);await click(w,'礼包模板');await click(w,'编辑版本');expect((w.find('[aria-label="物品数量 1000"]').element as HTMLInputElement).value).toBe('2');await w.find('[aria-label="物品数量 1000"]').setValue(5);await click(w,'邮件发放');expect((w.find('[aria-label="物品数量 1000"]').element as HTMLInputElement).value).toBe('7');await click(w,'礼包模板');expect((w.find('[aria-label="物品数量 1000"]').element as HTMLInputElement).value).toBe('5');w.unmount()
})
it('creating a separate gift draft does not detach an existing mail template binding',async()=>{
 const {w}=testApp();await flushPromises();await click(w,'礼包模板');await click(w,'用于发放');expect(w.text()).toContain('绑定模板 #9 v1');await click(w,'礼包模板');await click(w,'新建礼包');await click(w,'邮件发放');expect(w.text()).toContain('绑定模板 #9 v1');w.unmount()
})
it('gift item picker is local to template editing and does not add mail attachments',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'礼包模板');await click(w,'新建礼包');await click(w,'添加物品');expect(w.find('[role="dialog"]').attributes('aria-label')).toBe('为礼包选择物品');await w.find('[aria-label="礼包物品搜索"]').setValue('草莓');await click(w,'查询物品');expect(calls.at(-1)?.path).toBe('/catalog?q=%E8%8D%89%E8%8E%93&category=&page=1&allowed_only=1');await click(w,'加入清单');await click(w,'完成选择');expect(w.find('[aria-label="物品数量 1000"]').exists()).toBe(true);await click(w,'邮件发放');expect(w.text()).toContain('还没有添加物品');w.unmount()
})
it('uses positive and negative amount shortcuts without directly writing',async()=>{
 const {w,calls}=testApp();await target(w);await click(w,'扣减 −');await click(w,'10,000');expect((w.find('input[step="1"]').element as HTMLInputElement).value).toBe('-10000');await click(w,'充值 +');expect((w.find('input[step="1"]').element as HTMLInputElement).value).toBe('10000');expect(calls.some(c=>c.method==='POST')).toBe(false);w.unmount()
})
it('currency account operations do not show mail and template editing fields',async()=>{
 const {w}=testApp();await target(w);expect(w.find('[aria-label="收件角色"]').exists()).toBe(false);expect(w.find('.mail-fields').exists()).toBe(false);expect(w.find('#gift-editor').exists()).toBe(false);await click(w,'封禁管理');expect(w.find('[aria-label="处罚操作"]').exists()).toBe(true);expect(w.find('input[step="1"]').exists()).toBe(false);w.unmount()
})
it('rejects stack quantity above reviewed cap before requesting a preview',async()=>{
 const {w,calls}=testApp();await target(w);await click(w,'邮件发放');await w.find('[aria-label="收件角色"]').setValue('4');await click(w,'加入清单');await w.find('[aria-label="物品数量 1000"]').setValue(1001);await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试');await click(w,'生成预览 →');expect(w.text()).toContain('数量和堆叠上限');expect(calls.some(c=>c.path==='/operations/preview')).toBe(false);w.unmount()
})
it('returning from a confirmation never commits and a change invalidates it',async()=>{
 const {w,calls}=testApp();await target(w);await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试');await click(w,'生成预览 →');expect(w.find('[role="dialog"]').exists()).toBe(true);await click(w,'返回修改');expect(w.find('[role="dialog"]').exists()).toBe(false);await w.find('input[step="1"]').setValue(11);expect(calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(0);w.unmount()
})
it('audit result lookup is intentionally GET only and available without a selected account',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'操作审计');await w.find('input[placeholder="32位操作编号；用于断线、重登后核对"]').setValue('a'.repeat(32));await click(w,'只查询，不重放');expect(w.text()).toContain('数据库已提交');expect(calls.at(-1)?.method).toBe('GET');expect(calls.at(-1)?.path).toBe('/operations/'+'a'.repeat(32));w.unmount()
})
it('only appearance preference is written to localStorage, not session or password',async()=>{
 localStorage.clear();const {w}=testApp();await flushPromises();await w.find('[aria-label="界面主题"]').setValue('dark');expect(document.documentElement.dataset.theme).toBe('dark');expect(localStorage.getItem('dnf-gm.theme')).toBe('dark');expect(Object.keys(localStorage)).toEqual(['dnf-gm.theme']);await w.find('[aria-label="界面主题"]').setValue('white');expect(document.documentElement.dataset.theme).toBe('white');w.unmount();localStorage.clear()
})
it('can collapse the sidebar and open mobile navigation without making API writes',async()=>{
 const {w,calls}=testApp();await flushPromises();await w.find('[aria-label="收起侧栏"]').trigger('click');expect(w.classes()).toContain('is-collapsed');await w.find('[aria-label="打开导航"]').trigger('click');expect(w.classes()).toContain('mobile-open');await click(w,'邮件发放');expect(w.classes()).not.toContain('mobile-open');expect(calls.some(c=>c.method==='POST')).toBe(false);w.unmount()
})
it('restores independent catalog and mail search filters on navigation',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'物品索引');await w.find('input[aria-label="搜索条件"]').setValue('草莓');await click(w,'查询');await click(w,'邮件发放');await w.find('input[aria-label="物品搜索"]').setValue('结晶');await click(w,'查询');await click(w,'物品索引');expect(w.find('input[aria-label="搜索条件"]').element.getAttribute('aria-label')).toBe('搜索条件');expect((w.find('input[aria-label="搜索条件"]').element as HTMLInputElement).value).toBe('草莓');expect(calls.at(-1)?.path).toBe('/catalog?page=1&q=%E8%8D%89%E8%8E%93&category=');await click(w,'邮件发放');expect((w.find('input[aria-label="物品搜索"]').element as HTMLInputElement).value).toBe('结晶');w.unmount()
})
it('queried preview remains unsubmitted instead of being shown as a successful write',async()=>{
 const {w}=testApp();await target(w);await w.find('input[placeholder="必填，写入不可删除审计"]').setValue('测试');await click(w,'生成预览 →');const fetchMock=vi.mocked(fetch),original=fetchMock.getMockImplementation()!;fetchMock.mockImplementation(async(url,opts)=>url.toString().endsWith('/operations/'+'a'.repeat(32))?new Response(JSON.stringify({operation_id:'a'.repeat(32),status:'preview',result:null})):original(url,opts));await click(w,'按原编号查询结果');await click(w,'返回修改');expect(w.text()).toContain('尚未提交 / 仅预览');expect(w.find('.result').text()).not.toContain('数据库已提交');w.unmount()
})
it('uses the real API nested online status and channel field rather than legacy names',async()=>{
 const {w}=testApp();await flushPromises();const mocked=vi.mocked(fetch),original=mocked.getMockImplementation()!;mocked.mockImplementation(async(url,opts)=>url.toString().endsWith('/accounts/3')?new Response(JSON.stringify({uid:3,accountname:'gm',cera:1050,cera_point:0,online:{login_status:1,channel:3011}})):url.toString().includes('/accounts?')?new Response(JSON.stringify({items:[{uid:3,accountname:'gm',cera:1050,cera_point:0,login_status:1,channel:3011}]})):original(url,opts));await click(w,'账号与角色');expect(w.text()).toContain('频道 3011');await click(w,'管理 →');expect(w.find('.balance-strip').text()).toContain('在线');await click(w,'邮件发放');expect(w.find('.recipient-context').text()).toContain('在线');w.unmount()
})
it('defaults mail to reviewed sendable items but lets catalog browse every item',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'邮件发放');expect(calls.at(-1)?.path).toContain('allowed_only=1');await w.find('input[type="checkbox"]').setValue(false);expect(calls.at(-1)?.path).not.toContain('allowed_only');await click(w,'物品索引');expect(calls.at(-1)?.path).not.toContain('allowed_only');await w.find('input[type="checkbox"]').setValue(true);expect(calls.at(-1)?.path).toContain('allowed_only=1');w.unmount()
})
it('mail can resolve a character directly while rejecting deleted recipient results',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'邮件发放');await w.find('[aria-label="收件人搜索类型"]').setValue('role');await w.find('[aria-label="查找收件账号"]').setValue('deleted');await click(w,'查找角色');expect(calls.at(-1)?.path).toBe('/characters?q=deleted&page=1');const result=w.find('.recipient-options button');expect(result.text()).toContain('已删除');expect(result.attributes('disabled')).toBeDefined();expect(w.find('.recipient-context').exists()).toBe(false);w.unmount()
})
it('does not treat allowed flag alone as reviewed permission to send',async()=>{
 const {w}=testApp();await flushPromises();const mocked=vi.mocked(fetch),original=mocked.getMockImplementation()!;mocked.mockImplementation(async(url,opts)=>url.toString().includes('/catalog?')?new Response(JSON.stringify({items:[{id:12,name:'未审核',allowed:1,reviewed:0,category:'consumable'}]})):original(url,opts));await click(w,'邮件发放');const itemButton=w.findAll('button').find(b=>b.text()==='不可发放');expect(itemButton?.attributes('disabled')).toBeDefined();expect(w.find('.queue-panel').text()).toContain('还没有添加物品');w.unmount()
})

it('shows missing reason at the field and action, focuses it, and never calls preview',async()=>{
 const {w,calls}=testApp();await target(w);await click(w,'生成预览 →');const input=w.find('#operation-reason')
 expect(input.attributes('aria-invalid')).toBe('true');expect(input.attributes('aria-describedby')).toBe('operation-reason-error');expect(w.find('#operation-reason-error').text()).toContain('请填写操作原因')
 expect(document.activeElement).toBe(input.element);expect(w.find('[data-testid="account-operations"] .submit-error').exists()).toBe(true);expect(w.find('.feedback-toast').attributes('role')).toBe('alert');expect(calls.some(c=>c.path==='/operations/preview')).toBe(false)
 await input.setValue('  ');expect(input.attributes('aria-invalid')).toBe('true');await input.setValue('充值说明');expect(input.attributes('aria-invalid')).toBe('false');expect(w.find('#operation-reason-error').exists()).toBe(false);w.unmount()
})
it('collects amount and reason errors, then focuses the first input in visual order',async()=>{
 const {w,calls}=testApp();await target(w);await w.find('#operation-delta').setValue(0);await click(w,'生成预览 →');expect(w.find('#operation-delta-error').exists()).toBe(true);expect(w.find('#operation-reason-error').exists()).toBe(true);expect(document.activeElement).toBe(w.find('#operation-delta').element);expect(calls.some(c=>c.path==='/operations/preview')).toBe(false);w.unmount()
})
it('locates the missing reason for ban and unban without sending a write request',async()=>{
 const {w,calls}=testApp();await target(w);await click(w,'封禁管理');await click(w,'生成预览 →');expect(w.find('#operation-reason-error').text()).toContain('请填写');await w.find('[aria-label="处罚操作"]').setValue('unban');await click(w,'生成预览 →');expect(document.activeElement).toBe(w.find('#operation-reason').element);expect(calls.some(c=>c.method==='POST')).toBe(false);w.unmount()
})
it('shows mail recipient, attachments and reason problems together and focuses recipient',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'邮件发放');await click(w,'生成预览 →');for(const id of ['mail-recipient','mail-items','operation-reason'])expect(w.find('#'+id+'-error').exists()).toBe(true);expect(document.activeElement).toBe(w.find('#recipient-query').element);expect(calls.some(c=>c.path==='/operations/preview')).toBe(false);w.unmount()
})
it('marks mail role and exact invalid item quantity beside their controls',async()=>{
 const {w}=testApp();await target(w);await click(w,'邮件发放');await click(w,'加入清单');await w.find('#mail-quantity-0').setValue(1001);await w.find('#operation-reason').setValue('test');await click(w,'生成预览 →');expect(w.find('#mail-role-error').exists()).toBe(true);expect(w.find('#mail-quantity-0-error').text()).toContain('堆叠上限');expect(document.activeElement).toBe(w.find('#mail-role').element);await w.find('[aria-label="收件角色"]').setValue('4');await w.find('#mail-quantity-0').setValue(1);expect(w.find('#mail-role-error').exists()).toBe(false);expect(w.find('#mail-quantity-0-error').exists()).toBe(false);w.unmount()
})
it('does not leave new gift save silently disabled; shows name and attachment requirements',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'礼包模板');await click(w,'新建礼包');const button=w.findAll('button').find(b=>b.text()==='创建礼包模板')!;expect(button.attributes('disabled')).toBeUndefined();await click(w,'创建礼包模板');expect(w.find('#gift-name-error').text()).toContain('模板名称');expect(w.find('#gift-items-error').exists()).toBe(true);expect(document.activeElement).toBe(w.find('#gift-name').element);expect(calls.some(c=>c.path==='/gift-templates'&&c.method==='POST')).toBe(false);w.unmount()
})
it('validates audit UID and lookup ID locally beside the query, without invalid requests',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'操作审计');await w.find('#audit-uid').setValue('abc');await click(w,'查询');expect(w.find('#audit-uid-error').exists()).toBe(true);expect(document.activeElement).toBe(w.find('#audit-uid').element);expect(calls.some(c=>c.path.includes('uid=abc'))).toBe(false);await w.find('#lookup-id').setValue('invalid');await click(w,'只查询，不重放');expect(w.find('#lookup-id-error').text()).toContain('32位');expect(document.activeElement).toBe(w.find('#lookup-id').element);expect(calls.some(c=>c.path==='/operations/invalid')).toBe(false);w.unmount()
})
it('requires recipient search text beside that input rather than silently doing nothing',async()=>{
 const {w,calls}=testApp();await flushPromises();await click(w,'邮件发放');await click(w,'查找账号');expect(w.find('#recipient-query-error').exists()).toBe(true);expect(document.activeElement).toBe(w.find('#recipient-query').element);expect(calls.some(c=>c.path==='/accounts?q=&page=1')).toBe(false);w.unmount()
})
it('shows API business failures beside the preview button and in a persistent viewport toast',async()=>{
 const {w,calls}=testApp();await target(w);await w.find('#operation-reason').setValue('test');const mock=vi.mocked(fetch),original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>url.toString().endsWith('/operations/preview')?new Response('{"detail":"余额不足、缺失或超出字段范围"}',{status:422}):original(url,opts));await click(w,'生成预览 →');expect(w.find('.account-workspace .submit-error').text()).toContain('余额不足');expect(w.find('.feedback-toast').text()).toContain('余额不足');expect(calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(0);await w.find('[aria-label="关闭操作提示"]').trigger('click');expect(w.find('.feedback-toast').exists()).toBe(false);w.unmount()
})
it('links server structured validation errors to the corresponding field',async()=>{
 const {w}=testApp();await target(w);await w.find('#operation-reason').setValue('test');const mock=vi.mocked(fetch),original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>url.toString().endsWith('/operations/preview')?new Response(JSON.stringify({detail:[{loc:['body','reason'],type:'string_too_short'}]}),{status:422}):original(url,opts));await click(w,'生成预览 →');expect(w.find('#operation-reason-error').text()).toContain('操作原因');expect(document.activeElement).toBe(w.find('#operation-reason').element);w.unmount()
})
it('never puts a toast over the confirmation or reauthentication modal',async()=>{
 const {w}=testApp();await target(w);await w.find('#operation-reason').setValue('test');await click(w,'生成预览 →');expect(w.find('[role="dialog"]').exists()).toBe(true);expect(w.find('.feedback-toast').exists()).toBe(false);await click(w,'返回修改');await click(w,'重新认证');expect(w.find('[role="dialog"]').attributes('aria-label')).toBe('敏感操作重新认证');expect(w.find('.feedback-toast').exists()).toBe(false);w.unmount()
})

it('keeps server field errors visible until that field changes, not when another input changes',async()=>{
 const {w}=testApp();await target(w);await w.find('#operation-reason').setValue('test');const mock=vi.mocked(fetch),original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>url.toString().endsWith('/operations/preview')?new Response(JSON.stringify({detail:[{loc:['body','reason'],type:'string_too_short'}]}),{status:422}):original(url,opts));await click(w,'生成预览 →');await w.find('#operation-delta').setValue(10);expect(w.find('#operation-reason-error').exists()).toBe(true);await w.find('#operation-reason').setValue('corrected');expect(w.find('#operation-reason-error').exists()).toBe(false);w.unmount()
})
it('keeps confirmation failures beside the modal footer actions and never replays them',async()=>{
 const {w,calls}=testApp();await target(w);await w.find('#operation-reason').setValue('test');await click(w,'生成预览 →');const mock=vi.mocked(fetch),original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>url.toString().endsWith('/confirm')?new Response('{"detail":"明确拒绝操作"}',{status:422}):original(url,opts));await click(w,'确认执行一次');expect(w.find('.modal-footer [data-modal-error]').text()).toContain('明确拒绝操作');expect(document.activeElement).toBe(w.find('.modal-footer [data-modal-error]').element);expect(w.find('.feedback-toast').exists()).toBe(false);expect(calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(0);w.unmount()
})

it('dismissing viewport feedback keeps the persistent field and submit guidance intact',async()=>{
 const {w}=testApp();await target(w);await click(w,'生成预览 →');expect(w.find('.feedback-toast').text()).toContain('请填写操作原因');await w.find('[aria-label="关闭操作提示"]').trigger('click');expect(w.find('.feedback-toast').exists()).toBe(false);expect(w.find('#operation-reason-error').exists()).toBe(true);expect(w.find('.account-workspace .submit-error').exists()).toBe(true);await click(w,'生成预览 →');expect(w.find('.feedback-toast').exists()).toBe(true);w.unmount()
})

it('hides viewport feedback while the mobile navigation is open so it never blocks logout',async()=>{
 const {w}=testApp();await target(w);await click(w,'生成预览 →');expect(w.find('.feedback-toast').exists()).toBe(true);await w.find('[aria-label="打开导航"]').trigger('click');expect(w.find('.feedback-toast').exists()).toBe(false);await w.find('[aria-label="收起移动导航"]').trigger('click');expect(w.find('.feedback-toast').exists()).toBe(true);w.unmount()
})
it('focuses reauthentication failures beside the verification action',async()=>{
 const {w}=testApp();await target(w);await click(w,'重新认证');await w.find('input[type="password"]').setValue('wrong');const mock=vi.mocked(fetch),original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>url.toString().endsWith('/auth/reauth')?new Response('{"detail":"认证失败"}',{status:403}):original(url,opts));await w.find('#reauth-form').trigger('submit');await flushPromises();expect(w.find('.modal-footer [data-modal-error]').text()).toContain('认证失败');expect(document.activeElement).toBe(w.find('.modal-footer [data-modal-error]').element);w.unmount()
})

it('opens character inspector from account and deleted-role search via read-only GET',async()=>{
 const {w,calls}=testApp();await target(w);await click(w,'查看详情');expect(calls.at(-1)?.path).toBe('/characters/4');expect(calls.at(-1)?.method).toBe('GET');await click(w,'关闭详情');expect(w.find('[data-testid=character-detail]').exists()).toBe(false);await click(w,'按角色搜索');await click(w,'查看详情');expect(calls.at(-1)?.path).toBe('/characters/2');expect(calls.some(c=>c.path==='/operations/preview')).toBe(false);w.unmount()
})
