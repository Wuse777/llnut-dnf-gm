// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import InventoryEditor from './InventoryEditor.vue'
import {api,ApiError} from '../api'
import {operationStatus} from '../nativeStatus'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{constructor(message:string,public status:number){super(message)}},uncertainMessage:(e:any)=>e.message}))
const id='a'.repeat(32),storage='dnfgm-inventory-operation'
let wrappers:any[]=[],state:any,slot:any,history:any[]
const draft=()=>({operation_id:id,action:'item-edit',status:'preview',request:{container:'inventory',slot:0},preview:{target:{uid:900001,accountname:'测试账号',character:{charac_no:900001,charac_name:'测试角色'}},container:'inventory',slot:0,item_name:'测试装备',reason:'测试纠正',before:{id:990001,enhancement:3},after:{id:990001,enhancement:12}},result:null})
const setup=(selection:any={container:'inventory',slot:0})=>{const w=mount(InventoryEditor,{props:{characNo:900001,selection}});wrappers.push(w);return w}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>b.text()===text);expect(b,`missing ${text}`).toBeTruthy();await b.trigger('click');await flushPromises()}
async function prepare(w:any){await flushPromises();await w.get('[aria-label="强化"]').setValue('12');await w.get('[aria-label="装备维护原因"]').setValue('测试纠正');await w.get('form').trigger('submit');await flushPromises()}
beforeEach(()=>{
 sessionStorage.clear();state=draft();history=[]
 slot={uid:900001,charac_no:900001,container:'inventory',slot:0,reference:'f'.repeat(64),target:state.preview.target,item:{id:990001,name:'测试装备',enhancement:3,quality_raw:4294967295},maintenance:{available:true},enabled_actions:['item-edit','item-reclaim','item-restore']}
 vi.mocked(api).mockReset().mockImplementation(async(path,method,body)=>{
  if(path.startsWith('/inventory/characters/'))return structuredClone(slot)
  if(path.startsWith('/inventory/operations?'))return {items:structuredClone(history),has_more:false}
  if(path==='/inventory/preview')return structuredClone(state)
  if(path.endsWith('/confirm')){state={...state,status:'committed',result:{snapshot_id:id}};return structuredClone(state)}
  if(path.endsWith('/cancel-preview')){state={...state,status:'cancelled'};return structuredClone(state)}
  if(path==='/inventory/operations/'+id)return structuredClone(state)
  throw new Error('Unexpected API '+path+' '+method+' '+JSON.stringify(body))
 })
})
afterEach(()=>{for(const w of wrappers)w.unmount();wrappers=[];vi.restoreAllMocks();vi.useRealTimers();sessionStorage.clear()})
it('shows reason and numeric errors next to fields without POST',async()=>{
 const w=setup();await flushPromises();await w.get('[aria-label="强化"]').setValue('32');await w.get('form').trigger('submit');await flushPromises()
 expect(w.get('[aria-label="装备维护原因"]').element.parentElement!.textContent).toContain('请填写操作原因')
 expect(w.get('[aria-label="强化"]').element.parentElement!.textContent).toContain('0–31')
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('binds target/reference and changed fields only, then confirms exactly once',async()=>{
 const w=setup();await prepare(w)
 expect(api).toHaveBeenCalledWith('/inventory/preview','POST',expect.objectContaining({uid:900001,charac_no:900001,container:'inventory',slot:0,reference:'f'.repeat(64),changes:{enhancement:12}}))
 expect(w.emitted('pending')?.at(-1)).toEqual([true]);expect(w.text()).toContain('测试角色')
 await click(w,'确认执行装备操作');expect(w.emitted('changed')).toHaveLength(1)
 expect(w.emitted('pending')?.at(-1)).toEqual([false]);expect(operationStatus(state)).toContain('游戏效果待核验')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 expect(w.findAll('button').some((b:any)=>b.text()==='确认执行装备操作')).toBe(false)
})
it('does not re-enable POST after uncertain confirmation; query detects commit and marks stale',async()=>{
 const original=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation((path,...args)=>path.endsWith('/confirm')?Promise.reject(new Error('网络中断')):original(path,...args))
 const w=setup();await prepare(w);await click(w,'确认执行装备操作')
 expect(w.text()).toContain('不要重新确认');expect(w.findAll('button').some((b:any)=>b.text()==='确认执行装备操作')).toBe(false)
 state={...state,status:'committed'};await click(w,'查询原操作结果');expect(w.emitted('changed')).toHaveLength(1)
 await click(w,'查询原操作结果');expect(w.emitted('changed')).toHaveLength(1)
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
})
it('recovers operation ID after remount with GET only and no confirmation',async()=>{
 sessionStorage.setItem(storage,id);const w=setup();await flushPromises()
 expect(api).toHaveBeenCalledWith('/inventory/operations/'+id)
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
 expect(w.findAll('button').some((b:any)=>b.text()==='确认执行装备操作')).toBe(false)
 await click(w,'取消原预览');expect(w.text()).toContain('预览已取消')
})
it('does not overwrite original preview when another slot is selected',async()=>{
 const w=setup();await prepare(w);await w.setProps({selection:{container:'warehouse',slot:2}});await flushPromises()
 expect(w.text()).toContain('不能覆盖未完成的预览');expect(w.text()).toContain('角色背包 / 槽位 0')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].startsWith('/inventory/characters/'))).toHaveLength(1)
})
it.each(['no-window','disabled'])('explains capability unavailable: %s',async(why)=>{
 if(why==='no-window')slot.maintenance.available=false;else slot.enabled_actions=[]
 const w=setup();await flushPromises();expect(w.get('button.primary').attributes('disabled')).toBeDefined()
 expect(w.text()).toContain(why==='no-window'?'维护窗口不可用':'尚未激活')
})
it('restoration rereads slot and binds original snapshot; no immediate write',async()=>{
 history=[{...state,status:'committed',result:{snapshot_id:id}}];const w=setup(null);await flushPromises();await click(w,'创建恢复预览')
 expect(w.text()).toContain('整个当前容器');await w.get('[aria-label="装备维护原因"]').setValue('恢复测试')
 await w.get('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/inventory/preview','POST',expect.objectContaining({action:'item-restore',source_operation_id:id,changes:{}}))
 expect(vi.mocked(api).mock.calls.some(c=>c[0].endsWith('/confirm'))).toBe(false)
})
it('accepts original quantity field maximum without PVF cap',async()=>{
 slot.item={id:990002,name:'材料',quantity:4};const w=setup();await flushPromises();await w.get('[aria-label="数量"]').setValue('2147483647');await w.get('[aria-label="装备维护原因"]').setValue('测试数量');await w.get('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/inventory/preview','POST',expect.objectContaining({changes:{quantity:2147483647}}))
})
it('escapes names and raw quality is not a percentage',async()=>{
 slot.item.name='<img src=x onerror=alert(1)>';const w=setup();await flushPromises();expect(w.find('img').exists()).toBe(false);expect(w.text()).toContain('<img src=x');expect(w.text()).toContain('原始品级不是百分比');expect((w.get('[aria-label="原始品级（不是百分比）"]').element as HTMLInputElement).value).toBe('4294967295')
})
it('polls executing only while visible and stops at unmount',async()=>{
 vi.useFakeTimers({toFake:['setInterval','clearInterval']});const hidden=vi.spyOn(document,'hidden','get').mockReturnValue(false)
 state={...state,status:'executing'};sessionStorage.setItem(storage,id);const w=setup();await flushPromises();const n=vi.mocked(api).mock.calls.length
 await vi.advanceTimersByTimeAsync(10000);expect(api).toHaveBeenCalledTimes(n+1);hidden.mockReturnValue(true);await vi.advanceTimersByTimeAsync(20000);expect(api).toHaveBeenCalledTimes(n+1)
 w.unmount();hidden.mockReturnValue(false);await vi.advanceTimersByTimeAsync(10000);expect(api).toHaveBeenCalledTimes(n+1)
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true);expect(operationStatus(state)).toContain('结果待核对')
})
it('emits auth requirement but does not auto retry a failed confirmation',async()=>{
 const original=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation((path,...args)=>path.endsWith('/confirm')?Promise.reject(new ApiError('请重新认证',403)):original(path,...args))
 const w=setup();await prepare(w);await click(w,'确认执行装备操作');expect(w.emitted('reauth')).toHaveLength(1);expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
})
it('summarizes only changed fields before optional full snapshot',async()=>{
 const w=setup();await prepare(w);expect(w.get('[aria-label="本次变更"]').text()).toContain('强化3 → 12');expect(w.get('[aria-label="本次变更"]').text()).not.toContain('物品编号');expect(w.text()).toContain('查看完整修改前后存档字段')
})
it('explains unsupported or locked slots before preview instead of waiting for API failure',async()=>{
 slot.item.editable=false;slot.item.unsupported_reason='宠物涉及独立关联记录';const w=setup();await flushPromises();expect(w.text()).toContain('宠物涉及独立关联记录');expect(w.get('button.primary').attributes('disabled')).toBeDefined()
})
it('labels recovered operation from another role without retargeting or POST',async()=>{
 state.preview.target.character.charac_no=900002;sessionStorage.setItem(storage,id);const w=setup();await flushPromises();expect(w.text()).toContain('不是当前打开的角色 #900001');expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
