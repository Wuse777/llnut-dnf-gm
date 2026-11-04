// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import ItemCollection from './ItemCollection.vue'
import FavoriteButton from './FavoriteButton.vue'
import {setCsrf} from '../api'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
const sha='a'.repeat(64)
const item={id:8388,name:'同桌硬币',favorite:false,pvf_sha256:sha,sendable:true}
async function open(w:any){w.element.open=true;await w.trigger('toggle');await flushPromises()}
async function click(w:any,label:string){await w.findAll('button').find((b:any)=>b.text()===label||b.attributes('aria-label')===label)!.trigger('click');await flushPromises()}
it('does not load while collapsed and queries favorites lazily without writes',async()=>{
 const fetch=vi.fn(async(_url:unknown)=>new Response(JSON.stringify({items:[item],total:1})));vi.stubGlobal('fetch',fetch);const w=mount(ItemCollection);await flushPromises();expect(fetch).not.toHaveBeenCalled();await open(w);expect(fetch.mock.calls[0][0]).toBe('/dnf-gm/api/v1/catalog/collections?collection=favorites&page=1');expect(w.text()).toContain('同桌硬币');expect(w.text()).toContain('不代表发放或领取');await click(w,'加入清单');expect(w.emitted('select')?.[0]).toEqual([item]);expect(fetch).toHaveBeenCalledTimes(1);w.unmount()
})
it('switches recent/favorites and paginates in bounded requests',async()=>{
 const calls:string[]=[];vi.stubGlobal('fetch',vi.fn(async(url)=>{calls.push(url.toString());return new Response(JSON.stringify({items:[item],total:75}))}));const w=mount(ItemCollection);await open(w);await click(w,'下一页常用物品');expect(calls.at(-1)).toContain('favorites&page=2');await click(w,'最近选择');expect(calls.at(-1)).toContain('recent&page=1');w.unmount()
})
it('blocks disabled item selection without hiding the reason or the favorite control',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[{...item,sendable:false,policy_reason:'测试停用'}],total:1}))));const w=mount(ItemCollection);await open(w);expect(w.text()).toContain('测试停用');expect(w.findAll('button').find(b=>b.text()==='加入清单')!.attributes('disabled')).toBeDefined();expect(w.find('[aria-label="收藏 同桌硬币"]').attributes('disabled')).toBeUndefined();w.unmount()
})
it('queries again after preference changes only when open, and ignores a stale result',async()=>{
 let finish:(r:Response)=>void=()=>{};vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[item],total:1}))));const w=mount(ItemCollection,{props:{revision:0}});await open(w);vi.mocked(fetch).mockImplementationOnce(()=>new Promise(r=>finish=r));await w.setProps({revision:1});await click(w,'最近选择');finish(new Response(JSON.stringify({items:[{...item,name:'旧结果'}],total:1})));await flushPromises();expect(w.text()).not.toContain('旧结果');w.element.open=false;await w.trigger('toggle');const count=vi.mocked(fetch).mock.calls.length;await w.setProps({revision:2});expect(fetch).toHaveBeenCalledTimes(count);w.unmount()
})
it('renders request failure inside collection with a read-only retry',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('{"detail":"需要迁移"}',{status:503})));const w=mount(ItemCollection);await open(w);expect(w.find('[role=alert]').text()).toContain('需要迁移');expect(w.text()).not.toContain('没有收藏');vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({items:[],total:0})));await click(w,'重试常用物品查询');expect(w.text()).toContain('没有收藏');w.unmount()
})
it('favorite sends desired state plus PVF and CSRF, never sends a reward',async()=>{
 setCsrf('test-csrf');vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({favorite:true}))));const w=mount(FavoriteButton,{props:{item}});await w.find('button').trigger('click');await flushPromises();const [url,options]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('/dnf-gm/api/v1/catalog/8388/favorite');expect(options?.method).toBe('PUT');expect(JSON.parse(options?.body as string)).toEqual({pvf_sha256:sha,favorite:true});expect(options?.headers).toMatchObject({'X-CSRF-Token':'test-csrf'});expect(w.emitted('changed')?.[0]).toEqual([{id:8388,pvf_sha256:sha,favorite:true}]);w.unmount()
})
it('favorite error is local and does not falsely change saved state',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('{"detail":"索引版本已改变"}',{status:409})));const w=mount(FavoriteButton,{props:{item}});await w.find('button').trigger('click');await flushPromises();expect(w.find('[role=alert]').text()).toContain('索引版本已改变');expect(w.find('button').attributes('aria-pressed')).toBe('false');expect(w.emitted('changed')).toBeUndefined();w.unmount()
})
it('guards pending favorite requests and rejects item without version',async()=>{
 let finish:(v:Response)=>void=()=>{};vi.stubGlobal('fetch',vi.fn(()=>new Promise(r=>finish=r)));const w=mount(FavoriteButton,{props:{item}});await w.find('button').trigger('click');await w.find('button').trigger('click');expect(fetch).toHaveBeenCalledTimes(1);expect(w.find('button').attributes('disabled')).toBeDefined();finish(new Response('{"favorite":true}'));await flushPromises();await w.setProps({item:{...item,pvf_sha256:undefined}});expect(w.find('button').attributes('disabled')).toBeDefined();w.unmount()
})
it('renders untrusted item names as text',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[{...item,name:'<img src=x onerror=alert(1)>'}],total:1}))));const w=mount(ItemCollection);await open(w);expect(w.find('img').exists()).toBe(false);expect(w.text()).toContain('<img src=x');w.unmount()
})
