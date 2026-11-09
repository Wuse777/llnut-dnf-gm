// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterMaintenance from './CharacterMaintenance.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('validates next to fields, submits the fixed target, and never repeats uncertain confirmation',async()=>{
 sessionStorage.clear()
 const target={uid:900001,accountname:'test',character:{charac_no:900001,charac_name:'测试角色'}},id='a'.repeat(32)
 const result={operation_id:id,status:'preview',preview:{target,reason:'疲劳恢复',changes:{fatigue:{before:100,after:0}}}}
 vi.mocked(api).mockImplementation(async(path,method)=>{
  if(path.endsWith('/characters/900001'))return {target,archive:{fatigue:100,premium_fatigue:20,used_fatigue:88,max_fatigue:156,max_premium_fatigue:0},enabled:true,maintenance:{available:true},reference:'b'.repeat(64)}
  if(path.includes('/operations?'))return {items:[],has_more:false}
  if(path.endsWith('/preview'))return result
  if(path.endsWith('/confirm'))throw new Error('模拟响应丢失')
  if(method===undefined&&path.endsWith(id))return {...result,status:'committed'}
  throw new Error(path)
 })
 const w=mount(CharacterMaintenance,{props:{characNo:900001}})
 try{
 await flushPromises()
 const click=async(text:string)=>{const b=w.findAll('button').find(x=>x.text()===text);expect(b).toBeTruthy();await b!.trigger('click');await flushPromises()}
 await w.get('form').trigger('submit');await flushPromises()
 expect(w.get('#fatigue-reason-error').text()).toContain('请填写操作原因')
 expect(vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')).toHaveLength(0)
 await click('恢复全部疲劳');await w.get('input[placeholder="例如：角色疲劳恢复"]').setValue('疲劳恢复')
 await w.get('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/character-maintenance/preview','POST',expect.objectContaining({uid:900001,charac_no:900001,changes:{fatigue:0,premium_fatigue:0}}))
 await click('确认修改疲劳');expect(w.text()).toContain('不会自动重复提交')
 expect(w.findAll('button').some(b=>b.text()==='确认修改疲劳')).toBe(false)
 await click('查询原操作结果');expect(w.text()).toContain('存档、快照与成功审计已提交')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 }finally{w.unmount();sessionStorage.clear()}
})
