// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import GiftVersions from './GiftVersions.vue'
afterEach(()=>vi.unstubAllGlobals())
it('compares immutable rewards and copies chosen version without writes',async()=>{
 const f=vi.fn(async(_url:unknown,_options?:RequestInit)=>new Response(JSON.stringify({items:[{version:2,payload:{name:'奖励',gold:100,items:[]}},{version:1,payload:{name:'奖励',gold:50,items:[]}}],has_more:false})))
 vi.stubGlobal('fetch',f);const w=mount(GiftVersions,{props:{templateId:1}});await flushPromises()
 expect(w.text()).toContain('有变化');expect(w.text()).toContain('100');expect(w.text()).toContain('50')
 await w.findAll('button').find(b=>b.text()==='复制版本 A 为新模板')!.trigger('click')
 expect(w.emitted('copy')?.[0][0]).toEqual({name:'奖励',gold:100,items:[]})
 expect(f.mock.calls[0]?.[1]?.method).toBe('GET');w.unmount()
})
