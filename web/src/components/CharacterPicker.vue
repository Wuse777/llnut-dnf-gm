<script setup lang="ts">
import {computed,onMounted,onBeforeUnmount,ref} from 'vue'
import {api,uncertainMessage} from '../api'
const props=defineProps<{modelValue:string}>()
const emit=defineEmits<{'update:modelValue':[value:string]}>()
type Character={charac_no:number,uid:number,charac_name:string,lev:number,delete_flag:number}
const query=ref(''),uid=ref(''),page=ref(1),rows=ref<Character[]>([]),loading=ref(false),error=ref(''),loaded=ref(false)
const applied=ref({q:'',uid:0}),names=ref<Record<number,Character>>({})
let sequence=0
const tokens=computed(()=>props.modelValue.trim().split(/[\s,，;；]+/).filter(Boolean))
const valid=computed(()=>tokens.value.length<=5000&&tokens.value.every(t=>/^\d+$/.test(t)&&Number.isSafeInteger(Number(t))&&Number(t)>0&&Number(t)<=2147483647))
const chosen=computed(()=>valid.value?[...new Set(tokens.value.map(Number))]:[])
const current=computed(()=>rows.value.filter(r=>!r.delete_flag))
const allChecked=computed(()=>current.value.length>0&&current.value.every(r=>chosen.value.includes(r.charac_no)))
function update(values:number[]){if(!valid.value)return;const result=[...new Set(values)];if(result.length>5000){error.value='每次最多选择5000个角色，请分批创建任务。';return}error.value='';emit('update:modelValue',result.join(', '));names.value=Object.fromEntries([...Object.values(names.value),...rows.value].filter(r=>result.includes(r.charac_no)).map(r=>[r.charac_no,r]))}
function toggle(row:Character){if(row.delete_flag||!valid.value)return;update(chosen.value.includes(row.charac_no)?chosen.value.filter(id=>id!==row.charac_no):[...chosen.value,row.charac_no])}
function togglePage(){update(allChecked.value?chosen.value.filter(id=>!current.value.some(r=>r.charac_no===id)):[...chosen.value,...current.value.map(r=>r.charac_no)])}
async function load(target:number,search=false){
 if(search){const value=uid.value.trim();if(value&&(!/^\d+$/.test(value)||Number(value)<1||Number(value)>2147483647)){error.value='账号UID请输入有效正整数，或留空查询全部账号。';return}applied.value={q:query.value.trim(),uid:value?Number(value):0}}
 const request=++sequence;loading.value=true;error.value='';rows.value=[];loaded.value=false
 try{const result=await api('/characters?'+new URLSearchParams({uid:String(applied.value.uid),q:applied.value.q,page:String(target)}));if(request!==sequence)return;rows.value=result.items;page.value=target;loaded.value=true;names.value=Object.fromEntries([...Object.values(names.value),...rows.value].filter(r=>chosen.value.includes(r.charac_no)).map(r=>[r.charac_no,r]))}
 catch(e){if(request===sequence)error.value=uncertainMessage(e)}finally{if(request===sequence)loading.value=false}
}
onMounted(()=>load(1));onBeforeUnmount(()=>{sequence++})
</script>
<template>
 <section class="character-picker" aria-label="勾选奖励收件角色">
  <div class="toolbar"><label>角色名称／编号<input v-model="query" maxlength="80" aria-label="查找收件角色" placeholder="名称或完整角色编号" @keydown.enter.prevent="load(1,true)"></label><label>账号 UID<input v-model="uid" inputmode="numeric" aria-label="收件角色账号UID" placeholder="留空查询全部账号" @keydown.enter.prevent="load(1,true)"></label><button type="button" :disabled="loading" @click="load(1,true)">查询角色</button></div>
  <p class="field-hint">可跨页勾选，搜索和翻页不会清空已选角色；这里只修改草稿，不会发放奖励。账号归属以预览时核对结果为准。</p>
  <p v-if="!valid" class="submit-error" role="alert">下方编号名单包含无效编号或超过5000条，请先修正；不会自动丢弃已填写内容。</p>
  <p v-if="error" class="submit-error" role="alert">{{error}}</p>
  <div class="selection-summary"><strong>已选择 {{chosen.length}} 个角色</strong><button type="button" :disabled="!valid||!chosen.length" @click="update([])">清空选择</button></div>
  <div v-if="chosen.length" class="selection-chips" aria-label="已选收件角色"><button v-for="id in chosen.slice(0,50)" :key="id" type="button" :aria-label="'移除收件角色 '+id" @click="update(chosen.filter(n=>n!==id))">{{names[id]?.charac_name||'角色'}} #{{id}} <span v-if="names[id]"> · UID {{names[id].uid}}</span> ×</button><span v-if="chosen.length>50" class="field-hint">另有 {{chosen.length-50}} 个，完整名单见下方编号框。</span></div>
  <p v-if="loading" role="status">正在查询角色…</p>
  <div v-else-if="loaded" class="table-wrap"><table><thead><tr><th><input type="checkbox" aria-label="勾选本页可用角色" :checked="allChecked" :disabled="!valid||!current.length" @change="togglePage"></th><th>角色</th><th>账号 UID</th><th>等级／状态</th></tr></thead><tbody><tr v-for="row in rows" :key="row.charac_no"><td><input type="checkbox" :aria-label="'选择角色 '+row.charac_name+' #'+row.charac_no" :checked="chosen.includes(row.charac_no)" :disabled="!valid||!!row.delete_flag" @change="toggle(row)"></td><td>{{row.charac_name}} <small>#{{row.charac_no}}</small></td><td>UID {{row.uid}}</td><td>Lv.{{row.lev}} · {{row.delete_flag?'已删除，不可选':'可选择'}}</td></tr><tr v-if="!rows.length"><td colspan="4">没有找到角色，请调整查询条件。</td></tr></tbody></table></div>
  <div class="pagination"><button type="button" :disabled="loading||page<=1" @click="load(page-1)">上一页角色</button><span>第 {{page}} 页 · 每页最多50条</span><button type="button" :disabled="loading||!loaded||rows.length<50" @click="load(page+1)">下一页角色</button></div>
 </section>
</template>
<style scoped>
.character-picker{display:grid;gap:12px;border:1px solid var(--border-color);border-radius:12px;padding:16px;min-width:0}.toolbar{display:flex;gap:12px;align-items:end;flex-wrap:wrap}.toolbar label{display:grid;gap:6px;flex:1 1 180px}.selection-summary{display:flex;align-items:center;gap:12px;justify-content:space-between}.selection-chips{display:flex;gap:8px;flex-wrap:wrap;max-height:180px;overflow:auto}.selection-chips button{font-size:12px;overflow-wrap:anywhere;max-width:100%}input[type=checkbox]{width:18px;height:18px;accent-color:var(--accent-color,#ba8959)}td small{display:block;opacity:.7}.table-wrap{max-height:360px;overflow:auto}p{margin:0}.pagination{flex-wrap:wrap}@media(max-width:600px){.character-picker{padding:10px}.selection-summary{flex-wrap:wrap}td{white-space:normal}}
</style>
