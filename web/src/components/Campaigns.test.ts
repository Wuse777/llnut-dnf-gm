// @vitest-environment happy-dom
import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import Campaigns from './Campaigns.vue'
const cid='c'.repeat(32),op='a'.repeat(32),wrappers:any[]=[]
function campaign():any{return {id:cid,name:'回归补给',status:'active',activated:1,revision:1,definition:{name:'回归补给',description:'固定一期',dedupe:'account',targets:{mode:'all',min_level:0,max_level:255},template_id:7,template_version:2},reward:{},claims:{subjects:1,accounts:1},totals:[{metric:'cera',amount:'10'}],links:[],job_draft:{campaign_id:cid,targets:{mode:'all'},reward:{},account_reward_mode:'once_per_account',reason:'活动：回归补给'},note:'数据库提交不等于领取'}}
function setup(config:{sameSession?:boolean,loseCancel?:boolean,campaignWait?:{id:string,wait:Promise<void>}}={}){
 let lose=false,committed=false,cancelled=false
 const sameSession=config.sameSession!==false
 function operation(){return {operation_id:op,status:committed?'committed':cancelled?'cancelled':'preview',same_session:sameSession,confirmable:sameSession&&!committed&&!cancelled,preview:{definition:campaign().definition,reward:{currency_rewards:{cera:10},gold:0},binding:{snapshot:{rewards:{items:[]}}},status:'active'},result:committed?{campaign_id:cid}:null}}
 const fetcher=vi.fn(async(url:any,options:any)=>{
  const path=String(url)
  if(path.endsWith('/audience-schema'))return new Response(JSON.stringify({character_dates:{available:true,note:'角色存档日期'},returning:{note:'仅离线'},account_registration:{available:false}}))
  if(path.includes('/gift-templates?'))return new Response(JSON.stringify({items:[{id:7,name:'补给礼包',current_version:2}]}))
  if(path.includes('/gift-templates/7/versions'))return new Response(JSON.stringify({items:[{version:2},{version:1}]}))
  if(path.endsWith('/campaigns/preview')){const d=JSON.parse(options.body);return new Response(JSON.stringify({operation_id:op,preview:{definition:d,reward:{currency_rewards:{cera:10},gold:0},binding:{snapshot:{rewards:{items:[]}}},status:d.status,note:'只保存活动'}}))}
  if(path.endsWith('/confirm')){if(lose)throw new TypeError('connection lost');committed=true;return new Response(JSON.stringify({campaign_id:cid}))}
  if(path.endsWith('/cancel')){if(!committed)cancelled=true;if(config.loseCancel)throw new TypeError('cancel response lost');return new Response(JSON.stringify(operation()))}
  if(path.includes('/operations/'))return new Response(JSON.stringify(operation()))
  if(/\/campaigns\/[a-f0-9]{32}$/.test(path)){if(config.campaignWait&&path.endsWith('/'+config.campaignWait.id))await config.campaignWait.wait;const row=campaign();row.id=path.split('/').at(-1)!;row.job_draft.campaign_id=row.id;row.links=[{kind:'job',reference_id:'b'.repeat(32),status:'finished'},{kind:'schedule',reference_id:'d'.repeat(32),status:'active'},{kind:'reward',reference_id:'e'.repeat(32),status:'committed'}];return new Response(JSON.stringify(row))}
  return new Response(JSON.stringify({items:[campaign()],has_more:false}))
 })
 vi.stubGlobal('fetch',fetcher)
 const wrapper=mount(Campaigns,{attachTo:document.body});wrappers.push(wrapper)
 return {wrapper,fetcher,lose:()=>{lose=true},resolve:()=>{committed=true}}
}
async function click(w:any,label:string){await w.findAll('button').find((b:any)=>b.text()===label)!.trigger('click');await flushPromises()}
async function fill(w:any){await w.get('[aria-label="活动名称"]').setValue('回归一期');await w.get('[aria-label="活动操作原因"]').setValue('准备活动');await click(w,'查找礼包');await click(w,'补给礼包 #7')}
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;sessionStorage.clear();vi.unstubAllGlobals();document.body.innerHTML=''})
it('validates a campaign before any preview or reward writes',async()=>{
 const {wrapper:w,fetcher}=setup();await flushPromises();await w.get('form').trigger('submit');await flushPromises();expect(w.text()).toContain('请填写活动名称');expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
it('submits fixed gift version and verified character dates with tags without dispatching rewards',async()=>{
 const {wrapper:w,fetcher}=setup();await flushPromises();await fill(w)
 await w.get('[aria-label="活动玩家标签"]').setValue('回归, 公会');await w.get('[aria-label="角色创建起日"]').setValue('2026-10-01');await w.get('[aria-label="最后游玩早于"]').setValue('2026-11-01');await w.get('form').trigger('submit');await flushPromises()
 const request=JSON.parse(fetcher.mock.calls.find(([u])=>String(u).endsWith('/campaigns/preview'))![1].body)
 expect(request).toMatchObject({template_id:7,template_version:2,dedupe:'account',targets:{tags_all:['回归','公会'],created_from:'2026-10-01',inactive_before:'2026-11-01'}})
 expect(fetcher.mock.calls.some(([u])=>/reward-jobs|schedules/.test(String(u)))).toBe(false);expect(w.text()).toContain('角色创建日不是账号注册日')
})
it('emits the server campaign draft while keeping an activated definition read only',async()=>{
 const {wrapper:w}=setup();await flushPromises();await click(w,'回归补给进行中 · 修订 1')
 expect(w.get('[aria-label="活动名称"]').element.closest('fieldset')?.disabled).toBe(true)
 await click(w,'准备本活动批量发放');expect(w.emitted('batch')![0][0]).toMatchObject({campaign_id:cid,account_reward_mode:'once_per_account'})
})
it('restores uncertain save and queries its original operation without repeating confirmation',async()=>{
 const first=setup();await flushPromises();await fill(first.wrapper);await first.wrapper.get('form').trigger('submit');await flushPromises();first.lose();await click(first.wrapper,'确认保存活动');expect(first.wrapper.text()).toContain('保存结果待核对')
 first.wrapper.unmount();const second=setup();await flushPromises();expect(second.fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true);expect(second.wrapper.text()).toContain('保存结果待核对');expect(second.wrapper.findAll('button').some(b=>b.text()==='确认保存活动')).toBe(false)
 second.resolve();await click(second.wrapper,'核对原操作（只读）');expect(second.wrapper.text()).toContain('已按原编号核对');expect(second.fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
})
it('keeps a pending preview until explicitly returned for editing and clears its saved original on discard',async()=>{
 const {wrapper:w,fetcher}=setup();await flushPromises();await fill(w);await w.get('form').trigger('submit');await flushPromises()
 expect(sessionStorage.getItem('dnfgm.campaign-operation')).toContain(op)
 expect(w.findAll('button').find(b=>b.text()==='新建活动')!.attributes('disabled')).toBeDefined()
 expect(w.findAll('button').find(b=>b.text()==='回归补给进行中 · 修订 1')!.attributes('disabled')).toBeDefined()
 await w.get('form').trigger('submit');await flushPromises()
 expect(fetcher.mock.calls.filter(([u])=>String(u).endsWith('/campaigns/preview'))).toHaveLength(1)
 await click(w,'返回修改');expect(sessionStorage.getItem('dnfgm.campaign-operation')).toBeNull()
 await click(w,'新建活动');expect(w.find('[aria-label="活动变更预览"]').exists()).toBe(false)
})
it('recovers another login preview read only and explicitly cancels the original before editing',async()=>{
 sessionStorage.setItem('dnfgm.campaign-operation',JSON.stringify({id:op,key:'original-key',uncertain:true}))
 const {wrapper:w,fetcher}=setup({sameSession:false});await flushPromises()
 expect(fetcher.mock.calls.every(([,o])=>o.method==='GET')).toBe(true)
 expect(w.text()).toContain('当前登录不能确认这份预览')
 expect(w.findAll('button').some(b=>b.text()==='确认保存活动')).toBe(false)
 await click(w,'取消原预览并返回修改')
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST').map(([u])=>String(u))).toEqual(['/dnf-gm/api/v1/campaigns/operations/'+op+'/cancel'])
 expect(sessionStorage.getItem('dnfgm.campaign-operation')).toBeNull()
 expect(w.text()).toContain('原活动预览已取消')
 expect(w.findAll('button').find(b=>b.text()==='新建活动')!.attributes('disabled')).toBeUndefined()
})
it('keeps an unknown cancellation original and only reads it until cancellation is confirmed',async()=>{
 sessionStorage.setItem('dnfgm.campaign-operation',JSON.stringify({id:op,key:'original-key',uncertain:true}))
 const {wrapper:w,fetcher}=setup({sameSession:false,loseCancel:true});await flushPromises()
 await click(w,'取消原预览并返回修改')
 expect(JSON.parse(sessionStorage.getItem('dnfgm.campaign-operation')!)).toMatchObject({id:op,uncertain:true})
 expect(w.text()).toContain('保存结果待核对')
 expect(w.findAll('button').some(b=>b.text()==='取消原预览并返回修改')).toBe(false)
 const writes=fetcher.mock.calls.filter(([,o])=>o.method==='POST').length
 await click(w,'核对原操作（只读）')
 expect(w.text()).toContain('原活动预览已取消')
 expect(sessionStorage.getItem('dnfgm.campaign-operation')).toBeNull()
 expect(fetcher.mock.calls.filter(([,o])=>o.method==='POST')).toHaveLength(writes)
})
it('opens precise linked job and schedule ids and protects a pending preview from query changes',async()=>{
 const {wrapper:w,fetcher}=setup();await flushPromises();await w.setProps({initialCampaign:cid});await flushPromises()
 await click(w,'查看批量任务');await click(w,'查看定时计划');await click(w,'查看原操作')
 expect(w.emitted('navigate')).toEqual([[{page:'reward-jobs',id:'b'.repeat(32)}],[{page:'schedules',id:'d'.repeat(32)}]])
 expect(w.emitted('inspect')).toEqual([['e'.repeat(32)]])
 const next='f'.repeat(32);await w.setProps({initialCampaign:next});await flushPromises()
 expect(fetcher.mock.calls.some(([u])=>String(u).endsWith('/'+next))).toBe(true)
 await w.get('[aria-label="活动操作原因"]').setValue('暂停活动');await w.get('form').trigger('submit');await flushPromises()
 const reads=fetcher.mock.calls.length;await w.setProps({initialCampaign:cid});await flushPromises()
 expect(fetcher.mock.calls).toHaveLength(reads)
 expect(w.text()).toContain('已保留原编号')
 expect(sessionStorage.getItem('dnfgm.campaign-operation')).toContain(op)
})
it('opens the latest campaign query after an older detail read finishes without applying that stale result',async()=>{
 let release!:()=>void
 const first='1'.repeat(32),latest='2'.repeat(32),wait=new Promise<void>(resolve=>{release=resolve})
 const {wrapper:w,fetcher}=setup({campaignWait:{id:first,wait}});await flushPromises()
 await w.setProps({initialCampaign:first});await flushPromises()
 await w.setProps({initialCampaign:latest});await flushPromises()
 release();await flushPromises()
 expect(fetcher.mock.calls.filter(([u])=>String(u).endsWith('/'+latest))).toHaveLength(1)
 await click(w,'准备本活动批量发放')
 expect(w.emitted('batch')?.[0][0]).toMatchObject({campaign_id:latest})
})
