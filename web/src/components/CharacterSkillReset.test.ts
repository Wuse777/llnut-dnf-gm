// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterSkillReset from './CharacterSkillReset.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('shows learned/default skills, validates locally and confirms once for the selected fixed target',async()=>{
 sessionStorage.clear()
 const target={uid:900001,accountname:'test',character:{charac_no:900001,charac_name:'合成角色'}},id='a'.repeat(32)
 const before={skills:[{slot:0,skill_id:5,name:'合成已学技能',level:8}],sp:100,tp:3},after={skills:[{slot:0,skill_id:5,name:'合成默认技能',level:1}],sp:700,tp:21}
 const op={operation_id:id,status:'preview',preview:{target,reason:'合成洗点',changes:{tree_0:{tree:0,before,after,temporary_backup_reset:false,skipped_defaults:[]}}}}
 vi.mocked(api).mockImplementation(async(path)=>{
  if(path.endsWith('/characters/900001'))return {target,trees:[{tree:0,...before}],reset_defaults:after.skills,reset_points:{sp:700,tp:21},enabled:true,maintenance:{available:true},reference:'b'.repeat(64)}
  if(path.includes('/operations?'))return {items:[],has_more:false}
  if(path.endsWith('/preview'))return op
  if(path.endsWith('/confirm'))throw new Error('模拟响应丢失')
  if(path.endsWith(id))return {...op,status:'committed'}
  throw new Error(path)
 })
 const w=mount(CharacterSkillReset,{props:{characNo:900001}})
 try{
  await flushPromises();expect(w.text()).toContain('合成已学技能');expect(w.text()).toContain('合成默认技能')
  await w.get('form').trigger('submit');await flushPromises()
  expect(w.get('#skill-reset-reason-error').text()).toContain('请填写操作原因')
  expect(vi.mocked(api).mock.calls.some(c=>c[1]==='POST')).toBe(false)
  await w.get('input[placeholder="例如：修复角色加点异常"]').setValue('合成洗点')
  await w.get('form').trigger('submit');await flushPromises()
  expect(api).toHaveBeenCalledWith('/character-skill-reset/preview','POST',expect.objectContaining({uid:900001,charac_no:900001,trees:[0]}))
  const button=(text:string)=>w.findAll('button').find(b=>b.text()===text)!
  await button('确认重置所选技能树').trigger('click');await flushPromises()
  expect(w.text()).toContain('不会自动重复提交');expect(button('确认重置所选技能树')).toBeUndefined()
  await button('查询原操作结果').trigger('click');await flushPromises()
  expect(w.text()).toContain('技能存档、快照与审计已提交')
  expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 }finally{w.unmount();sessionStorage.clear()}
})
