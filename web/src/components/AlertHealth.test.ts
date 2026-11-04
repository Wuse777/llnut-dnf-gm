// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,afterEach,it,expect,vi} from 'vitest'
import AlertHealth from './AlertHealth.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn()}))
let wrappers:any[]=[]
function sample(){return {state:'ok',updated_at:100,notification:{state:'accepted',last_accepted:100,last_attempt:100},pending_count:0,rules:[{key:'gm',label:'GM接口不可用',active:false,observed:'healthy',pending_confirmation:false}],history:[]}}
function render(){const w=mount(AlertHealth);wrappers.push(w);return w}
beforeEach(()=>{vi.mocked(api).mockReset();vi.mocked(api).mockResolvedValue(sample())})
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers=[];vi.useRealTimers();vi.restoreAllMocks()})
it('uses only authenticated read route and distinguishes acceptance from delivery',async()=>{const w=render();await flushPromises();expect(api).toHaveBeenCalledWith('/alerts');expect(w.text()).toContain('不代表人已收到');expect(w.text()).toContain('最近观测正常');expect(w.findAll('button')).toHaveLength(1)})
it('shows unavailable and expired reports without current healthy claims',async()=>{vi.mocked(api).mockResolvedValue({state:'unavailable'});const w=render();await flushPromises();expect(w.text()).toContain('不能据此判断服务正常');vi.mocked(api).mockResolvedValue({...sample(),state:'stale'});await w.find('button').trigger('click');await flushPromises();expect(w.text()).toContain('告警报告已过期');expect(w.text()).not.toContain('最近观测正常')})
it('unknown active alerts are not marked recovered and candidate changes are explicit',async()=>{const d=sample();d.rules[0].active=true;d.rules[0].observed='unknown';vi.mocked(api).mockResolvedValue(d);const w=render();await flushPromises();expect(w.text()).toContain('故障尚未确认恢复');d.rules[0].observed='healthy';d.rules[0].pending_confirmation=true;await w.find('button').trigger('click');await flushPromises();expect(w.text()).toContain('等待连续健康确认')})
it('clears old healthy content after read failure and puts the error next to refresh',async()=>{const w=render();await flushPromises();vi.mocked(api).mockRejectedValue(new Error('登录已过期'));await w.find('button').trigger('click');await flushPromises();expect(w.find('[role=alert]').text()).toBe('登录已过期');expect(w.text()).not.toContain('最近观测正常')})
it('escapes labels and does not render markup from reports',async()=>{const d=sample();d.rules[0].label='<img src=x onerror=alert(1)>';vi.mocked(api).mockResolvedValue(d);const w=render();await flushPromises();expect(w.find('img').exists()).toBe(false);expect(w.text()).toContain('<img src=x')})
it('polls only visible and never after unmount',async()=>{vi.useFakeTimers({toFake:['setInterval','clearInterval']});const visible=vi.spyOn(document,'hidden','get').mockReturnValue(false);const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(30000);expect(api).toHaveBeenCalledTimes(2);visible.mockReturnValue(true);await vi.advanceTimersByTimeAsync(60000);expect(api).toHaveBeenCalledTimes(2);w.unmount();wrappers=[];visible.mockReturnValue(false);await vi.advanceTimersByTimeAsync(60000);expect(api).toHaveBeenCalledTimes(2)})
