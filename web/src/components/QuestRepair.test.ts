// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi} from 'vitest'
import QuestRepair from './QuestRepair.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
it('validates next to fields, submits the fixed target, and never repeats uncertain confirmation',async()=>{
 sessionStorage.clear()
 const target={uid:900001,accountname:'test',character:{charac_no:900001,charac_name:'测试角色'}},id='a'.repeat(32)
 const result={operation_id:id,status:'preview',request:{charac_no:900001},preview:{target,slot:1,reason:'清理任务',quest_name:'合成任务',changes:{id:{before:2,after:0},trigger_raw:{before:7,after:0}}}}
 vi.mocked(api).mockImplementation(async(path,method)=>{
  if(path.endsWith('/characters/900001'))return {target,slots:[{slot:1,id:2,trigger_raw:7,definition:{name:'合成任务'}}],supported:true,enabled:true,maintenance:{available:true},reference:'b'.repeat(64)}
  if(path.includes('/operations?'))return {items:[],has_more:false}
  if(path.endsWith('/preview'))return result
  if(path.endsWith('/confirm'))throw new Error('模拟响应丢失')
  if(method===undefined&&path.endsWith(id))return {...result,status:'committed'}
  throw new Error(path)
 })
 const w=mount(QuestRepair,{props:{characNo:900001}})
 try{
 await flushPromises()
 const click=async(text:string)=>{const b=w.findAll('button').find(x=>x.text()===text);expect(b).toBeTruthy();await b!.trigger('click');await flushPromises()}
 await w.get('form').trigger('submit');await flushPromises()
 expect(w.get('#quest-reason-error').text()).toContain('请填写操作原因')
 expect(vi.mocked(api).mock.calls.filter(c=>c[1]==='POST')).toHaveLength(0)
 await w.get('input[placeholder="例如：指定任务卡住，清理该进行中槽"]').setValue('角色位置救援')
 await w.get('select').setValue('1')
 await w.get('form').trigger('submit');await flushPromises()
 expect(api).toHaveBeenCalledWith('/quest-repairs/preview','POST',expect.objectContaining({uid:900001,charac_no:900001,slot:1,action:'quest-clear'}))
 await click('确认清理这一个任务槽');expect(w.text()).toContain('不会自动重复提交')
 expect(w.findAll('button').some(b=>b.text()==='确认清理这一个任务槽')).toBe(false)
 await click('查询原操作结果');expect(w.text()).toContain('存档、快照与成功审计已提交')
 expect(vi.mocked(api).mock.calls.filter(c=>c[0].endsWith('/confirm'))).toHaveLength(1)
 }finally{w.unmount();sessionStorage.clear()}
})
