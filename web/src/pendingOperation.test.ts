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
