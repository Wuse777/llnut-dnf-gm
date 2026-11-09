import {afterEach,expect,it,vi} from 'vitest'
import {api,ApiError,invalidateApiReads,setCsrf} from './api'
import {createReadQuery,invalidateReadQueries,isReadAbort} from './readQuery'

const readers:ReturnType<typeof createReadQuery>[]=[]
function reader(options:Parameters<typeof createReadQuery>[0]={}){const value=createReadQuery(options);readers.push(value);return value}
function deferredFetch(){
 const pending:{resolve:(value:Response)=>void,signal:AbortSignal}[]=[]
 const fetcher=vi.fn((_url,options)=>new Promise<Response>(resolve=>pending.push({resolve,signal:options.signal})))
 vi.stubGlobal('fetch',fetcher)
 return {pending,fetcher,reply:(index:number,value:unknown,status=200)=>pending[index].resolve(new Response(JSON.stringify(value),{status}))}
}
afterEach(()=>{readers.splice(0).forEach(value=>value.dispose());vi.unstubAllGlobals();vi.useRealTimers()})

it('shares identical in-flight GETs while preserving path and partition boundaries',async()=>{
 const {fetcher,reply}=deferredFetch(),reads=reader()
 const first=reads.get('/catalog?page=1',{partition:'pvf-a'}),same=reads.get('/catalog?page=1',{partition:'pvf-a'})
 const next=reads.get('/catalog?page=2',{partition:'pvf-a'}),other=reads.get('/catalog?page=1',{partition:'pvf-b'})
 expect(fetcher).toHaveBeenCalledTimes(3)
 reply(0,{items:[{id:1}]});reply(1,{items:[]});reply(2,{items:[]})
 const [a,b]=await Promise.all([first,same]);a.items[0].id=9;expect(b.items[0].id).toBe(1)
 await Promise.all([next,other])
})
it('cancels one subscriber independently and aborts transport when the last subscriber leaves',async()=>{
 const {pending,reply}=deferredFetch(),reads=reader(),a=new AbortController(),b=new AbortController()
 const first=reads.get('/shared',{signal:a.signal}),second=reads.get('/shared',{signal:b.signal})
 const rejected=expect(first).rejects.toMatchObject({name:'AbortError'});a.abort();await rejected
 expect(pending[0].signal.aborted).toBe(false)
 reply(0,{ok:true});await expect(second).resolves.toEqual({ok:true})
 const last=new AbortController(),abandoned=reads.get('/abandoned',{signal:last.signal}),cancelled=expect(abandoned).rejects.toMatchObject({name:'AbortError'})
 last.abort();await cancelled;expect(pending[1].signal.aborted).toBe(true)
 reply(1,{ignored:true})
})
it('bounds cached results at twelve entries and thirty seconds, supports refresh, and stores copies',async()=>{
 vi.useFakeTimers();let count=0
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({value:++count})));vi.stubGlobal('fetch',fetcher)
 const reads=reader({ttlMs:999999,maxEntries:99})
 const initial=await reads.get('/0');initial.value=999;expect((await reads.get('/0')).value).toBe(1)
 await reads.get('/0',{force:true});expect(fetcher).toHaveBeenCalledTimes(2)
 for(let index=1;index<13;index++)await reads.get('/'+index)
 await reads.get('/0');expect(fetcher).toHaveBeenCalledTimes(15)
 await reads.get('/0');expect(fetcher).toHaveBeenCalledTimes(15)
 await vi.advanceTimersByTimeAsync(30001);await reads.get('/0');expect(fetcher).toHaveBeenCalledTimes(16)
})
it('does not cache workspace results unless requested',async()=>{
 const fetcher=vi.fn(async()=>new Response('{}'));vi.stubGlobal('fetch',fetcher)
 const reads=reader();await reads.get('/accounts');await reads.get('/accounts');expect(fetcher).toHaveBeenCalledTimes(2)
})
it('revalidates a cache hit if a write invalidates it before its consumer runs',async()=>{
 let version=0
 const fetcher=vi.fn(async()=>new Response(JSON.stringify({version:++version})));vi.stubGlobal('fetch',fetcher)
 const reads=reader({ttlMs:30000});await reads.get('/catalog')
 const cached=reads.get('/catalog');invalidateApiReads('mutation')
 await expect(cached).resolves.toEqual({version:2});expect(fetcher).toHaveBeenCalledTimes(2)
})
it('clears cached state and cancels all reads on session changes including cached microtasks',async()=>{
 const {pending,reply,fetcher}=deferredFetch(),reads=reader({ttlMs:30000})
 const first=reads.get('/cached');reply(0,{id:1});await first
 const cached=reads.get('/cached'),slow=reads.get('/slow')
 const cachedRejected=expect(cached).rejects.toMatchObject({name:'AbortError'}),slowRejected=expect(slow).rejects.toMatchObject({name:'AbortError'})
 invalidateReadQueries();await cachedRejected;await slowRejected;expect(pending[1].signal.aborted).toBe(true)
 reply(1,{id:99})
 const fresh=reads.get('/cached');expect(fetcher).toHaveBeenCalledTimes(3);reply(2,{id:2});await expect(fresh).resolves.toEqual({id:2})
})
it('invalidates cache after writes without cancelling unrelated GETs or repopulating from pre-write responses',async()=>{
 const {pending,reply,fetcher}=deferredFetch(),reads=reader({ttlMs:30000})
 const before=reads.get('/catalog'),write=api('/players/visit','POST',{uid:1})
 reply(1,{});await write;expect(pending[0].signal.aborted).toBe(false)
 const fresh=reads.get('/catalog');expect(fetcher).toHaveBeenCalledTimes(3);reply(2,{version:'after'});await fresh
 reply(0,{version:'before'});await expect(before).resolves.toEqual({version:'before'})
 await expect(reads.get('/catalog')).resolves.toEqual({version:'after'});expect(fetcher).toHaveBeenCalledTimes(3)
})
it('preserves the originating 401 while cancelling other pending queries',async()=>{
 const {reply,pending}=deferredFetch(),reads=reader({ttlMs:30000})
 const denied=reads.get('/denied'),other=reads.get('/other')
 const deniedRejected=expect(denied).rejects.toBeInstanceOf(ApiError),otherRejected=expect(other).rejects.toMatchObject({name:'AbortError'})
 reply(0,{detail:'登录已过期'},401);await deniedRejected;await otherRejected
 expect(pending[1].signal.aborted).toBe(true);reply(1,{old:true})
 expect(isReadAbort(new DOMException('cancel','AbortError'))).toBe(true)
 expect(isReadAbort(new DOMException('timeout','TimeoutError'))).toBe(false)
})
it('does not let a stale raw 401 invalidate a new session cache or active query',async()=>{
 const {reply,pending,fetcher}=deferredFetch()
 setCsrf('read-query-old');const old=api('/old-session'),oldRejected=expect(old).rejects.toMatchObject({status:401})
 setCsrf('read-query-new');const reads=reader({ttlMs:30000}),fresh=reads.get('/catalog')
 reply(1,{fresh:true});await fresh
 const active=reads.get('/accounts')
 reply(0,{detail:'old session expired'},401);await oldRejected
 expect(pending[2].signal.aborted).toBe(false);await expect(reads.get('/catalog')).resolves.toEqual({fresh:true});expect(fetcher).toHaveBeenCalledTimes(3)
 reply(2,{items:[]});await active
})
