// @vitest-environment happy-dom
import {afterEach,beforeEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import TargetedMessageFields from './TargetedMessageFields.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{constructor(message:string,public status:number){super(message)}},uncertainMessage:(e:any)=>e.message}))
let wrappers:any[]=[]
const ready={implemented:true,enabled:true,ready:true,bridge_state:'ready',note:'只请求显示消息，不保证客户端送达'}
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api).mockImplementation(async path=>path==='/native-controls/status'?{private_message:ready}:{items:[{charac_no:990002,charac_name:'本地角色',lev:60,delete_flag:0},{charac_no:990003,charac_name:'已删角色',lev:1,delete_flag:1}]})})
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers=[]})
const setup=(account:any={uid:990001,accountname:'合成账号'})=>{const w=mount(TargetedMessageFields,{props:{account}});wrappers.push(w);return w}
it('reads readiness and only chooses a non-deleted character from the selected account',async()=>{
 const w=setup();await flushPromises();expect(api).toHaveBeenCalledWith('/characters?uid=990001&page=1');expect(w.text()).toContain('已就绪，可生成预览');expect(w.emitted('ready')?.at(-1)).toEqual([true])
 await w.get('select').setValue('990002');expect(w.emitted('update:characNo')?.at(-1)).toEqual([990002]);await w.get('select').setValue('990003');expect(w.emitted('update:characNo')?.at(-1)).toEqual([null]);expect(w.find('option[value="990003"]').attributes('disabled')).toBeDefined()
})
it('shows actual disabled or bridge unavailable status without claiming the action is ready',async()=>{
 vi.mocked(api).mockImplementation(async path=>path==='/native-controls/status'?{private_message:{...ready,enabled:false,ready:false,bridge_state:'disabled',note:'未激活生产桥接'}}:{items:[]})
 const w=setup();await flushPromises();expect(w.text()).toContain('能力已停用');expect(w.text()).toContain('未激活生产桥接');expect(w.emitted('ready')?.at(-1)).toEqual([false])
 vi.mocked(api).mockResolvedValueOnce({private_message:{...ready,ready:false,bridge_state:'unavailable'}});await w.findAll('button').find(b=>b.text()==='重新核验消息能力')!.trigger('click');await flushPromises();expect(w.text()).toContain('游戏桥接未就绪')
})
it('clears the old target on account change and ignores a late character response',async()=>{
 let release!:(r:any)=>void;vi.mocked(api).mockImplementation(path=>path.includes('uid=990001')?new Promise(r=>{release=r}):Promise.resolve(path==='/native-controls/status'?{private_message:ready}:{items:[{charac_no:990009,charac_name:'新账号角色',delete_flag:0}]}))
 const w=setup();await w.setProps({account:{uid:990008,accountname:'新账号'}});await flushPromises();release({items:[{charac_no:990002,charac_name:'旧账号角色',delete_flag:0}]});await flushPromises();expect(w.text()).toContain('新账号角色');expect(w.text()).not.toContain('旧账号角色');expect(w.emitted('update:characNo')?.at(-1)).toEqual([null])
})
it('keeps capability unknown after a failed read and offers explicit retry',async()=>{
 vi.mocked(api).mockImplementation(path=>path==='/native-controls/status'?Promise.reject(new Error('状态读取中断')):Promise.resolve({items:[]}));const w=setup();await flushPromises();expect(w.text()).toContain('能力状态读取失败');expect(w.emitted('ready')?.at(-1)).toEqual([false]);expect(w.text()).toContain('重新核验消息能力')
})
