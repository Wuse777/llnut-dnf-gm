// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {ref,defineComponent} from 'vue'
import {mount,flushPromises} from '@vue/test-utils'
import {usePendingOperation,readPendingOperation} from './pendingOperation'
afterEach(()=>{vi.useRealTimers();vi.unstubAllGlobals();sessionStorage.clear()})
it('persists operation identity and recovers by GET without replaying',async()=>{
 vi.useFakeTimers();const f=vi.fn(async(_url:unknown,_options?:RequestInit)=>new Response(JSON.stringify({status:'committed',operation_id:'a'.repeat(32)})));vi.stubGlobal('fetch',f)
 const id=ref(''),resolved=vi.fn()
 const w=mount(defineComponent({setup(){usePendingOperation(id,ref(true),ref(false),resolved);return()=>null}}))
 id.value='a'.repeat(32);expect(readPendingOperation()).toBe(id.value)
 await vi.advanceTimersByTimeAsync(5000);await flushPromises()
 expect(resolved).toHaveBeenCalledTimes(1);expect(id.value).toBe('');expect(readPendingOperation()).toBe('');expect(f.mock.calls[0]?.[1]?.method).toBe('GET');w.unmount()
})
it('retains unresolved operation and keeps polling read-only, paused when not logged in',async()=>{
 vi.useFakeTimers();const f=vi.fn(async(_url:unknown,_options?:RequestInit)=>new Response(JSON.stringify({status:'preview'})));vi.stubGlobal('fetch',f)
 const id=ref('b'.repeat(32)),active=ref(false),resolved=vi.fn()
 const w=mount(defineComponent({setup(){usePendingOperation(id,active,ref(false),resolved);return()=>null}}))
 await vi.advanceTimersByTimeAsync(5000);expect(f).not.toHaveBeenCalled();active.value=true
 await vi.advanceTimersByTimeAsync(10000);expect(f).toHaveBeenCalledTimes(2);expect(id.value).toBe('b'.repeat(32));expect(resolved).not.toHaveBeenCalled();w.unmount()
 await vi.advanceTimersByTimeAsync(5000);expect(f).toHaveBeenCalledTimes(2)
})
it.each([false,true])('ignores an old lookup after logout even if logged back in before it returns (%s)',async relogin=>{
 vi.useFakeTimers()
 let release!:(value:Response)=>void
 const f=vi.fn((_url:unknown,_options?:RequestInit)=>new Promise<Response>(resolve=>release=resolve));vi.stubGlobal('fetch',f)
 const id=ref('c'.repeat(32)),active=ref(true),resolved=vi.fn()
 let pending!:ReturnType<typeof usePendingOperation>
 const w=mount(defineComponent({setup(){pending=usePendingOperation(id,active,ref(false),resolved);return()=>null}}))
 try{
  id.value='d'.repeat(32)
  await vi.advanceTimersByTimeAsync(5000);expect(f).toHaveBeenCalledTimes(1)
  const signal=f.mock.calls[0][1]?.signal
  active.value=false;expect(signal?.aborted).toBe(true)
  if(relogin)active.value=true
  release(new Response(JSON.stringify({status:'committed',operation_id:id.value})));await flushPromises()
  expect(resolved).not.toHaveBeenCalled();expect(id.value).toBe('d'.repeat(32));expect(readPendingOperation()).toBe(id.value)
  expect(pending.pendingChecked.value).toBe(0);expect(pending.pendingStatus.value).toBe('')
  if(relogin){
   f.mockResolvedValueOnce(new Response(JSON.stringify({status:'committed',operation_id:id.value})))
   await vi.advanceTimersByTimeAsync(5000);await flushPromises()
   expect(resolved).toHaveBeenCalledTimes(1);expect(id.value).toBe('')
  }
  expect(f.mock.calls.every(([,options])=>options?.method==='GET')).toBe(true)
 }finally{w.unmount()}
})
it('cancels an in-flight lookup on disposal without clearing its original identity',async()=>{
 vi.useFakeTimers()
 let release!:(value:Response)=>void
 const f=vi.fn((_url:unknown,_options?:RequestInit)=>new Promise<Response>(resolve=>release=resolve));vi.stubGlobal('fetch',f)
 const id=ref('e'.repeat(32)),resolved=vi.fn()
 const w=mount(defineComponent({setup(){usePendingOperation(id,ref(true),ref(false),resolved);return()=>null}}))
 await vi.advanceTimersByTimeAsync(5000)
 const signal=f.mock.calls[0][1]?.signal
 w.unmount();expect(signal?.aborted).toBe(true)
 release(new Response(JSON.stringify({status:'committed',operation_id:id.value})));await flushPromises()
 expect(resolved).not.toHaveBeenCalled();expect(id.value).toBe('e'.repeat(32))
 await vi.advanceTimersByTimeAsync(10000);expect(f).toHaveBeenCalledTimes(1)
})
