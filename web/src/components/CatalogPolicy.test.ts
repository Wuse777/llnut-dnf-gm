// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import CatalogPolicy from './CatalogPolicy.vue'
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
const op='a'.repeat(32)
const summary={matched:120,supported:100,skipped:20,affected:90,unchanged:10,policy_revision:2}
function setup(handler?:(p:string,o:any)=>Promise<Response>){
 const calls:{path:string,body:any}[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url,opts:any={})=>{const path=url.toString();calls.push({path,body:opts.body&&JSON.parse(opts.body)});if(handler)return handler(path,opts);return new Response(JSON.stringify(path.endsWith('/preview')?{operation_id:op,preview:summary}:path.endsWith('/confirm')?{affected:90,policy_revision:3}:{status:'committed',result:{affected:90,policy_revision:3}}))}))
 const w=mount(CatalogPolicy,{props:{filters:{q:'材料',category:'material',allowed_only:false}},attachTo:document.body});return {w,calls}
}
async function click(w:any,text:string){const button=w.findAll('button').find((b:any)=>b.text()===text)!;expect(button,'button '+text).toBeTruthy();await button.trigger('click');await flushPromises()}
async function preview(w:any){await w.find('#policy-reason').setValue('批量测试原因');await click(w,'预览影响范围')}
it('requires reason locally, places feedback beside field and focuses it without network',async()=>{
 const {w,calls}=setup();await click(w,'预览影响范围');expect(calls.length).toBe(0);expect(w.find('#policy-reason').attributes('aria-invalid')).toBe('true');expect(w.find('#policy-reason-error').text()).toContain('请填写');expect(document.activeElement).toBe(w.find('#policy-reason').element);w.unmount()
})
it('sends frozen full filters without page and shows counts before confirm',async()=>{
 const {w,calls}=setup();await preview(w);expect(calls[0].body).toEqual({item_id:null,enabled:true,filters:{q:'材料',category:'material',allowed_only:false},reason:'批量测试原因'});expect(w.text()).toContain('不仅是当前页');for(const n of ['120','90','20'])expect(w.text()).toContain(n);expect(calls).toHaveLength(1);expect(w.text()).toContain('不发送物品');await click(w,'确认变更一次');expect(w.text()).toContain('策略已保存');expect(w.emitted('changed')).toHaveLength(1);expect(calls[1].body.idempotency_key.length).toBeGreaterThan(16);w.unmount()
})
it('item disable starts with correct target and cannot claim manual enabling is verified',async()=>{
 const {w}=setup();w.unmount();const x=mount(CatalogPolicy,{props:{item:{id:990001,name:'普通装备',sendable:true,policy_reason:'允许试发'},filters:{}},attachTo:document.body});expect((x.find('select').element as HTMLSelectElement).value).toBe('false');await preview(x);expect(x.text()).toContain('禁止发放 · 变更预览');expect(x.text()).toContain('不冒充客户端已验证');x.unmount()
})
it('unconfirmed return allows new preview but never writes by itself',async()=>{
 const {w,calls}=setup();await preview(w);await click(w,'返回修改');expect(w.find('#policy-reason').exists()).toBe(true);expect(calls).toHaveLength(1);w.unmount()
})
it('lost response blocks repeat writes and queries original operation instead',async()=>{
 const {w,calls}=setup(async(p)=>{if(p.endsWith('/confirm'))throw new TypeError('网络中断');return new Response(JSON.stringify(p.endsWith('/preview')?{operation_id:op,preview:summary}:{status:'committed',result:{affected:90,policy_revision:3}}))});await preview(w);await click(w,'确认变更一次');expect(w.text()).toContain('结果待确认');expect(w.findAll('button').find(b=>b.text()==='确认变更一次')!.attributes('disabled')).toBeDefined();await click(w,'按原编号查询结果');expect(w.text()).toContain('策略已保存');expect(calls.filter(c=>c.path.endsWith('/confirm'))).toHaveLength(1);expect(calls.at(-1)!.path).toContain('/operations/'+op);w.unmount()
})
it('conflict error is in dialog, focusable and requires another preview',async()=>{
 const {w,calls}=setup(async(p)=>p.endsWith('/confirm')?new Response('{"detail":"策略版本变化，请重新预览"}',{status:409}):new Response(JSON.stringify({operation_id:op,preview:summary})));await preview(w);await click(w,'确认变更一次');expect(w.find('[role=alert]').text()).toContain('重新预览');expect(document.activeElement).toBe(w.find('[data-policy-error]').element);await click(w,'返回修改');await preview(w);expect(calls.filter(c=>c.path.endsWith('/preview'))).toHaveLength(2);w.unmount()
})
it('reauth rejection emits prompt, does not automatically retry',async()=>{
 const {w,calls}=setup(async()=>new Response('{"detail":"请重新认证"}',{status:403}));await preview(w);expect(w.emitted('reauth')).toHaveLength(1);expect(calls).toHaveLength(1);w.unmount()
})
it('escapes names and reasons and closes without writing',async()=>{
 const {w,calls}=setup();await w.setProps({item:{id:7,name:'<img src=x onerror=alert(1)>',policy_reason:'<script>bad</script>'}});expect(w.find('img').exists()).toBe(false);expect(w.find('script').exists()).toBe(false);expect(w.text()).toContain('<img');await click(w,'关闭');expect(w.emitted('close')).toHaveLength(1);expect(calls).toHaveLength(0);w.unmount()
})
it('session expiry closes policy via parent instead of retrying a sensitive request',async()=>{
 const {w,calls}=setup(async()=>new Response('{"detail":"请登录"}',{status:401}));await preview(w);expect(w.emitted('expired')).toHaveLength(1);expect(calls).toHaveLength(1);w.unmount()
})
