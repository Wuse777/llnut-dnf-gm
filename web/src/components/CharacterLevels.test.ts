// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterLevels from './CharacterLevels.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('keeps errors beside fields and submits one target-bound linked level change',async()=>{
 sessionStorage.clear()
 const target={uid:900001,accountname:'test',character:{charac_no:900001,charac_name:'测试角色'}},id='a'.repeat(32)
 const result={operation_id:id,status:'preview',preview:{target,reason:'等级补偿',changes:{lev:{before:2,after:3}}}}
 vi.mocked(api).mockImplementation(async(path)=>{
  if(path.endsWith('/characters/900001'))return {target,archive:{info:{lev:2}},labels:{lev:'等级'},levels:[{level:2,experience:100},{level:3,experience:200}],enabled:true,maintenance:{available:true},reference:'b'.repeat(64)}
  if(path.includes('/operations?'))return {items:[],has_more:false}
  if(path.endsWith('/preview'))return result
  if(path.endsWith('/confirm'))throw new Error('模拟响应丢失')
  if(path.endsWith(id))return {...result,status:'committed'}
  throw new Error(path)
 })
 const w=mount(CharacterLevels,{props:{characNo:900001}})
 try{
  await flushPromises();await w.get('form').trigger('submit');await flushPromises()
  expect(w.get('#level-reason-error').text()).toContain('请填写操作原因')
  expect(vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')).toHaveLength(0)
  await w.get('select').setValue('3');await w.get('input[maxlength="200"]').setValue('等级补偿')
  await w.get('form').trigger('submit');await flushPromises()
  expect(api).toHaveBeenCalledWith('/character-levels/preview','POST',expect.objectContaining({uid:900001,charac_no:900001,level:3,experience:null}))
  const click=async(text:string)=>{const b=w.findAll('button').find(x=>x.text()===text);expect(b).toBeTruthy();await b!.trigger('click');await flushPromises()}
  await click('确认修改等级与关联存档');expect(w.text()).toContain('不会自动重复提交')
  expect(w.findAll('button').some(b=>b.text()==='确认修改等级与关联存档')).toBe(false)
  await click('查询原操作结果');expect(w.text()).toContain('关联存档、快照与审计已提交')
  expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 }finally{w.unmount();sessionStorage.clear()}
})
