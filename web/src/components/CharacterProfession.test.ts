// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import CharacterProfession from './CharacterProfession.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('selects a named profession, displays linked preview and reconciles one uncertain confirmation',async()=>{
 sessionStorage.clear()
 const target={uid:900001,accountname:'test',character:{charac_no:900001,charac_name:'合成角色'}},id='c'.repeat(32)
 const choices=[{first:1,second:0,code:1,name:'合成分支甲',branch:'分支甲',stage:'未觉醒'},{first:2,second:1,code:18,name:'合成乙一觉',branch:'分支乙',stage:'一觉'}]
 const tree={skills:[{slot:0,skill_id:5,name:'合成技能',level:1}],sp:700,tp:21}
 const op={operation_id:id,status:'preview',preview:{target,reason:'合成转职',profession_before:choices[0],profession_after:choices[1],before:{info:{grow_type:1}},changes:{maxHP:{label:'基础生命存档',before:10000,after:10550}},skill_changes:{tree_0:{tree:0,before:tree,after:tree,temporary_backup_reset:false,skipped_defaults:[]}}}}
 vi.mocked(api).mockImplementation(async path=>{
  if(path.endsWith('/characters/900001'))return {target,current:choices[0],base_name:'合成基础',job:0,level:70,choices,enabled:true,maintenance:{available:true},reference:'b'.repeat(64)}
  if(path.includes('/operations?'))return {items:[],has_more:false}
  if(path.endsWith('/preview'))return op
  if(path.endsWith('/confirm'))throw Error('模拟响应丢失')
  if(path.endsWith(id))return {...op,status:'committed'}
  throw Error(path)
 })
 const w=mount(CharacterProfession,{props:{characNo:900001}})
 try{
  await flushPromises();expect(w.text()).toContain('基础职业（保持不变）');expect(w.findAll('select option')).toHaveLength(2)
  await w.get('form').trigger('submit');await flushPromises();expect(w.get('#profession-reason-error').text()).toContain('请填写操作原因');expect(w.get('#profession-choice-error').text()).toContain('当前相同')
  expect(vi.mocked(api).mock.calls.some(c=>c[1]==='POST')).toBe(false)
  await w.get('select').setValue('18');await w.get('input[placeholder="例如：调整角色转职分支"]').setValue('合成转职');await w.get('form').trigger('submit');await flushPromises()
  expect(api).toHaveBeenCalledWith('/character-profession/preview','POST',expect.objectContaining({uid:900001,charac_no:900001,first:2,second:1}))
  expect(w.text()).toContain('基础生命存档');expect(w.text()).toContain('10550')
  const button=(text:string)=>w.findAll('button').find(b=>b.text()===text)!
  await button('确认修改转职／觉醒及关联存档').trigger('click');await flushPromises();expect(w.text()).toContain('不会自动重复提交')
  expect(button('确认修改转职／觉醒及关联存档')).toBeUndefined()
  await button('查询原操作结果').trigger('click');await flushPromises();expect(w.text()).toContain('职业、成长、技能存档与快照／审计已提交')
  expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 }finally{w.unmount();sessionStorage.clear()}
})
