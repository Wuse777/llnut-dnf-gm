<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
const data=ref<any>(null),busy=ref(false),error=ref('')
let alive=true,timer:ReturnType<typeof setInterval>|undefined
const deliveryNames:Record<string,string>={disabled:'未配置外部通知，仅保留本地记录',pending:'发送结果待确认',accepted:'接收端已接受（不代表人已收到）',retrying:'通知失败或未确认，等待重试'}
function date(v:any){return typeof v==='number'?new Date(v*1000).toLocaleString():'未记录'}
function status(r:any){if(data.value?.state!=='ok')return '历史状态，不代表当前健康';if(r.observed==='disabled')return '未启用此项证据告警（保留历史）';if(r.observed==='unknown')return r.active?'故障尚未确认恢复；当前观测未知':'当前观测未知';if(r.pending_confirmation)return r.active?'等待连续健康确认':'等待连续异常确认';return r.active?'故障中':'最近观测正常'}
async function load(){if(busy.value)return;busy.value=true;error.value='';try{const d=await api('/alerts');if(alive)data.value=d}catch(e:any){if(alive){data.value=null;error.value=e.message||'告警状态读取失败'}}finally{if(alive)busy.value=false}}
onMounted(()=>{void load();timer=setInterval(()=>{if(!document.hidden)void load()},30000)})
onUnmounted(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template><section class="panel alert-health" aria-labelledby="alert-health-title">
 <div class="section-heading"><h2 id="alert-health-title">主动健康告警</h2><button :disabled="busy" @click="load">{{busy?'正在读取告警…':'刷新告警'}}</button></div>
 <p class="field-hint">独立观察器每30秒检查；连续异常／恢复确认后记录一次。同一故障不重复刷屏，未知数据不判定为恢复。这里只读，不会重启服务。规则可在“功能与版本”中开关；未启用不代表任务正常。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="data">
  <p v-if="data.state==='unavailable'" class="warning">告警观察器未启用或报告不可读，不能据此判断服务正常。需要维护者检查独立定时器。</p>
  <template v-else>
   <p :class="data.state==='stale'?'warning':'field-hint'">采集时间 {{date(data.updated_at)}}<span v-if="data.state==='stale'"> · 告警报告已过期，下面仅为历史状态</span></p>
   <div class="alert-rules"><article v-for="r in data.rules" :key="r.key" :class="{warning:(r.active&&r.observed!=='disabled')||r.observed==='unknown'||data.state==='stale'}"><strong>{{r.label}}</strong><p>{{status(r)}}</p><small v-if="r.changed_at">最近变化 {{date(r.changed_at)}}</small></article></div>
   <p v-if="data.observer_policy" class="field-hint">网页告警策略 · {{data.observer_policy.source==='live'?'已同步':data.observer_policy.source==='cached'?'暂用上次同步配置，未因GM故障自动关闭':'安装默认配置'}}<span v-if="data.observer_policy.revision"> · 版本 {{data.observer_policy.revision}}</span>。在“功能与版本”调整核心资源、备份及运营任务三个告警开关，约30秒生效；不停止独立观察器。</p>
   <h3>通知渠道状态</h3><p>{{deliveryNames[data.notification.state]||'未知'}} · 待通知 {{data.pending_count}} 项</p>
   <p class="field-hint">最后尝试 {{date(data.notification.last_attempt)}} · 最后接受 {{date(data.notification.last_accepted)}}<span v-if="data.notification.state==='retrying'"> · 下次尝试 {{date(data.notification.next_attempt)}}</span></p>
   <p class="field-hint">通知失败时保留并合并最新状态；响应丢失可能重复通知，接收端可按事件编号去重。渠道地址和密钥不在网页展示。</p>
   <details><summary>最近变化记录（最多100条）</summary><p v-if="!data.history.length" class="empty">尚无已确认的故障或恢复变化，不代表从未发生故障。</p><ol class="alert-history"><li v-for="e in data.history" :key="e.id"><b>{{e.label}} · {{e.state==='firing'?'确认异常':'确认恢复'}}</b><span>{{date(e.occurred_at)}}</span><code>{{e.id}}</code></li></ol></details>
  </template>
 </template>
</section></template>
<style scoped>
.section-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.alert-rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px}.alert-rules article{border:1px solid var(--border-color);border-radius:10px;padding:12px;min-width:0}.alert-rules p{margin:8px 0}.alert-history{padding-left:20px}.alert-history li{margin:12px 0}.alert-history span,.alert-history code{display:block;overflow-wrap:anywhere}.alert-health p{overflow-wrap:anywhere}
</style>
