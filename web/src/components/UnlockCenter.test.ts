// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import UnlockCenter from './UnlockCenter.vue'
import UnlockRequests from './UnlockRequests.vue'
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();sessionStorage.clear();document.body.innerHTML=''})
const op='a'.repeat(32),storage='dnf-gm.unlock-batch-pending'
const role={uid:3,charac_no:4,charac_name:'测试测试',accountname:'fixture',login_status:0,delete_flag:0,state:'ok',pending:1,expired:0,locked:0}
function setup(options:{lost?:boolean,conflict?:boolean,reauth?:boolean,next?:number|null}={}){
 const calls:any[]=[];let p:any=null,committed=false
 const request={lock_key:1,state:2,requested_at:Math.floor(Date.now()/1000)-100,due_at:Math.floor(Date.now()/1000)+100,expired:false,mapping_state:'matched',item:{id:10,name:'合成装备',container_name:'穿戴装备',slot_label:'武器',slot:0,enhancement:7,forge:3}}
 const result={operation_id:op,action:'unlock-batch',targets:[{charac_no:4}],state:'requests_expired_pending_game_load'}
 vi.stubGlobal('fetch',vi.fn(async(url,opts:any={})=>{
  const path=url.toString().replace('/dnf-gm/api/v1',''),body=opts.body&&JSON.parse(opts.body);calls.push({path,body,method:opts.method??'GET'})
  if(path.startsWith('/unlock-requests'))return new Response(JSON.stringify({items:[role],next_after:options.next??null,note:'本页扫描后筛选'}))
  if(path==='/characters/4/unlock-requests')return new Response(JSON.stringify({...role,write_enabled:true,wait_seconds:259200,collected_at:Date.now()/1000,items:[request]}))
  if(path==='/unlock-batches/preview'){
   p={action:'unlock-batch',reason:body.reason,role_count:1,request_count:1,targets:[{target:{accountname:'fixture',character:role},requests:[request]}],note:'设为到期不是已解锁'}
   return new Response(JSON.stringify({operation_id:op,preview:p,write_enabled:true,expires_at:Date.now()/1000+300}))
  }
  if(path.endsWith('/confirm')){
   if(options.reauth)return new Response('{"detail":"敏感操作需要重新认证"}',{status:403})
   if(options.conflict)return new Response('{"detail":"装备存档变化，请重新预览"}',{status:409})
   committed=true;if(options.lost)throw Error('lost response');return new Response(JSON.stringify(result))
  }
  if(path==='/operations/'+op)return new Response(JSON.stringify({operation_id:op,action:'unlock-batch',status:committed?'committed':'preview',preview:p,result:committed?result:null}))
  throw Error('Unknown route '+path)
 }))
 return {calls,mount:()=>mount(UnlockCenter,{attachTo:document.body})}
}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>b.text()===text);expect(b, text).toBeTruthy();await b!.trigger('click');await flushPromises()}
async function choose(w:any){await flushPromises();await click(w,'查看并选择申请');await w.find('[aria-label="选择解锁申请 1"]').setValue(true);await click(w,'加入批量处理清单（1项）')}
async function preview(w:any){await choose(w);await w.find('#unlock-batch-reason').setValue('测试整批提前处理');await click(w,'生成批量解锁预览')}
it('search and keyset navigation remain read only',async()=>{
 const x=setup({next:25}),w=x.mount();await flushPromises();await w.find('[aria-label="解锁角色搜索"]').setValue('测试');await w.find('form').trigger('submit');await flushPromises();expect(x.calls.at(-1).path).toContain('q='+encodeURIComponent('测试'))
 await click(w,'下一页申请角色');expect(x.calls.at(-1).path).toContain('after=25');await click(w,'上一页申请角色');expect(x.calls.at(-1).path).toContain('after=0');expect(x.calls.every(c=>c.method==='GET')).toBe(true);w.unmount()
})
it('selects explicit request, shows adjacent reason error and previews exact target',async()=>{
 const x=setup(),w=x.mount();await choose(w);expect(w.text()).toContain('1 个角色');await click(w,'生成批量解锁预览');expect(w.find('#unlock-batch-reason-error').text()).toContain('原因');expect(x.calls.filter(c=>c.method!=='GET')).toHaveLength(0)
 await w.find('#unlock-batch-reason').setValue('提前处理');await click(w,'生成批量解锁预览');expect(x.calls.at(-1).body).toEqual({reason:'提前处理',targets:[{uid:3,charac_no:4,lock_keys:[1]}]});expect(w.text()).toContain('合成装备');expect(w.text()).toContain('全部拒绝');w.unmount()
})
it('same character selection replaces rather than duplicates basket',async()=>{
 const x=setup(),w=x.mount();await choose(w);await choose(w);expect(w.findAll('.unlock-basket-row')).toHaveLength(1);w.unmount()
})
it('querying an unsubmitted local preview does not disable its confirmation',async()=>{
 const x=setup(),w=x.mount();await preview(w);await click(w,'查询原批次结果');expect(w.findAll('button').find(b=>b.text()==='确认整批提前处理一次')!.attributes('disabled')).toBeUndefined();expect(x.calls.some(c=>c.path.endsWith('/confirm'))).toBe(false);w.unmount()
})
it('confirmation submits once and reports database-only completion',async()=>{
 const x=setup(),w=x.mount();await preview(w);await click(w,'确认整批提前处理一次');expect(x.calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(1);expect(w.text()).toContain('不是游戏已解锁');expect(w.text()).not.toContain('确认整批提前处理一次');expect(sessionStorage.getItem(storage)).toBeNull();w.unmount()
})
it('lost reply blocks retries, persists original id and recovers after remount with GET only',async()=>{
 const x=setup({lost:true});let w=x.mount();await preview(w);await click(w,'确认整批提前处理一次');expect(w.text()).toContain('结果待确认');expect(w.findAll('button').find(b=>b.text()==='确认整批提前处理一次')!.attributes('disabled')).toBeDefined();expect(JSON.parse(sessionStorage.getItem(storage)!)).toEqual({id:op,uncertain:true});w.unmount()
 const n=x.calls.length;w=x.mount();await flushPromises();expect(w.text()).toContain('不是游戏已解锁');expect(x.calls.slice(n).every(c=>c.method==='GET')).toBe(true);expect(x.calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(1);w.unmount()
})
it('restores unsubmitted preview without accidentally confirming it',async()=>{
 const x=setup();let w=x.mount();await preview(w);w.unmount();w=x.mount();await flushPromises();expect(w.text()).toContain('尚未提交的预览');await click(w,'放弃此预览并重选');expect(x.calls.some(c=>c.path.endsWith('/confirm'))).toBe(false);expect(w.find('#unlock-batch-reason').exists()).toBe(true);w.unmount()
})
it('changed inventory is an inline conflict, with no automatic retry',async()=>{
 const x=setup({conflict:true}),w=x.mount();await preview(w);await click(w,'确认整批提前处理一次');expect(w.find('[role=alert]').text()).toContain('存档变化');expect(x.calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(1);await click(w,'放弃此预览并重选');w.unmount()
})
it('reauthentication request is explicit and never automatically replays confirmation',async()=>{
 const x=setup({reauth:true}),w=x.mount();await preview(w);await click(w,'确认整批提前处理一次');expect(w.emitted('reauth')).toHaveLength(1);expect(x.calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(1);w.unmount()
})
it('countdown is anchored to server snapshot and stops selecting expired requests',async()=>{
 vi.useFakeTimers({toFake:['setInterval','clearInterval','Date']});setup();const w=mount(UnlockRequests,{props:{characNo:4,selectOnly:true}});await flushPromises();expect(w.text()).toContain('1分 40秒');await vi.advanceTimersByTimeAsync(101000);expect(w.text()).toContain('已到期，待游戏处理');expect(w.find('[aria-label="选择解锁申请 1"]').attributes('disabled')).toBeDefined();w.unmount()
})
