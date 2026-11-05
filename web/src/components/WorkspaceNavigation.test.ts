// @vitest-environment happy-dom
import {expect,it} from 'vitest'
import {mount} from '@vue/test-utils'
import WorkspaceNavigation from './WorkspaceNavigation.vue'
it('filters groups without losing hidden features and selects exact routes',async()=>{
 const w=mount(WorkspaceNavigation,{props:{tabs:[['accounts','账号与角色'],['mail','邮件发放'],['maintenance','维护中心'],['future','新功能']],icons:{},current:'accounts',collapsed:false,busy:false,mailCount:2}})
 expect(w.findAll('section')).toHaveLength(4)
 expect(w.find('[aria-current=page]').text()).toContain('账号与角色')
 await w.find('input').setValue('邮件');expect(w.findAll('section')).toHaveLength(1)
 await w.find('section button').trigger('click');expect(w.emitted('choose')?.[0]).toEqual(['mail'])
 await w.find('input').setValue('不存在');expect(w.find('[role=status]').exists()).toBe(true)
 await w.find('input').trigger('keydown',{key:'Escape'});expect(w.text()).toContain('新功能');w.unmount()
})
