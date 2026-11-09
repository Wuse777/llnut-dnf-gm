// @vitest-environment happy-dom
import {afterEach,it,expect,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createRouter,createMemoryHistory} from 'vue-router'
vi.mock('@/router',()=>({router:{push:vi.fn(),replace:vi.fn()}}))
import RewardComposerView from './RewardComposerView.vue'
import {workspaceFixture} from '../../stores/gm/workspace.test-helper'
const cleanups:(()=>void)[]=[]
afterEach(()=>{cleanups.splice(0).forEach(cleanup=>cleanup());sessionStorage.clear();vi.unstubAllGlobals()})
it('restores exact recipient from direct URL and keeps edits scoped to target draft',async()=>{const {gm,pinia,cleanup}=workspaceFixture();cleanups.push(cleanup);const router=createRouter({history:createMemoryHistory(),routes:[{path:'/rewards/compose',component:RewardComposerView}]});await router.push('/rewards/compose?uid=3&charac_no=30');await router.isReady();const wrapper=mount(RewardComposerView,{global:{plugins:[pinia,router]}});cleanups.push(()=>wrapper.unmount());await flushPromises();expect(gm.account.uid).toBe(3);expect(gm.selectedRole).toBe(30);expect((wrapper.get('#mail-role').element as HTMLSelectElement).value).toBe('30');await wrapper.get('#mail-gold').setValue(7);await router.replace('/rewards/compose?uid=4&charac_no=40');await flushPromises();expect(gm.account.uid).toBe(4);expect((wrapper.get('#mail-gold').element as HTMLInputElement).value).toBe('0');await router.replace('/rewards/compose?uid=3&charac_no=30');await flushPromises();expect((wrapper.get('#mail-gold').element as HTMLInputElement).value).toBe('7')})

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
