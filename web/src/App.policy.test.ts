// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import App from './App.vue'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
function setup(){
 const calls:any[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url,opts:any={})=>{
 const path=url.toString();calls.push({path,body:opts.body&&JSON.parse(opts.body)})
 let data:any={}
 if(path.endsWith('/auth/methods'))data={totp_required:false}
 else if(path.endsWith('/auth/me'))data={csrf:'fixture'}
 else if(path.endsWith('/overview'))data={counts:{accounts:3,characters:2},server:{fresh:false},enabled_writes:[]}
 else if(path.includes('/catalog?'))data={total:125,items:[{id:12,name:'未审核材料',category:'material',stack_limit:100,reviewed:0,allowed:1,sendable:true,supported:true,policy_state:'trial',policy_reason:'管理员允许试发'},{id:13,name:'特殊宠物',category:'special',sendable:false,supported:false,policy_state:'blocked',policy_reason:'特殊类型不能开放'}]}
 else if(path.endsWith('/catalog/policy/preview'))data={operation_id:'a'.repeat(32),preview:{matched:125,affected:123,skipped:2,unchanged:0,policy_revision:1}}
 else if(path.endsWith('/confirm'))data={affected:123,policy_revision:2}
 return new Response(JSON.stringify(data))
 }))
 return {calls,w:mount(App,{attachTo:document.body})}
}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>b.text()===text||b.find('.nav-text').exists()&&b.find('.nav-text').text()===text)!;expect(b,'button '+text).toBeTruthy();await b.trigger('click');await flushPromises()}
it('shows trial status and blocked reason, trial items with reviewed=0 join mailing queue',async()=>{
 const {w}=setup();await flushPromises();await click(w,'物品索引');expect(w.text()).toContain('允许试发、未验证');expect(w.text()).toContain('特殊类型不能开放');expect(w.findAll('button').filter(b=>b.text()==='调整策略').at(1)!.attributes('disabled')).toBeDefined();await click(w,'加入清单');expect(w.text()).toContain('1 条附件已加入邮件草稿');w.unmount()
})
it('batch uses last applied filters, not unsubmitted edits or current page, and refreshes catalogue after commit',async()=>{
 const {w,calls}=setup();await flushPromises();await click(w,'物品索引');await w.find('[aria-label="搜索条件"]').setValue('尚未提交的搜索');await click(w,'批量调整当前筛选（全部 125 项）');await w.find('#policy-reason').setValue('测试完整筛选');await click(w,'预览影响范围');const req=calls.find(c=>c.path.endsWith('/policy/preview'));expect(req.body.filters).toEqual({q:'',category:'',allowed_only:false});expect(req.body.filters.page).toBeUndefined();expect(w.text()).toContain('125');await click(w,'确认变更一次');expect(calls.filter(c=>c.path.includes('/catalog?')).length).toBe(2);expect(w.text()).toContain('尚未进行任何物品发放');w.unmount()
})
