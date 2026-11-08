// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import Schedules from './Schedules.vue'
import RewardJobs from './RewardJobs.vue'
import {api,ApiError} from '../api'
import {shanghaiInput,shanghaiTimestamp} from '../scheduleTime'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{constructor(message:string,public status:number){super(message)}},uncertainMessage:(e:any)=>e.message}))
const id='d'.repeat(32),storage='dnfgm-schedule-id'
let state:any,wrappers:any[]=[]
function make(request:any){return {id,title:request.title,kind:request.kind,fingerprint:'f'.repeat(64),status:'preview',next_due:request.first_due,request,worker_enabled:true,preview:{note:'到期冻结名单；错过不补发',estimate:{target_count:1,account_count:1},binding:{reward:{gold:0,rewards:{items:[]}}}}}}
function setup(){const w=mount(Schedules,{attachTo:document.body});wrappers.push(w);return w}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>b.text()===text);expect(b,'Missing '+text).toBeTruthy();await b!.trigger('click');await flushPromises()}
async function notice(w:any){await w.get('[aria-label="计划名称"]').setValue('每周公告');await w.get('[aria-label="计划类型"]').setValue('notice');await w.get('[aria-label="定时公告文字"]').setValue('测试公告');await w.get('[aria-label="定时公告原因"]').setValue('fixture');await click(w,'预览定时公告计划')}
beforeEach(()=>{
 sessionStorage.clear();state=null
 vi.mocked(api).mockReset().mockImplementation(async(path,method,data:any)=>{
  if(path==='/schedules/preview'){state=make(data);return JSON.parse(JSON.stringify(state))}
  if(path.endsWith('/activate')){state={...state,status:'active'};return JSON.parse(JSON.stringify(state))}
  if(path.endsWith('/control')){state={...state,status:data.action==='pause'?'paused':data.action==='resume'?'active':'cancelled'};return JSON.parse(JSON.stringify(state))}
  if(path.includes('/runs?'))return {items:[],page:1}
  if(path==='/schedules/'+id)return JSON.parse(JSON.stringify(state))
  if(path.startsWith('/schedules?'))return {items:state?[JSON.parse(JSON.stringify(state))]:[],worker_enabled:true}
  if(path.startsWith('/characters?'))return {items:[]}
  throw Error('Unexpected '+path)
 })
})
afterEach(()=>{for(const w of wrappers)w.unmount();wrappers=[];vi.useRealTimers();vi.restoreAllMocks()})
it('uses Beijing time even for browsers in other zones and rejects invalid dates',()=>{
 expect(shanghaiTimestamp('2026-11-05T20:00')).toBe(Date.parse('2026-11-05T12:00:00Z')/1000)
 expect(shanghaiInput(Date.parse('2026-11-05T12:00:00Z')/1000)).toBe('2026-11-05T20:00')
 expect(()=>shanghaiTimestamp('2026-02-30T12:00')).toThrow()
 expect(()=>shanghaiTimestamp('not-a-time')).toThrow()
})
it('reuses reward draft without querying or creating immediate batch jobs',async()=>{
 const w=setup();await flushPromises()
 expect(vi.mocked(api).mock.calls.every(c=>c[0].startsWith('/schedules')||c[0].startsWith('/characters?'))).toBe(true)
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
 await w.get('[aria-label="计划名称"]').setValue('周末礼包')
 await w.get('[aria-label="角色编号名单"]').setValue('900001')
 await w.get('[aria-label="批量点券"]').setValue(100)
 await w.get('[aria-label="批量发放原因"]').setValue('test')
 await w.getComponent(RewardJobs).find('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/schedules/preview','POST',expect.objectContaining({kind:'reward',reward_job:expect.objectContaining({targets:{mode:'selected',charac_nos:[900001]}})}))
 expect(vi.mocked(api).mock.calls.some(c=>c[0].startsWith('/reward-jobs'))).toBe(false)
 expect(w.text()).toContain('不是本次实际名单')
})
it('keeps input validation near fields and sends nothing on invalid dates or notice',async()=>{
 const w=setup();await flushPromises();await w.get('[aria-label="计划类型"]').setValue('notice');await click(w,'预览定时公告计划')
 expect(w.get('[aria-label="计划名称"]').attributes('aria-invalid')).toBe('true')
 expect(w.get('[aria-label="定时公告原因"]').element.parentElement!.textContent).toContain('请填写公告原因')
 expect(vi.mocked(api).mock.calls.some(c=>c[1]==='POST')).toBe(false)
 await w.get('[aria-label="首次北京时间"]').setValue('2000-01-01T00:00');await click(w,'预览定时公告计划')
 expect(w.get('[aria-label="首次北京时间"]').element.parentElement!.textContent).toContain('必须在未来')
})
it('requires broadcast scope and recurrence acknowledgement before activating',async()=>{
 const w=setup();await flushPromises();await w.get('[aria-label="执行周期"]').setValue('daily');await notice(w)
 await click(w,'确认启用计划');expect(w.text()).toContain('请确认周期性执行')
 await w.get('.schedule-check input').setValue(true);await click(w,'确认启用计划');expect(w.text()).toContain('确认范围')
 await w.get('[aria-label="定时全服确认"]').setValue('全服公告');await click(w,'确认启用计划')
 expect(api).toHaveBeenCalledWith('/schedules/'+id+'/activate','POST',expect.objectContaining({fingerprint:'f'.repeat(64),acknowledge_recurring:true,all_server_confirmation:'全服公告'}))
 expect(w.text()).toContain('已启用')
})
it('lost activation only queries original ID and never replays on reload',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation(async(path,...args)=>{if(path.endsWith('/activate')){state={...state,status:'active'};throw new ApiError('响应丢失',503)}return original(path,...args)})
 let w=setup();await flushPromises();await notice(w);await w.get('[aria-label="定时全服确认"]').setValue('全服公告');await click(w,'确认启用计划')
 expect(w.text()).toContain('激活结果待确认');expect(sessionStorage.getItem(storage)).toBe(id)
 await click(w,'刷新原计划（只读）');expect(w.text()).toContain('已启用')
 w.unmount();w=setup();await flushPromises()
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/activate'))).toHaveLength(1)
 expect(w.text()).not.toContain('确认启用计划')
})
it('restoring an old preview does not restore confirm authority',async()=>{
 state=make({title:'旧预览',kind:'notice',first_due:Math.floor(Date.now()/1000)+1000,recurrence:'once',notice:{message:'hi'}});sessionStorage.setItem(storage,id)
 const w=setup();await flushPromises()
 expect(w.text()).not.toContain('确认启用计划')
 expect(w.text()).toContain('恢复的预览只允许查询或取消')
 await click(w,'取消后续期次');expect(w.text()).toContain('已取消')
})
it('copies a plan as an unactivated draft with a new future first time',async()=>{
 const w=setup();await flushPromises();await notice(w);await click(w,'复制为新计划草稿')
 expect((w.get('[aria-label="计划名称"]').element as HTMLInputElement).value).toBe('每周公告（副本）')
 expect(w.text()).not.toContain('确认启用计划');expect(sessionStorage.getItem(storage)).toBeNull()
 expect(vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')).toHaveLength(1)
})
it('reauth failure preserves preview without an automatic resubmission',async()=>{
 const original=vi.mocked(api).getMockImplementation()!
 vi.mocked(api).mockImplementation((path,...args)=>path.endsWith('/activate')?Promise.reject(new ApiError('需要重新认证',403)):original(path,...args))
 const w=setup();await flushPromises();await notice(w);await w.get('[aria-label="定时全服确认"]').setValue('全服公告');await click(w,'确认启用计划')
 expect(w.emitted('reauth')).toHaveLength(1);expect(w.text()).not.toContain('激活结果待确认')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/activate'))).toHaveLength(1)
})
it('polling is read-only, hidden tabs stop polling and unmount clears timer',async()=>{
 vi.useFakeTimers({toFake:['setInterval','clearInterval']});const hidden=vi.spyOn(document,'hidden','get').mockReturnValue(false)
 state={...make({title:'ongoing',kind:'notice',first_due:Date.now()/1000+1000,recurrence:'once',notice:{message:'hello'}}),status:'active'};sessionStorage.setItem(storage,id)
 const w=setup();await flushPromises();const n=vi.mocked(api).mock.calls.length
 await vi.advanceTimersByTimeAsync(30000);expect(vi.mocked(api).mock.calls.length).toBe(n+3)
 hidden.mockReturnValue(true);await vi.advanceTimersByTimeAsync(60000);expect(vi.mocked(api).mock.calls.length).toBe(n+3)
 w.unmount();hidden.mockReturnValue(false);await vi.advanceTimersByTimeAsync(60000);expect(vi.mocked(api).mock.calls.length).toBe(n+3)
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('opens an anomaly target without activation or changing its schedule',async()=>{
 state=make({title:'异常计划',kind:'notice',first_due:1,recurrence:'once',notice:{message:'hi'}});state.status='active'
 const w=mount(Schedules,{props:{initialSchedule:id}});wrappers.push(w);await flushPromises()
 expect(api).toHaveBeenCalledWith('/schedules/'+id);expect(w.emitted('opened')).toEqual([[]]);expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('keeps a recovered preview rather than replacing uncertain context',async()=>{
 state=make({title:'原计划',kind:'notice',first_due:1,recurrence:'once',notice:{message:'hi'}});sessionStorage.setItem(storage,id)
 const other='a'.repeat(32),w=mount(Schedules,{props:{initialSchedule:other}});wrappers.push(w);await flushPromises()
 expect(w.text()).toContain('保留尚未确认的原计划');expect(api).not.toHaveBeenCalledWith('/schedules/'+other);expect(sessionStorage.getItem(storage)).toBe(id)
})
