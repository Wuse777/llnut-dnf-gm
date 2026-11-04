// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import SupportDesk from './SupportDesk.vue'
import {api,ApiError} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{constructor(message:string,public status:number){super(message)}},uncertainMessage:(e:any)=>e.message}))
const cid='a'.repeat(32),operation='b'.repeat(32),storage='dnfgm-support-request'
let wrappers:any[]=[],profile:any,record:any,cases:any[],events:any[],links:any[],result:any
const mountDesk=(uid=900001)=>{const w=mount(SupportDesk,{props:{uid}});wrappers.push(w);return w}
async function click(w:any,text:string){const b=w.findAll('button').find((b:any)=>b.text()===text);expect(b,`missing ${text}`).toBeTruthy();if(b.element.type==='submit'&&b.element.form){await w.findAll('form').find((f:any)=>f.element===b.element.form)!.trigger('submit')}else await b.trigger('click');await flushPromises()}
async function open(w:any){await flushPromises();await w.get('.support-case').trigger('click');await flushPromises()}
beforeEach(()=>{
 sessionStorage.clear();profile={uid:900001,revision:0,notes:'',tags:[],target:{uid:900001,accountname:'测试账号'}}
 record={case_id:cid,uid:900001,charac_no:900001,title:'邮件未到账',category:'mail',description:'核对邮件',status:'open',revision:1,compensation_count:0,target:{accountname:'测试账号',character:{charac_no:900001,charac_name:'测试角色'}},updated_at:1793800000}
 cases=[record];events=[];links=[];result={request_id:'saved'.repeat(4),kind:'case-comment',state:'management_committed',uid:900001,case_id:cid,revision:2}
 vi.mocked(api).mockReset().mockImplementation(async(path,method='GET',body:any)=>{
  if(path.startsWith('/support/requests/'))return structuredClone(result)
  if(path.startsWith('/support/profiles/')){if(method==='PUT'){profile={...profile,notes:body.notes,tags:body.tags,revision:profile.revision+1};return {...result,kind:'player-profile',case_id:undefined}}return structuredClone(profile)}
  if(path.startsWith('/support/cases?'))return {items:structuredClone(cases),has_more:false,page:1}
  if(path==='/support/cases'&&method==='POST')return {...result,kind:'case-create',revision:1}
  if(method==='GET'&&path.startsWith('/support/cases/'))return {case:structuredClone(record),events:structuredClone(events),links:structuredClone(links),events_has_more:false,links_has_more:false}
  if(method!=='GET'&&path.startsWith('/support/cases/'))return structuredClone(result)
  throw new Error('Unexpected API '+path)
 })
})
afterEach(()=>{for(const w of wrappers)w.unmount();wrappers=[];sessionStorage.clear();vi.restoreAllMocks()})
it('loads scoped cases and account profile without any writes',async()=>{
 const w=mountDesk();await flushPromises();expect(w.text()).toContain('测试账号');expect(api).toHaveBeenCalledWith(expect.stringContaining('uid=900001'));expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('saves profile with expected revision and trims tags',async()=>{
 const w=mountDesk();await flushPromises();await w.get('[aria-label="账号备注"]').setValue('待核对');await w.get('[aria-label="玩家标签"]').setValue(' 活动，测试 ');await click(w,'保存账号备注与标签')
 expect(api).toHaveBeenCalledWith('/support/profiles/900001','PUT',expect.objectContaining({expected_revision:0,notes:'待核对',tags:['活动','测试'],idempotency_key:expect.any(String)}));expect(sessionStorage.getItem(storage)).toBeNull()
})
it('validates new case near fields instead of issuing an empty POST',async()=>{
 const w=mountDesk();await flushPromises();await click(w,'建立问题记录');await click(w,'保存新问题')
 expect(w.get('[aria-label="问题标题"]').element.parentElement!.textContent).toContain('请填写问题标题');expect(w.get('[aria-label="问题描述"]').element.parentElement!.textContent).toContain('请填写问题描述');expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('creates a case with explicit account and optional character, never rewards',async()=>{
 const w=mountDesk();await flushPromises();await click(w,'建立问题记录');await w.get('[aria-label="问题标题"]').setValue('测试');await w.get('[aria-label="问题描述"]').setValue('只保存问题');await w.get('[aria-label="问题角色编号"]').setValue('900001');await click(w,'保存新问题')
 expect(api).toHaveBeenCalledWith('/support/cases','POST',expect.objectContaining({uid:900001,charac_no:900001,title:'测试',description:'只保存问题'}));expect(vi.mocked(api).mock.calls.every(c=>c[0].startsWith('/support/'))).toBe(true)
})
it('puts backend save errors next to the relevant submit button',async()=>{
 const original=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation((p,m,...args)=>m==='PUT'?Promise.reject(new ApiError('记录已变化，请刷新',409)):original(p,m,...args))
 const w=mountDesk();await flushPromises();await w.get('[aria-label="账号备注"]').setValue('修改');await click(w,'保存账号备注与标签');expect(w.get('form.support-form').text()).toContain('记录已变化');expect(sessionStorage.getItem(storage)).toBeNull()
})
it('preserves unsaved account notes across comment refresh and blocks accidental context switch',async()=>{
 const w=mountDesk();await open(w);await w.get('[aria-label="账号备注"]').setValue('未保存备注');await w.get('[aria-label="处理记录"]').setValue('已核对');await click(w,'追加处理记录');expect((w.get('[aria-label="账号备注"]').element as HTMLTextAreaElement).value).toBe('未保存备注');await w.get('[aria-label="工作台账号 UID"]').setValue('900002');await click(w,'查询问题');expect(w.text()).toContain('先保存或放弃备注修改')
})
it('does not duplicate a timed out create and reload only queries original request',async()=>{
 const original=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation((p,m,...args)=>m==='PUT'?Promise.reject(new Error('网络中断')):original(p,m,...args))
 const w=mountDesk();await flushPromises();await click(w,'保存账号备注与标签');const id=sessionStorage.getItem(storage);expect(id).toBeTruthy();expect(w.text()).toContain('保存结果待确认');w.unmount();const before=vi.mocked(api).mock.calls.filter(c=>c[1]).length
 const second=mountDesk();await flushPromises();expect(api).toHaveBeenCalledWith('/support/requests/'+id);expect(vi.mocked(api).mock.calls.filter(c=>c[1])).toHaveLength(before);expect(second.text()).toContain('管理记录已保存')
})
it('missing receipt remains uncertain rather than claiming failure or retrying',async()=>{
 sessionStorage.setItem(storage,'z'.repeat(32));const original=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation((p,...args)=>p.includes('/requests/')?Promise.reject(new ApiError('暂未查到提交记录',404)):original(p,...args))
 const w=mountDesk();await flushPromises();expect(w.text()).toContain('保存结果待确认');expect(sessionStorage.getItem(storage)).toBe('z'.repeat(32));expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('creates compensation drafts with case target and does not POST from workbench',async()=>{
 record.compensation_count=2;const w=mountDesk();await open(w);expect(w.text()).toContain('2 笔补偿');await click(w,'创建余额纠正草稿');expect(w.emitted('compensate')?.[0]?.[0]).toMatchObject({case_id:cid,uid:900001,charac_no:900001,kind:'currency'});expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('links old operation explicitly without executing it',async()=>{
 const w=mountDesk();await open(w);await w.get('[aria-label="关联操作编号"]').setValue(operation);await w.get('[aria-label="关联说明"]').setValue('这是原投递');await click(w,'关联原操作');expect(api).toHaveBeenCalledWith('/support/cases/'+cid+'/links','POST',expect.objectContaining({expected_revision:1,operation_id:operation,relation:'reference',note:'这是原投递'}));expect(vi.mocked(api).mock.calls.some(c=>c[0].endsWith('/confirm'))).toBe(false)
})
it('status updates include revision and required processing note',async()=>{
 const w=mountDesk();await open(w);await click(w,'保存问题修改');expect(w.get('[aria-label="状态修改说明"]').element.parentElement!.textContent).toContain('请说明本次修改');await w.get('[aria-label="修改问题状态"]').setValue('resolved');await w.get('[aria-label="状态修改说明"]').setValue('核对后解决');await click(w,'保存问题修改');expect(api).toHaveBeenCalledWith('/support/cases/'+cid,'PUT',expect.objectContaining({status:'resolved',expected_revision:1,note:'核对后解决'}))
})
it('shows missing linked results as unknown and escapes stored content',async()=>{
 record.title='<img src=x onerror=alert(1)>';links=[{operation_id:operation,relation:'reference',status:null}];events=[{kind:'case-comment',revision:1,note:'<script>bad</script>',details:{},created_at:1793800000}];const w=mountDesk();await open(w);expect(w.find('img').exists()).toBe(false);expect(w.find('script').exists()).toBe(false);expect(w.text()).toContain('<script>bad</script>');expect(w.text()).toContain('原操作记录缺失')
})
it('global list does not read a fabricated profile',async()=>{
 const w=mountDesk(0);await flushPromises();expect(w.text()).toContain('输入账号 UID');expect(vi.mocked(api).mock.calls.some(c=>c[0].includes('/profiles/'))).toBe(false)
})

it('preserves edited case text and its original revision across a fresh detail read',async()=>{
 const w=mountDesk();await open(w);await w.get('[aria-label="修改问题标题"]').setValue('本地草稿');record.revision=2;record.title='另一次修改';await click(w,'刷新问题详情');expect((w.get('[aria-label="修改问题标题"]').element as HTMLInputElement).value).toBe('本地草稿');expect(w.text()).toContain('仍基于 v1');await w.get('[aria-label="状态修改说明"]').setValue('人工核对');await click(w,'保存问题修改');expect(api).toHaveBeenCalledWith('/support/cases/'+cid,'PUT',expect.objectContaining({expected_revision:1,title:'本地草稿'}))
})
it('blocks changing case or account with an unsaved comment until explicitly discarded',async()=>{
 const w=mountDesk();await open(w);await w.get('[aria-label="处理记录"]').setValue('未保存');await w.get('.support-case').trigger('click');await flushPromises();expect((w.get('[aria-label="处理记录"]').element as HTMLTextAreaElement).value).toBe('未保存');await click(w,'查询问题');expect(w.text()).toContain('当前问题还有未保存');await click(w,'放弃当前问题草稿');await click(w,'查询问题');expect(w.find('[aria-label="处理记录"]').exists()).toBe(false)
})
it('a folded new case draft cannot silently move to a different account',async()=>{
 const w=mountDesk();await flushPromises();await click(w,'建立问题记录');await w.get('[aria-label="问题标题"]').setValue('未保存');await click(w,'收起新问题');await w.get('[aria-label="工作台账号 UID"]').setValue('900002');await click(w,'查询问题');expect(w.text()).toContain('新问题尚未保存');expect(api).not.toHaveBeenCalledWith('/support/profiles/900002');await click(w,'建立问题记录');await click(w,'取消新问题并清空草稿');await click(w,'查询问题');expect(api).toHaveBeenCalledWith('/support/profiles/900002')
})

it('does not navigate or create a compensation draft while unsaved notes would be lost',async()=>{
 const w=mountDesk();await open(w);await w.get('[aria-label="账号备注"]').setValue('需要保存');await click(w,'创建余额纠正草稿');expect(w.emitted('compensate')).toBeUndefined();expect(w.text()).toContain('再离开工作台');expect(w.vm.canNavigate()).toBe(false);await click(w,'放弃备注修改');expect(w.vm.canNavigate()).toBe(true);await click(w,'创建余额纠正草稿');expect(w.emitted('compensate')).toHaveLength(1)
})
it('HTTP timeout is uncertain and retains the original receipt key',async()=>{
 const original=vi.mocked(api).getMockImplementation()!;vi.mocked(api).mockImplementation((p,m,...args)=>m==='PUT'?Promise.reject(new ApiError('网关超时',408)):original(p,m,...args));const w=mountDesk();await flushPromises();await click(w,'保存账号备注与标签');expect(w.text()).toContain('保存结果待确认');expect(sessionStorage.getItem(storage)).toBeTruthy()
})
