// @vitest-environment happy-dom
import {afterEach,expect,it,vi} from 'vitest'
import {createPinia,disposePinia,setActivePinia} from 'pinia'
import {api,setCsrf} from '../../api'
import {useGmCatalogStore} from './catalog'

const piniaStores:ReturnType<typeof createPinia>[]=[]
function setup(){const pinia=createPinia();piniaStores.push(pinia);setActivePinia(pinia);return useGmCatalogStore()}
const shaA='a'.repeat(64),shaB='b'.repeat(64)
afterEach(()=>{piniaStores.splice(0).forEach(disposePinia);vi.unstubAllGlobals()})

it('caches the first catalog result under its resolved PVF and isolates policy revisions',async()=>{
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:shaA},items:[{id:1,sendable:true}]})))
 vi.stubGlobal('fetch',fetcher);const catalog=setup()
 const first=await catalog.read('/catalog?page=1');first.items[0].sendable=false
 expect((await catalog.read('/catalog?page=1')).items[0].sendable).toBe(true);expect(fetcher).toHaveBeenCalledTimes(1)
 await catalog.read('/catalog?page=1',{revision:1});expect(fetcher).toHaveBeenCalledTimes(2)
 await catalog.read('/catalog?page=2',{revision:1});expect(fetcher).toHaveBeenCalledTimes(3)
})
it('prefers the latest resolved PVF over stale mounted context and refreshes after writes',async()=>{
 let sha=shaA
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:sha},items:[]})))
 vi.stubGlobal('fetch',fetcher);const catalog=setup()
 await catalog.read('/catalog?page=1');sha=shaB
 await catalog.read('/catalog?page=1',{force:true,pvf:shaA})
 expect((await catalog.read('/catalog?page=1',{pvf:shaA})).metadata.pvf_sha256).toBe(shaB);expect(fetcher).toHaveBeenCalledTimes(2)
 await api('/catalog/preferences','POST',{});await catalog.read('/catalog?page=1');expect(fetcher).toHaveBeenCalledTimes(4)
})
it('clears query contexts and cached PVF when the authenticated identity changes',async()=>{
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({metadata:{pvf_sha256:shaA},items:[]})))
 vi.stubGlobal('fetch',fetcher);const catalog=setup()
 catalog.contexts.player={filters:{q:'secret'},page:1,comparison:[],pvf:shaA}
 await catalog.read('/catalog?page=1');const version=catalog.sessionVersion;setCsrf('catalog-new-session')
 expect(catalog.contexts).toEqual({});expect(catalog.pvf).toBe('');expect(catalog.sessionVersion).toBeGreaterThan(version)
 await catalog.read('/catalog?page=1');expect(fetcher).toHaveBeenCalledTimes(2)
})
