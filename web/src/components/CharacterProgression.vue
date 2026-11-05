<script setup lang="ts">
import {ref,onMounted,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
const props=defineProps<{characNo:number}>(),emit=defineEmits(['expired'])
const data=ref<any>(null),busy=ref(false),error=ref('')
let alive=true
const catalogLabels:Record<string,string>={matched:'匹配配置PVF的参考阈值',mismatch:'PVF不匹配，不推断经验区间',unsupported_program:'程序版本未适配，不推断经验区间',not_installed:'未安装经验参考表',unavailable:'经验参考表不可用'}
const fields=[{key:'selection',title:'选角信息经验',source:'charac_info.exp'},{key:'saved',title:'角色存档经验',source:'charac_stat.exp'}]
const number=(v:any)=>v===null||v===undefined?'未知':Number(v).toLocaleString('zh-CN')
async function load(){
 if(busy.value)return
 busy.value=true;error.value='';data.value=null
 try{const result=await api(`/characters/${props.characNo}/progression`);if(alive)data.value=result}
 catch(e){if(alive){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}}
 finally{if(alive)busy.value=false}
}
onMounted(load);onBeforeUnmount(()=>{alive=false})
</script>
<template><section class="progression-panel">
 <header><div><h3>等级与经验存档</h3><p class="field-hint">只读核对 · 不修改玩家进度</p></div><button :disabled="busy" @click="load">刷新经验存档</button></header>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <p v-if="busy" role="status">正在读取等级与经验…</p>
 <template v-if="data">
  <p class="notice">{{data.note}}</p>
  <div class="progression-summary"><strong>Lv. {{data.level}}</strong><span>{{data.target.character.charac_name}} · #{{data.target.character.charac_no}}</span><span class="pill">{{catalogLabels[data.catalog.state]||'参考状态未知'}}</span></div>
  <p v-if="!data.stat_present" class="submit-error" role="alert">角色经验存档缺失，不能视为经验为0。</p>
  <p v-else-if="data.same_value===false" class="notice">两处经验记录不同。在线时可能尚未同步保存；这里只提示差异，不认定角色损坏。</p>
  <p v-if="!data.catalog.runtime_fresh" class="notice">运行状态采集已过期或不可用，未确认当前运行中的PVF版本。</p>
  <div class="experience-cards"><article v-for="field in fields" :key="field.key">
   <h4>{{field.title}}</h4><small>{{field.source}}</small><strong class="experience-value">{{number(data[field.key].unsigned)}}</strong>
   <dl><dt>数据库原值（有符号）</dt><dd>{{number(data[field.key].raw)}}</dd><dt>32位原始表示</dt><dd>{{data[field.key].hex||'未知'}}</dd></dl>
   <p v-if="data[field.key].raw<0" class="field-hint">按同一32位数据的无符号表示显示，不把负的数据库原值当成经验不足。</p>
   <template v-if="data[field.key].reference.state!=='unknown'">
    <p v-if="data[field.key].reference.state==='outside_reference'" class="notice">超出PVF参考区间；请结合插件、存档时点排查，不自动修正。</p>
    <template v-else><progress :value="Math.min(100,Math.max(0,data[field.key].reference.progress_percent))" max="100" :aria-label="field.title+'参考进度'"/><p>参考进度 {{data[field.key].reference.progress_percent}}% · 距上界 {{number(data[field.key].reference.remaining)}}</p></template>
   </template><p v-else class="field-hint">没有可用的完整参考区间，进度未知。</p>
  </article></div>
  <p v-if="data.range.state==='available'">本级参考起点 {{number(data.range.lower)}} → 下级参考阈值 {{number(data.range.upper)}}（非运行时升级保证）</p>
  <p class="field-hint">{{data.catalog.note}} 数据采集于 {{new Date(data.collected_at*1000).toLocaleString('zh-CN',{hour12:false})}}。</p>
  <details><summary>存档维护与在线升级有什么区别？</summary><p>当前镜像的原生升级还会处理技能点、职业成长属性、活动奖励等。下方等级维护会同步已适配的存档字段，但不会模拟在线升级事件、活动奖励或任务完成。职业修改与技能重置仍是独立功能。</p></details>
 </template>
</section></template>
<style scoped>
.progression-panel{display:grid;gap:14px}header,.progression-summary{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}h3,h4{margin:0}.progression-summary>strong{font-size:26px;color:var(--primary-color)}.experience-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}article{border:1px solid var(--border-color);border-radius:14px;background:var(--bg-secondary);padding:18px;overflow-wrap:anywhere}.experience-value{display:block;font-size:28px;margin:14px 0}dl{display:grid;grid-template-columns:1fr 1fr;gap:8px}dd{margin:0;text-align:right}progress{width:100%;accent-color:var(--primary-color)}summary{cursor:pointer}@media(max-width:640px){.experience-cards{grid-template-columns:1fr}dl{grid-template-columns:1fr}dd{text-align:left}}
</style>
