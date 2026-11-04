// @vitest-environment happy-dom
import {mount} from '@vue/test-utils'
import {expect,it} from 'vitest'
import ItemQueue from './ItemQueue.vue'

it.each(['mail','gift'])('allows quantities above PVF caps and multiple equipment copies in %s',async(prefix)=>{
 const items=[{id:1,name:'未知上限',stack_limit:0,quantity:1},
 {id:2,name:'已知上限',category:'material',stack_limit:99,quantity:1},
 {id:3,name:'装备',category:'equipment',single_item:true,stack_limit:1,quantity:1}]
 const wrapper=mount(ItemQueue,{props:{items,busy:false,prefix,errors:{}}})
 const inputs=wrapper.findAll('input[type="number"]')
 for(const input of inputs){
  expect(input.attributes('disabled')).toBeUndefined()
  expect(input.attributes('max')).toBe('2147483647')
  await input.setValue('1000001')
 }
 expect(wrapper.emitted('quantity')).toEqual([[0,1000001],[1,1000001],[2,1000001]])
 expect(wrapper.text()).toContain('发放不限量')
 expect(wrapper.text()).toContain('每件独立投递')
})
