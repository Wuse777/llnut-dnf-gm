// @vitest-environment happy-dom
import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import CharacterDetails from './CharacterDetails.vue'
import CharacterOverview from './CharacterOverview.vue'
import {api} from '../api'
vi.mock('../api',()=>({api:vi.fn(),uncertainMessage:(error:Error)=>error.message}))
const mounted:ReturnType<typeof mount>[]=[]
afterEach(()=>{mounted.splice(0).forEach(wrapper=>wrapper.unmount());vi.mocked(api).mockReset();document.body.innerHTML=''})
function overview(id=4){return {character:{charac_no:id,uid:id+10,charac_name:'角色'+id,lev:60,fatigue:22,max_fatigue:156,delete_flag:0},account:{uid:id+10,accountname:'账号'+id},account_online:{login_status:0},profession:{name:'剑魂'},wealth:{state:'ok',gold:2300},play_state:{fatigue:22,last_play_time:'2026-11-09 12:30:00'},equipment:{state:'ok',items:[{id:100,slot:0,name:'存档武器',quantity:1,enhancement:9,category:'equipment'}]},backpack_summary:{state:'ok',occupied_slots:9,slot_count:249,items:[{id:200,slot:8,name:'背包药水',quantity:30}]},support_summary:{state:'ok',open_count:1,in_progress_count:1,items:[{case_id:'a'.repeat(32),title:'任务卡住',scope:'character',status:'open'},{case_id:'b'.repeat(32),title:'账号补偿',scope:'account',status:'in_progress'}]},mail_summary:{state:'ok',checked_attachments:17,unclaimed_marker:3,client_verified:false},attributes:[],catalog_state:'ok',collected_at:1794227400,snapshot_note:'数据库存档快照'}}
function render(){const wrapper=mount(CharacterDetails,{props:{characNo:4,embedded:true},global:{stubs:{CharacterMaintenance:{template:'<p>疲劳恢复表单</p>'}}},attachTo:document.body});mounted.push(wrapper);return wrapper}
it('loads one lightweight overview and shows equipment, backpack and follow-up summaries',async()=>{
 vi.mocked(api).mockResolvedValue(overview());const wrapper=render();await flushPromises()
 expect(api).toHaveBeenCalledTimes(1);expect(api).toHaveBeenCalledWith('/characters/4/overview')
 expect(wrapper.findAll('.overview-equipment-grid>button')).toHaveLength(12)
 expect(wrapper.text()).toContain('存档武器');expect(wrapper.text()).toContain('背包药水');expect(wrapper.text()).toContain('任务卡住');expect(wrapper.text()).toContain('账号问题');expect(wrapper.text()).toContain('最近 17 条后台投递附件')
 expect(wrapper.text()).not.toContain('暂无可用人物图片');expect(wrapper.find('.character-basic-visual').exists()).toBe(false)
 await wrapper.get('[aria-label="武器：存档武器"]').trigger('click');await flushPromises()
 expect(document.querySelector('[role=dialog]')?.textContent).toContain('存档武器');expect(api).toHaveBeenCalledTimes(1)
})
it('reads full containers only when opened, keeps a loading state, and reuses the result',async()=>{
 let resolveDetail:(value:any)=>void=()=>{}
 vi.mocked(api).mockImplementation(path=>path.endsWith('/overview')?Promise.resolve(overview()):new Promise(resolve=>{resolveDetail=resolve}))
 const wrapper=render();await flushPromises();await wrapper.get('#character-tab-backpack').trigger('click');await flushPromises()
 expect(api).toHaveBeenCalledTimes(2);expect(api).toHaveBeenLastCalledWith('/characters/4');expect(wrapper.text()).toContain('按需读取此页的完整存档')
 expect(wrapper.find('#character-section-backpack')?.isVisible()).toBe(false)
 resolveDetail({...overview(),backpack:{state:'ok',slot_count:249,items:[{id:201,slot:1,name:'完整背包物品',quantity:1}]},warehouse:{state:'ok',items:[],slot_count:10}});await flushPromises()
 expect(wrapper.text()).toContain('完整背包物品');await wrapper.get('#character-tab-warehouse').trigger('click');await flushPromises();expect(api).toHaveBeenCalledTimes(2)
 await wrapper.get('#character-tab-basic').trigger('click');await flushPromises();expect(wrapper.text()).toContain('任务卡住')
})
it('does not let an old full-detail response replace a newly selected character',async()=>{
 let resolveOld:(value:any)=>void=()=>{}
 vi.mocked(api).mockImplementation(path=>path.endsWith('/overview')?Promise.resolve(overview(path.includes('/5/')?5:4)):new Promise(resolve=>{resolveOld=resolve}))
 const wrapper=render();await flushPromises();await wrapper.get('#character-tab-attributes').trigger('click');await flushPromises();await wrapper.setProps({characNo:5,initialSection:'basic'});await flushPromises()
 resolveOld({...overview(4),backpack:{state:'ok',items:[]}});await flushPromises()
 expect(wrapper.text()).toContain('角色5');expect(wrapper.text()).not.toContain('角色4');expect(wrapper.find('[data-testid=character-overview]').exists()).toBe(true)
})
it('keeps issue identity and known mail-marker scope explicit without inventing zeros',async()=>{
 const data=overview();const wrapper=mount(CharacterOverview,{props:{detail:data}});mounted.push(wrapper)
 await wrapper.findAll('.overview-case')[0].trigger('click');expect(wrapper.emitted('support')?.[0]).toEqual([{uid:14,case_id:'a'.repeat(32)}])
 await wrapper.setProps({detail:{...data,backpack_summary:{state:'unknown',items:[]},support_summary:{state:'unknown',items:[]},mail_summary:{state:'unknown'}}})
 expect(wrapper.text()).toContain('问题摘要暂不可用');expect(wrapper.text()).toContain('不能视为空背包');expect(wrapper.text()).not.toContain('暂无待处理问题')
})
