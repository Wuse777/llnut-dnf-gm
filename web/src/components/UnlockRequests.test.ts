// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import UnlockRequests from './UnlockRequests.vue'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
function setup(status=0,opts:{bad?:boolean,lost?:boolean,reauth?:boolean}={}){
 const calls:any[]=[];const requests=[{lock_key:1,state:2,requested_at:1792890000,due_at:1793149200,expired:false},{lock_key:2,state:1,requested_at:1792890000,due_at:null,expired:false},{lock_key:3,state:2,requested_at:1792500000,due_at:1792759200,expired:true}]
 const target={uid:3,accountname:'gm',character:{charac_no:4,charac_name:'测试测试'}}
 vi.stubGlobal('fetch',vi.fn(async(url,options:any={})=>{
 const path=url.toString().replace('/dnf-gm/api/v1',''),body=options.body&&JSON.parse(options.body);calls.push({path,body})
 if(path.endsWith('/unlock-requests'))return new Response(JSON.stringify({uid:3,charac_no:4,login_status:status,delete_flag:0,wait_seconds:259200,write_enabled:!opts.bad,state:opts.bad?'unsupported':'ok',message:'格式不支持',items:opts.bad?[]:requests,collected_at:1792890000}))
 if(path==='/operations/preview')return new Response(JSON.stringify(opts.reauth?{detail:'敏感操作需要重新认证'}:{operation_id:'a'.repeat(32),write_enabled:true,preview:{...body,target,requests:[requests[0]],note:'申请设为到期'}}),{status:opts.reauth?403:200})
 if(path.endsWith('/confirm')){if(opts.lost)throw new Error('连接中断');return new Response(JSON.stringify({state:'requests_expired_pending_game_load'}))}
 return new Response(JSON.stringify({status:'committed',result:{state:'requests_expired_pending_game_load'}}))
 }))
 return {calls,w:mount(UnlockRequests,{props:{characNo:4},attachTo:document.body})}
}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>b.text().includes(text));expect(b).toBeTruthy();await b!.trigger('click');await flushPromises()}
async function select(w:any){await flushPromises();await w.find('[aria-label="选择解锁申请 1"]').setValue(true);await w.find('#unlock-reason').setValue('测试提前解锁');await click(w,'预览提前解锁')}
it('shows pending/locked/expired separately and permits only pending selection',async()=>{const {w,calls}=setup();await flushPromises();expect(w.text()).toContain('已到期，待游戏处理');expect(w.find('[aria-label="选择解锁申请 2"]').attributes('disabled')).toBeDefined();expect(w.find('[aria-label="选择解锁申请 3"]').attributes('disabled')).toBeDefined();expect(calls).toHaveLength(1);w.unmount()})
it.each([1,2,null])('online or unknown %s is read only',async(s)=>{const {w,calls}=setup(s as any);await flushPromises();expect(w.find('[aria-label="选择解锁申请 1"]').attributes('disabled')).toBeDefined();expect(calls).toHaveLength(1);w.unmount()})
it('requires inline reason, then previews exact character and keys, confirms once',async()=>{const {w,calls}=setup();await flushPromises();await w.find('[aria-label="选择解锁申请 1"]').setValue(true);await click(w,'预览提前解锁');expect(w.find('#unlock-reason-error').text()).toContain('原因');expect(calls).toHaveLength(1);await w.find('#unlock-reason').setValue('提前处理');await click(w,'预览提前解锁');expect(calls[1].body).toEqual({action:'equipment-unlock',uid:3,charac_no:4,lock_keys:[1],reason:'提前处理'});expect(w.text()).toContain('测试测试');await click(w,'确认提前处理一次');expect(w.text()).toContain('本后台未验证客户端最终解锁效果');expect(w.text()).not.toContain('确认提前处理一次');expect(calls.filter(x=>x.path.endsWith('/confirm'))).toHaveLength(1);w.unmount()})
it('lost response disables resend, query recovers original operation',async()=>{const {w,calls}=setup(0,{lost:true});await select(w);await click(w,'确认提前处理一次');expect(w.text()).toContain('结果待确认');expect(w.findAll('button').find(b=>b.text().includes('确认提前处理一次'))!.attributes('disabled')).toBeDefined();await click(w,'按原编号查询结果');expect(w.text()).toContain('选中申请已设为到期');expect(calls.filter(x=>x.path.endsWith('/confirm'))).toHaveLength(1);expect(calls.at(-1).path).toBe('/operations/'+'a'.repeat(32));w.unmount()})
it('unsupported archive is visibly blocked',async()=>{const {w}=setup(0,{bad:true});await flushPromises();expect(w.text()).toContain('格式不支持');expect(w.text()).toContain('提前解锁未启用');w.unmount()})
it('requests reauthentication without automatic replay',async()=>{const {w,calls}=setup(0,{reauth:true});await select(w);expect(w.emitted('reauth')).toHaveLength(1);expect(calls.some(x=>x.path.endsWith('/confirm'))).toBe(false);w.unmount()})
