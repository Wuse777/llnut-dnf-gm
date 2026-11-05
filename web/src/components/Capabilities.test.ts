// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,afterEach,it,expect,vi} from 'vitest'
import Capabilities from './Capabilities.vue'
import {api,ApiError} from '../api'
vi.mock('../api',async()=>{const real=await vi.importActual<typeof import('../api')>('../api');return {...real,api:vi.fn()}})
let wrappers:any[]=[]
function sample(){return {checked_at:100,application:{version:'fixture',source_revision:null,source_state:'unknown'},schema:{state:'ok',versions:[1,12]},policy:{state:'legacy',revision:0,enabled:['mail'],choices:[{id:'mail',label:'邮件'},{id:'currency',label:'点券'}],account_scope:'legacy'},scope:{test_only:true},binding:{pvf_sha256:'a'.repeat(64),image_digest:'sha256:'+'b'.repeat(64)},catalog:{state:'matched'},assets:{state:'not_installed'},runtime:{fresh:true,collected_at:99},note:'只读状态不是执行权限',items:[{id:'mail',label:'奖励邮件',group:'运营',state:'configured',checks:[],verification:{state:'not_recorded'},note:'打开不发放',destination:'mail'},{id:'private-message',label:'私信',group:'待适配',state:'not_implemented',checks:[],verification:{state:'not_recorded'},note:'尚未适配',destination:null}]}}
function render(){const w=mount(Capabilities,{attachTo:document.body});wrappers.push(w);return w}
function button(w:any,name:string){return w.findAll('button').find((b:any)=>b.text()===name)!}
beforeEach(()=>{vi.mocked(api).mockReset();vi.mocked(api).mockResolvedValue(sample());sessionStorage.clear()})
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers=[];document.body.innerHTML='';vi.useRealTimers()})
it('separates enabled, implementation and validation and filters without requests',async()=>{const w=render();await flushPromises();expect(w.text()).toContain('配置已启用');expect(w.text()).toContain('未关联当前版本验收记录');expect(w.text()).toContain('未记录源码提交');await w.find('[aria-label="筛选功能状态"]').setValue('not_implemented');expect(w.findAll('.capability-card')).toHaveLength(1);expect(w.find('.capability-card').text()).toContain('私信');expect(api).toHaveBeenCalledTimes(1)})
it('all only selects, reason error is local, then confirms one durable update',async()=>{const w=render();await flushPromises();await button(w,'全部开放').trigger('click');expect(api).toHaveBeenCalledTimes(1);await button(w,'核对并保存权限').trigger('click');expect(w.find('#capability-reason-error').text()).toContain('至少2');expect(w.find('[role=dialog]').exists()).toBe(false);await w.find('#capability-reason').setValue('网页权限测试');await button(w,'核对并保存权限').trigger('click');expect(w.find('[role=dialog]').text()).toContain('点券');vi.mocked(api).mockResolvedValueOnce({revision:1,status:'committed'}).mockResolvedValue({...sample(),policy:{...sample().policy,state:'managed',revision:1,enabled:['mail','currency'],account_scope:'all'}});await button(w,'确认保存权限').trigger('click');await flushPromises();const post=vi.mocked(api).mock.calls.find(c=>c[1]==='POST')!;expect(post[2]).toMatchObject({expected_revision:0,enabled:['mail','currency'],reason:'网页权限测试'});expect((post[2] as any).request_id).toMatch(/^[a-f0-9]{32}$/);expect(w.text()).toContain('不需要重启服务');expect(sessionStorage.getItem('dnf-gm.capability-pending')).toBeNull()})
it('uncertain update is recovered by GET after remount, never automatically replayed',async()=>{const w=render();await flushPromises();await button(w,'全部开放').trigger('click');await w.find('#capability-reason').setValue('fixture');await button(w,'核对并保存权限').trigger('click');vi.mocked(api).mockRejectedValueOnce(new Error('连接中断'));await button(w,'确认保存权限').trigger('click');await flushPromises();const id=sessionStorage.getItem('dnf-gm.capability-pending');expect(id).toMatch(/^[a-f0-9]{32}$/);expect(button(w,'确认保存权限').attributes('disabled')).toBeDefined();await button(w,'稍后查询').trigger('click');expect(w.find('[role=dialog]').exists()).toBe(false);w.unmount();wrappers=[];vi.mocked(api).mockResolvedValue(sample());const next=render();await flushPromises();vi.mocked(api).mockResolvedValueOnce({status:'committed',revision:1}).mockResolvedValue(sample());await button(next,'查询原权限请求').trigger('click');await flushPromises();expect(api).toHaveBeenCalledWith('/capabilities/policy/requests/'+id);expect(vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')).toHaveLength(1);expect(sessionStorage.getItem('dnf-gm.capability-pending')).toBeNull()})
it('reauth rejection remains editable and emits reauth rather than unknown',async()=>{const w=render();await flushPromises();await w.find('#capability-reason').setValue('fixture');await button(w,'核对并保存权限').trigger('click');vi.mocked(api).mockRejectedValueOnce(new ApiError('需要重新认证',403));await button(w,'确认保存权限').trigger('click');await flushPromises();expect(w.emitted('reauth')).toHaveLength(1);expect(sessionStorage.getItem('dnf-gm.capability-pending')).toBeNull();expect(button(w,'确认保存权限').attributes('disabled')).toBeUndefined()})
it('failed refresh removes stale enable state and does not navigate to injected destinations',async()=>{const d=sample();d.items[0].destination='javascript:alert(1)';vi.mocked(api).mockResolvedValue(d);const w=render();await flushPromises();expect(w.find('.capability-card button').exists()).toBe(false);vi.mocked(api).mockRejectedValueOnce(new Error('暂时不可读取'));await button(w,'刷新功能状态').trigger('click');await flushPromises();expect(w.findAll('.capability-card')).toHaveLength(0);expect(w.find('[role=alert]').text()).toContain('暂时不可读取')})
it('hidden pages pause receipt polling and unmount cancels it',async()=>{vi.useFakeTimers({toFake:['setInterval','clearInterval']});sessionStorage.setItem('dnf-gm.capability-pending','a'.repeat(32));const hidden=vi.spyOn(document,'hidden','get').mockReturnValue(true);const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(10000);expect(api).toHaveBeenCalledTimes(1);hidden.mockReturnValue(false);await vi.advanceTimersByTimeAsync(5000);expect(api).toHaveBeenCalledWith('/capabilities/policy/requests/'+'a'.repeat(32));w.unmount();wrappers=[];const n=vi.mocked(api).mock.calls.length;await vi.advanceTimersByTimeAsync(10000);expect(api).toHaveBeenCalledTimes(n);hidden.mockRestore()})

it('shows dependency changes in the selection and confirmation before submitting',async()=>{
 const d=sample();d.policy.enabled=[]
 d.policy.choices=[{id:'native-monitor',label:'会话查询'},{id:'native-notice',label:'公告'},{id:'native-kick',label:'踢人'},{id:'batch-reward',label:'批量奖励'},{id:'batch-worker',label:'批量执行器'}]
 vi.mocked(api).mockResolvedValue(d);const w=render();await flushPromises()
 const box=(id:string)=>w.find(`input[value="${id}"]`)
 await box('native-notice').setValue(true);await box('native-kick').setValue(true)
 expect((box('native-monitor').element as HTMLInputElement).checked).toBe(true)
 await box('native-monitor').setValue(false)
 expect((box('native-notice').element as HTMLInputElement).checked).toBe(false)
 expect((box('native-kick').element as HTMLInputElement).checked).toBe(false)
 await box('batch-worker').setValue(true)
 expect((box('batch-reward').element as HTMLInputElement).checked).toBe(true)
 await box('batch-reward').setValue(false)
 expect((box('batch-worker').element as HTMLInputElement).checked).toBe(false)
 await box('native-notice').setValue(true)
 await w.find('#capability-reason').setValue('开启公告及其会话前提');await button(w,'核对并保存权限').trigger('click')
 expect(w.find('[role=dialog]').text()).toContain('会话查询、公告')
 expect(api).toHaveBeenCalledTimes(1)
})
