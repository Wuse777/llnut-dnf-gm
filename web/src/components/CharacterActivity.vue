<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {inventoryNames,nativeNames,supportNames} from '../nativeStatus'
const props=defineProps<{characNo:number,busy?:boolean}>()
const emit=defineEmits<{inspect:[id:string],expired:[]}>()
const data=ref<any>(null),loading=ref(false),error=ref(''),before=ref(0),back=ref<number[]>([]),includeAccount=ref(true)
const names:Record<string,string>={...inventoryNames,...nativeNames,...supportNames,currency:'账号余额调整',mail:'奖励邮件',reward:'组合奖励',ban:'封禁',unban:'解封','equipment-unlock':'装备提前解锁'}
let epoch=0
function parsed(v:unknown){try{return typeof v==='string'?JSON.parse(v):{}}catch{return {}}}
function operation(r:any){const id=parsed(r.result_json)?.operation_id||r.operation_id;return typeof id==='string'&&/^[a-f0-9]{32}$/.test(id)?id:''}
async function load(){const n=++epoch;loading.value=true;error.value='';data.value=null;try{const r=await api(`/characters/${props.characNo}/activity?before=${before.value}&include_account=${includeAccount.value}`);if(n===epoch)data.value=r}catch(e){if(n===epoch){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}}finally{if(n===epoch)loading.value=false}}
function reset(){before.value=0;back.value=[];void load()}
function next(){back.value.push(before.value);before.value=data.value.next_before;void load()}
function previous(){before.value=back.value.pop()??0;void load()}
watch(()=>props.characNo,reset,{immediate:true});onBeforeUnmount(()=>epoch++)
</script>
<template><section class="character-activity">
 <div class="section-title"><h3>角色与账号管理记录</h3><button :disabled="loading" @click="reset">刷新记录</button></div>
 <label><input v-model="includeAccount" type="checkbox" :disabled="loading" @change="reset">同时显示未绑定具体角色的账号记录</label>
 <p v-if="error" class="submit-error" role="alert">{{error}} <button @click="load">重试查询</button></p>
 <p v-if="loading" role="status">正在读取记录…</p>
 <template v-if="data"><p class="field-hint">{{data.note}}</p>
 <article v-for="r in data.items" :key="r.id"><div class="section-title"><b>{{names[r.action]||r.action}}</b><span class="pill">{{r.scope==='character'?'关联本角色':'账号记录 · 未绑定角色'}}</span></div><p>{{r.reason}}</p><small>{{r.created_at}} UTC · {{r.actor}}</small><p class="mono">{{r.operation_id}}</p><details><summary>查看请求与结果</summary><pre>{{JSON.stringify({request:parsed(r.request_json),result:parsed(r.result_json)},null,2)}}</pre></details><button v-if="operation(r)" :disabled="busy" @click="emit('inspect',operation(r))">查看原操作结果</button></article>
 <p v-if="!data.items.length" class="empty">本页没有匹配记录。{{data.next_before?'还有更早的账号记录，可以继续下一页。':'已到记录末尾。'}}</p>
 <div class="pagination"><button :disabled="loading||!back.length" @click="previous">上一页记录</button><span>第 {{back.length+1}} 页</span><button :disabled="loading||!data.next_before" @click="next">下一页记录</button></div>
 </template>
</section></template>
<style scoped>
.character-activity article{padding:16px 0;border-bottom:1px solid var(--border-color)}.character-activity label{display:flex;align-items:center;gap:8px}.character-activity label input{width:auto}.mono{overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style>
