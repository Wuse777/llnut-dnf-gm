<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
const props=defineProps<{characNo:number}>(),emit=defineEmits(['expired'])
const data=ref<any>(null),busy=ref(false),error=ref(''),query=ref(''),queryError=ref(''),filter=ref(''),onlyIssues=ref(false)
let alive=true,generation=0
const labels:Record<string,string>={empty_with_progress:'空槽仍保存进度值',id_out_of_range:'超出原生任务编号范围',duplicate_active:'多个槽位保存同一任务',missing_definition:'匹配PVF中没有此任务',active_with_clear_flag:'进行中同时有完成标记（可能是重复任务）'}
const catalogLabels:Record<string,string>={matched:'匹配当前配置PVF',mismatch:'PVF版本不匹配，隐藏名称以免误认',not_installed:'未安装任务索引',unavailable:'任务索引不可用',not_checked:'未检查'}
const active=computed(()=>(data.value?.active??[]).filter((x:any)=>
 (x.id||x.trigger_raw)&&(!onlyIssues.value||x.issues.length)&&(!filter.value.trim()||String(x.id).includes(filter.value.trim())||(x.definition?.name??'').includes(filter.value.trim()))))
function clearText(v:any){return v===null||v===undefined?'未知':v?'有完成标记':'无完成标记（不代表当前可接）'}
async function load(page=1){
 if(busy.value)return
 queryError.value='';const id=query.value.trim()
 if(id&&(!/^\d+$/.test(id)||Number(id)<1||Number(id)>65535)){queryError.value='任务编号须为1至65535整数';return}
 const n=++generation;busy.value=true;error.value=''
 try{const r=await api(`/characters/${props.characNo}/quests?page=${page}&quest_id=${id||0}`);if(alive&&n===generation)data.value=r}
 catch(e){if(alive){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}}
 finally{if(alive&&n===generation)busy.value=false}
}
onMounted(()=>load());onBeforeUnmount(()=>{alive=false;generation++})
</script>
<template><section class="quest-panel">
 <header class="quest-heading"><div><h3>任务存档排查</h3><p class="field-hint">只读查询，不完成、不放弃、不重置任务。</p></div><button :disabled="busy" @click="load(data?.page||1)">刷新任务存档</button></header>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <form @submit.prevent="load(1)" class="quest-query" novalidate>
  <label>按任务编号核对<input v-model="query" inputmode="numeric" placeholder="例如：38" :aria-invalid="!!queryError" aria-describedby="quest-query-error" :disabled="busy" @input="queryError=''"/></label><button class="primary" :disabled="busy">查询任务</button>
  <p v-if="queryError" id="quest-query-error" class="submit-error" role="alert">{{queryError}}</p>
 </form>
 <template v-if="data">
  <p class="notice">{{data.note}}</p>
  <p class="field-hint">{{data.target.accountname}} · {{data.target.character.charac_name}} #{{data.target.character.charac_no}} · 采集于 {{new Date(data.collected_at*1000).toLocaleString()}}</p>
  <p :class="data.catalog.state==='matched'?'field-hint':'warning'">任务名称索引：{{catalogLabels[data.catalog.state]||data.catalog.state}}<span v-if="data.catalog.state==='matched'&&!data.catalog.runtime_fresh">；实时PVF快照过期，版本匹配仅依据配置</span></p>
  <p v-if="data.state==='missing'" class="warning">{{data.message}}</p>
  <p v-for="issue in data.issues" :key="issue.code" class="warning">{{issue.message}}</p>
  <article v-if="data.lookup" class="quest-card lookup-card">
   <h4>查询结果 · #{{data.lookup.id}} {{data.lookup.definition?.name||'无可用名称'}}</h4>
   <p>{{clearText(data.lookup.clear_flag)}} · 进行中槽位：{{data.lookup.active_slots.join('、')||'未占用'}}</p>
   <p v-if="!data.lookup.within_native_range" class="warning">超出当前原生完成标记编号范围</p>
   <template v-if="data.lookup.definition"><p>分类 {{data.lookup.definition.grade}} · 等级 {{data.lookup.definition.min_level??'未知'}}–{{data.lookup.definition.max_level??'未知'}}</p><p>前置条件原值：{{JSON.stringify(data.lookup.definition.prerequisites)}}</p><p class="quest-condition">{{data.lookup.definition.condition||'无条件文本'}}</p></template>
  </article>
  <template v-if="data.state==='read'">
   <div class="quest-heading"><h4>进行中存档 · 20个槽位</h4><label class="inline"><input v-model="onlyIssues" type="checkbox"/>仅显示疑点</label></div>
   <label>筛选进行中任务<input v-model="filter" placeholder="名称或编号"/></label>
   <p v-if="!active.length" class="empty">没有符合条件的任务槽记录。</p>
   <div class="quest-cards"><article v-for="x in active" :key="x.slot" class="quest-card">
    <div class="quest-heading"><strong>{{x.definition?.name|| (x.id?'无可用任务名称':'空槽')}}</strong><span class="pill">槽 {{x.slot}} · #{{x.id}}</span></div>
    <p>进度原值 {{x.trigger_raw}} · {{clearText(x.clear_flag)}}</p><p class="field-hint">进度字段可能编码多个条件，不能当成百分比。</p>
    <p v-for="code in x.issues" :key="code" class="warning">{{labels[code]||code}}</p>
    <details v-if="x.definition"><summary>查看PVF任务条件</summary><p>{{x.definition.grade}} · 等级 {{x.definition.min_level??'未知'}}–{{x.definition.max_level??'未知'}}</p><p>前置条件原值：{{JSON.stringify(x.definition.prerequisites)}}</p><p class="quest-condition">{{x.definition.condition}}</p></details>
   </article></div>
   <p>紧急任务原编号：{{data.urgent.id}} {{data.urgent.definition?.name||''}}</p>
   <h4>数据库完成标记 · {{data.completed_count??'未知'}} 项</h4>
   <p v-if="data.completed_count===0" class="empty">没有非零完成标记。</p>
   <div class="quest-cards"><article v-for="x in data.completed" :key="x.id" class="quest-card"><strong>#{{x.id}} {{x.definition?.name||'无可用任务名称'}}</strong><span class="pill">标记 {{x.clear_flag}}</span></article></div>
   <div class="button-row"><button :disabled="busy||data.page<=1" @click="load(data.page-1)">上一页</button><span>第 {{data.page}} 页 · 每页50项</span><button :disabled="busy||!data.has_more" @click="load(data.page+1)">下一页</button></div>
  </template>
 </template>
 <p v-if="busy" role="status">正在读取任务存档…</p>
</section></template>
<style scoped>
.quest-panel{display:grid;gap:14px}.quest-heading,.button-row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.quest-heading h3,.quest-heading h4{margin:0}.quest-query{display:flex;align-items:end;flex-wrap:wrap;gap:12px}.quest-query label{flex:1;min-width:160px}.quest-query p{flex-basis:100%}label{display:grid;gap:6px}label.inline{display:flex;align-items:center;gap:8px}.inline input{width:auto}.quest-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:12px}.quest-card{background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:12px;padding:14px;overflow-wrap:anywhere}.quest-card>.pill{margin-left:8px}.quest-condition{white-space:pre-wrap}.lookup-card{border-left:3px solid var(--primary-color)}.button-row{justify-content:flex-start}details>summary{cursor:pointer}
</style>
