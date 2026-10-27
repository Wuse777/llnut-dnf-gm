// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import App from './App.vue'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
function setup(){
 const calls:any[]=[];let mail:any
 vi.stubGlobal('fetch',vi.fn(async(url,opts:any={})=>{
 const path=url.toString().replace('/dnf-gm/api/v1',''),body=opts.body&&JSON.parse(opts.body);calls.push({path,body})
 let d:any={}
 if(path==='/auth/methods')d={totp_required:false}
 else if(path==='/auth/me')d={csrf:'fixture'}
 else if(path==='/overview')d={counts:{},server:{fresh:false},enabled_writes:['mail']}
 else if(path.startsWith('/accounts?'))d={items:[{uid:3,accountname:'gm'}]}
 else if(path==='/accounts/3')d={uid:3,accountname:'gm'}
 else if(path.startsWith('/characters?'))d={items:[{charac_no:4,charac_name:'测试测试',delete_flag:0}]}
 else if(path.startsWith('/catalog?'))d={items:[{id:1000,name:'材料',category:'material',stack_limit:99,allowed:1,reviewed:1}]}
 else if(path==='/operations/preview'){mail=body;d={operation_id:'a'.repeat(32),write_enabled:true,preview:{...body,target:{uid:3,accountname:'gm',character:{charac_name:'测试测试',charac_no:4}},rewards:{items:body.items}}}}
 else if(path.endsWith('/confirm'))d={operation_id:'a'.repeat(32),action:'mail',gold:mail.gold,postal_ids:[5],state:'database_delivered_not_claimed'}
 else if(path.startsWith('/gift-templates?'))d={items:[{id:9,name:'模板',enabled:true,current_version:1,rewards:{items:[{id:1000,name:'材料',category:'material',quantity:1,stack_limit:99}]}}]}
 return new Response(JSON.stringify(d))
 }))
 return {calls,w:mount(App,{attachTo:document.body})}
}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>b.text()===text||b.find('.nav-text').exists()&&b.find('.nav-text').text()===text);expect(b,'button '+text).toBeTruthy();await b!.trigger('click');await flushPromises()}
async function target(w:any){await flushPromises();await click(w,'账号与角色');await click(w,'管理 →');await click(w,'邮件发放');await w.find('#mail-role').setValue('4');await w.find('#operation-reason').setValue('金币附件测试')}
it('gold-only preview submits amount, shows confirmation, and confirmed result displays it',async()=>{
 const {w,calls}=setup();await target(w);await w.find('#mail-gold').setValue(1000);await click(w,'生成预览 →');expect(calls.find(c=>c.path==='/operations/preview').body).toMatchObject({gold:1000,items:[],charac_no:4});expect(w.find('[data-testid=preview-gold]').text()).toContain('1,000');await click(w,'确认执行一次');expect(w.text()).toContain('金币附件合计：1,000');w.unmount()
})
it('changing gold invalidates prior preview',async()=>{
 const {w}=setup();await target(w);await w.find('#mail-gold').setValue(10);await click(w,'生成预览 →');await w.find('#mail-gold').setValue(11);expect(w.find('[role=dialog]').exists()).toBe(false);expect(w.text()).toContain('旧预览已失效');w.unmount()
})
it.each([-1,1000000001,1.5])('invalid gold %s has inline error and makes no preview request',async(gold)=>{
 const {w,calls}=setup();await target(w);await w.find('#mail-gold').setValue(gold);await click(w,'生成预览 →');expect(w.find('#mail-gold-error').text()).toContain('整数');expect(w.find('#mail-gold').attributes('aria-invalid')).toBe('true');expect(calls.some(c=>c.path==='/operations/preview')).toBe(false);await w.find('#mail-gold').setValue(5);expect(w.find('#mail-gold-error').exists()).toBe(false);w.unmount()
})
it('adding gold clears missing-items feedback without requiring a fake coin item',async()=>{
 const {w}=setup();await target(w);await click(w,'生成预览 →');expect(w.find('#mail-items-error').exists()).toBe(true);await w.find('#mail-gold').setValue(5);expect(w.find('#mail-items-error').exists()).toBe(false);await click(w,'生成预览 →');expect(w.find('[data-testid=preview-gold]').text()).toContain('5');w.unmount()
})
it('item plus gold keeps real items separate, and using template resets supplemental gold',async()=>{
 const {w,calls}=setup();await target(w);await w.find('#mail-gold').setValue(20);await click(w,'加入清单');await click(w,'生成预览 →');expect(calls.find(c=>c.path==='/operations/preview').body).toMatchObject({gold:20,items:[{id:1000,quantity:1}]});await click(w,'返回修改');await click(w,'礼包模板');await click(w,'用于发放');expect((w.find('#mail-gold').element as HTMLInputElement).value).toBe('0');w.unmount()
})
it('unknown commit prevents retry and disables gold editing',async()=>{
 const {w,calls}=setup();await target(w);await w.find('#mail-gold').setValue(10);await click(w,'生成预览 →');const mock=vi.mocked(fetch),original=mock.getMockImplementation()!;mock.mockImplementation(async(url,opts)=>{if(url.toString().endsWith('/confirm'))throw new Error('lost reply');return original(url,opts)});await click(w,'确认执行一次');expect(w.find('#mail-gold').attributes('disabled')).toBeDefined();await click(w,'返回修改');await click(w,'生成预览 →');expect(calls.filter(c=>c.path==='/operations/preview')).toHaveLength(1);w.unmount()
})
