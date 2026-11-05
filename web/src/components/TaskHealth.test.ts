// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,afterEach,it,expect,vi} from 'vitest'
import TaskHealth from './TaskHealth.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn()}))
const id='a'.repeat(32)
let wrappers:any[]=[]
function sample(){return {state:'attention',checked_at:100,issues:[{kind:'reward',id,code:'uncertain',ordinal:2}],workers:{rewards:{state:'responding',failures:0},schedules:{state:'disabled',failures:0}},truncated:false}}
function render(){const w=mount(TaskHealth);wrappers.push(w);return w}
beforeEach(()=>{vi.mocked(api).mockReset();vi.mocked(api).mockResolvedValue(sample())})
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers=[];vi.useRealTimers();vi.restoreAllMocks()})
it('shows uncertain rather than failed and opens original without any write',async()=>{const w=render();await flushPromises();expect(api).toHaveBeenCalledWith('/task-health');expect(w.text()).toContain('提交结果待核对');expect(w.text()).toContain('不自动重发');await w.findAll('button')[1].trigger('click');expect(w.emitted('inspect')).toEqual([['reward',id]]);expect(api).toHaveBeenCalledTimes(1)})
it('navigates schedules distinctly',async()=>{const d=sample();d.issues=[{kind:'schedule',id,code:'overdue',ordinal:0}];vi.mocked(api).mockResolvedValue(d);const w=render();await flushPromises();await w.findAll('button')[1].trigger('click');expect(w.emitted('inspect')).toEqual([['schedule',id]])})
it('does not display an incomplete or observing check as clear',async()=>{vi.mocked(api).mockResolvedValue({...sample(),state:'unknown',issues:[],truncated:true});const w=render();await flushPromises();expect(w.text()).toContain('列表不完整');expect(w.text()).toContain('不能判断任务正常');expect(w.text()).not.toContain('本次检查未发现');vi.mocked(api).mockResolvedValue({...sample(),state:'observing',issues:[],truncated:false});await w.find('button').trigger('click');await flushPromises();expect(w.text()).toContain('不能据此认定任务已经完成')})
it('clears old issues on fetch error and renders near its refresh',async()=>{const w=render();await flushPromises();vi.mocked(api).mockRejectedValue(new Error('读取失败'));await w.find('button').trigger('click');await flushPromises();expect(w.find('[role=alert]').text()).toBe('读取失败');expect(w.find('.task-issues').exists()).toBe(false)})
it('skips hidden polling and never polls after unmount',async()=>{vi.useFakeTimers({toFake:['setInterval','clearInterval']});const visible=vi.spyOn(document,'hidden','get').mockReturnValue(false);const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(30000);expect(api).toHaveBeenCalledTimes(2);visible.mockReturnValue(true);await vi.advanceTimersByTimeAsync(60000);expect(api).toHaveBeenCalledTimes(2);w.unmount();wrappers=[];visible.mockReturnValue(false);await vi.advanceTimersByTimeAsync(60000);expect(api).toHaveBeenCalledTimes(2)})
it('explains maintenance waiting without hiding uncertain targets or adding mutation calls',async()=>{vi.mocked(api).mockResolvedValue({...sample(),write_gate:{state:'frozen',operation_id:id}});const w=render();await flushPromises();expect(w.text()).toContain('维护已冻结新奖励和定时触发');expect(w.text()).toContain('提交结果待核对');expect(w.text()).toContain('不自动补发错过的期次');expect(vi.mocked(api).mock.calls.every(call=>!call[1])).toBe(true)})
it('explains an unverifiable gate without presenting healthy or completed tasks',async()=>{vi.mocked(api).mockResolvedValue({...sample(),state:'unknown',issues:[],write_gate:{state:'unknown'}});const w=render();await flushPromises();expect(w.text()).toContain('维护写入屏障无法核验');expect(w.text()).not.toContain('本次检查未发现待处理异常');expect(w.findAll('button')).toHaveLength(1)})
