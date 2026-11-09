// @vitest-environment happy-dom
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createPinia,setActivePinia} from 'pinia'
import GameBackupControls from './GameBackupControls.vue'
import MailCenter from './MailCenter.vue'
import RewardJobs from './RewardJobs.vue'
import PlayerInvestigation from './PlayerInvestigation.vue'

const id='a'.repeat(32),campaignId='c'.repeat(32),windowId='d'.repeat(32)
const wrappers:any[]=[]
function render(component:any,props:any={}){const w=mount(component,{props,attachTo:document.body});wrappers.push(w);return w}
function reply(value:any){return new Response(JSON.stringify(value))}
async function click(w:any,text:string){const b=w.findAll('button').find((button:any)=>button.text()===text);expect(b,'Missing '+text).toBeTruthy();await b!.trigger('click');await flushPromises()}
beforeEach(()=>{sessionStorage.clear();setActivePinia(createPinia())})
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;vi.unstubAllGlobals();sessionStorage.clear();document.body.innerHTML=''})
const worker={configured:true,copy_configured:true,rehearsal_configured:true}
function run(state='preview'){return {run_id:id,backup_id:id,action:'backup',state,window_id:windowId,reason:'test',fingerprint:'f'.repeat(64),created_at:1794000000,expires_at:1794000300}}

it('keeps a timed-out backup confirmation and only queries that original request after reload',async()=>{
 let result:any=run()
 const fetcher=vi.fn(async(url:any,options:any)=>{const path=String(url);if(path.endsWith('/confirm'))throw new TypeError('connection lost');if(path.endsWith('/preview'))return reply(result);if(path.endsWith('/'+id))return reply(result);return reply({items:[],worker,has_more:false})})
 vi.stubGlobal('fetch',fetcher)
 const w=render(GameBackupControls);await flushPromises();await w.get('[aria-label="游戏备份维护窗口"]').setValue(windowId);await w.get('[aria-label="游戏备份原因"]').setValue('fixture');await w.get('form.backup-form').trigger('submit');await flushPromises();await w.get('input[type=checkbox]').setValue(true);await click(w,'确认创建该恢复点');expect(w.text()).toContain('请求结果待核对');expect(JSON.parse(sessionStorage.getItem('dnfgm.game-backup-request')!).id).toBe(id)
 w.unmount();result=run('queued');const writes=fetcher.mock.calls.filter(([,o])=>o?.method==='POST').length;const second=render(GameBackupControls);await flushPromises();expect(second.text()).toContain('已排队');expect(fetcher.mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(writes);expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/'+id))).toBe(true)
})

it('shows independent evidence tied to the restore point even when a newer copy attempt failed',async()=>{
 const backup=run('succeeded'),copy={run_id:'b'.repeat(32),backup_id:id,action:'copy',state:'failed',finished_at:1794001000}
 const success={...copy,state:'succeeded',finished_at:1794000500}
 vi.stubGlobal('fetch',vi.fn(async(url:any,_options?:any)=>String(url).endsWith('/'+id)?reply({...backup,evidence:{artifact_sha256:'1'.repeat(64),backup,copy:{latest_attempt:copy,verified_run:success},rehearse:{latest_attempt:null,verified_run:null}},related_runs:[]}):reply({items:[backup],worker,has_more:false})))
 const w=render(GameBackupControls,{initialRun:id});await flushPromises();const cards=w.findAll('.backup-stages article');expect(cards[0].text()).toContain('成功');expect(cards[1].text()).toContain('失败');expect(cards[1].text()).toContain('同一文件已有成功收据');expect(cards[2].text()).toContain('尚无对应执行记录')
})

it('sends bounded mail search filters and rejects reversed dates without another read',async()=>{
 const fetcher=vi.fn(async(_url:any,_options?:any)=>reply({items:[],has_more:false}));vi.stubGlobal('fetch',fetcher);const w=render(MailCenter,{uid:3,characNo:4,lockedTarget:true});await flushPromises();await w.get('[aria-label="邮件名称搜索"]').setValue('剑魂');await w.get('[aria-label="邮件物品编号"]').setValue('99');await w.get('[aria-label="邮件礼包编号"]').setValue('8');await w.get('[aria-label="邮件领取标记"]').setValue('record_missing');await w.get('[aria-label="邮件开始日期"]').setValue('2026-11-01');await w.get('[aria-label="邮件结束日期"]').setValue('2026-11-09');await w.get('form').trigger('submit');await flushPromises();const url=new URL(String(fetcher.mock.calls.at(-1)![0]),'http://localhost');expect(Object.fromEntries(url.searchParams)).toMatchObject({uid:'3',charac_no:'4',q:'剑魂',item_id:'99',template_id:'8',receipt:'record_missing',created_from:'2026-11-01',created_to:'2026-11-09'});const reads=fetcher.mock.calls.length;await w.get('[aria-label="邮件开始日期"]').setValue('2026-11-10');await w.get('form').trigger('submit');await flushPromises();expect(w.text()).toContain('开始日期不能晚于结束日期');expect(fetcher).toHaveBeenCalledTimes(reads)
})

it('does not display another player mail detail inside a locked investigation target',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:any,_options?:any)=>String(url).includes('/mail-center?')?reply({items:[],has_more:false}):reply({batch:{target_uid:9,charac_no:10},items:[]})))
 const w=render(MailCenter,{uid:3,characNo:4,lockedTarget:true,operationId:id,inlineDetails:true,allowDraft:false});await flushPromises();expect(w.text()).toContain('不属于当前问题');expect(w.text()).not.toContain('另建奖励草稿')
})

it('keeps campaign targets and rewards fixed in the batch preview request',async()=>{
 const draft={campaign_id:campaignId,targets:{mode:'filtered',tags_all:['回归'],inactive_before:'2026-10-01'},reward:{},account_reward_mode:'once_per_account',reason:'活动：秋日'}
 const fetcher=vi.fn(async(url:any,_options?:any)=>{const path=String(url);if(path.endsWith('/campaigns/'+campaignId))return reply({name:'秋日',definition:{template_id:9,template_version:2,dedupe:'account',targets:draft.targets},reward:{}});if(path.includes('/targets?'))return reply({items:[],next_after:null});if(path.endsWith('/preview'))return reply({id,status:'preview',fingerprint:'f'.repeat(64),target_count:0,account_count:0,worker_enabled:false,request:draft,preview:{rewards:{items:[]},currency_totals:{},gold_total:'0'},counts:{}});return reply({items:[],has_more:false})})
 vi.stubGlobal('fetch',fetcher);const w=render(RewardJobs,{initialDraft:draft});await flushPromises();expect(w.find('[aria-label="目标模式"]').exists()).toBe(false);expect(w.text()).toContain('重复目标跳过整份礼包');await w.get('form').trigger('submit');await flushPromises();const request=fetcher.mock.calls.find(([url])=>String(url).endsWith('/preview'))!;expect(JSON.parse((request[1] as any).body)).toEqual(draft);expect(fetcher.mock.calls.some(([url])=>String(url).endsWith('/start'))).toBe(false)
})

it('filters failed batch targets by state and reason and keeps uncertain original operation queryable',async()=>{
 const operation='e'.repeat(32)
 const fetcher=vi.fn(async(url:any,_options?:any)=>{const path=String(url);if(path.includes('/targets?'))return reply({items:[{ordinal:7,target_uid:3,charac_no:4,target:{charac_name:'角色',accountname:'账号'},operation_id:operation,status:'uncertain',attempts:1,error_type:'busy',error_message:'稍后核对'}],next_after:null,errors:[{error_type:'busy',n:1}]});if(path.endsWith('/'+id))return reply({id,status:'needs_attention',reason:'test',counts:{uncertain:1},request:{targets:{},reward:{}},preview:{currency_totals:{},rewards:{items:[]}},worker_enabled:true});return reply({items:[],has_more:false})})
 vi.stubGlobal('fetch',fetcher);const w=render(RewardJobs,{initialJob:id,initialStatus:'uncertain'});await flushPromises();await w.get('[aria-label="目标失败原因"]').setValue('busy');await w.findAll('form').find(f=>f.find('[aria-label="目标失败原因"]').exists())!.trigger('submit');await flushPromises();expect(fetcher.mock.calls.some(([url])=>String(url).includes('status=uncertain&error_type=busy'))).toBe(true);await click(w,'查看原操作结果');expect(w.emitted('inspect')?.[0]).toEqual([operation]);expect(fetcher.mock.calls.every(([,options])=>!options?.method||options.method==='GET')).toBe(true)
})

it('rejects an original operation for a different player and saves checklist as a draft only',async()=>{
 const fetcher=vi.fn(async(url:any,_options?:any)=>{const path=String(url);if(path.endsWith('/overview'))return reply({character:{uid:3,charac_no:4,charac_name:'角色'},account_online:{login_status:0},equipment:{items:[]}});if(path.includes('/mail-center?'))return reply({items:[],has_more:false});return reply({operation_id:id,action:'mail',status:'committed',request:{uid:9,charac_no:10}})})
 vi.stubGlobal('fetch',fetcher);const w=render(PlayerInvestigation,{record:{uid:3,charac_no:4,category:'mail'},links:[]});await flushPromises();await w.get('[aria-label="排查原操作编号"]').setValue(id);await w.get('form').trigger('submit');await flushPromises();expect(w.text()).toContain('原操作目标与当前问题不一致');await w.get('input[type=checkbox]').setValue(true);await click(w,'加入处理记录草稿');expect(w.emitted('note')?.[0][0]).toContain('已核对');expect(fetcher.mock.calls.every(([,options])=>!options?.method||options.method==='GET')).toBe(true)
})
