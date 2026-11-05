// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterRename from './CharacterRename.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('validates next to fields, submits the fixed target, and never repeats uncertain confirmation',async()=>{
 sessionStorage.clear()
 const target={uid:900001,accountname:'test',character:{charac_no:900001,charac_name:'测试角色'}},id='a'.repeat(32)
 const result={operation_id:id,status:'preview',preview:{target,reason:'角色改名',changes:{name:{before:'测试角色',after:'改名测试'}}}}
 vi.mocked(api).mockImplementation(async(path,method)=>{
  if(path.endsWith('/characters/900001'))return {target,server_id:3,linked_counts:{guild_member:1,blacklist:0},enabled:true,maintenance:{available:true},reference:'b'.repeat(64)}
  if(path.includes('/operations?'))return {items:[],has_more:false}
  if(path.endsWith('/preview'))return result
  if(path.endsWith('/confirm'))throw new Error('模拟响应丢失')
  if(method===undefined&&path.endsWith(id))return {...result,status:'committed'}
  throw new Error(path)
 })
 const w=mount(CharacterRename,{props:{characNo:900001}})
 try{
 await flushPromises()
 const click=async(text:string)=>{const b=w.findAll('button').find(x=>x.text()===text);expect(b).toBeTruthy();await b!.trigger('click');await flushPromises()}
 await w.get('form').trigger('submit');await flushPromises()
 expect(w.get('#rename-reason-error').text()).toContain('请填写操作原因')
 expect(vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')).toHaveLength(0)
 await w.get('input[placeholder="新的角色名称"]').setValue('改名测试');await w.get('input[placeholder="例如：角色改名"]').setValue('角色改名')
 await w.get('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/character-renames/preview','POST',expect.objectContaining({uid:900001,charac_no:900001,new_name:'改名测试'}))
 await click('确认修改角色名');expect(w.text()).toContain('不会自动重复提交')
 expect(w.findAll('button').some(b=>b.text()==='确认修改角色名')).toBe(false)
 await click('查询原操作结果');expect(w.text()).toContain('存档、快照与成功审计已提交')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 }finally{w.unmount();sessionStorage.clear()}
})
