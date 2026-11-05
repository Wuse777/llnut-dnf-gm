// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterQuests from './CharacterQuests.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('queries only the chosen character and keeps invalid input next to the field',async()=>{
 vi.mocked(api).mockResolvedValue({target:{accountname:'test',character:{charac_name:'测试',charac_no:900001}},collected_at:1,state:'read',catalog:{state:'not_installed'},active:[],completed:[],completed_count:null,has_more:false,page:1,issues:[{code:'clear_unknown',message:'完成标记未知'}],urgent:{id:0}})
 const w=mount(CharacterQuests,{props:{characNo:900001}})
 try{
 await flushPromises();expect(api).toHaveBeenCalledWith('/characters/900001/quests?page=1&quest_id=0');expect(w.text()).toContain('完成标记未知')
 await w.get('input[placeholder="例如：38"]').setValue('abc');await w.get('form').trigger('submit');await flushPromises();expect(w.get('#quest-query-error').text()).toContain('整数');expect(api).toHaveBeenCalledTimes(1)
 await w.get('input[placeholder="例如：38"]').setValue('38');await w.get('form').trigger('submit');await flushPromises();expect(api).toHaveBeenLastCalledWith('/characters/900001/quests?page=1&quest_id=38')
 expect(vi.mocked(api).mock.calls.every(x=>x[1]===undefined)).toBe(true)
 }finally{w.unmount()}
})
