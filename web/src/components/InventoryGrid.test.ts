// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import InventoryGrid from './InventoryGrid.vue'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
const item={slot:0,slot_label:'武器',id:100,name:'合成测试装备',quantity:1,type_name:'装备',level:20,enhancement:7,forge:3,durability:30,amplify_type:0,amplify_value:0,orb_id:0,sealed_raw:0}
it('displays actual slot positions and empty stored slots, without claiming unlocked',()=>{
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12,equipment:true}})
 expect(w.findAll('.inventory-slot')).toHaveLength(12);expect(w.findAll('.empty-slot')).toHaveLength(11);expect(w.find('.slot-enhancement').text()).toBe('+7');expect(w.text()).toContain('称号');w.unmount()
})
it('selection opens detailed read-only pane and restores keyboard focus',async()=>{
 vi.stubGlobal('fetch',vi.fn());const w=mount(InventoryGrid,{props:{items:[item],slotCount:12},attachTo:document.body})
 const b=w.find('button.inventory-slot');await b.trigger('click');await flushPromises()
 expect(w.find('[role=region]').text()).toContain('合成测试装备');expect(w.find('[role=region]').text()).toContain('实际已开放格数');expect(document.activeElement).toBe(w.find('[role=region]').element)
 await w.find('[role=region] button').trigger('click');await flushPromises();expect(document.activeElement).toBe(b.element);expect(fetch).not.toHaveBeenCalled();w.unmount()
})
it('bounds pages and drops detail when container/filter changes',async()=>{
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:249}});expect(w.findAll('.inventory-slot')).toHaveLength(30)
 await w.findAll('button').find(b=>b.text()==='下一页槽位')!.trigger('click');expect(w.find('.empty-slot').text()).toContain('#30')
 await w.setProps({filtered:true,items:[{...item,slot:99}]});expect(w.findAll('.inventory-slot')).toHaveLength(1);expect(w.find('.pagination').text()).toContain('1 / 1');expect(w.find('input').attributes('disabled')).toBeDefined();w.unmount()
})
it('hides empty slots on demand and refuses unbounded slot expansion',async()=>{
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12}});await w.find('input').setValue(false);expect(w.findAll('.inventory-slot')).toHaveLength(1)
 await w.setProps({slotCount:100000000});await w.find('input').setValue(true);expect(w.findAll('.inventory-slot')).toHaveLength(0);w.unmount()
})
it('mobile selection opens bottom drawer and closes back to the exact slot',async()=>{
 const media={matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()}
 vi.stubGlobal('matchMedia',()=>media);vi.stubGlobal('fetch',vi.fn())
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12,manageable:true},attachTo:document.body})
 await w.find('button.inventory-slot').trigger('click');await flushPromises()
 expect(w.find('[role=region]').exists()).toBe(false);expect(document.querySelector('.item-drawer')).not.toBeNull()
 const dialog=document.querySelector('[role=dialog]')!;expect(dialog.textContent).toContain('存档数量')
 const manage=Array.from(dialog.querySelectorAll<HTMLButtonElement>('button')).find(b=>b.textContent==='维护此物品')!;manage.click();await flushPromises()
 expect(w.emitted('manage')?.[0]).toEqual([item]);expect(document.querySelector('[role=dialog]')).toBeNull();expect(fetch).not.toHaveBeenCalled();w.unmount();expect(media.removeEventListener).toHaveBeenCalled()
})
it('page changes close an old item detail rather than show a different page with stale selection',async()=>{
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:60},attachTo:document.body})
 await w.find('button.inventory-slot').trigger('click');expect(w.find('[role=region]').exists()).toBe(true)
 await w.findAll('button').find(b=>b.text()==='下一页槽位')!.trigger('click');expect(w.find('[role=region]').exists()).toBe(false);w.unmount()
})
it('groups equipment by adapted slot while preserving unknown positions',()=>{
 const w=mount(InventoryGrid,{props:{items:[item,{...item,slot:12,slot_label:'扩展槽'}],slotCount:13,equipment:true}})
 expect(w.findAll('.equipment-group-title').map(h=>h.text())).toEqual(['武器与称号1 / 2','防具0 / 5','首饰0 / 3','特殊装备0 / 2','其他存档槽位1 / 1'])
 expect(w.findAll('.inventory-slot')).toHaveLength(13);w.unmount()
})
