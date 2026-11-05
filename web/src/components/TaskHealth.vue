<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {api} from '../api'
const emit=defineEmits<{inspect:[kind:string,id:string]}>()
const data=ref<any>(null),busy=ref(false),error=ref('')
let alive=true,timer:ReturnType<typeof setInterval>|undefined
const states:Record<string,string>={disabled:'未启用',stopped:'未运行',stalled:'长时间无响应',failing:'最近执行失败',observing:'等待观察',responding:'最近执行有响应'}
const reasons:Record<string,string>={uncertain:'提交结果待核对（取消任务也不能忽略）',executing:'单目标执行超过120秒或缺少时间记录',failed:'未提交目标需要处理',schedule_error:'计划处于异常或带错误暂停',overdue:'计划到期超过120秒未触发',unreconciled:'期次超过120秒未核对结果',no_progress:'连续观察120秒，队首未执行目标没有推进',worker_disabled:'仍有待处理任务，但执行器未启用',worker_stopped:'仍有待处理任务，但执行器未运行',worker_failing:'执行器最近一次处理失败',worker_stalled:'执行器长时间无响应'}
async function load(){if(busy.value)return;busy.value=true;error.value='';try{const d=await api('/task-health');if(alive)data.value=d}catch(e:any){if(alive){data.value=null;error.value=e.message||'任务状态读取失败'}}finally{if(alive)busy.value=false}}
onMounted(()=>{void load();timer=setInterval(()=>{if(!document.hidden)void load()},30000)})
onUnmounted(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template><section class="panel task-health" aria-labelledby="task-health-title">
 <div class="task-heading"><h2 id="task-health-title">任务异常中心</h2><button :disabled="busy" @click="load">{{busy?'正在核对任务…':'刷新任务状态'}}</button></div>
 <p class="field-hint">只读检查批量奖励和定时运营，不自动重发奖励。点击原任务查看详情后，再决定如何处理。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="data">
  <p v-if="data.state==='unknown'" class="warning">状态未知：查询失败、繁忙或证据不完整，不能判断任务正常。</p>
  <p v-else-if="data.state==='attention'" class="warning">有任务需要处理。结果待核对不等于未发放，请勿重复创建奖励。</p>
  <p v-else-if="data.state==='observing'" class="notice">正在观察执行进展，暂未发现下列异常；不能据此认定任务已经完成。</p>
  <p v-else class="notice">本次检查未发现待处理异常，不代表奖励在游戏内已生效。</p>
  <p class="field-hint">最后核对 {{new Date(data.checked_at*1000).toLocaleString('zh-CN',{hour12:false})}}。页面隐藏时暂停轮询；启用独立任务观察后仍会持续检查。所有观察来源合计超过90秒中断时重新计时。</p>
  <p v-if="data.truncated" class="warning">至少一类候选记录超过50条，列表不完整。请到原任务列表继续排查。</p>
  <div v-if="data.workers" class="toolbar"><span v-for="(worker,key) in data.workers" :key="key" class="pill">{{key==='rewards'?'奖励执行器':'计划执行器'}}：{{states[worker.state]||'未知'}}<template v-if="worker.failures"> · 连续失败 {{worker.failures}} 次</template></span></div>
  <ul v-if="data.issues?.length" class="task-issues"><li v-for="(item,i) in data.issues" :key="i">
   <div><strong>{{reasons[item.code]||'需要核对'}}</strong><p>{{item.kind==='reward'?'奖励任务':'定时计划'}} <code>{{item.id}}</code><span v-if="item.ordinal"> · 目标序号 {{item.ordinal}}</span></p></div>
   <button @click="emit('inspect',item.kind,item.id)">查看原{{item.kind==='reward'?'任务':'计划'}}</button>
  </li></ul>
 </template>
</section></template>
<style scoped>
.task-heading{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.task-health p{margin:10px 0;overflow-wrap:anywhere}.task-issues{list-style:none;padding:0;max-height:540px;overflow:auto}.task-issues li{display:flex;gap:12px;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border-color);padding:12px 0}.task-issues li>div{min-width:0}.task-issues code{overflow-wrap:anywhere}.task-issues button{flex-shrink:0}@media(max-width:600px){.task-issues li{align-items:flex-start;flex-direction:column}}
</style>
