// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import CharacterPicker from './CharacterPicker.vue'
import RewardJobs from './RewardJobs.vue'
let wrapper:any
const row=(id:number,deleted=0)=>({charac_no:id,uid:7,charac_name:'测试'+id,lev:70,delete_flag:deleted})
afterEach(()=>{wrapper?.unmount();vi.unstubAllGlobals()})
function setup(){
 const fetcher=vi.fn(async(url:string)=>new Response(JSON.stringify({items:url.includes('page=2')?[row(51),row(52,1)]:Array.from({length:50},(_,i)=>row(i+1))})))
 vi.stubGlobal('fetch',fetcher)
 wrapper=mount(CharacterPicker,{props:{modelValue:'','onUpdate:modelValue':(v:string)=>wrapper.setProps({modelValue:v})}})
 return fetcher
}
async function click(text:string){await wrapper.findAll('button').find((b:any)=>b.text()===text).trigger('click');await flushPromises()}
it('retains checked recipients across pages, deduplicates imported IDs and excludes deleted rows',async()=>{
 const fetcher=setup();await flushPromises();await wrapper.get('[aria-label="选择角色 测试1 #1"]').setValue(true)
 await click('下一页角色');await wrapper.get('[aria-label="选择角色 测试51 #51"]').setValue(true)
 expect(wrapper.props('modelValue')).toBe('1, 51');expect(wrapper.get('[aria-label="选择角色 测试52 #52"]').attributes('disabled')).toBeDefined()
 await wrapper.setProps({modelValue:'1, 51, 51'});await wrapper.get('[aria-label="勾选本页可用角色"]').setValue(false)
 expect(wrapper.props('modelValue')).toBe('1');expect(fetcher.mock.calls.every(([url])=>url.includes('/characters?'))).toBe(true)
})
it('keeps invalid imports intact and reports lookup failures beside the picker',async()=>{
 const fetcher=setup();await flushPromises();await wrapper.setProps({modelValue:'1, abc'})
 expect(wrapper.get('[aria-label="选择角色 测试1 #1"]').attributes('disabled')).toBeDefined();expect(wrapper.props('modelValue')).toBe('1, abc')
 fetcher.mockRejectedValueOnce(new TypeError('offline'));await click('查询角色');expect(wrapper.find('[role="alert"]').exists()).toBe(true);expect(wrapper.findAll('tbody tr')).toHaveLength(0)
})
it('uses checkbox recipients in the existing schedule draft contract without writes',async()=>{
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({items:[row(9)]})));vi.stubGlobal('fetch',fetcher)
 wrapper=mount(RewardJobs,{props:{scheduleDraft:true}});await flushPromises()
 await wrapper.get('[aria-label="选择角色 测试9 #9"]').setValue(true)
 await wrapper.get('[aria-label="批量点券"]').setValue(10);await wrapper.get('[aria-label="批量发放原因"]').setValue('勾选测试')
 await wrapper.get('form').trigger('submit');await flushPromises()
 expect(wrapper.emitted('schedule')[0][0].targets).toEqual({mode:'selected',charac_nos:[9]})
 expect(fetcher.mock.calls).toHaveLength(1)
})
