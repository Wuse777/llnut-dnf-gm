// @vitest-environment happy-dom
import {mount,flushPromises} from '@vue/test-utils'
import {describe,it,expect,vi} from 'vitest'
import AssetCoverage from './AssetCoverage.vue'
vi.mock('../api',()=>({api:vi.fn(),ApiError:class extends Error{},uncertainMessage:(e:any)=>e.message}))
import {api} from '../api'
describe('asset coverage',()=>{
 it('labels promotional artwork honestly and filters/paginates missing item records',async()=>{
  vi.mocked(api).mockResolvedValue({pvf_sha256:'a'.repeat(64),item_states:{ready:2,missing:38},portrait_total:1,portraits:[{job:0,grow_type:-1,sex:-1,name:'合成职业',image:{state:'ready',source_kind:'official_promotional',source_label:'官方来源说明',source_page:'https://dnf.qq.com/',match_level:'base'}}],items:[{id:990001,name:'合成物品',state:'missing'}],page:1,has_more:true})
  const w=mount(AssetCoverage);await flushPromises()
  expect(w.text()).toContain('5.0');expect(w.text()).toContain('不是从当前客户端NPK提取');expect(w.text()).toContain('基础职业示意');expect(w.text()).toContain('合成物品')
  expect(w.get('a').attributes('rel')).toContain('noopener')
  await w.get('select').setValue('unsupported');await flushPromises();expect(api).toHaveBeenLastCalledWith('/assets/coverage?state=unsupported&page=1')
  await w.findAll('button').find(b=>b.text()==='下一页')!.trigger('click');await flushPromises();expect(api).toHaveBeenLastCalledWith('/assets/coverage?state=unsupported&page=2')
  expect(vi.mocked(api).mock.calls.every(c=>c.length===1)).toBe(true);w.unmount()
 })
})
