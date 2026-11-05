// @vitest-environment happy-dom
import {mount} from '@vue/test-utils'
import {it,expect} from 'vitest'
import EquipmentComparison from './EquipmentComparison.vue'
const image={state:'ready',url:'/dnf-gm/api/v1/assets/'+ 'a'.repeat(64)+'/'+ 'b'.repeat(64)+'.png',note:'匹配图片'}
it('shows the exact fields being changed, text markers and native raw-value semantics',()=>{
 const w=mount(EquipmentComparison,{props:{preview:{item_name:'测试长剑',item_info:{part_name:'武器',base_durability:40},before:{id:123,enhancement:3,forge:0,amplify_type:0,amplify_value:0,durability:30,orb_id:0,quality_raw:4294967295},after:{id:123,enhancement:12,forge:0,amplify_type:0,amplify_value:0,durability:40,orb_id:0,quality_raw:4294967295}},currentItem:{id:123,image}}})
 expect(w.findAll('img')).toHaveLength(2)
 expect(w.findAll('.changed-marker')).toHaveLength(2)
 expect(w.findAll('.changed').map(e=>e.text())).toEqual(['+12','40PVF基础值 40'])
 expect(w.text()).toContain('原始字段，不是品级百分比');expect(w.text()).toContain('原始代码，未推断属性名称')
 w.unmount()
})
it('does not mislabel an empty slot as the old item after reclaim',()=>{
 const w=mount(EquipmentComparison,{props:{preview:{action:'item-reclaim',item_name:'测试长剑',before:{id:123,enhancement:3},after:{id:0,empty:true}}}})
 const after=w.get('[aria-label="修改后"]');expect(after.text()).toContain('空槽位');expect(after.text()).not.toContain('测试长剑');expect(after.find('dl').exists()).toBe(false)
 expect(w.text()).toContain('不影响其他槽位');w.unmount()
})
it('uses each side metadata for restored items and never reuses another item image',()=>{
 const w=mount(EquipmentComparison,{props:{preview:{item_name:'空槽位',before:{id:0,empty:true},after:{id:456,enhancement:5,orb_id:789},before_item_info:{},after_item_info:{name:'快照中的项链',part_name:'项链'},after_enchantment:{id:789,name:'测试附魔',summary:'力量 +10'}},currentItem:{id:123,image}}})
 const after=w.get('[aria-label="修改后"]');expect(after.text()).toContain('快照中的项链');expect(after.text()).toContain('测试附魔');expect(after.text()).toContain('力量 +10');expect(w.find('img').exists()).toBe(false);w.unmount()
})
it('keeps legacy records readable without falsely naming a different after item',()=>{
 const w=mount(EquipmentComparison,{props:{preview:{item_name:'旧版物品名称',item_info:{name:'旧版物品名称'},before:{id:123,quantity:1},after:{id:456,quantity:2147483647}}}})
 expect(w.get('[aria-label="修改前"]').text()).toContain('旧版物品名称');expect(w.get('[aria-label="修改后"]').text()).toContain('未知物品 #456');expect(w.text()).toContain('2,147,483,647');w.unmount()
})
