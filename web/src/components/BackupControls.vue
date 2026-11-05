<script setup lang="ts">
import {onMounted,onBeforeUnmount,ref} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
const emit=defineEmits(['reauth'])
const data=ref<any>(null),busy=ref(false),error=ref(''),notice=ref(''),dirty=ref(false)
const enabled=ref(true),at=ref('04:00'),days=ref('7'),alerts=ref(true),reason=ref('调整GM管理库自动备份计划'),manualReason=ref('手动备份GM管理库')
const fields=ref<Record<string,string>>({}),page=ref(1),current=ref<any>(null),pending=ref<{kind:'policy'|'run',id:string}|null>(null)
const storage='dnfgm-backup-request'
const states:Record<string,string>={queued:'等待执行',running:'正在备份',succeeded:'备份完成',failed:'备份失败',cancelled:'已取消'}
const workers:Record<string,string>={ready:'执行器就绪',running:'执行器正在备份',deferred:'等待维护或资源条件恢复',unconfigured:'执行器尚未配置',error:'执行器需要处理',unknown:'执行器状态未知或过期'}
const errors:Record<string,string>={backup_failed:'备份未完成，保留原编号，不会自动重放',backup_interrupted:'执行中断，没有重新导出；保留原始文件供核对',backup_verification_failed:'备份文件与收据核验失败'}
let alive=true,timer:ReturnType<typeof setInterval>|undefined
const date=(v:any)=>typeof v==='number'?new Date(v*1000).toLocaleString('zh-CN',{hour12:false}):'未记录'
function apply(policy:any){enabled.value=policy.enabled;at.value=String(policy.hour).padStart(2,'0')+':'+String(policy.minute).padStart(2,'0');days.value=String(policy.retention_days);alerts.value=policy.failure_alerts;dirty.value=false}
function remember(value:{kind:'policy'|'run',id:string}){pending.value=value;try{sessionStorage.setItem(storage,JSON.stringify(value))}catch{}}
function clear(){pending.value=null;try{sessionStorage.removeItem(storage)}catch{}}
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
async function load(){if(busy.value)return;busy.value=true
 try{const d=await api('/backups?page='+page.value);if(alive){data.value=d;if(!dirty.value)apply(d.policy);const row=d.items.find((r:any)=>r.run_id===current.value?.run_id);if(row)current.value=row}}
 catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
}
async function query(){if(busy.value||!pending.value)return;busy.value=true;error.value=''
 const original={...pending.value}
 try{const r=await api(original.kind==='policy'?'/backups/policy/requests/'+original.id:'/backups/runs/'+original.id);if(!alive)return
  if(original.kind==='policy'){apply(r.policy);notice.value='已按原编号确认：设置已保存'}else{current.value=r;notice.value='已找到原备份任务，不重复创建'}clear()
 }catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}
 if(alive&&!pending.value)void load()
}
async function save(){if(busy.value||pending.value||!data.value)return;fields.value={};error.value='';notice.value=''
 if(!/^\d{2}:\d{2}$/.test(at.value)||Number(at.value.slice(0,2))>23||Number(at.value.slice(3))>59)fields.value.at='请选择有效时间'
 if(!/^\d+$/.test(days.value)||Number(days.value)<1||Number(days.value)>30)fields.value.days='保留周期为1–30天，至少保留最近两份完整备份'
 if(!reason.value.trim())fields.value.reason='请填写修改原因'
 if(Object.keys(fields.value).length)return
 const id=crypto.randomUUID().replaceAll('-','');remember({kind:'policy',id});busy.value=true
 try{const r=await api('/backups/policy','POST',{request_id:id,expected_revision:data.value.policy.revision,enabled:enabled.value,hour:Number(at.value.slice(0,2)),minute:Number(at.value.slice(3)),retention_days:Number(days.value),failure_alerts:alerts.value,reason:reason.value.trim()});if(alive){apply(r.policy);clear();notice.value='备份计划已保存；停用自动计划不会中断已开始的备份'}}
 catch(e){if(alive){fail(e);if(e instanceof ApiError&&e.status>=400&&e.status<500&&e.status!==408)clear()}}
 finally{if(alive)busy.value=false}if(alive&&!pending.value)void load()
}
async function request(){if(busy.value||pending.value)return;fields.value={};error.value='';notice.value=''
 if(!manualReason.value.trim()){fields.value.manual='请填写备份原因';return}
 const id=crypto.randomUUID().replaceAll('-','');remember({kind:'run',id});busy.value=true
 try{const r=await api('/backups/runs','POST',{request_id:id,reason:manualReason.value.trim()});if(alive){current.value=r;clear();notice.value='任务已持久保存，执行器约30秒内检查；不是已完成备份'}}
 catch(e){if(alive){fail(e);if(e instanceof ApiError&&e.status>=400&&e.status<500&&e.status!==408)clear()}}
 finally{if(alive)busy.value=false}if(alive&&!pending.value)void load()
}
onMounted(()=>{try{const d=JSON.parse(sessionStorage.getItem(storage)||'null');if(d&&['policy','run'].includes(d.kind)&&/^[a-f0-9]{32}$/.test(d.id))pending.value=d}catch{};void load();timer=setInterval(()=>{if(!document.hidden)void load()},30000)})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template><section class="panel backup-controls" aria-labelledby="backup-schedule-title">
 <div class="section-title"><div><h2 id="backup-schedule-title">GM管理库自动备份</h2><p class="field-hint">在线一致性快照 · 不停止GM或游戏 · Asia/Shanghai</p></div><button :disabled="busy" @click="load">刷新备份计划</button></div>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="notice" class="submit-success" role="status">{{notice}}</p>
 <div v-if="pending" class="notice backup-pending" role="status"><b>提交结果待确认，请只查询原编号</b><code>{{pending.id}}</code><button :disabled="busy" @click="query">查询原备份请求</button></div>
 <template v-if="data">
  <p :class="['ready','running'].includes(data.worker.state)&&!data.worker.failure?'field-hint':'warning'">{{workers[data.worker.state]||'执行器状态未知'}} · 核对 {{date(data.worker.checked_at)}}<template v-if="data.worker.failure"> · 存在失败或执行器异常，请查看下方记录</template></p>
  <div class="backup-control-columns">
   <form @submit.prevent="save" @input="dirty=true" @change="dirty=true"><h3>每日计划</h3>
    <label class="checkbox-field"><input v-model="enabled" type="checkbox" :disabled="busy||!!pending" aria-label="启用每日管理库备份">启用每日管理库备份</label>
    <div class="backup-time-row"><label>每日时间（北京时间）<input v-model="at" type="time" aria-label="每日备份时间" :disabled="busy||!!pending" :aria-invalid="!!fields.at"><small v-if="fields.at" class="field-error" role="alert">{{fields.at}}</small></label><label>保留天数<input v-model="days" inputmode="numeric" aria-label="备份保留天数" :disabled="busy||!!pending" :aria-invalid="!!fields.days"><small v-if="fields.days" class="field-error" role="alert">{{fields.days}}</small></label></div>
    <label class="checkbox-field"><input v-model="alerts" type="checkbox" :disabled="busy||!!pending" aria-label="备份失败告警">将执行失败纳入备份告警</label>
    <label>修改原因<input v-model="reason" maxlength="200" aria-label="备份计划修改原因" :disabled="busy||!!pending" :aria-invalid="!!fields.reason"><small v-if="fields.reason" class="field-error" role="alert">{{fields.reason}}</small></label>
    <button class="primary" :disabled="busy||!!pending">保存备份计划</button>
    <p class="field-hint">{{data.policy.enabled?'下次常规时间：'+date(data.next_due_at):'自动计划已停用；仍可手动创建备份。'}}<template v-if="data.today_pending"> · 今天已到时间，等待执行器补一次。</template></p>
   </form>
   <form @submit.prevent="request"><h3>立即备份</h3><p class="field-hint">创建持久任务，不直接导出到浏览器。维护窗口或资源条件不允许时等待，不自动停止任何服务。</p><label>备份原因<input v-model="manualReason" maxlength="200" aria-label="手动备份原因" :disabled="busy||!!pending" :aria-invalid="!!fields.manual"><small v-if="fields.manual" class="field-error" role="alert">{{fields.manual}}</small></label><button :disabled="busy||!!pending">立即创建管理库备份</button>
    <p class="field-hint">清理只处理本功能生成的过期完整备份，至少保留最近两份；不删除历史手动备份、未知文件或未完成文件。备份仅在服务器本地，尚未建立异地副本。</p>
    <div v-if="current" class="backup-current" role="status"><b>{{states[current.state]||'未知状态'}}</b><code>{{current.run_id}}</code><span v-if="current.error_code">{{errors[current.error_code]||'执行失败，请核对原记录'}}</span><p v-if="current.state==='succeeded'">文件及校验收据已生成；不代表已通过隔离恢复。</p></div>
   </form>
  </div>
  <h3>备份记录</h3><p v-if="!data.items.length" class="empty">暂无任务记录，不代表已经备份。</p>
  <div class="backup-run-list"><article v-for="row in data.items" :key="row.run_id"><div class="section-title"><b>{{states[row.state]||'未知状态'}}</b><span class="pill">{{row.origin==='daily'?'每日计划':'手动创建'}}</span></div><p>{{row.reason}}</p><small>创建 {{date(row.created_at)}} · 完成 {{date(row.finished_at)}}</small><code>{{row.run_id}}</code><p v-if="row.error_code" class="warning">{{errors[row.error_code]||'执行异常，请核对原编号'}}</p><p v-if="row.result">{{row.result.tables}}张表 · {{row.result.rows}}行 · {{(row.result.bytes/1048576).toFixed(2)}}MiB<template v-if="row.result.retention_deleted"> · 清理{{row.result.retention_deleted}}份过期备份</template><template v-if="row.result.retention_failed"> · 过期清理异常，旧文件已保留</template></p></article></div>
  <div class="pagination"><button :disabled="busy||page<=1" @click="page--;load()">上一页备份</button><span>第 {{page}} 页</span><button :disabled="busy||!data.has_more" @click="page++;load()">下一页备份</button></div>
 </template>
 <p class="warning">只覆盖GM管理库，不含游戏存档、配置密钥、PVF或图片。失败不自动重放；恢复演练与备份分别记录，不提供生产整库恢复按钮。</p>
</section></template>
<style scoped>
.backup-controls h2,.backup-controls h3{margin-top:0}.backup-controls p{overflow-wrap:anywhere}.backup-control-columns{display:grid;grid-template-columns:1.15fr 1fr;gap:18px;margin:18px 0}.backup-control-columns form{display:grid;align-content:start;gap:12px;padding:18px;border:1px solid var(--border-color);border-radius:12px;min-width:0}.backup-control-columns label{display:grid;gap:6px}.backup-control-columns label.checkbox-field{display:flex;gap:8px}.backup-time-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}.backup-current,.backup-pending{display:grid;gap:8px;padding:12px;border:1px solid var(--border-color);border-radius:10px}.backup-controls code{display:block;overflow-wrap:anywhere;font-size:12px}.backup-run-list{display:grid;grid-template-columns:1fr 1fr;gap:12px}.backup-run-list article{min-width:0;padding:14px;border:1px solid var(--border-color);border-radius:10px}.backup-run-list article p{margin:8px 0}.backup-run-list article small{display:block;color:var(--text-secondary);margin-bottom:8px}@media(max-width:760px){.backup-control-columns,.backup-run-list{grid-template-columns:1fr}.backup-control-columns form{padding:14px}.backup-time-row{grid-template-columns:1fr}}
</style>
