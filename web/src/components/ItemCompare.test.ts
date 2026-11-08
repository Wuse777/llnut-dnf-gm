// @vitest-environment happy-dom
import {it,expect,vi} from 'vitest'
import {mount} from '@vue/test-utils'
import ItemCompare from './ItemCompare.vue'
it('compares only supplied definition values and emits removal without requests',async()=>{
 vi.stubGlobal('fetch',vi.fn())
 const w=mount(ItemCompare,{props:{items:[{id:1,name:'样本甲',level:50,rarity:0,base_attributes:[{tag:'[physical attack]',label:'物理攻击',values:[20,30]}]},{id:2,name:'样本乙',level:60}]}})
 expect(w.text()).toContain('20 / 30');expect(w.text()).toContain('未收录');expect(w.text()).not.toContain('史诗')
 await w.find('[aria-label="移出对比 1"]').trigger('click');expect(w.emitted('remove')).toEqual([[1]]);expect(fetch).not.toHaveBeenCalled();w.unmount();vi.unstubAllGlobals()
})
