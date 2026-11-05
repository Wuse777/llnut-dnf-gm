// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {afterEach,it,expect,vi} from 'vitest'
import EnchantmentPicker from './EnchantmentPicker.vue'
import EquipmentComparison from './EquipmentComparison.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),uncertainMessage:(e:any)=>e.message}))
let wrappers:any[]=[]
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers=[];vi.resetAllMocks()})
it('searches PVF-defined effects, selects an ID and allows clearing without writing',async()=>{
 vi.mocked(api).mockResolvedValue({state:'ok',metadata_state:'ok',page:1,has_more:false,items:[{id:3604,name:'烈焰彼诺修卡片',target_names:['武器'],summary:'攻击属性 火属性'}]})
 const w=mount(EnchantmentPicker,{props:{modelValue:'0'}});wrappers.push(w)
 await w.get('[aria-label="附魔搜索条件"]').setValue('火属性');await w.findAll('button').find(b=>b.text()==='查询附魔')!.trigger('click');await flushPromises()
 expect(api).toHaveBeenCalledWith('/catalog/enchantments?q=%E7%81%AB%E5%B1%9E%E6%80%A7&page=1')
 expect(w.text()).toContain('攻击属性 火属性');await w.get('[aria-label="选择附魔 3604 烈焰彼诺修卡片"]').trigger('click')
 expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['3604'])
 await w.setProps({modelValue:'3604'});expect(w.text()).toContain('已选择')
 await w.findAll('button').find(b=>b.text()==='清除附魔')!.trigger('click');expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['0'])
 expect(vi.mocked(api).mock.calls.every(c=>!c[1])).toBe(true)
})
it('keeps mismatch results read-only and shows before/after enchant names',async()=>{
 vi.mocked(api).mockResolvedValue({state:'mismatch',metadata_state:'ok',page:1,has_more:false,items:[{id:3604,name:'卡片',target_names:[],summary:'原值'}]})
 const w=mount(EnchantmentPicker,{props:{modelValue:'0'}});wrappers.push(w);await w.findAll('button').find(b=>b.text()==='查询附魔')!.trigger('click');await flushPromises()
 expect(w.get('[aria-label="选择附魔 3604 卡片"]').attributes('disabled')).toBeDefined()
 const comparison=mount(EquipmentComparison,{props:{preview:{item_name:'测试装备',before:{id:1,enhancement:3,orb_id:0},after:{id:1,enhancement:12,orb_id:3604},before_enchantment:{name:'无附魔'},after_enchantment:{id:3604,name:'烈焰彼诺修卡片',summary:'攻击属性 火属性'}}}});wrappers.push(comparison)
 expect(comparison.text()).toContain('修改前');expect(comparison.text()).toContain('烈焰彼诺修卡片');expect(comparison.text()).toContain('修改后')
})
