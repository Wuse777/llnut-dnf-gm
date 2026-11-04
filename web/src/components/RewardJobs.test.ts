// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import RewardJobs from './RewardJobs.vue'
const id='b'.repeat(32)
function fixture(){return {id,fingerprint:'f'.repeat(64),target_count:2,account_count:1,status:'preview',reason:'batch fixture',worker_enabled:true,write_enabled:true,request:{targets:{mode:'selected'},account_reward_mode:'once_per_account',reward:{currency_rewards:{cera:10}}},preview:{currency_totals:{cera:'10'},gold_total:'0',rewards:{items:[]},note:'database only'},counts:{pending:2}}}
const wrappers:any[]=[]
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;sessionStorage.clear();vi.unstubAllGlobals();vi.useRealTimers();document.body.innerHTML=''})
async function click(w:any,text:string){await w.findAll('button').find((b:any)=>b.text()===text)!.trigger('click');await flushPromises()}
function setup(overrides:any={}){
 let job={...fixture(),...overrides};let lose=false
 const fetcher=vi.fn(async(url:any,options:any)=>{
  const path=String(url),method=options?.method||'GET'
  if(path.endsWith('/start')){if(lose)throw new TypeError('connection lost');job={...job,status:'running'};return new Response(JSON.stringify(job))}
  if(path.endsWith('/control')){const action=JSON.parse(options.body).action;job={...job,status:action==='resume'?'running':'paused'};return new Response(JSON.stringify(job))}
  if(path.includes('/targets?'))return new Response(JSON.stringify({items:[{ordinal:1,target_uid:1,charac_no:2,target:{charac_name:'Test',accountname:'gm'},operation_id:'a'.repeat(32),status:'pending',attempts:0}],next_after:null}))
  if(path.endsWith('/preview'))return new Response(JSON.stringify(job))
  if(path.includes('/catalog?'))return new Response(JSON.stringify({items:[{id:99,name:'Material',category:'material',sendable:true}]}))
  if(path.endsWith('/'+id))return new Response(JSON.stringify(job))
  return new Response(JSON.stringify({items:[job],has_more:false}))
 });vi.stubGlobal('fetch',fetcher);const w=mount(RewardJobs,{attachTo:document.body});wrappers.push(w)
 return {w,fetcher,lose:()=>{lose=true},resolve:()=>{job={...job,status:'running'}}}
}
async function fill(w:any){await w.find('[aria-label="角色编号名单"]').setValue('2, 3,2');await w.find('[aria-label="批量点券"]').setValue(10);await w.find('[aria-label="批量发放原因"]').setValue('test reason')}
async function preview(w:any){await w.find('form').trigger('submit');await flushPromises()}
it('keeps missing reason and bad identifiers next to their fields without sending writes',async()=>{
 const {w,fetcher}=setup();await flushPromises();await preview(w);expect(w.text()).toContain('请填写发放原因');expect(w.find('[aria-label="批量发放原因"]').attributes('aria-invalid')).toBe('true');expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(0)
})
it('freezes preview and confirms server fingerprint and count, not changed draft',async()=>{
 const {w,fetcher}=setup();await flushPromises();await fill(w);await preview(w);await w.find('[aria-label="批量点券"]').setValue(999)
 await click(w,'确认启动该任务');const request=fetcher.mock.calls.find(([u])=>String(u).endsWith('/start'))![1]
 expect(JSON.parse(request.body)).toMatchObject({fingerprint:'f'.repeat(64),target_count:2,account_count:1});expect(JSON.parse(request.body)).not.toHaveProperty('reward');expect(w.text()).toContain('执行中')
})
it('allows unknown-stack material quantity above PVF values and removing never submits',async()=>{
 const {w,fetcher}=setup();await flushPromises();await fill(w);await click(w,'搜索物品');await click(w,'＋ Material #99');await w.find('[aria-label="物品数量 99"]').setValue(2147483647);await preview(w)
 const body=JSON.parse(fetcher.mock.calls.find(([u])=>String(u).endsWith('/preview'))![1].body);expect(body.reward.items).toEqual([{id:99,quantity:2147483647}])
 const before=fetcher.mock.calls.filter(([u])=>String(u).endsWith('/preview')).length;await w.find('[aria-label="移除物品 99 第1条"]').trigger('click');await flushPromises();expect(fetcher.mock.calls.filter(([u])=>String(u).endsWith('/preview'))).toHaveLength(before)
})
it('requires explicit all-server phrase and repeated account acknowledgement',async()=>{
 const {w,fetcher}=setup({request:{targets:{mode:'all'},account_reward_mode:'per_character',reward:{currency_rewards:{cera:10}}}});await flushPromises();await fill(w);await preview(w);await click(w,'确认启动该任务');expect(w.text()).toContain('请在启动按钮上方输入');await w.find('[aria-label="全服确认"]').setValue('全服发放');await click(w,'确认启动该任务');expect(w.text()).toContain('请确认同一账号');expect(fetcher.mock.calls.some(([u])=>String(u).endsWith('/start'))).toBe(false)
 await w.find('input[type=checkbox]').setValue(true);await click(w,'确认启动该任务');expect(fetcher.mock.calls.some(([u])=>String(u).endsWith('/start'))).toBe(true)
})
it('retains uncertain start across remount and only reads original job',async()=>{
 const x=setup();await flushPromises();await fill(x.w);await preview(x.w);x.lose();await click(x.w,'确认启动该任务');expect(x.w.text()).toContain('启动结果待确认');expect(x.w.findAll('button').find(b=>b.text()==='确认启动该任务')!.attributes('disabled')).toBeDefined()
 x.w.unmount();const y=setup();await flushPromises();expect(y.w.text()).toContain('启动结果待确认');expect(y.fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true);y.resolve();await click(y.w,'刷新原任务（只读）');expect(y.w.text()).not.toContain('启动结果待确认');expect(y.fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
it('stops hidden-page polling and never starts the worker from reads',async()=>{
 vi.useFakeTimers();const {w,fetcher}=setup();await flushPromises();await click(w,'查看任务');vi.spyOn(document,'hidden','get').mockReturnValue(true);const calls=fetcher.mock.calls.length;await vi.advanceTimersByTimeAsync(60000);expect(fetcher.mock.calls).toHaveLength(calls);vi.restoreAllMocks()
})
it('displays unavailable worker and disables starting',async()=>{
 const {w}=setup({worker_enabled:false});await flushPromises();await fill(w);await preview(w);expect(w.text()).toContain('执行器未启用');expect(w.findAll('button').find(b=>b.text()==='确认启动该任务')!.attributes('disabled')).toBeDefined()
})
