<script setup lang="ts">
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import {api,uncertainMessage} from '../api'
const props=defineProps<{uid:number}>()
const data=ref<any>(null),busy=ref(false),error=ref(''),now=ref(Date.now())
let epoch=0,timer:ReturnType<typeof setInterval>|undefined
const observed=computed(()=>Number(data.value?.native?.observed_at??0)*1000)
const stale=computed(()=>!!observed.value&&(now.value-observed.value>15000||now.value<observed.value-5000))
const state=computed(()=>stale.value?'unknown':data.value?.native?.state??'unknown')
const label=computed(()=>({online:'原生会话在线',offline:'原生会话离线',unknown:'实时状态未知'}[state.value as string]??'实时状态未知'))
const databaseLabel=computed(()=>data.value?.database?.record?.login_status===1?'登录表记录为在线':data.value?.database?.record?.login_status===0?'登录表记录为离线':'无确定的登录表状态')
function clearTimer(){if(timer!==undefined){clearInterval(timer);timer=undefined}}
async function refresh(){
 if(busy.value)return
 const current=++epoch,uid=props.uid
 busy.value=true;error.value='';data.value=null;clearTimer()
 try{
  const result=await api('/online/'+uid+'/live')
  if(current!==epoch)return
  if(result.uid!==uid||result.native?.uid!==uid)throw new Error('查询结果与当前账号不匹配，请重新查询')
  data.value=result;now.value=Date.now()
  // Only age the displayed observation. No background network polling.
  if(result.native.observed_at)timer=setInterval(()=>{now.value=Date.now();if(stale.value)clearTimer()},1000)
 }catch(e){if(current===epoch)error.value=uncertainMessage(e)}
 finally{if(current===epoch)busy.value=false}
}
function reset(){epoch++;clearTimer();data.value=null;error.value='';busy.value=false}
watch(()=>props.uid,reset)
onBeforeUnmount(reset)
function clock(v:number){return new Date(v*1000).toLocaleString('zh-CN',{hour12:false})}
</script>
<template>
 <section class="live-session" aria-label="原生在线会话核对">
  <div class="section-title"><div><h3>实时会话核对</h3><p class="field-hint">UID {{uid}} · 只读查询游戏 monitor，不修改账号状态</p></div><button type="button" :disabled="busy" @click="refresh">{{busy?'正在查询…':'查询实时状态'}}</button></div>
  <p v-if="error" class="submit-error" role="alert">{{error}} · 实时状态未知，可手动重新查询。</p>
  <div v-if="data" role="status">
   <p><span class="status-badge" :class="state==='online'?'success':'neutral'">{{label}}</span> <span>{{databaseLabel}}</span></p>
   <p v-if="data.database?.record?.channel" class="field-hint">登录表记录频道：{{data.database.record.channel}}（不是原生查询返回的实时角色或频道）</p>
   <p v-if="stale" class="warning">上次响应已超过 15 秒或时钟发生变化，不能继续视为当前状态，请手动刷新。</p>
   <p v-else>{{data.native.reason}}</p>
   <p v-if="observed" class="field-hint">原生响应时间：{{clock(data.native.observed_at)}}</p>
  </div>
  <p v-else-if="busy" role="status" class="field-hint">正在向原生服务查询，尚未收到有效响应…</p>
  <p v-else-if="!error" class="field-hint">尚未查询。此处与数据库登录记录分开展示，超时不会被判断为离线。</p>
  <p class="field-hint">会话查询不证明客户端响应、当前角色或存档已落盘；不作为装备编辑的离线凭证。</p>
 </section>
</template>
