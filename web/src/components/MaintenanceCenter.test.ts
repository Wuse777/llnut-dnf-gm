// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest'
import MaintenanceCenter from './MaintenanceCenter.vue'
import {api,ApiError} from '../api'
vi.mock('../api',async original=>({...await original<typeof import('../api')>(),api:vi.fn()}))
const wrappers:any[]=[],storage='dnf-gm.maintenance-pending',id='a'.repeat(32),fingerprint='b'.repeat(64)
let record:any,ready:any
const initial=()=>({operation_id:id,status:'preparing',reason:'修改测试装备',created_at:1000,result:null,can_confirm:false,can_cancel:true,worker_fresh:true,retry_dispatch_allowed:false})
const planned=()=>({...initial(),can_confirm:true,result:{state:'prepared',fingerprint,games:['game_fixture'],expires_at:Date.now()/1000+300,can_confirm:true}})
function setup(){const w=mount(MaintenanceCenter);wrappers.push(w);return w}
async function click(w:any,label:string){const b=w.findAll('button').find((b:any)=>b.text()===label);expect(b,`Missing button: ${label}`).toBeTruthy();await b.trigger('click');await flushPromises()}
async function prepare(w:any){await flushPromises();await w.find('#maintenance-reason').setValue('修改测试装备');await w.find('.maintenance-request-form').trigger('submit');await flushPromises()}
function posts(){return vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')}
beforeEach(()=>{sessionStorage.clear();ready={write_gate:{state:'open'},state:'ok',enabled:true,prepare_supported:true,execute_supported:true,message:'测试执行器状态'};record=initial();vi.mocked(api).mockReset();vi.spyOn(crypto,'randomUUID').mockReturnValue('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');vi.mocked(api).mockImplementation(async(path,method,body:any)=>{
 if(path==='/maintenance')return {...ready}
 if(path==='/maintenance/requests'&&method==='POST'){expect(JSON.parse(sessionStorage.getItem(storage)!).id).toBe(body.request_id);return {...record}}
 if(path.startsWith('/maintenance/requests?')||path==='/maintenance/requests')return {items:[],next_cursor:null}
 if(path===`/maintenance/requests/${id}`)return structuredClone(record)
 if(path.endsWith('/confirm')){record={...record,status:'queued',can_confirm:false,can_cancel:false};return structuredClone(record)}
 if(path.endsWith('/cancel')){record={...record,status:'cancelled',can_cancel:false,result:{state:'cancelled'}};return structuredClone(record)}
 if(path.endsWith('/observe')){record={...record,observation_pending:true};return structuredClone(record)}
 if(path.endsWith('/dispatch'))return structuredClone(record)
 throw new Error('unexpected request '+method+' '+path)
})})
afterEach(()=>{wrappers.splice(0).forEach(w=>w.unmount());vi.useRealTimers();vi.restoreAllMocks();vi.unstubAllGlobals();sessionStorage.clear()})
describe('web maintenance workflow',()=>{
 it('does not show a modal until explicitly confirming and links to web capability policy',async()=>{const w=setup();await flushPromises();expect(w.find('[role=dialog]').exists()).toBe(false);await click(w,'网页管理功能开关');expect(w.emitted('navigate')?.[0]).toEqual(['capabilities']);expect(posts()).toHaveLength(0)})
 it('explains unavailable execution independently of owner permission',async()=>{ready={...ready,execute_supported:false,message:'完整退出与恢复执行器尚未接通'};const w=setup();await flushPromises();expect(w.text()).toContain('已开启');expect(w.text()).toContain('尚未接通');expect(w.text()).not.toContain('核对并确认维护');expect(posts()).toHaveLength(0)})
 it('shows the missing reason beside the field without sending any request',async()=>{const w=setup();await flushPromises();await w.find('.maintenance-request-form').trigger('submit');await flushPromises();expect(w.find('#maintenance-reason-error').text()).toContain('维护原因');expect(w.find('#maintenance-reason').attributes('aria-invalid')).toBe('true');expect(posts()).toHaveLength(0)})
 it('persists id before POST then queries the same request for its root plan',async()=>{const w=setup();await prepare(w);expect(posts()).toHaveLength(1);expect(w.text()).toContain('等待只读计划');record=planned();await click(w,'只查询原申请');expect(w.text()).toContain('game_fixture');expect(w.text()).toContain('核对并确认维护');expect(posts()).toHaveLength(1)})
 it('requires impact acknowledgement and confirms the exact root plan once',async()=>{const w=setup();await prepare(w);record=planned();await click(w,'只查询原申请');await click(w,'核对并确认维护');expect(w.find('[role=dialog]').exists()).toBe(true);await click(w,'确认执行一次');expect(w.find('#maintenance-ack-error').text()).toContain('断开');expect(posts()).toHaveLength(1);await w.find('input[type=checkbox]').setValue(true);await click(w,'确认执行一次');expect(posts()).toHaveLength(2);expect(posts()[1]).toEqual([`/maintenance/requests/${id}/confirm`,'POST',{idempotency_key:id,fingerprint,acknowledge_disconnect:true}]);expect(w.text()).toContain('确认已入队');expect(w.text()).not.toContain('核对并确认维护');expect(sessionStorage.getItem(storage)).toContain(id)})
 it('response loss keeps the original ID and never automatically resends',async()=>{const normal=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation(async(p,m,b)=>{if(p==='/maintenance/requests'&&m==='POST')throw new Error('连接断开');return normal(p,m,b)});const w=setup();await prepare(w);expect(w.text()).toContain('编号已保留');expect(w.text()).toContain(id);record=planned();await click(w,'只查询原申请');expect(w.text()).not.toContain('核对并确认维护');expect(posts()).toHaveLength(1)})
 it('reload only queries the saved request and does not restore confirm',async()=>{record=planned();sessionStorage.setItem(storage,JSON.stringify({id}));const w=setup();await flushPromises();expect(w.text()).toContain('从历史或刷新恢复');expect(w.text()).not.toContain('核对并确认维护');expect(posts()).toHaveLength(0);expect(vi.mocked(api).mock.calls.some(c=>c[0]===`/maintenance/requests/${id}`&&!c[1])).toBe(true)})
 it('failed status lookup keeps old record visibly stale and disables confirm',async()=>{const w=setup();await prepare(w);record=planned();await click(w,'只查询原申请');const normal=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation(async(p,m,b)=>{if(p===`/maintenance/requests/${id}`)throw new Error('查询失败');return normal(p,m,b)});await click(w,'只查询原申请');expect(w.text()).toContain('上次记录');expect(w.text()).not.toContain('核对并确认维护')})
 it('allows cancellation and forgets only a terminal root receipt',async()=>{const w=setup();await prepare(w);await click(w,'取消尚未执行的计划');expect(w.text()).toContain('预览已取消');expect(sessionStorage.getItem(storage)).toBeNull();await click(w,'结束查看');expect(w.text()).not.toContain(id)})
 it('game-drained is not full maintenance completion or permission',async()=>{record={...initial(),status:'queued',can_cancel:false,result:{state:'game_drained',maintenance_permit:false,events:[{sequence:1,phase:'signal-intent',at:1000,service:'game_fixture'}]}};sessionStorage.setItem(storage,JSON.stringify({id}));const w=setup();await flushPromises();expect(w.text()).toContain('尚非完整维护窗口');expect(w.text()).toContain('已记录退出信号意向');expect(w.text()).not.toContain('结束查看');expect(posts()).toHaveLength(0)})
 it('polls GET only while visible and cleans up timers',async()=>{vi.useFakeTimers();const w=setup();await prepare(w);vi.mocked(api).mockClear();vi.spyOn(document,'hidden','get').mockReturnValue(true);await vi.advanceTimersByTimeAsync(20000);expect(vi.mocked(api)).not.toHaveBeenCalled();vi.spyOn(document,'hidden','get').mockReturnValue(false);await vi.advanceTimersByTimeAsync(10000);await flushPromises();expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true);expect(vi.mocked(api).mock.calls.length).toBe(2);w.unmount();vi.mocked(api).mockClear();await vi.advanceTimersByTimeAsync(10000);expect(vi.mocked(api)).not.toHaveBeenCalled()})
 it('reauthentication prompts do not clear an uncertain request',async()=>{const normal=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation(async(p,m,b)=>{if(m==='POST')throw new ApiError('请重新认证',403);return normal(p,m,b)});const w=setup();await prepare(w);expect(w.emitted('reauth')).toHaveLength(1);expect(sessionStorage.getItem(storage)).toContain(id)})
 it('explicitly queues a readonly probe, shows its timestamp and does not call control routes',async()=>{
  record={...planned(),can_observe:true};sessionStorage.setItem(storage,JSON.stringify({id}));const w=setup();await flushPromises()
  await click(w,'核对实际状态（只读）');expect(posts()).toEqual([[`/maintenance/requests/${id}/observe`,'POST']]);expect(w.text()).toContain('核对请求已排队')
  record={...record,observation_pending:false,result:{...record.result,observation:{state:'observed',collected_at:1000,games:[{service:'game_fixture',state:'down_normal'}],maintenance_permit:false}}}
  await click(w,'只查询原申请');expect(w.text()).toContain('不是存档验收凭据');expect(w.text()).toContain('采集时间');expect(posts()).toHaveLength(1)
  expect(w.text()).not.toContain('核对并确认维护')
 })
 it('renders hostile reason as text, not HTML',async()=>{record={...initial(),reason:'<img src=x onerror=alert(1)>'};sessionStorage.setItem(storage,JSON.stringify({id}));const w=setup();await flushPromises();expect(w.text()).toContain('<img src=x');expect(w.find('img').exists()).toBe(false)})
})
it.each(['open','frozen','unknown','not_configured'])('shows %s write admission independently of feature permission without an override',async(state)=>{ready.write_gate={state,operation_id:state==='frozen'?id:''};const w=setup();await flushPromises();const status=w.find('.maintenance-write-gate');expect(status.exists()).toBe(true);expect(status.text()).toContain({open:'普通写入已开放',frozen:'维护冻结中',unknown:'状态未知',not_configured:'尚未安装维护写入屏障'}[state]!);if(state==='frozen'){expect(status.text()).toContain(id);expect(status.text()).toContain('功能权限无需重新开启')}expect(status.find('button').exists()).toBe(false);expect(posts()).toHaveLength(0)})

it('removes a previously offered confirmation when status refresh finds a frozen gate',async()=>{const w=setup();await prepare(w);record=planned();await click(w,'只查询原申请');expect(w.findAll('button').some((b:any)=>b.text()==='核对并确认维护')).toBe(true);ready.write_gate={state:'frozen',operation_id:id};await click(w,'刷新执行器状态');expect(w.findAll('button').some((b:any)=>b.text()==='核对并确认维护')).toBe(false);expect(posts()).toHaveLength(1)})

it('renders database-admission stages without presenting transaction drain as a maintenance permit',async()=>{
 record={...initial(),status:'queued',can_cancel:false,result:{state:'needs_review',maintenance_permit:false,events:[
  {sequence:1,phase:'freeze-intent',at:1000},
  {sequence:2,phase:'write-gate-frozen',at:1001},
  {sequence:3,phase:'database-drained',at:1002},
 ]}}
 ready.write_gate={state:'frozen',operation_id:id}
 sessionStorage.setItem(storage,JSON.stringify({id}))
 const w=setup();await flushPromises()
 expect(w.text()).toContain('已记录冻结新写入意向')
 expect(w.text()).toContain('普通游戏写入已冻结')
 expect(w.text()).toContain('已核对原数据库普通写事务结束')
 expect(w.text()).toContain('执行结果待核对')
 expect(w.text()).not.toContain('维护窗口已建立')
 expect(w.text()).not.toContain('确认执行一次')
 expect(posts()).toHaveLength(0)
})

it('shows auxiliary writer progress without implying a maintenance permit',async()=>{
 const w=setup();await prepare(w)
 record={...initial(),status:'running',result:{state:'writers_stopped',events:[{sequence:1,phase:'writer-stopped',at:1001,service:'auction'}],observation:{state:'observed',collected_at:1002,games:[],services:[{service:'auction',state:'down_normal'},{service:'llnut_gate',state:'down_terminated'}]}}}
 await click(w,'只查询原申请')
 expect(w.text()).toContain('auction')
 expect(w.text()).toContain('llnut_gate')
 expect(w.text()).toContain('TERM退出')
 expect(w.text()).toContain('不开放装备写入')
 expect(w.text()).not.toContain('核对并确认维护')
 expect(posts()).toHaveLength(1)
})

it('labels restore phases and process observations without claiming gameplay verification',async()=>{
 const w=setup();await prepare(w)
 record={...initial(),status:'queued',result:{state:'resuming',events:[{sequence:1,phase:'window-closed',at:1001},{sequence:2,phase:'restore-start-sent',at:1002,service:'guild'}],observation:{state:'observed',collected_at:1003,services:[{service:'guild',state:'starting'},{service:'mysql',state:'restored'}]}}}
 await click(w,'只查询原申请')
 expect(w.text()).toContain('窗口已关闭并完成数据库核对')
 expect(w.text()).toContain('组件启动命令已返回')
 expect(w.text()).toContain('正在核对就绪状态')
 expect(w.text()).not.toContain('核对并确认维护')
 expect(posts()).toHaveLength(1)
})

it('shows reconciled outcomes without calling unknown native effects successful or replaying',async()=>{
 record={...initial(),result:{state:'writers_stopped',ordinary_outcomes:{rewards_committed:2,rewards_failed:1,native_uncertain:3,game_writes:false,automatic_replay:false}}}
 sessionStorage.setItem(storage,JSON.stringify({id}));const w=setup();await flushPromises()
 const panel=w.find('[aria-label="维护前结果核对"]')
 expect(panel.text()).toContain('确认已提交 2 项')
 expect(panel.text()).toContain('确认未提交 1 项')
 expect(panel.text()).toContain('3 条原生指令结果不确定')
 expect(panel.text()).toContain('不自动重发')
 expect(panel.find('.warning').exists()).toBe(true)
 expect(panel.text()).toContain('不是游戏内效果证明')
 expect(posts()).toHaveLength(0)
})
