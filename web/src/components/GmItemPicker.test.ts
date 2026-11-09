// @vitest-environment happy-dom
import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createPinia,disposePinia,setActivePinia} from 'pinia'
import GmItemPicker from './GmItemPicker.vue'
import {setCsrf} from '../api'
import {useGmCatalogStore} from '../stores/gm/catalog'

const sha='a'.repeat(64),wrappers:ReturnType<typeof mount>[]=[],piniaStores:ReturnType<typeof createPinia>[]=[]
function setup(){const pinia=createPinia();piniaStores.push(pinia);setActivePinia(pinia);return pinia}
function picker(pinia:ReturnType<typeof createPinia>,contextKey='catalog'){
 const wrapper=mount(GmItemPicker,{props:{contextKey},global:{plugins:[pinia],stubs:{ItemCard:{template:'<div><slot/></div>'},CatalogFilters:true,ItemCompare:true,ItemCollection:true,FavoriteButton:true,SvgIcon:true}}})
 wrappers.push(wrapper);return wrapper
}
afterEach(()=>{wrappers.splice(0).forEach(wrapper=>wrapper.unmount());piniaStores.splice(0).forEach(disposePinia);localStorage.clear();vi.unstubAllGlobals()})

it('restores a mounted catalog from bounded memory cache and allows explicit refresh',async()=>{
 let id=1
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:1,items:[{id:id++,name:'fixture',sendable:true}]})))
 vi.stubGlobal('fetch',fetcher);const pinia=setup(),first=picker(pinia)
 await flushPromises();expect(first.findAll('.picker-item')).toHaveLength(1);first.unmount()
 const second=picker(pinia);await flushPromises();expect(fetcher).toHaveBeenCalledTimes(1)
 await second.findAll('button').find(button=>button.text()==='刷新目录')!.trigger('click');await flushPromises()
 expect(fetcher).toHaveBeenCalledTimes(2);expect(second.emitted('loaded')).toHaveLength(2)
})
it('shares a same-query request across pickers and cancels transport only when all leave',async()=>{
 const pending:{resolve:(response:Response)=>void,signal:AbortSignal}[]=[]
 const fetcher=vi.fn((_url,options)=>new Promise<Response>(resolve=>pending.push({resolve,signal:options.signal})))
 vi.stubGlobal('fetch',fetcher);const pinia=setup(),first=picker(pinia,'one'),second=picker(pinia,'two')
 expect(fetcher).toHaveBeenCalledTimes(1);first.unmount();expect(pending[0].signal.aborted).toBe(false)
 second.unmount();expect(pending[0].signal.aborted).toBe(true)
 pending[0].resolve(new Response(JSON.stringify({metadata:{pvf_sha256:sha},items:[{id:1}]})));await flushPromises()
 expect(first.emitted('loaded')).toBeUndefined();expect(second.emitted('loaded')).toBeUndefined()
})
it('does not restore an old session context during unmount',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:sha},items:[]}))))
 const pinia=setup(),wrapper=picker(pinia);await flushPromises();setCsrf('picker-replaced-session');wrapper.unmount()
 expect(useGmCatalogStore(pinia).contexts).toEqual({})
})
it('cancels superseded query revisions and applies only the latest response',async()=>{
 const pending:{resolve:(response:Response)=>void,signal:AbortSignal}[]=[]
 const fetcher=vi.fn((_url,options)=>new Promise<Response>(resolve=>pending.push({resolve,signal:options.signal})))
 vi.stubGlobal('fetch',fetcher);const wrapper=picker(setup())
 await wrapper.setProps({revision:1});expect(fetcher).toHaveBeenCalledTimes(2);expect(pending[0].signal.aborted).toBe(true)
 pending[1].resolve(new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:1,items:[{id:2}]})));await flushPromises()
 pending[0].resolve(new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:90,items:[{id:1}]})));await flushPromises()
 expect(wrapper.emitted('loaded')).toHaveLength(1);expect(wrapper.emitted('loaded')![0][0]).toMatchObject({total:1})
})
it('lets a new search interrupt a slow query while keeping result actions locked',async()=>{
 const pending:{resolve:(response:Response)=>void,signal:AbortSignal,url:string}[]=[]
 vi.stubGlobal('fetch',vi.fn((url,options)=>new Promise<Response>(resolve=>pending.push({resolve,signal:options.signal,url:String(url)}))))
 const wrapper=picker(setup()),search=wrapper.get('[aria-label="物品搜索"]')
 expect(search.attributes('disabled')).toBeUndefined();expect(wrapper.get('[aria-label="物品分类"]').attributes('disabled')).toBeUndefined()
 expect(wrapper.get('.checkbox-field input').attributes('disabled')).toBeUndefined()
 expect(wrapper.findAll('.pagination button').every(button=>button.attributes('disabled')!==undefined)).toBe(true)
 await search.setValue('新条件');await wrapper.get('form.toolbar').trigger('submit')
 expect(pending).toHaveLength(2);expect(pending[0].signal.aborted).toBe(true);expect(pending[1].url).toContain('q='+encodeURIComponent('新条件'))
 pending[1].resolve(new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:1,items:[{id:2}]})));await flushPromises()
 pending[0].resolve(new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:2,items:[{id:1}]})));await flushPromises()
 expect(wrapper.emitted('loaded')).toHaveLength(1);expect(wrapper.emitted('loaded')![0][0]).toMatchObject({total:1,filters:{q:'新条件'}})
})
it('defaults to compact rows with one main selection action and defers auxiliary panels',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:1,items:[{id:2,name:'短剑',sendable:true,part_name:'武器',policy_state:'trial'}]}))))
 const wrapper=picker(setup());await flushPromises()
 expect(wrapper.get('.picker-card-grid').classes()).toContain('picker-card-grid--list')
 expect(wrapper.get('.picker-more').attributes('open')).toBeUndefined()
 expect(wrapper.findAll('.picker-item-actions>button')).toHaveLength(1)
 expect(wrapper.findComponent({name:'CatalogFilters'}).exists()).toBe(false)
 expect(wrapper.get('.picker-search').element.compareDocumentPosition(wrapper.get('.picker-card-grid').element)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})
it('opens mobile-ready filter and favorite tools without adding an item or mutating policy',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:1,items:[{id:2,name:'短剑',sendable:true}]}))))
 const wrapper=picker(setup());await flushPromises();await wrapper.get('.picker-tools-trigger').trigger('click');await flushPromises()
 expect(document.querySelector('[role=dialog]')?.getAttribute('aria-label')).toContain('筛选、收藏')
 expect(wrapper.emitted('select')).toBeUndefined();expect(wrapper.emitted('policy')).toBeUndefined()
})
it('restores an explicit grid preference while new catalogs stay compact',async()=>{
 localStorage.setItem('dnfgm.catalog-view.v1.'+sha,'grid')
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:sha},total:0,items:[]}))))
 const wrapper=picker(setup());await flushPromises();expect(wrapper.get('.picker-card-grid').classes()).not.toContain('picker-card-grid--list')
 await wrapper.findAll('.picker-view-switch button')[1].trigger('click');expect(localStorage.getItem('dnfgm.catalog-view.v1.'+sha)).toBe('list')
})
