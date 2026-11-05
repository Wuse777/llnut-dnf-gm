// @vitest-environment happy-dom
import {mount} from '@vue/test-utils'
import {describe,it,expect} from 'vitest'
import PluginDiagnostics from './PluginDiagnostics.vue'
describe('plugin source evidence',()=>{
 it('distinguishes reviewed disk configuration from runtime and client permissions',()=>{
  const data={state:'matched',fresh:true,collected_at:100,source_sha256:'a'.repeat(64),note:'磁盘脚本不是运行中状态',startup:[{id:'x',label:'已识别功能',source_setting:'启动注册',scope:'游戏进程',activation:'下次加载'}],configuration:{note:'仅数据库连接，无游戏开关'},client:{note:'不能证明普通账号或GM账号的辅助权限'}}
  const w=mount(PluginDiagnostics,{props:{data}})
  expect(w.text()).toContain('未核验，不能当作已生效');expect(w.text()).toContain('启动注册');expect(w.findAll('input,button').length).toBe(0)
  w.unmount()
 })
 it('does not display old startup rows with stale evidence',()=>{
  const w=mount(PluginDiagnostics,{props:{data:{state:'unknown',fresh:false,note:'未知',startup:[{id:'x',label:'旧功能'}],configuration:{note:'未知'},client:{note:'未检查'}}}})
  expect(w.text()).toContain('采集未知／过期');expect(w.text()).not.toContain('旧功能')
 })
})
