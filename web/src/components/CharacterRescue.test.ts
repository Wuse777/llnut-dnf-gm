// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterRescue from './CharacterRescue.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('validates next to fields, submits the fixed target, and never repeats uncertain confirmation',async()=>{
 sessionStorage.clear()
 const target={uid:900001,accountname:'test',character:{charac_no:900001,charac_name:'测试角色'}},id='a'.repeat(32)
 const result={operation_id:id,status:'preview',preview:{target,reason:'角色位置救援',changes:{saved_village:{before:6,after:1}}}}
 vi.mocked(api).mockImplementation(async(path,method)=>{
  if(path.endsWith('/characters/900001'))return {target,destination:1,archive:{selection_village:6,saved_village:6,previous_village:2},enabled:true,maintenance:{available:true},reference:'b'.repeat(64)}
  if(path.includes('/operations?'))return {items:[],has_more:false}
  if(path.endsWith('/preview'))return result
  if(path.endsWith('/confirm'))throw new Error('模拟响应丢失')
  if(method===undefined&&path.endsWith(id))return {...result,status:'committed'}
  throw new Error(path)
 })
 const w=mount(CharacterRescue,{props:{characNo:900001}})
 try{
 await flushPromises()
 const click=async(text:string)=>{const b=w.findAll('button').find(x=>x.text()===text);expect(b).toBeTruthy();await b!.trigger('click');await flushPromises()}
 await w.get('form').trigger('submit');await flushPromises()
 expect(w.get('#rescue-reason-error').text()).toContain('请填写操作原因')
 expect(vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')).toHaveLength(0)
 await w.get('input[placeholder="例如：卡死位置，返回默认城镇"]').setValue('角色位置救援')
 await w.get('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/character-rescues/preview','POST',expect.objectContaining({uid:900001,charac_no:900001}))
 await click('确认重置城镇');expect(w.text()).toContain('不会自动重复提交')
 expect(w.findAll('button').some(b=>b.text()==='确认重置城镇')).toBe(false)
 await click('查询原操作结果');expect(w.text()).toContain('存档、快照与成功审计已提交')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 }finally{w.unmount();sessionStorage.clear()}
})
