// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {defineComponent} from 'vue'
import ItemCard from './ItemCard.vue'
import Modal from './Modal.vue'
const item={id:100,name:'合成测试武器',category:'equipment',quantity:2147483647,level:50,single_item:true,policy_state:'trial'}
afterEach(()=>{document.body.innerHTML='';document.body.style.overflow='';vi.unstubAllGlobals()})
it('shows shared metadata and opens a read-only detail without a request',async()=>{
 vi.stubGlobal('fetch',vi.fn())
 const w=mount(ItemCard,{props:{item},attachTo:document.body})
 expect(w.text()).toContain('Lv. 50');await w.find('button').trigger('click');await flushPromises()
 const dialog=document.querySelector('[role=dialog]')!
 expect(dialog.textContent).toContain('每件独立投递');expect(dialog.textContent).toContain('不按 PVF 限额');expect(dialog.textContent).toContain('2,147,483,647')
 expect(dialog.textContent).toContain('未收录');expect(fetch).not.toHaveBeenCalled();expect(document.body.style.overflow).toBe('hidden')
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await flushPromises()
 expect(document.querySelector('[role=dialog]')).toBeNull();expect(document.activeElement).toBe(w.find('button').element);expect(document.body.style.overflow).toBe('');w.unmount()
})
it('nested drawer owns Escape and keeps parent confirmation and scroll lock',async()=>{
 const Host=defineComponent({components:{Modal,ItemCard},data:()=>({item}),template:'<Modal title="发放预览" @close="$emit(\'closed\')"><ItemCard :item="item"/></Modal>'})
 const w=mount(Host,{attachTo:document.body});await w.find('.item-inspect').trigger('click');await flushPromises()
 expect(document.querySelectorAll('[role=dialog]')).toHaveLength(2)
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await flushPromises()
 expect(document.querySelectorAll('[role=dialog]')).toHaveLength(1);expect(w.emitted('closed')).toBeUndefined();expect(document.body.style.overflow).toBe('hidden')
 expect(document.activeElement).toBe(w.find('.item-inspect').element)
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(w.emitted('closed')).toHaveLength(1);w.unmount();expect(document.body.style.overflow).toBe('')
})
it('traps Tab within top drawer, including focus arriving from outside',async()=>{
 const w=mount(ItemCard,{props:{item},attachTo:document.body});await w.find('button').trigger('click');await flushPromises()
 const buttons=document.querySelector('[role=dialog]')!.querySelectorAll<HTMLButtonElement>('button')
 buttons[buttons.length-1]!.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));expect(document.activeElement).toBe(buttons[0])
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true}));expect(document.activeElement).toBe(buttons[buttons.length-1])
 w.find('button').element.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));expect(document.activeElement).toBe(buttons[0]);w.unmount()
})
it('escapes names and never turns unknown rarity or quantity into zero',async()=>{
 const w=mount(ItemCard,{props:{item:{id:9,name:'<img src=x onerror=alert(1)>',quantity:null,rarity:4}},attachTo:document.body})
 await w.find('button').trigger('click');await flushPromises();const dialog=document.querySelector('[role=dialog]')!
 expect(dialog.querySelector('img')).toBeNull();expect(dialog.textContent).toContain('原始值 4');expect(dialog.textContent).not.toContain('史诗');expect(dialog.textContent).toContain('未收录');w.unmount()
})
it('changing item closes obsolete detail; no hidden selection survives',async()=>{
 const w=mount(ItemCard,{props:{item},attachTo:document.body});await w.find('button').trigger('click');await flushPromises();await w.setProps({item:{...item,id:101}});await flushPromises();expect(document.querySelector('[role=dialog]')).toBeNull();w.unmount()
})
