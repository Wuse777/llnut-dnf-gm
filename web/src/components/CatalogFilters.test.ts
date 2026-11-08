// @vitest-environment happy-dom
import {afterEach,it,expect} from 'vitest'
import {mount} from '@vue/test-utils'
import CatalogFilters from './CatalogFilters.vue'
afterEach(()=>localStorage.clear())
const facets={equipment_metadata:true,parts:[{code:'[weapon]',name:'武器',count:2}],rarities:[{value:0,label:'PVF 品级 0',count:1}]}
it('emits explicit zero rarity, applies bounds, and keeps saved conditions PVF scoped',async()=>{
 const w=mount(CatalogFilters,{props:{modelValue:{q:'样本',rarity:'',min_level:'',sort:'id'},pvf:'a'.repeat(64),facets}})
 await w.findAll('select')[1]!.setValue('0');expect(w.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({rarity:'0'})
 await w.setProps({modelValue:{q:'样本',rarity:0,min_level:10,sort:'level_desc'}})
 await w.find('[aria-label="常用筛选名称"]').setValue('普通武器');await w.findAll('button').find(b=>b.text()==='保存筛选')!.trigger('click')
 expect(localStorage.getItem('dnfgm.catalog-filters.v1.'+'a'.repeat(64))).toContain('普通武器')
 await w.find('.saved-filters button').trigger('click');expect(w.emitted('apply')).toHaveLength(1)
 expect(w.emitted('update:modelValue')?.at(-1)?.[0]).toMatchObject({rarity:0,min_level:10})
 await w.setProps({pvf:'b'.repeat(64)});expect(w.find('.saved-filters').exists()).toBe(false);w.unmount()
})
it('handles corrupt storage and missing optional metadata without losing basic queries',()=>{
 localStorage.setItem('dnfgm.catalog-filters.v1.'+'a'.repeat(64),'{')
 const w=mount(CatalogFilters,{props:{modelValue:{},pvf:'a'.repeat(64),facets:{equipment_metadata:false}}})
 expect(w.findAll('select')[0]!.attributes('disabled')).toBeDefined();expect(w.text()).toContain('无法读取');expect(w.text()).toContain('暂不可用');w.unmount()
})
