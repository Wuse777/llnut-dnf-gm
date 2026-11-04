// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import LiveSession from './LiveSession.vue'
const reply=(uid=3,state='online')=>({uid,database:{record:{login_status:1,channel:3011}},native:{uid,state,reason:state==='unknown'?'原生查询超时；不能据此判断离线':'原生响应',observed_at:state==='unknown'?null:Date.now()/1000}})
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers()})
it('only queries the exact selected account on demand using GET',async()=>{
 const fetch=vi.fn(async(_url:unknown,_options?:unknown)=>new Response(JSON.stringify(reply())));vi.stubGlobal('fetch',fetch)
 const w=mount(LiveSession,{props:{uid:3}});await flushPromises();expect(fetch).not.toHaveBeenCalled()
 await w.get('button').trigger('click');await flushPromises()
 expect(fetch).toHaveBeenCalledOnce();expect(fetch.mock.calls[0]?.[0]).toBe('/dnf-gm/api/v1/online/3/live')
 expect((fetch.mock.calls[0] as any)?.[1].method).toBe('GET')
 expect(w.text()).toContain('原生会话在线');expect(w.text()).toContain('登录表记录频道：3011');w.unmount()
})
it('shows native and database states separately rather than silently repairing',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(reply(3,'offline')))))
 const w=mount(LiveSession,{props:{uid:3}});await w.get('button').trigger('click');await flushPromises()
 expect(w.text()).toContain('原生会话离线');expect(w.text()).toContain('登录表记录为在线');w.unmount()
})
it('renders timeout as unknown and never offline',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(reply(3,'unknown')))))
 const w=mount(LiveSession,{props:{uid:3}});await w.get('button').trigger('click');await flushPromises()
 expect(w.text()).toContain('实时状态未知');expect(w.text()).not.toContain('原生会话离线');w.unmount()
})
it('shows local errors and clears previous success before refresh',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(reply()))).mockRejectedValueOnce(new Error('连接失败'))
 vi.stubGlobal('fetch',fetch)
 const w=mount(LiveSession,{props:{uid:3}});await w.get('button').trigger('click');await flushPromises()
 expect(w.text()).toContain('原生会话在线');await w.get('button').trigger('click');await flushPromises()
 expect(w.get('[role="alert"]').text()).toContain('连接失败');expect(w.text()).not.toContain('原生会话在线');w.unmount()
})
it('discards previous-player late replies and enables a new query',async()=>{
 let old:(x:Response)=>void=()=>{}
 const fetch=vi.fn().mockImplementationOnce(()=>new Promise(r=>old=r)).mockResolvedValueOnce(new Response(JSON.stringify(reply(4,'offline'))))
 vi.stubGlobal('fetch',fetch)
 const w=mount(LiveSession,{props:{uid:3}});await w.get('button').trigger('click');expect(w.get('button').attributes('disabled')).toBeDefined()
 await w.setProps({uid:4});await w.get('button').trigger('click');await flushPromises()
 old(new Response(JSON.stringify(reply())));await flushPromises()
 expect(w.text()).toContain('UID 4');expect(w.text()).toContain('原生会话离线');expect(w.text()).not.toContain('原生会话在线');w.unmount()
})
it('expires an observation without polling and clears its timer on unmount',async()=>{
 vi.useFakeTimers();const fetch=vi.fn(async(_url:unknown,_options?:unknown)=>new Response(JSON.stringify(reply())));vi.stubGlobal('fetch',fetch)
 const w=mount(LiveSession,{props:{uid:3}});await w.get('button').trigger('click');await flushPromises()
 expect(w.text()).toContain('原生会话在线');await vi.advanceTimersByTimeAsync(16000)
 expect(w.text()).toContain('实时状态未知');expect(w.text()).toContain('上次响应已超过 15 秒');expect(fetch).toHaveBeenCalledOnce()
 w.unmount();const calls=fetch.mock.calls.length;await vi.advanceTimersByTimeAsync(60000);expect(fetch.mock.calls.length).toBe(calls)
})
it('does not accept a response for another account',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(reply(4)))))
 const w=mount(LiveSession,{props:{uid:3}});await w.get('button').trigger('click');await flushPromises()
 expect(w.get('[role="alert"]').text()).toContain('不匹配');expect(w.text()).not.toContain('原生会话在线');w.unmount()
})
it('escapes returned descriptions',async()=>{
 const r=reply(3,'unknown');r.native.reason='<img src=x onerror=alert(1)>'
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify(r))))
 const w=mount(LiveSession,{props:{uid:3}});await w.get('button').trigger('click');await flushPromises()
 expect(w.find('img').exists()).toBe(false);expect(w.text()).toContain('<img');w.unmount()
})
