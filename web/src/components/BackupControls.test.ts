// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import BackupControls from './BackupControls.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{constructor(message:string,public status:number){super(message)}},uncertainMessage:(e:any)=>e.message}))
const sample=()=>({policy:{revision:1,enabled:true,hour:4,minute:0,retention_days:7,failure_alerts:true},worker:{state:'ready',checked_at:1,failure:false},items:[],has_more:false,next_due_at:2})
let wrappers:any[]=[]
beforeEach(()=>{sessionStorage.clear();vi.mocked(api).mockReset();vi.mocked(api).mockResolvedValue(sample())})
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers=[];sessionStorage.clear();vi.restoreAllMocks()})
function setup(){const w=mount(BackupControls);wrappers.push(w);return w}
async function button(w:any,name:string){await w.findAll('button').find((b:any)=>b.text()===name).trigger('click');await flushPromises()}
it('keeps input errors beside controls and submits a durable manual request once',async()=>{
 const w=setup();await flushPromises();await w.get('[aria-label="备份保留天数"]').setValue('0');await w.findAll('form')[0].trigger('submit');await flushPromises()
 expect(w.get('[aria-label="备份保留天数"]').element.parentElement!.textContent).toContain('1–30天')
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
 vi.mocked(api).mockImplementation(async(path,method,body:any)=>path==='/backups/runs'?{run_id:body.request_id,state:'queued'}:sample())
 await w.findAll('form')[1].trigger('submit');await flushPromises()
 expect(w.text()).toContain('不是已完成备份');expect(w.text()).toContain('不停止GM或游戏')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0]==='/backups/runs'&&c[1]==='POST')).toHaveLength(1)
 expect(w.find('a[download]').exists()).toBe(false)
})
it('recovers an uncertain settings save by GET without replaying the POST',async()=>{
 const id='b'.repeat(32);sessionStorage.setItem('dnfgm-backup-request',JSON.stringify({kind:'policy',id}))
 vi.mocked(api).mockImplementation(async path=>path.startsWith('/backups/policy/requests/')?{status:'committed',policy:{...sample().policy,revision:2,enabled:false}}:sample())
 const w=setup();await flushPromises();expect(w.get('button.primary').attributes('disabled')).toBeDefined()
 await button(w,'查询原备份请求')
 expect(api).toHaveBeenCalledWith('/backups/policy/requests/'+id)
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true);expect(w.text()).toContain('已按原编号确认')
 expect(sessionStorage.getItem('dnfgm-backup-request')).toBeNull()
})
