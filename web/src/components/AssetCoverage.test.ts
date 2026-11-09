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
  expect(w.get('.portrait-browser').attributes('open')).toBeUndefined()
  expect(w.get('.portrait-gallery').attributes('tabindex')).toBe('0')
  await w.get('select').setValue('unsupported');await flushPromises();expect(api).toHaveBeenLastCalledWith('/assets/coverage?state=unsupported&page=1')
  await w.findAll('button').find(b=>b.text()==='下一页')!.trigger('click');await flushPromises();expect(api).toHaveBeenLastCalledWith('/assets/coverage?state=unsupported&page=2')
  expect(vi.mocked(api).mock.calls.every(c=>c.length===1)).toBe(true);w.unmount()
 })
 it('keeps a small remaining gap visible and previews authenticated icons',async()=>{
  const image={state:'ready',url:'/dnf-gm/api/v1/assets/'+'a'.repeat(64)+'/'+'b'.repeat(64)+'.png'}
  vi.mocked(api).mockResolvedValue({pvf_sha256:'a'.repeat(64),item_states:{ready:66450,missing:3,missing_reference:1,unsupported:2},portrait_total:0,portraits:[],items:[{id:990001,name:'合成图标',state:'ready',image}],page:1,has_more:false})
  const w=mount(AssetCoverage);await flushPromises()
  expect(w.text()).toContain('>99.9');expect(w.text()).not.toContain('100.0');expect(w.text()).toContain('仍有 6 项图标不可读取')
  expect(w.get('img').attributes('src')).toBe(image.url);w.unmount()
 })
})

it('distinguishes profession fallback from exact growth portrait mappings',async()=>{
 const image={state:'ready',source_kind:'client',source_page:'https://www.dfoneople.com/gameinfo/character/all'}
 vi.mocked(api).mockResolvedValue({pvf_sha256:'a'.repeat(64),item_states:{},portrait_total:3,portraits:[
 {job:0,grow_type:17,sex:-1,name:'同转职插画',image:{...image,match_level:'profession',awakening_specific:false}},
 {job:0,grow_type:1,sex:-1,name:'精确转职插画',image:{...image,match_level:'growth'}},
 {job:0,grow_type:-1,sex:-1,name:'范围未核验插画',image}
 ],items:[],page:1,has_more:false})
 const w=mount(AssetCoverage);await flushPromises()
 expect(w.text()).toContain('同转职示意（觉醒未匹配）');expect(w.text()).toContain('精确转职映射');expect(w.text()).toContain('映射范围待核验')
 expect(w.findAll('a')).toHaveLength(3);expect(w.text()).toContain('客户端职业图');w.unmount()
})
