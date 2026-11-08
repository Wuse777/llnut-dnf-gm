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
it('equipment layout keeps exact stored slots and opens the same protected item details',async()=>{
 vi.stubGlobal('fetch',vi.fn());const w=mount(InventoryGrid,{props:{items:[item,{...item,id:102,slot:12,slot_label:'扩展槽'}],slotCount:13,equipment:true,anatomy:true,manageable:true},attachTo:document.body})
 expect(w.findAll('.inventory-slot')).toHaveLength(13);expect(w.text()).toContain('非角色实际外观');expect(w.find('.equipment-extra-slots').text()).toContain('扩展槽')
 await w.find('button.equipment-body-slot').trigger('click');await flushPromises();expect(w.get('[role=region]').text()).toContain('合成测试装备')
 await w.findAll('[role=region] button').find(b=>b.text()==='维护此物品')!.trigger('click');expect(w.emitted('manage')?.[0]).toEqual([item]);expect(fetch).not.toHaveBeenCalled();w.unmount()
})
it('equipment filtering falls back to matching cells rather than showing unfiltered empty positions',async()=>{
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12,equipment:true,anatomy:true,filtered:true}})
 expect(w.find('.equipment-body-board').exists()).toBe(false);expect(w.findAll('.inventory-slot')).toHaveLength(1);expect(w.find('.empty-slot').exists()).toBe(false);w.unmount()
})
it('shows an optional verified default base job pose with explicit appearance limits and a schematic toggle',async()=>{
 const url='/dnf-gm/api/v1/assets/'+'a'.repeat(64)+'/'+'b'.repeat(64)+'.png'
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12,equipment:true,anatomy:true,jobPreview:{state:'ready',url,source_kind:'client_default_pose',note:'客户端基础职业默认站姿首帧'}}})
 expect(w.get('img.equipment-default-pose').attributes('src')).toBe(url);expect(w.text()).toContain('非当前装备外观');expect(w.text()).toContain('不代表转职或觉醒形态')
 await w.findAll('.equipment-pose-switch button').find(b=>b.text()==='槽位示意')!.trigger('click');expect(w.find('img.equipment-default-pose').exists()).toBe(false);expect(w.find('.equipment-outline svg').exists()).toBe(true)
 await w.findAll('.equipment-pose-switch button').find(b=>b.text()==='基础职业默认站姿')!.trigger('click');await w.get('img.equipment-default-pose').trigger('error');expect(w.find('.equipment-pose-switch').exists()).toBe(false);expect(w.find('.equipment-outline svg').exists()).toBe(true);w.unmount()
})
it('does not treat an arbitrary promotional image or unavailable job preview as a default pose',async()=>{
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12,equipment:true,anatomy:true,jobPreview:{state:'ready',url:'/unsafe.png',source_kind:'client_default_pose'}}})
 expect(w.find('img.equipment-default-pose').exists()).toBe(false)
 await w.setProps({jobPreview:{state:'ready',url:'/dnf-gm/api/v1/assets/'+'a'.repeat(64)+'/'+'b'.repeat(64)+'.png',source_kind:'official_promotional'}});expect(w.find('.equipment-pose-switch').exists()).toBe(false);w.unmount()
})
it('prefers an exact saved outfit and falls back to the honest default pose after image failure',async()=>{
 const base='/dnf-gm/api/v1/assets/'+'a'.repeat(64)+'/'
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12,equipment:true,anatomy:true,jobPreview:{state:'ready',url:base+'b'.repeat(64)+'.png',source_kind:'client_default_pose'},outfitPreview:{state:'ready',url:base+'c'.repeat(64)+'.png',source_kind:'saved_avatar_outfit',pose:'waiting_first_frame',note:'已核实服装存档配方'}}})
 expect(w.get('img.equipment-default-pose').attributes('src')).toBe(base+'c'.repeat(64)+'.png');expect(w.text()).toContain('服装存档首帧');expect(w.text()).toContain('不含武器、染色或变身效果');expect(w.text()).not.toContain('非当前装备外观')
 await w.get('img.equipment-default-pose').trigger('error');expect(w.get('img.equipment-default-pose').attributes('src')).toBe(base+'b'.repeat(64)+'.png');expect(w.text()).toContain('非当前装备外观')
 await w.get('img.equipment-default-pose').trigger('error');expect(w.find('.equipment-outline svg').exists()).toBe(true);w.unmount()
})
it('keeps unsupported outfit reasons visible and refuses an unverified outfit source',async()=>{
 const base='/dnf-gm/api/v1/assets/'+'a'.repeat(64)+'/'
 const w=mount(InventoryGrid,{props:{items:[item],slotCount:12,equipment:true,anatomy:true,jobPreview:{state:'ready',url:base+'b'.repeat(64)+'.png',source_kind:'client_default_pose'},outfitPreview:{state:'unsupported',note:'穿戴时装含透明替代或染色标识'}}})
 expect(w.text()).toContain('服装预览：穿戴时装含透明替代或染色标识');expect(w.get('img.equipment-default-pose').attributes('src')).toBe(base+'b'.repeat(64)+'.png')
 await w.setProps({outfitPreview:{state:'ready',url:base+'c'.repeat(64)+'.png',source_kind:'saved_avatar_outfit'}});expect(w.get('img.equipment-default-pose').attributes('src')).toBe(base+'b'.repeat(64)+'.png');w.unmount()
})
