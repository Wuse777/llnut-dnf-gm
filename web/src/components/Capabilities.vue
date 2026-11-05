<script setup lang="ts">
import {computed,ref,onMounted,onUnmounted} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import Modal from './Modal.vue'
import FieldError from './FieldError.vue'
const emit=defineEmits<{expired:[],reauth:[],navigate:[tab:string]}>()
const data=ref<any>(null),busy=ref(false),error=ref(''),success=ref(''),reason=ref(''),reasonError=ref(''),enabled=ref<string[]>([]),search=ref(''),filter=ref('all'),confirm=ref(false),pending=ref(''),checking=ref(false)
const storage='dnf-gm.capability-pending'
let alive=true,timer:ReturnType<typeof setInterval>|undefined
const destinations=new Set(['accounts','mail','gifts','reward-jobs','schedules','unlock-center','online','native-controls','mail-center','support','economy','compatibility','catalog'])
const states:Record<string,string>={configured:'配置已启用',disabled:'尚未启用',attention:'已启用 · 前提待处理',not_implemented:'待实现'}
const statusNames:Record<string,string>={ok:'完整',incomplete:'迁移不完整',unknown:'未知',recorded:'构建记录可读',dirty:'构建包含未提交变更',matched:'指纹匹配',mismatch:'版本不匹配',unavailable:'不可读取',ready:'图片包匹配',not_installed:'未安装',legacy:'沿用旧配置',managed:'网页管理',loaded:'记录已读取',not_configured:'未提供验收记录'}
const rows=computed(()=>(data.value?.items??[]).filter((i:any)=>(filter.value==='all'||i.state===filter.value)&&(!search.value||[i.label,i.group,i.note].some(s=>s.includes(search.value)))))
const changed=computed(()=>JSON.stringify([...enabled.value].sort())!==JSON.stringify([...(data.value?.policy?.enabled??[])].sort()))
const choices=computed(()=>data.value?.policy?.choices??[])
const added=computed(()=>choices.value.filter((c:any)=>enabled.value.includes(c.id)&&!data.value?.policy?.enabled.includes(c.id)))
const removed=computed(()=>choices.value.filter((c:any)=>!enabled.value.includes(c.id)&&data.value?.policy?.enabled.includes(c.id)))
const frozen=computed(()=>busy.value||!!pending.value)
function date(v:any){return typeof v==='number'?new Date(v*1000).toLocaleString('zh-CN',{hour12:false}):'未记录'}
function failure(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError){if(e.status===401)emit('expired');else if(e.status===403&&e.message.includes('重新认证'))emit('reauth')}}
function remember(id:string){pending.value=id;try{if(id)sessionStorage.setItem(storage,id);else sessionStorage.removeItem(storage)}catch{}}
async function load(){
 if(busy.value)return;busy.value=true;error.value='';data.value=null
 try{const d=await api('/capabilities');if(alive){data.value=d;enabled.value=[...(d.policy?.enabled??[])]}}
 catch(e){if(alive)failure(e)}finally{if(alive)busy.value=false}
}
function all(){enabled.value=choices.value.map((c:any)=>c.id)}
function toggle(id:string,event:Event){
 const active=new Set(enabled.value),checked=(event.target as HTMLInputElement).checked
 if(checked){
  active.add(id)
  if(id==='native-notice'||id==='native-kick')active.add('native-monitor')
  if(id==='batch-worker')active.add('batch-reward')
 }else{
  active.delete(id)
  if(id==='native-monitor'){active.delete('native-notice');active.delete('native-kick')}
  if(id==='batch-reward')active.delete('batch-worker')
 }
 enabled.value=choices.value.map((c:any)=>c.id).filter((key:string)=>active.has(key))
}

function preview(){
 if(frozen.value||data.value?.policy?.revision==null)return
 reasonError.value='';error.value='';success.value=''
 if(reason.value.trim().length<2){reasonError.value='请填写至少2个字的权限调整原因。';return}
 if(!changed.value&&data.value.policy.state==='managed'){error.value='权限没有变化。';return}
 confirm.value=true
}
async function save(){
 if(frozen.value||!confirm.value)return
 const id=crypto.randomUUID().replaceAll('-','');remember(id);busy.value=true;error.value=''
 try{const r=await api('/capabilities/policy','POST',{request_id:id,expected_revision:data.value.policy.revision,enabled:enabled.value,reason:reason.value.trim()});remember('');confirm.value=false;success.value='权限版本 '+r.revision+' 已保存，管理员可操作所有账号。开关即时生效，不需要重启服务。';reason.value=''}
 catch(e){if(e instanceof ApiError&&[400,401,403,404,409,422,429].includes(e.status))remember('');failure(e)}
 finally{busy.value=false}
 if(!pending.value&&!confirm.value&&alive)await load()
}
async function reconcile(){
 if(!pending.value||checking.value||busy.value)return
 checking.value=true;const id=pending.value
 try{const r=await api('/capabilities/policy/requests/'+id);if(r.status==='committed'&&pending.value===id){remember('');confirm.value=false;success.value='已按原编号确认权限版本 '+r.revision+' 提交成功；没有重新发送。';if(alive)await load()}}
 catch(e){if(alive)failure(e)}finally{checking.value=false}
}
onMounted(()=>{try{const id=sessionStorage.getItem(storage)||'';if(/^[a-f0-9]{32}$/.test(id))pending.value=id}catch{};void load();timer=setInterval(()=>{if(!document.hidden&&pending.value)void reconcile()},5000)})
onUnmounted(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template>
 <div class="capability-center">
  <section class="panel"><div class="section-title"><div><h2>功能与版本</h2><p class="muted">管理员能力、运行前提与验收记录分开查看</p></div><button type="button" :disabled="frozen" @click="load">刷新功能状态</button></div>
   <p v-if="busy" role="status">正在读取或保存功能配置…</p><p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="success" class="submit-success" role="status">{{success}}</p>
   <div v-if="pending" class="warning" role="status"><b>权限保存结果待确认</b><p>请求编号 <code>{{pending}}</code>。每5秒只读核对；不重复提交、不另建请求。</p><button type="button" :disabled="checking||busy" @click="reconcile">查询原权限请求</button></div>
   <template v-if="data"><p class="field-hint">{{data.note}}</p><div class="capability-summary"><article><small>当前代码版本</small><strong>{{data.application.version}}</strong><code>{{data.application.source_revision||'未记录源码提交'}}</code><span>{{statusNames[data.application.source_state]||'未知'}}</span></article><article><small>管理库迁移</small><strong>{{statusNames[data.schema.state]||'未知'}}</strong><span>{{data.schema.versions.join(' / ')||'无可用记录'}}</span></article><article><small>管理员权限</small><strong>{{statusNames[data.policy.state]||'未知'}}</strong><span>{{data.policy.account_scope==='all'?'所有账号，不限测试UID':data.scope.test_only?'旧配置仍有限定账号；可在下方一键开放':'所有账号'}}</span><span>修订 {{data.policy.revision??'未知'}}</span></article></div>
    <details class="capability-binding"><summary>版本绑定与数据时间</summary><dl class="character-facts"><div><dt>PVF配置指纹</dt><dd><code>{{data.binding.pvf_sha256||'未提供有效指纹'}}</code></dd></div><div><dt>镜像配置指纹</dt><dd><code>{{data.binding.image_digest||'未提供有效指纹'}}</code></dd></div><div><dt>物品索引</dt><dd>{{statusNames[data.catalog.state]||'未知'}}</dd></div><div><dt>图片包</dt><dd>{{statusNames[data.assets.state]||'未知'}}</dd></div><div><dt>采集时间</dt><dd>{{date(data.runtime.collected_at)}} · {{data.runtime.fresh?'本次有效':'缺失／过期'}}</dd></div><div><dt>功能状态读取</dt><dd>{{date(data.checked_at)}}</dd></div></dl></details>
   </template>
  </section>
  <section v-if="data" class="panel capability-permissions"><div class="section-title"><div><h2>管理员功能开关</h2><p class="muted">网页内管理，无需编辑服务器配置</p></div><button type="button" :disabled="frozen||data.policy.revision==null" @click="all">全部开放</button></div>
   <p class="field-hint">保存后不再限制测试账号；“全部开放”仅选择开关，核对后点击保存。关闭开关不会撤回已完成操作，也不取消已经开始的事务。</p>
   <fieldset :disabled="frozen||data.policy.revision==null"><legend class="sr-only">选择管理员功能</legend><div class="capability-switches"><label v-for="c in choices" :key="c.id"><input type="checkbox" :checked="enabled.includes(c.id)" :value="c.id" @change="toggle(c.id,$event)"><span>{{c.label}}</span></label></div><label for="capability-reason">权限调整原因<input id="capability-reason" v-model="reason" maxlength="200" :aria-invalid="!!reasonError" :aria-describedby="reasonError?'capability-reason-error':undefined" placeholder="例如：开放所有功能进行网页测试"></label><FieldError id="capability-reason-error" :message="reasonError"/><button type="button" class="primary" @click="preview">核对并保存权限</button></fieldset>
   <p v-if="data.policy.state==='unknown'" class="warning">权限记录当前不可读取，请修复数据库连接后刷新；不会把未知状态当作已开放。</p>
  </section>
  <section v-if="data" class="panel"><form class="toolbar" @submit.prevent><input v-model="search" aria-label="搜索功能" placeholder="搜索功能名称、用途"><select v-model="filter" aria-label="筛选功能状态"><option value="all">全部状态</option><option v-for="(label,key) in states" :key="key" :value="key">{{label}}</option></select></form>
   <p class="field-hint">“人工记录：游戏客户端”仅代表绑定该源码／镜像／PVF的维护验收记录，不保证此刻可执行；没有记录不等于权限关闭。</p>
   <div class="capability-grid"><article v-for="item in rows" :key="item.id" class="capability-card"><div class="section-title"><small>{{item.group}}</small><span class="pill" :class="{'capability-attention':item.state==='attention'}">{{states[item.state]||'未知'}}</span></div><h3>{{item.label}}</h3><ul v-if="item.checks.length" class="capability-checks"><li v-for="check in item.checks" :key="check.code">{{check.message}}</li></ul><p>{{item.note}}</p><div class="capability-verification"><template v-if="item.verification.state==='matched'"><b>人工记录：{{item.verification.level==='client'?'游戏客户端':'接口／数据库'}}</b><small>{{date(item.verification.checked_at)}} · {{item.verification.reference}}</small></template><template v-else-if="item.verification.state==='version_mismatch'"><b>历史验收记录不匹配当前版本</b><small>{{item.verification.reference}}</small></template><span v-else>未关联当前版本验收记录</span></div><button v-if="destinations.has(item.destination)" type="button" @click="emit('navigate',item.destination)">打开功能 →</button></article></div><p v-if="!rows.length" class="empty">没有匹配的功能。</p>
  </section>
  <Modal v-if="confirm" title="确认管理员权限调整" :busy="busy" @close="confirm=false"><p>权限将立即用于当前唯一管理员，操作范围为所有账号。</p><p><b>启用：</b>{{added.map((c:any)=>c.label).join('、')||'无新增'}}</p><p><b>关闭：</b>{{removed.map((c:any)=>c.label).join('、')||'无关闭'}}</p><p>公告／踢人会同时启用原生会话适配；批量执行器会同时启用批量奖励。已有任务可能在启用执行器后继续执行。</p><p>原因：{{reason}}</p><p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="pending" class="warning">结果待确认，请查询原编号；禁止重复提交。</p><template #footer><button type="button" :disabled="busy" @click="confirm=false">{{pending?'稍后查询':'返回修改'}}</button><button v-if="pending" type="button" :disabled="checking||busy" @click="reconcile">查询原权限请求</button><button type="button" class="primary" :disabled="frozen" @click="save">确认保存权限</button></template></Modal>
 </div>
</template>
