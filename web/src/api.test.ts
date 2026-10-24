import {afterEach,describe,it,expect,vi} from 'vitest'
import {api,setCsrf,uncertainMessage} from './api'
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
it('reports field validation without exposing supplied passwords',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:[{loc:['body','delta'],type:'int_type',input:'secret-not-for-logs'}]}),{status:422})))
 await expect(api('/operations/preview','POST',{})).rejects.toThrow('变更金额：请填写整数')
})
