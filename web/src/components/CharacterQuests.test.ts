// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterQuests from './CharacterQuests.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('queries only the chosen character and keeps invalid input next to the field',async()=>{
 vi.mocked(api).mockResolvedValue({target:{accountname:'test',character:{charac_name:'测试',charac_no:900001}},collected_at:1,state:'read',catalog:{state:'not_installed'},active:[],completed:[],completed_count:null,has_more:false,page:1,issues:[{code:'clear_unknown',message:'完成标记未知'}],urgent:{id:0}})
 const w=mount(CharacterQuests,{props:{characNo:900001},global:{stubs:{QuestRepair:true}}})
 try{
 await flushPromises();expect(api).toHaveBeenCalledWith('/characters/900001/quests?page=1&quest_id=0');expect(w.text()).toContain('完成标记未知')
 await w.get('input[placeholder="例如：38"]').setValue('abc');await w.get('.quest-lookup-form').trigger('submit');await flushPromises();expect(w.get('#quest-query-error').text()).toContain('整数');expect(api).toHaveBeenCalledTimes(1)
 await w.get('input[placeholder="例如：38"]').setValue('38');await w.get('.quest-lookup-form').trigger('submit');await flushPromises();expect(api).toHaveBeenLastCalledWith('/characters/900001/quests?page=1&quest_id=38')
 expect(vi.mocked(api).mock.calls.every(x=>x[1]===undefined)).toBe(true)
 }finally{w.unmount()}
})
it('searches full task names, opens exact prerequisite details and retains the repair target',async()=>{
 const target={uid:900001,accountname:'test',character:{charac_name:'测试',charac_no:900001}}
 const view={target,collected_at:1,state:'read',catalog:{state:'matched'},active:[],completed:[],completed_count:0,has_more:false,page:1,issues:[],urgent:{id:0}}
 vi.mocked(api).mockImplementation(async(path)=>{
  if(path.includes('/search?'))return {catalog:{state:'matched'},items:[{id:2,name:'测试觉醒任务',clear_flag:0,active_slots:[1]}],page:1,has_more:false}
  return {...view,...(path.endsWith('quest_id=2')?{lookup:{id:2,active_slots:[1],clear_flag:0,within_native_range:true,definition:{name:'测试觉醒任务',min_level:1,max_level:99,prerequisites:[1]},prerequisites:{items:[{id:1,name:'前置任务',clear_flag:1,active_slots:[]}],raw:[1],note:'不推断可接资格'}}}:{})}
 })
 const w=mount(CharacterQuests,{props:{characNo:900001},global:{stubs:{QuestRepair:true}}})
 try{
 await flushPromises()
 await w.get('input[placeholder="例如：转职、觉醒或38"]').setValue('觉醒')
 await w.get('.quest-search form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/characters/900001/quests/search?q=%E8%A7%89%E9%86%92&page=1')
 const open=w.findAll('button').find(x=>x.text()==='查看条件与前置任务')!
 await open.trigger('click');await flushPromises()
 expect(api).toHaveBeenCalledWith('/characters/900001/quests?page=1&quest_id=2')
 expect(w.text()).toContain('前置任务逐项核对');expect(w.text()).toContain('不推断可接资格')
 }finally{w.unmount()}
})
