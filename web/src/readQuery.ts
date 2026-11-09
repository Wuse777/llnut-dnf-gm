import {api,invalidateApiReads,onApiReadInvalidation} from './api'

type ReadOptions={signal?:AbortSignal,force?:boolean,partition?:string}
type Cached={value:unknown,expires:number}
type Pending={controller:AbortController,promise:Promise<unknown>,subscribers:Set<(error:Error)=>void>,cancelled:boolean,settled:boolean}

function abortError(){return new DOMException('只读查询已取消','AbortError')}
export function isReadAbort(error:unknown){return error instanceof Error&&error.name==='AbortError'}
/** End an authentication lifetime. This never retries or replays a request. */
export function invalidateReadQueries(){invalidateApiReads('session')}

/** Memory-only GET queries. Result caching is opt-in; each caller owns its cancellation. */
export function createReadQuery(options:{ttlMs?:number,maxEntries?:number,resultPartition?:(value:any,requestedPartition:string)=>string}={}){
 const ttl=Math.max(0,Math.min(options.ttlMs??0,30000))
 const limit=Math.max(1,Math.min(options.maxEntries??12,12))
 const cache=new Map<string,Cached>(),inflight=new Map<string,Pending>(),active=new Set<Pending>()
 let session=0,cacheRevision=0,disposed=false
 const keyFor=(path:string,partition='')=>JSON.stringify([session,partition,path])
 const copy=<T>(value:T):T=>structuredClone(value)
 function stop(entry:Pending){
  entry.cancelled=true
  for(const reject of [...entry.subscribers])reject(abortError())
  entry.controller.abort()
 }
 function cancel(){for(const entry of [...active])stop(entry);inflight.clear()}
 function clear(){cacheRevision++;cache.clear();inflight.clear()}
 const unsubscribe=onApiReadInvalidation(event=>{
  clear()
  if(event.reason==='mutation')return
  session++
  // Preserve the originating 401 so its caller can end the authenticated UI session.
  for(const entry of [...active])if(entry.controller.signal!==event.source)stop(entry)
 })
 function save(key:string,value:unknown){
  if(!ttl)return
  const now=Date.now()
  for(const [oldKey,item] of cache)if(item.expires<=now)cache.delete(oldKey)
  cache.delete(key);cache.set(key,{value:copy(value),expires:now+ttl})
  while(cache.size>limit)cache.delete(cache.keys().next().value!)
 }
 function subscribe<T>(entry:Pending,signal?:AbortSignal):Promise<T>{
  return new Promise<T>((resolve,reject)=>{
   let done=false
   function cleanup(){done=true;entry.subscribers.delete(cancelCaller);signal?.removeEventListener('abort',onAbort)}
   function cancelCaller(error:Error=abortError()){
    if(done)return
    cleanup();reject(error)
    if(!entry.settled&&!entry.subscribers.size){entry.cancelled=true;entry.controller.abort()}
   }
   entry.subscribers.add(cancelCaller)
   function onAbort(){cancelCaller()}
   // Event listeners call with an Event argument, never use that as the rejection value.
   signal?.addEventListener('abort',onAbort,{once:true})
   entry.promise.then(value=>{if(!done){cleanup();resolve(copy(value as T))}},error=>{if(!done){cleanup();reject(error)}})
   if(signal?.aborted)onAbort()
  })
 }
 function get<T=any>(path:string,readOptions:ReadOptions={}):Promise<T>{
  if(disposed||readOptions.signal?.aborted)return Promise.reject(abortError())
  const key=keyFor(path,readOptions.partition),cached=cache.get(key)
  if(!readOptions.force&&cached&&cached.expires>Date.now()){
   cache.delete(key);cache.set(key,cached)
   const identity=session,revision=cacheRevision
   return Promise.resolve().then(()=>{
    if(disposed||identity!==session||readOptions.signal?.aborted)throw abortError()
    // A write completed between the lookup and its consumer: make the first network read.
    if(revision!==cacheRevision)return get<T>(path,{...readOptions,force:true})
    return copy(cached.value as T)
   })
  }
  if(cached)cache.delete(key)
  let entry=inflight.get(key)
  if(!entry||entry.cancelled){
   const revision=cacheRevision
   const next:Pending={controller:new AbortController(),promise:Promise.resolve(),subscribers:new Set(),cancelled:false,settled:false}
   next.promise=api(path,'GET',undefined,{signal:next.controller.signal}).then(value=>{
    if(next.cancelled)throw abortError()
    if(revision===cacheRevision){const partition=options.resultPartition?.(value,readOptions.partition??'')??readOptions.partition;save(keyFor(path,partition),value)}
    return value
   }).finally(()=>{next.settled=true;active.delete(next);if(inflight.get(key)===next)inflight.delete(key)})
   entry=next;inflight.set(key,next);active.add(next)
  }
  return subscribe<T>(entry,readOptions.signal)
 }
 function dispose(){if(disposed)return;disposed=true;clear();cancel();unsubscribe()}
 return {get,cancel,clear,dispose}
}
