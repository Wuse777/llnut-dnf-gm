// @vitest-environment happy-dom
import {it,expect} from 'vitest'
import {mount} from '@vue/test-utils'
import {nextTick} from 'vue'
import MailWorkbench from './MailWorkbench.vue'
it('switches only presentation and keeps both draft and picker mounted',async()=>{
 const w=mount(MailWorkbench,{props:{modelValue:'draft' as 'items'|'draft',count:2,quantity:7,gold:100,hasCurrencies:true,busy:false,'onUpdate:modelValue':(value:'items'|'draft')=>w.setProps({modelValue:value})},slots:{items:'<input id="picker-query" value="药水">',draft:'<input id="draft-reason" value="活动奖励">'}})
 expect(w.get('.mail-workbench-frame').attributes('data-pane')).toBe('draft')
 expect(w.get('[aria-label="邮件工作区切换"]').text()).toContain('7 件 · 100 金币 · 含账号货币')
 await w.findAll('button')[0].trigger('click');await nextTick()
 expect(w.get('.mail-workbench-frame').attributes('data-pane')).toBe('items')
 expect(w.get('#draft-reason').element).toHaveProperty('value','活动奖励')
 await w.findAll('button')[1].trigger('click');expect(w.get('#picker-query').element).toHaveProperty('value','药水')
 w.unmount()
})
it('does not switch while a request is busy',async()=>{
 const w=mount(MailWorkbench,{props:{modelValue:'draft',count:0,quantity:0,gold:0,hasCurrencies:false,busy:true}})
 await w.findAll('button')[0].trigger('click');expect(w.emitted('update:modelValue')).toBeUndefined();w.unmount()
})
