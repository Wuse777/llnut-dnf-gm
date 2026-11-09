<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {useGmConfirmation} from '../stores/gm/confirmation'
const props=defineProps<{initialRun?:string}>()
const emit=defineEmits<{reauth:[],expired:[],navigate:[page:string]}>()
const lease=useGmConfirmation(),data=ref<any>(null),selected=ref<any>(null),page=ref(1),busy=ref(false),error=ref(''),notice=ref('')
const windowId=ref(''),reason=ref(''),ack=ref(false),query=ref(''),pending=ref(''),uncertain=ref(false),followupReason=ref('')
const storage='dnfgm.game-backup-request'
const states:Record<string,string>={preview:'待确认预览',queued:'已排队',running:'执行中',succeeded:'成功，已有执行收据',failed:'失败，请核对原因',needs_review:'中断或结果待核对'}
const actions:Record<string,string>={backup:'一致性备份',copy:'加密异地副本',rehearse:'隔离恢复演练'}
const related=computed(()=>selected.value?.related_runs||[])
const locked=computed(()=>busy.value||uncertain.value||['queued','running'].includes(selected.value?.state))
const original=computed(()=>selected.value?.original_backup||(selected.value?.action==='backup'?selected.value:related.value.find((r:any)=>r.run_id===selected.value?.backup_id)))
let alive=true,timer:ReturnType<typeof setInterval>|undefined
function remember(id:string,unknown:boolean){pending.value=id;uncertain.value=unknown;try{if(id)sessionStorage.setItem(storage,JSON.stringify({id,uncertain:unknown}));else sessionStorage.removeItem(storage)}catch{}}
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('认证'))emit('reauth')}
function time(value:any){return typeof value==='number'?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'未记录'}
function stage(action:string){if(!selected.value)return null;const evidence=selected.value.evidence;if(evidence){if(action==='backup')return evidence.backup;return evidence[action]?.latest_attempt||null}if(selected.value.action===action)return selected.value;return related.value.find((r:any)=>r.action===action)||null}
function verified(action:string){return selected.value?.evidence?.[action]?.verified_run||null}
async function list(){const r=await api('/game-backups?page='+page.value);if(alive)data.value=r}
async function read(id:string){if(!/^[a-f0-9]{32}$/.test(id))throw new Error('请输入32位游戏备份请求编号。');const r=await api('/game-backups/'+id);if(!alive)return;selected.value=r;query.value=id;ack.value=false;if(pending.value===id)remember(id,false)}
async function refresh(id=query.value||pending.value){if(busy.value)return;busy.value=true;error.value='';try{if(id)await read(id);await list()}catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}}
async function preview(){
 if(locked.value)return;error.value='';notice.value=''
 if(!/^[a-f0-9]{32}$/.test(windowId.value.trim())){error.value='请填写维护中心已经开启并核验的32位维护窗口编号。';return}
 if(!reason.value.trim()){error.value='请填写玩家存档备份原因。';return}
 if(!lease.acquire('game-backup')){error.value='请先完成或关闭当前确认面板。';return}
 const id=crypto.randomUUID().replaceAll('-','');remember(id,true);busy.value=true
 try{const r=await api('/game-backups/preview','POST',{request_id:id,window_id:windowId.value.trim(),reason:reason.value.trim()});if(!alive)return;selected.value=r;query.value=id;remember(id,false);ack.value=false;await list()}
 catch(e){if(e instanceof ApiError&&e.status<500){remember('',false);lease.release('game-backup')}if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function confirm(){
 if(locked.value||selected.value?.state!=='preview')return;error.value='';if(!ack.value){error.value='请确认玩家存档备份范围与维护窗口。';return}
 if(!lease.acquire('game-backup')){error.value='请先完成或关闭当前确认面板。';return}
 const run=selected.value;remember(run.run_id,true);busy.value=true
 try{await api('/game-backups/'+run.run_id+'/confirm','POST',{fingerprint:run.fingerprint,acknowledge_game_scope:true});if(!alive)return;await read(run.run_id);await list();notice.value='已提交原备份请求；执行结果以该编号和收据为准。';lease.release('game-backup')}
 catch(e){if(e instanceof ApiError&&e.status<500)remember(run.run_id,false);if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function followup(action:'copy'|'rehearse'){
 if(locked.value||original.value?.state!=='succeeded')return;error.value='';notice.value=''
 if(!followupReason.value.trim()){error.value='请填写异地复制或隔离演练原因。';return}
 const id=crypto.randomUUID().replaceAll('-',''),backup=original.value.run_id;remember(id,true);query.value=id;busy.value=true
 try{await api('/game-backups/'+backup+'/'+action,'POST',{request_id:id,reason:followupReason.value.trim()});if(!alive)return;await read(id);await list();notice.value='已提交'+actions[action]+'请求，与原恢复点绑定。'}
 catch(e){if(e instanceof ApiError&&e.status<500)remember('',false);if(alive)fail(e)}finally{if(alive)busy.value=false}
}
onMounted(async()=>{try{const saved=JSON.parse(sessionStorage.getItem(storage)||'null');if(saved&&/^[a-f0-9]{32}$/.test(saved.id)){remember(saved.id,!!saved.uncertain);query.value=saved.id;await read(saved.id)}if(props.initialRun){if(uncertain.value&&props.initialRun!==pending.value)error.value='请先核对原备份请求 '+pending.value;else await read(props.initialRun)}await list()}catch(e){if(alive)fail(e)}if(!alive)return;timer=setInterval(()=>{if(!document.hidden&&!busy.value&&selected.value&&['queued','running'].includes(selected.value.state))void refresh(selected.value.run_id)},30000)})
watch(()=>props.initialRun,id=>{if(id&&!uncertain.value)void refresh(id)})
watch(()=>selected.value?.state==='preview',value=>{if(value)lease.acquire('game-backup');else lease.release('game-backup')})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer);lease.release('game-backup')})
</script>
<template><section class="game-backups">
 <header class="section-title"><div><h2>游戏存档恢复点</h2><p class="muted">全业务库一致性备份 → 加密异地副本 → 隔离同版 MySQL 恢复演练</p></div><button @click="emit('navigate','maintenance')">进入维护中心</button></header>
 <p class="notice">这里覆盖游戏业务库；GM 管理库备份在维护中心单独展示。备份须使用已核验的维护窗口，不会自动停服或结束维护；恢复演练只写入预先配置的隔离环境。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="notice" class="notice" role="status">{{notice}}</p>
 <div v-if="uncertain" class="warning"><strong>请求结果待核对</strong><p>保留原编号 {{pending}}；只查询原请求，未查到记录也不等于未执行。</p><button :disabled="busy" @click="refresh(pending)">查询原备份请求</button></div>
 <section class="panel"><div class="section-title"><h3>创建恢复点</h3><span class="pill">{{data?.worker.configured?'执行器已配置':'未配置或状态未知'}}</span></div><form class="backup-form" @submit.prevent="preview"><label>已开启的维护窗口编号<input v-model="windowId" aria-label="游戏备份维护窗口" maxlength="32" :disabled="locked" placeholder="从维护中心核对并复制"></label><label>备份原因<input v-model="reason" aria-label="游戏备份原因" maxlength="200" :disabled="locked"></label><button class="primary" :disabled="locked||!data?.worker.configured">预览玩家存档备份</button></form><p class="field-hint">数据库范围、版本、输出位置、加密接收方和隔离环境均由安装配置固定。网页只提交原因和原维护窗口编号。</p></section>
 <section v-if="selected" class="panel" aria-label="游戏备份请求详情"><div class="section-title"><h3>{{actions[selected.action]}} · {{states[selected.state]||selected.state}}</h3><button :disabled="busy" @click="refresh(selected.run_id)">刷新原请求</button></div><p><code>{{selected.run_id}}</code> · {{selected.reason}}</p><p v-if="selected.backup_id!==selected.run_id">原恢复点：<button :disabled="busy||uncertain" @click="refresh(selected.backup_id)">{{selected.backup_id}}</button></p><p>提交 {{time(selected.created_at)}} · 完成 {{time(selected.finished_at)}}</p><p v-if="selected.error_code" class="warning">{{selected.error_code}}，请核对执行器记录。</p>
 <div class="backup-stages"><article v-for="(label,action) in actions" :key="action"><small>{{label}}</small><strong>{{stage(String(action))?(states[stage(String(action)).state]||stage(String(action)).state):'尚无对应执行记录'}}</strong><span>{{time(stage(String(action))?.finished_at)}}</span><span v-if="verified(String(action))">同一文件已有成功收据：{{time(verified(String(action)).finished_at)}}</span></article></div><p class="field-hint">三个阶段分别取同一恢复点的执行收据；备份成功不能替代异地复制或恢复演练成功。</p>
 <template v-if="selected.state==='preview'"><p>预览到期：{{time(selected.expires_at)}} · 原窗口 {{selected.window_id}}</p><label class="backup-ack"><input v-model="ack" type="checkbox" :disabled="locked">我已核对玩家存档范围和维护窗口；备份后仍需单独复制、演练，并在维护中心结束维护。</label><button class="primary" :disabled="locked||!ack" @click="confirm">确认创建该恢复点</button></template>
 <div v-if="original?.state==='succeeded'" class="backup-followup"><label>后续操作原因<input v-model="followupReason" aria-label="游戏备份后续原因" maxlength="200" :disabled="locked"></label><div class="button-row"><button :disabled="locked||!data?.worker.copy_configured" @click="followup('copy')">复制到固定异地接收方</button><button :disabled="locked||!data?.worker.rehearsal_configured" @click="followup('rehearse')">在隔离 MySQL 中恢复演练</button></div><small v-if="!data?.worker.copy_configured||!data?.worker.rehearsal_configured" class="muted">未配置的接收方或隔离环境需先由维护者安装，再刷新执行器状态。</small></div>
 <details v-if="selected.result"><summary>执行证据摘要</summary><pre>{{JSON.stringify(selected.result,null,2)}}</pre></details>
 </section>
 <section class="panel"><div class="section-title"><h3>恢复点与操作历史</h3><button :disabled="busy" @click="refresh()">刷新历史</button></div><form class="toolbar" @submit.prevent="refresh()"><label>按原请求编号查询<input v-model="query" aria-label="游戏备份原请求编号" maxlength="32" :disabled="uncertain"></label><button :disabled="busy">查询原请求</button></form><div class="table-wrap"><table><thead><tr><th>请求 / 范围</th><th>独立阶段</th><th>状态 / 时间</th><th>操作</th></tr></thead><tbody><tr v-for="row in data?.items||[]" :key="row.run_id"><td><b>{{row.reason}}</b><small class="cell-note">{{row.run_id}}</small></td><td>{{actions[row.action]}}</td><td>{{states[row.state]||row.state}}<small class="cell-note">{{time(row.created_at)}}</small></td><td><button :disabled="busy||uncertain" @click="refresh(row.run_id)">核对该请求</button></td></tr></tbody></table></div><p v-if="data&&!data.items.length" class="empty">尚无玩家存档备份记录。</p><div class="pagination"><button :disabled="busy||page===1" @click="page--;refresh()">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||!data?.has_more" @click="page++;refresh()">下一页</button></div></section>
</section></template>
<style scoped>.game-backups{display:grid;gap:18px}.game-backups h2,.game-backups h3{margin:0}.game-backups label{display:grid;gap:6px}.backup-form{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto;gap:12px;align-items:end}.backup-ack{display:flex!important;align-items:start;gap:8px;margin:14px 0}.backup-ack input{width:auto;flex:none;margin-top:5px}.backup-stages{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:18px 0}.backup-stages article{padding:14px;background:var(--bg-quinary);border:1px solid var(--border-color);border-radius:var(--radius-sm);display:grid;gap:7px}.backup-stages small{color:var(--amber-text)}.backup-stages strong{font-size:13px}.backup-stages span,.backup-followup small{font-size:11px;color:var(--text-secondary)}.backup-followup{border-top:1px solid var(--border-color);padding-top:16px;margin-top:18px}.game-backups code,.game-backups small{overflow-wrap:anywhere}.game-backups pre{white-space:pre-wrap;overflow-wrap:anywhere}.game-backups .toolbar label{flex:1;min-width:0}.game-backups .button-row{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}@media(max-width:700px){.backup-form,.backup-stages{grid-template-columns:1fr}.game-backups>.section-title{align-items:start}.game-backups>.section-title h2{font-size:20px}.game-backups table{min-width:580px}.game-backups .toolbar{flex-wrap:wrap}}</style>
