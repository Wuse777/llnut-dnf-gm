// @vitest-environment happy-dom
import {expect,it,vi} from 'vitest'
import {mount} from '@vue/test-utils'
import ItemQuickFacts from './ItemQuickFacts.vue'
it('shows only known PVF facts and stored enhancement without deriving combat stats',()=>{
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher)
 const wrapper=mount(ItemQuickFacts,{props:{stored:true,item:{id:102,name:'测试短剑',rarity_name:'史诗',level:60,part_name:'武器',enhancement:12,usable_jobs:[{name:'鬼剑士'}],set_id:8,set_name:'测试套装',base_attributes:[{tag:'physical attack',label:'物理攻击',values:[310,350]}],enchantment:{summary:'力量 10'}}}})
 expect(wrapper.classes()).toContain('rarity-epic');expect(wrapper.text()).toContain('+12');expect(wrapper.text()).toContain('鬼剑士');expect(wrapper.text()).toContain('310 / 350');expect(wrapper.text()).toContain('存档属性');expect(wrapper.text()).not.toContain('战斗力');expect(fetcher).not.toHaveBeenCalled();wrapper.unmount();vi.unstubAllGlobals()
})
it('escapes text and never maps an unverified rarity number or policy to a known one',()=>{
 const wrapper=mount(ItemQuickFacts,{props:{item:{id:103,name:'<img src=x onerror=alert(1)>',rarity:4,policy_state:'trial'}}})
 expect(wrapper.find('img').exists()).toBe(false);expect(wrapper.text()).toContain('<img');expect(wrapper.text()).toContain('品级未收录');expect(wrapper.text()).not.toContain('史诗');expect(wrapper.text()).toContain('允许试发');wrapper.unmount()
})
