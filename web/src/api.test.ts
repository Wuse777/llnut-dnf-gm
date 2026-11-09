import {afterEach,describe,it,expect,vi} from 'vitest'
import {api,setCsrf,uncertainMessage,validationMessage,onApiReadInvalidation} from './api'
describe('same-origin API safety',()=>{
 afterEach(()=>vi.unstubAllGlobals())
 it('sends cookie and CSRF only on mutations, never stores tokens',async()=>{
  const fetcher=vi.fn().mockResolvedValue(new Response('{}',{status:200}));vi.stubGlobal('fetch',fetcher);setCsrf('ephemeral-csrf')
  await api('/operations/preview','POST',{uid:3});expect(fetcher.mock.calls[0][1].credentials).toBe('same-origin');expect(fetcher.mock.calls[0][1].headers['X-CSRF-Token']).toBe('ephemeral-csrf')
 })
 it('does not automatically replay an uncertain write',async()=>{
  const fetcher=vi.fn().mockRejectedValue(new Error('network lost'));vi.stubGlobal('fetch',fetcher)
  await expect(api('/operations/abc/confirm','POST',{idempotency_key:'fixture'})).rejects.toThrow('network lost');expect(fetcher).toHaveBeenCalledTimes(1)
 })
 it('returns sanitized service errors',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('{"detail":"余额变化，必须重新预览"}',{status:409})));await expect(api('/x')).rejects.toThrow('重新预览')})
 it('unknown errors instruct result lookup instead of resubmission',()=>{expect(uncertainMessage(null)).toContain('原编号')})
})

describe('explicit GET cancellation',()=>{
 afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers()})
 it('cancels a GET without retrying and rejects cancellation options on writes',async()=>{
  const fetcher=vi.fn((_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true})))
  vi.stubGlobal('fetch',fetcher)
  const controller=new AbortController(),read=api('/catalog','GET',undefined,{signal:controller.signal})
  const rejected=expect(read).rejects.toMatchObject({name:'AbortError'});controller.abort();await rejected
  await expect(api('/operations/id/confirm','POST',{}, {signal:controller.signal})).rejects.toThrow('写请求不支持取消')
  expect(fetcher).toHaveBeenCalledTimes(1)
 })
 it('retains the ten-second timeout and never retries reads',async()=>{
  vi.useFakeTimers()
  const fetcher=vi.fn((_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true})))
  vi.stubGlobal('fetch',fetcher)
  const read=api('/slow'),rejected=expect(read).rejects.toMatchObject({name:'TimeoutError'})
  await vi.advanceTimersByTimeAsync(9999);expect(fetcher.mock.calls[0][1].signal.aborted).toBe(false)
  await vi.advanceTimersByTimeAsync(1);await rejected;expect(fetcher).toHaveBeenCalledTimes(1)
 })
 it('does not invalidate a new session for an old request 401 or completed write',async()=>{
  const responses:((value:Response)=>void)[]=[],events:string[]=[]
  vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(resolve=>responses.push(resolve))))
  setCsrf('identity-a')
  const unsubscribe=onApiReadInvalidation(event=>events.push(event.reason))
  const oldRead=api('/old'),oldWrite=api('/players/visit','POST',{uid:1})
  setCsrf('identity-b');events.length=0
  const rejected=expect(oldRead).rejects.toMatchObject({status:401})
  responses[0](new Response('{"detail":"过期"}',{status:401}));responses[1](new Response('{}'))
  await rejected;await oldWrite;expect(events).toEqual([]);unsubscribe()
 })
})
it('reports field validation without exposing supplied passwords',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:[{loc:['body','delta'],type:'int_type',input:'secret-not-for-logs'}]}),{status:422})))
 await expect(api('/operations/preview','POST',{})).rejects.toThrow('变更金额：请填写整数')
})

it('uses Chinese support field names without echoing stored text',()=>{
 const message=validationMessage([{loc:['body','note'],type:'string_too_short',input:'private-note'},{loc:['body','tags',0],type:'string_too_long'}]);expect(message).toContain('处理说明：内容不能为空');expect(message).toContain('玩家标签 / 0');expect(message).not.toContain('private-note')
})
