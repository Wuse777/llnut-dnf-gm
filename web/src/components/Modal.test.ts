// @vitest-environment happy-dom
import {it,expect} from 'vitest'
import {mount} from '@vue/test-utils'
import Modal from './Modal.vue'
it('traps focus, handles Escape and restores focus to the trigger',async()=>{
 const trigger=document.createElement('button');document.body.append(trigger);trigger.focus();const w=mount(Modal,{attachTo:document.body,props:{title:'确认'},slots:{default:'<button id="first">返回</button><button id="last">确认</button>'}})
 const panel=w.find('[role="dialog"]');expect(document.activeElement).toBe(panel.element)
 ;(w.find('#last').element as HTMLElement).focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));expect(document.activeElement).toBe(w.find('button[aria-label="关闭对话框"]').element)
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(document.activeElement).toBe(w.find('#last').element)
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(w.emitted('close')).toHaveLength(1);w.unmount();expect(document.activeElement).toBe(trigger);trigger.remove()
})
it('does not allow Escape to dismiss an in-flight submission',async()=>{
 const w=mount(Modal,{props:{title:'提交',busy:true}});document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));expect(w.emitted('close')).toBeUndefined();w.unmount()
})

it('does not trap keyboard users in hidden groups or inactive tabs and includes source links',async()=>{
 const w=mount(Modal,{attachTo:document.body,props:{title:'导航'},slots:{default:'<button id="visible">可见</button><button tabindex="-1" id="inactive">其他页签</button><div style="display:none"><button id="hidden">隐藏页操作</button></div><a href="https://example.com" id="source">素材出处</a><div hidden><input id="hidden-last"></div>'}})
 try{(w.get('#source').element as HTMLElement).focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));expect(document.activeElement).toBe(w.get('button[aria-label="关闭对话框"]').element)
 document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(document.activeElement).toBe(w.get('#source').element)
 }finally{w.unmount()}
})
it('includes disclosure summaries and excludes actions inside a closed disclosure',()=>{
 const w=mount(Modal,{attachTo:document.body,props:{title:'更多操作'},slots:{default:'<button id="primary">发奖励</button><details><summary id="more">更多操作</summary><button id="penalty">封禁</button></details>'}})
 try{
  ;(w.get('#more').element as HTMLElement).focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));expect(document.activeElement).toBe(w.get('[aria-label="关闭对话框"]').element)
  document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));expect(document.activeElement).toBe(w.get('#more').element)
 }finally{w.unmount()}
})
