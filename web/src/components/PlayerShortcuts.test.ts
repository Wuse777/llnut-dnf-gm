// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import PlayerShortcuts from './PlayerShortcuts.vue'
afterEach(()=>vi.unstubAllGlobals())
it('saved target opens exact ids and favorite only changes navigation metadata',async()=>{
 const calls:any[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url,options:any={})=>{calls.push({url:String(url),method:options.method,body:options.body?JSON.parse(options.body):null});return new Response(JSON.stringify(String(url).includes('/collections')?{items:[{uid:7,charac_no:9,favorite:false,available:true,account:{accountname:'gm'},character:{charac_name:'测试'}}],total:1,page_size:12}:{}))}))
 const w=mount(PlayerShortcuts,{props:{revision:0,current:{uid:7,charac_no:9,label:'测试'}}});await flushPromises()
 await w.find('.target-open').trigger('click');expect(w.emitted('choose')?.[0][0]).toEqual({uid:7,charac_no:9})
 await w.get('[aria-label="收藏目标 7:9"]').trigger('click');await flushPromises()
 expect(calls.find(c=>c.method==='PUT')?.body).toEqual({uid:7,charac_no:9,favorite:true})
 expect(calls.some(c=>c.url.includes('/operations'))).toBe(false);w.unmount()
})
it('unavailable targets stay removable and a late response cannot replace a newer collection',async()=>{
 let old:(v:any)=>void=()=>{}
 vi.stubGlobal('fetch',vi.fn(url=>String(url).includes('collection=recent')?new Promise(r=>old=r):Promise.resolve(new Response(JSON.stringify({items:[{uid:7,charac_no:9,favorite:true,available:false}],total:1,page_size:12})))))
 const w=mount(PlayerShortcuts,{props:{revision:0}})
 await w.findAll('button').find(b=>b.text()==='常用目标')!.trigger('click');await flushPromises()
 old(new Response(JSON.stringify({items:[],total:0})));await flushPromises()
 expect(w.get('.target-open').attributes('disabled')).toBeDefined();expect(w.get('[aria-label="取消收藏目标 7:9"]').attributes('disabled')).toBeUndefined();w.unmount()
})
