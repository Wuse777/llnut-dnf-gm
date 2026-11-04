<script setup lang="ts">
import {supportNames,inventoryNames,nativeNames} from '../nativeStatus'
import {ref,watch,onBeforeUnmount} from 'vue'
import {api,uncertainMessage} from '../api'
import MailCenter from './MailCenter.vue'
const props=defineProps<{account:any,busy?:boolean}>()
const emit=defineEmits<{action:[value:{action:string,uid:number,charac_no?:number}],draft:[value:any],inspect:[id:string],correction:[value:any]}>()
const tab=ref('roles'),rows=ref<any[]>([]),page=ref(1),loading=ref(false),error=ref('')
const names:Record<string,string>={...nativeNames,...inventoryNames,...supportNames,currency:'余额变更',mail:'奖励邮件',ban:'封禁',unban:'解封','equipment-unlock':'装备提前解锁'}
let epoch=0
function parse(v:string){try{return JSON.parse(v)}catch{return {}}}
async function load(){
 const current=++epoch;error.value='';rows.value=[]
 if(tab.value==='mail')return
 loading.value=true
 try{const data=await api((tab.value==='roles'?'/characters?uid=':'/audit?uid=')+props.account.uid+'&page='+page.value);if(current===epoch)rows.value=data.items}
 catch(e){if(current===epoch)error.value=uncertainMessage(e)}finally{if(current===epoch)loading.value=false}
}
function act(action:string,charac_no?:number){emit('action',{action,uid:props.account.uid,charac_no})}
function switchTab(next:string){tab.value=next;page.value=1;void load()}
watch(()=>props.account.uid,()=>{page.value=1;void load()},{immediate:true})
onBeforeUnmount(()=>epoch++)
</script>
<template><section class="account-characters player-center"><div class="section-title"><div><h2>角色与管理历史</h2><p class="muted">UID {{account.uid}} · 所有操作保留当前玩家上下文</p></div><div class="button-row"><button :disabled="busy" @click="act('currency')">调整账号余额</button><button :disabled="busy" @click="act('ban')">封禁此账号</button><button :disabled="busy" @click="act('unban')">解除此账号封禁</button></div></div>
 <div class="button-row" role="group" aria-label="玩家中心视图"><button :disabled="busy" @click="act('support')">备注与问题记录</button><button :aria-pressed="tab==='roles'" @click="switchTab('roles')">旗下角色</button><button :aria-pressed="tab==='mail'" @click="switchTab('mail')">该玩家邮件</button><button :aria-pressed="tab==='history'" @click="switchTab('history')">该玩家操作历史</button></div>
 <MailCenter v-if="tab==='mail'" :uid="account.uid" @draft="emit('draft',$event)" />
 <template v-else><p v-if="error" class="submit-error" role="alert">{{error}} <button @click="load">重试查询</button></p><p v-if="loading" role="status">正在读取玩家资料…</p>
 <div v-if="tab==='roles'&&rows.length" class="table-wrap"><table><thead><tr><th>角色</th><th>等级</th><th>状态</th><th>快捷操作</th></tr></thead><tbody><tr v-for="r in rows" :key="r.charac_no"><td><b>{{r.charac_name}}</b><small class="cell-note">#{{r.charac_no}}</small></td><td>{{r.lev}}</td><td>{{r.delete_flag?'已删除':'正常'}}</td><td><div class="button-row"><button :disabled="busy" @click="act('detail',r.charac_no)">查看详情</button><button :disabled="busy||!!r.delete_flag" @click="act('mail',r.charac_no)">给此角色发奖励</button><button :disabled="busy||!!r.delete_flag" @click="act('unlock',r.charac_no)">此角色解锁申请</button></div></td></tr></tbody></table></div>
 <div v-else-if="tab==='history'" class="audit-list"><p><a :href="'/dnf-gm/api/v1/audit/export?uid='+account.uid" download>导出该玩家全部操作记录（NDJSON）</a></p><article v-for="r in rows" :key="r.id"><div class="section-title"><b>{{names[r.action]||r.action}}</b><time>{{r.created_at}} UTC</time></div><p>{{r.reason}}</p><p v-if="r.action==='currency'">余额 {{parse(r.result_json).before}} → {{parse(r.result_json).after}}</p><code>{{r.operation_id}}</code><details><summary>请求与结果</summary><pre>{{JSON.stringify({request:parse(r.request_json),result:parse(r.result_json)},null,2)}}</pre></details><button v-if="/^[a-f0-9]{32}$/.test(parse(r.result_json).operation_id||r.operation_id)" :disabled="busy" @click="emit('inspect',parse(r.result_json).operation_id||r.operation_id)">查看原操作结果</button><button v-if="['currency','mail','ban','unban'].includes(r.action)" :disabled="busy" @click="emit('correction',{operation_id:r.operation_id,request:parse(r.request_json)})">建立纠正草稿</button></article></div>
 <p v-if="!loading&&!error&&!rows.length" class="empty">{{tab==='roles'?'该账号没有角色记录。':'该玩家没有符合条件的管理记录。'}}</p><div class="pagination"><button :disabled="loading||page<=1" @click="page--;load()">上一页玩家记录</button><span>第 {{page}} 页</span><button :disabled="loading||rows.length<50" @click="page++;load()">下一页玩家记录</button></div></template>
 </section></template>
