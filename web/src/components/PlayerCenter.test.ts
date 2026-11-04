// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import PlayerCenter from './PlayerCenter.vue'
afterEach(()=>vi.unstubAllGlobals())
it('binds role actions to exact UID and character without writing',async()=>{
 const f=vi.fn(async(_url:unknown)=>new Response(JSON.stringify({items:[{charac_no:7,charac_name:'角色',lev:60,delete_flag:0}]})));vi.stubGlobal('fetch',f)
 const w=mount(PlayerCenter,{props:{account:{uid:3,accountname:'gm'}}});await flushPromises()
 await w.findAll('button').find(b=>b.text()==='给此角色发奖励')!.trigger('click')
 expect(w.emitted('action')?.[0][0]).toEqual({action:'mail',uid:3,charac_no:7})
 await w.findAll('button').find(b=>b.text()==='该玩家操作历史')!.trigger('click');await flushPromises()
 expect(f.mock.calls.map(c=>String(c[0]))).toContain('/dnf-gm/api/v1/audit?uid=3&page=1');w.unmount()
})
it('hides late responses belonging to the previous account',async()=>{
 let old:(r:Response)=>void=()=>{}
 vi.stubGlobal('fetch',vi.fn((u)=>String(u).includes('uid=3')?new Promise(r=>old=r):Promise.resolve(new Response(JSON.stringify({items:[{charac_no:9,charac_name:'新账号角色'}]})))))
 const w=mount(PlayerCenter,{props:{account:{uid:3,accountname:'old'}}});await w.setProps({account:{uid:4,accountname:'new'}});await flushPromises();old(new Response(JSON.stringify({items:[{charac_no:1,charac_name:'旧账号角色'}]})));await flushPromises()
 expect(w.text()).toContain('新账号角色');expect(w.text()).not.toContain('旧账号角色');w.unmount()
})
