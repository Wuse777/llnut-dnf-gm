// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,afterEach,it,expect,vi} from 'vitest'
import BackupHealth from './BackupHealth.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn()}))
let wrappers:any[]=[]
function sample(){return {state:'ok',checked_at:100,policy:{backup_hours:24,restore_days:30},backup:{state:'recent',completed_at:95,artifact_sha256:'a'.repeat(64),bytes:123456,tables:30,rows:500},restore:{state:'recent',completed_at:99}}}
function render(){const w=mount(BackupHealth);wrappers.push(w);return w}
beforeEach(()=>{vi.mocked(api).mockReset();vi.mocked(api).mockResolvedValue(sample())})
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers=[];vi.useRealTimers();vi.restoreAllMocks()})
it('reports management scope, real restore evidence and a read-only route',async()=>{const w=render();await flushPromises();expect(api).toHaveBeenCalledWith('/backup-health');expect(w.text()).toContain('不包含游戏存档');expect(w.text()).toContain('已实际恢复这份备份');expect(w.findAll('button')).toHaveLength(1);expect(w.find('a[download]').exists()).toBe(false)})
it('missing evidence is not a successful backup',async()=>{vi.mocked(api).mockResolvedValue({state:'unavailable'});const w=render();await flushPromises();expect(w.text()).toContain('无法判断备份是否成功');expect(w.find('.backup-cards').exists()).toBe(false)})
it('stale and corrupted evidence hide old success',async()=>{vi.mocked(api).mockResolvedValue({...sample(),state:'stale'});const w=render();await flushPromises();expect(w.text()).toContain('证据已过期');expect(w.text()).not.toContain('已实际恢复这份备份');vi.mocked(api).mockResolvedValue({state:'integrity_failed'});await w.find('button').trigger('click');await flushPromises();expect(w.text()).toContain('校验失败')})
it('older artifact drills are distinguished from a current restore',async()=>{const d=sample();d.restore.state='other_artifact';vi.mocked(api).mockResolvedValue(d);const w=render();await flushPromises();expect(w.text()).toContain('不能证明当前备份可恢复');expect(w.text()).not.toContain('已实际恢复这份备份')})
it('clears old results and shows the failure beside the controls',async()=>{const w=render();await flushPromises();vi.mocked(api).mockRejectedValue(new Error('连接中断'));await w.find('button').trigger('click');await flushPromises();expect(w.find('[role=alert]').text()).toBe('连接中断');expect(w.find('.backup-cards').exists()).toBe(false)})
it('pauses hidden polling and stops after unmount',async()=>{vi.useFakeTimers({toFake:['setInterval','clearInterval']});const visible=vi.spyOn(document,'hidden','get').mockReturnValue(false);const w=render();await flushPromises();await vi.advanceTimersByTimeAsync(30000);expect(api).toHaveBeenCalledTimes(2);visible.mockReturnValue(true);await vi.advanceTimersByTimeAsync(60000);expect(api).toHaveBeenCalledTimes(2);w.unmount();wrappers=[];visible.mockReturnValue(false);await vi.advanceTimersByTimeAsync(60000);expect(api).toHaveBeenCalledTimes(2)})
