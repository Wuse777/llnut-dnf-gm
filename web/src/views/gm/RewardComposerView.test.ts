// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createRouter,createMemoryHistory} from 'vue-router'
vi.mock('@/router',()=>({router:{push:vi.fn(),replace:vi.fn()}}))
import RewardComposerView from './RewardComposerView.vue'
import {workspaceFixture} from '../../stores/gm/workspace.test-helper'
const cleanups:(()=>void)[]=[]
afterEach(()=>{cleanups.splice(0).forEach(cleanup=>cleanup());sessionStorage.clear();vi.unstubAllGlobals()})
it('restores exact recipient from direct URL and keeps edits scoped to target draft',async()=>{const {gm,pinia,cleanup}=workspaceFixture();cleanups.push(cleanup);const router=createRouter({history:createMemoryHistory(),routes:[{path:'/rewards/compose',component:RewardComposerView}]});await router.push('/rewards/compose?uid=3&charac_no=30');await router.isReady();const wrapper=mount(RewardComposerView,{global:{plugins:[pinia,router]}});cleanups.push(()=>wrapper.unmount());await flushPromises();expect(gm.account.uid).toBe(3);expect(gm.selectedRole).toBe(30);expect(wrapper.get('.recipient-summary').text()).toContain('#30');await wrapper.get('#mail-gold').setValue(7);await router.replace('/rewards/compose?uid=4&charac_no=40');await flushPromises();expect(gm.account.uid).toBe(4);expect((wrapper.get('#mail-gold').element as HTMLInputElement).value).toBe('0');await router.replace('/rewards/compose?uid=3&charac_no=30');await flushPromises();expect((wrapper.get('#mail-gold').element as HTMLInputElement).value).toBe('7')})

it('updates the URL for local recipient and role choices after the target lock releases',async()=>{
 const {gm,pinia,cleanup}=workspaceFixture();cleanups.push(cleanup)
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/rewards/compose',component:RewardComposerView}]})
 await router.push('/rewards/compose?uid=3&charac_no=30');await router.isReady()
 const wrapper=mount(RewardComposerView,{global:{plugins:[pinia,router]}});cleanups.push(()=>wrapper.unmount());await flushPromises()
 gm.mailGold=7;await gm.pickRecipient({uid:4,charac_no:40});await flushPromises()
 expect(router.currentRoute.value.query).toMatchObject({uid:'4',charac_no:'40'})
 expect(wrapper.get('.recipient-summary').text()).toContain('#40');expect(gm.mailGold).toBe(0)
 gm.selectedRole=0;await flushPromises()
 expect(router.currentRoute.value.query.charac_no).toBeUndefined();expect(wrapper.find('.recipient-panel').exists()).toBe(true)
 await gm.pickRecipient({uid:3,charac_no:30});await flushPromises()
 expect(router.currentRoute.value.query.uid).toBe('3');expect(gm.mailGold).toBe(7)
})

it('hides the old recipient form when a pending submission prevents a URL target change',async()=>{
 const {gm,pinia,cleanup}=workspaceFixture();cleanups.push(cleanup)
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/rewards/compose',component:RewardComposerView}]})
 await router.push('/rewards/compose?uid=3&charac_no=30');await router.isReady()
 const wrapper=mount(RewardComposerView,{global:{plugins:[pinia,router]}});cleanups.push(()=>wrapper.unmount());await flushPromises()
 gm.pendingId='a'.repeat(32);await router.replace('/rewards/compose?uid=4&charac_no=40');await flushPromises()
 expect(gm.account.uid).toBe(3);expect(gm.pendingId).toBe('a'.repeat(32))
 expect(wrapper.find('#mail-gold').exists()).toBe(false);expect(wrapper.get('.selection-guide').text()).toContain('尚未切换')
})

it('tracks target, preview and original submission status through all four stages',async()=>{
 const {gm,pinia,calls,cleanup}=workspaceFixture();cleanups.push(cleanup)
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/rewards/compose',component:RewardComposerView}]})
 await router.push('/rewards/compose');await router.isReady()
 const wrapper=mount(RewardComposerView,{global:{plugins:[pinia,router]}});cleanups.push(()=>wrapper.unmount());await flushPromises()
 const current=()=>wrapper.get('.reward-workflow-steps [aria-current="step"]').text()
 expect(current()).toContain('选择目标')
 expect(wrapper.findAll('.reward-workflow-steps li')).toHaveLength(4)
 await router.replace('/rewards/compose?uid=3&charac_no=30');await flushPromises()
 expect(current()).toContain('编辑奖励')
 await wrapper.get('#mail-gold').setValue(7);await wrapper.get('#operation-reason').setValue('阶段回归验证')
 await gm.makePreview();await flushPromises()
 expect(current()).toContain('核对预览')
 expect(calls.filter(call=>call.path.endsWith('/confirm'))).toHaveLength(0)
 gm.pendingId=gm.preview.operation_id;await flushPromises()
 expect(current()).toContain('确认与结果')
 expect(wrapper.get('.reward-workflow-hint').text()).toContain('待核对')
 gm.pendingId='';await gm.confirmOperation();await flushPromises()
 expect(current()).toContain('确认与结果')
 expect(wrapper.get('.reward-workflow-hint').text()).toContain('已取得提交结果')
 expect(calls.filter(call=>call.path.endsWith('/confirm'))).toHaveLength(1)
 await gm.nextMailDraft();await flushPromises()
 expect(current()).toContain('编辑奖励')
 expect(gm.account.uid).toBe(3);expect(gm.selectedRole).toBe(30)
})
it('collapses recipient search after target selection and reopening it keeps the draft intact',async()=>{
 const {gm,pinia,calls,cleanup}=workspaceFixture();cleanups.push(cleanup)
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/rewards/compose',component:RewardComposerView}]})
 await router.push('/rewards/compose?uid=3&charac_no=30');await router.isReady()
 const wrapper=mount(RewardComposerView,{global:{plugins:[pinia,router]}});cleanups.push(()=>wrapper.unmount());await flushPromises()
 expect(wrapper.find('.recipient-panel form').exists()).toBe(false);expect(wrapper.find('.recipient-context').exists()).toBe(false);expect(wrapper.find('.player-shortcuts').exists()).toBe(false);expect(wrapper.get('.recipient-summary').text()).toContain('UID 3 · #30')
 const beforeWrites=calls.filter(call=>call.method!=='GET').length
 gm.mailGold=19;await wrapper.get('.recipient-change').trigger('click');await flushPromises()
 expect(wrapper.get('.recipient-change').attributes('aria-expanded')).toBe('true');expect(gm.account.uid).toBe(3);expect(gm.selectedRole).toBe(30);expect(gm.mailGold).toBe(19)
 expect(calls.filter(call=>call.method!=='GET')).toHaveLength(beforeWrites)
 gm.pendingId='c'.repeat(32);await flushPromises();expect(wrapper.get('.recipient-change').attributes('disabled')).toBeDefined()
})

function mobile(){vi.stubGlobal('matchMedia',vi.fn((query:string)=>({matches:query.includes('max-width'),media:query,addEventListener:vi.fn(),removeEventListener:vi.fn(),addListener:vi.fn(),removeListener:vi.fn(),dispatchEvent:vi.fn()})))}
async function renderMobile(prepare?:(gm:ReturnType<typeof workspaceFixture>['gm'])=>Promise<void>|void){
 mobile();const {gm,pinia,cleanup}=workspaceFixture();cleanups.push(cleanup);await prepare?.(gm)
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/rewards/compose',component:RewardComposerView}]});await router.push('/rewards/compose?uid=3&charac_no=30');await router.isReady()
 const wrapper=mount(RewardComposerView,{global:{plugins:[pinia,router]}});cleanups.push(()=>wrapper.unmount());await flushPromises();return {wrapper,gm,router}
}
it('opens an empty mobile reward draft on items with one compact target row',async()=>{
 const {wrapper,gm}=await renderMobile();expect(gm.mailPane).toBe('items');expect(wrapper.get('.mail-workbench-frame').attributes('data-pane')).toBe('items');expect(wrapper.get('.recipient-summary').text()).toContain('角色3');expect(wrapper.find('.recipient-context').exists()).toBe(false);expect(wrapper.find('.player-shortcuts').exists()).toBe(false)
 await wrapper.get('.recipient-change').trigger('click');expect(wrapper.get('#mail-role').element).toHaveProperty('value','30');expect(wrapper.find('.player-shortcuts').exists()).toBe(true);expect(gm.mailPane).toBe('items')
})
it('keeps an existing nonempty mobile draft visible and preserves it across target changes',async()=>{
 const {wrapper,gm,router}=await renderMobile(async gm=>{await gm.setTarget(3,30);gm.mailGold=19;gm.reason='保留的草稿'});expect(gm.mailPane).toBe('draft');expect(gm.mailGold).toBe(19)
 await router.replace('/rewards/compose?uid=4&charac_no=40');await flushPromises();expect(gm.mailPane).toBe('items');expect(gm.mailGold).toBe(0)
 await router.replace('/rewards/compose?uid=3&charac_no=30');await flushPromises();expect(gm.mailPane).toBe('draft');expect(gm.mailGold).toBe(19);expect(gm.reason).toBe('保留的草稿');expect(wrapper.get('.recipient-summary').text()).toContain('#30')
})
it('keeps pending mobile submission context in the draft pane',async()=>{
 const {wrapper,gm}=await renderMobile(async gm=>{await gm.setTarget(3,30);gm.pendingId='f'.repeat(32)});expect(gm.mailPane).toBe('draft');expect(gm.pendingId).toBe('f'.repeat(32));expect(wrapper.get('.recipient-change').attributes('disabled')).toBeDefined()
})
