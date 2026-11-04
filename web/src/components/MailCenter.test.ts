// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import MailCenter from './MailCenter.vue'
const op='a'.repeat(32)
const batch={operation_id:op,target_uid:3,charac_no:4,account_name:'gm',character_name:'测试',postal_count:51,recorded_count:51,history_complete:1,message:'reward',letter_id:8,request:{uid:3,charac_no:4,items:[{id:99,quantity:51}],gold:10},created_at:'2026-11-04 00:00:00'}
afterEach(()=>{vi.unstubAllGlobals();document.body.innerHTML=''})
function setup(){
 const fetcher=vi.fn(async(url:any)=>{
  const path=String(url)
  if(path.includes('/mail-center?'))return new Response(JSON.stringify({items:[batch],has_more:false}))
  return new Response(JSON.stringify({batch,items:[{ordinal:1,postal_id:1,item_id:99,quantity:1,gold:10,receipt_state:path.includes('after=50')?'record_missing':'unclaimed_marker'}],next_after:path.includes('after=50')?null:50,note:'数据库标记，不表示游戏内效果'}))
 });vi.stubGlobal('fetch',fetcher);return {w:mount(MailCenter),fetcher}
}
async function click(w:any,text:string){await w.findAll('button').find((b:any)=>b.text()===text)!.trigger('click');await flushPromises()}
it('queries complete receipt pages and emits a draft without posting',async()=>{
 const {w,fetcher}=setup();await flushPromises();await click(w,'查看全部附件');expect(w.text()).toContain('数据库未领取');await click(w,'下一页附件');expect(w.text()).toContain('记录缺失 · 领取未知');expect(fetcher.mock.calls.some(([u])=>String(u).endsWith('after=50'))).toBe(true);await click(w,'复制为新发放草稿');expect(w.emitted('draft')?.[0][0]).toEqual(batch.request);expect(w.find('[role=dialog]').exists()).toBe(false);w.unmount()
})
it('validates immediately beside filters and sends no invalid request',async()=>{
 const {w,fetcher}=setup();await flushPromises();await w.find('[aria-label="邮件账号UID"]').setValue('-2');await w.find('form').trigger('submit');await flushPromises();expect(w.find('[role=alert]').text()).toContain('正整数');expect(fetcher).toHaveBeenCalledTimes(1);w.unmount()
})
it('shows errors at detail view and retries only reads',async()=>{
 const {w,fetcher}=setup();await flushPromises();fetcher.mockResolvedValueOnce(new Response('{"detail":"读取失败"}',{status:503}));await click(w,'查看全部附件');expect(w.find('[role=dialog] [role=alert]').text()).toContain('读取失败');await click(w,'重试查询');expect(w.text()).toContain('数据库未领取');w.unmount()
})
it('clears stale detail when target changes',async()=>{
 const {w}=setup();await flushPromises();await click(w,'查看全部附件');await w.setProps({uid:9,characNo:10});await flushPromises();expect(w.find('[role=dialog]').exists()).toBe(false);expect((w.find('[aria-label="邮件账号UID"]').element as HTMLInputElement).value).toBe('9');w.unmount()
})
