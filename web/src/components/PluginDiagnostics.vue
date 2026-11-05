<script setup lang="ts">
defineProps<{data:any}>()
const states:Record<string,string>={matched:'磁盘脚本已匹配',unreviewed:'脚本版本变化 · 待核对',unknown:'采集未知／过期'}
function date(v:any){return typeof v==='number'?new Date(v*1000).toLocaleString('zh-CN',{hour12:false}):'暂无有效采集时间'}
</script>
<template><section class="panel plugin-diagnostics" aria-labelledby="plugin-diagnostics-title">
 <header class="section-title"><div><small>LLNUT · 插件与客户端辅助</small><h2 id="plugin-diagnostics-title">插件来源与配置说明</h2></div><span class="pill">{{states[data.state]||states.unknown}}</span></header>
 <p class="notice">{{data.note}}</p>
 <dl class="plugin-facts"><div><dt>证据时间</dt><dd>{{date(data.collected_at)}}{{data.fresh?'':' · 非实时有效证据'}}</dd></div><div><dt>运行中加载状态</dt><dd>未核验，不能当作已生效</dd></div><div><dt>已确认可编辑的游戏开关</dt><dd>暂无；不是管理员权限被限制</dd></div></dl>
 <details v-if="data.source_sha256"><summary>查看已采集脚本指纹</summary><code>{{data.source_sha256}}</code></details>
 <template v-if="data.state==='matched'"><h3>已识别的服务端启动配置</h3><p class="field-hint">全服／频道范围表示代码的作用对象，不代表当前每个进程均已加载；本页不修改这些启动调用。</p><div class="plugin-rows"><article v-for="row in data.startup" :key="row.id"><div><b>{{row.label}}</b><p>{{row.source_setting}}</p></div><div><small>作用范围</small><p>{{row.scope}}</p><small>生效边界</small><p>{{row.activation}}</p></div></article></div></template>
 <p v-else class="warning">无法确认当前脚本的配置范围。请使用页面上方“刷新状态”重新采集；版本变化时不会沿用旧说明或伪造开关。</p>
 <section class="plugin-boundary"><h3>配置文件能改什么？</h3><p>{{data.configuration.note}}</p></section>
 <section class="plugin-boundary"><h3>客户端的技能0CD／无敌菜单</h3><p>{{data.client.note}}</p><p class="field-hint">没有匹配客户端的证据前，不承诺“仅GM可用”“所有账号默认开启”或“后台已禁止”。已有公告、踢人与角色维护仍通过各自的GM入口操作。</p></section>
</section></template>
<style scoped>
.plugin-diagnostics{display:grid;gap:16px}.plugin-diagnostics header{align-items:flex-start;gap:16px;flex-wrap:wrap}.plugin-diagnostics h2{margin:6px 0 0}.plugin-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0}.plugin-facts>div,.plugin-boundary{padding:14px;border:1px solid var(--border-color);border-radius:10px;background:var(--bg-secondary)}dt,small{color:var(--text-secondary);font-size:12px}dd{margin:6px 0 0}.plugin-rows{border:1px solid var(--border-color);border-radius:10px;overflow:hidden}.plugin-rows article{display:grid;grid-template-columns:minmax(150px,1fr) minmax(0,2fr);gap:18px;padding:16px}.plugin-rows article+article{border-top:1px solid var(--border-color)}.plugin-rows p{margin:6px 0 10px}.plugin-diagnostics p,.plugin-diagnostics code,.plugin-diagnostics dd{overflow-wrap:anywhere}.plugin-diagnostics code{display:block;margin-top:10px;font-size:12px}.plugin-boundary h3{margin:0 0 8px}.plugin-boundary p{margin:8px 0 0}@media(max-width:680px){.plugin-facts,.plugin-rows article{grid-template-columns:1fr}.plugin-rows article{gap:8px}}
</style>
