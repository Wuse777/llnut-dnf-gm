<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import Modal from './Modal.vue'
import FieldError from './FieldError.vue'
const emit=defineEmits<{expired:[],reauth:[],navigate:[tab:string]}>()
const state=ref<any>(null),detail=ref<any>(null),history=ref<any[]>([]),cursor=ref<string|null>('')
const reason=ref(''),reasonError=ref(''),error=ref(''),busy=ref(false),historyBusy=ref(false),id=ref(''),lookup=ref('')
const fresh=ref(false),attempted=ref(false),restored=ref(false),dialog=ref(false),ack=ref(false),ackError=ref(''),key=ref('')
const storage='dnf-gm.maintenance-pending'
let alive=true,timer:ReturnType<typeof setInterval>|undefined
const names:Record<string,string>={cancelling:'取消已保存 · 等待释放原计划',preparing:'等待只读计划',prepared:'计划已生成 · 尚未执行',queued:'确认已入队 · 未证明开始',running:'已记录执行开始 · 需核对进度',needs_review:'执行结果待核对',game_drained:'游戏退出阶段完成 · 尚非完整维护窗口',maintenance_open:'维护窗口已建立',resuming:'正在核对并恢复服务',completed:'维护流程已结束',cancelled:'预览已取消',expired:'计划已过期',rejected:'执行器已拒绝'}
const phases:Record<string,string>={'freeze-intent':'已记录冻结新写入意向','write-gate-frozen':'普通游戏写入已冻结','database-drained':'已核对原数据库普通写事务结束','drain-started':'开始游戏退出阶段','inhibit-intent':'已记录禁止自动重启意向','inhibit-applied':'禁止自动重启命令已返回','marker-intent':'已记录停止标记意向','marker-applied':'停止标记命令已返回','signal-intent':'已记录退出信号意向','signal-sent':'退出信号命令已返回','game-drained':'游戏进程已正常退出','drain-finished':'游戏退出阶段记录完成'}
const terminal=computed(()=>['cancelled','expired','rejected','completed'].includes(detail.value?.result?.state))
const canConfirm=computed(()=>fresh.value&&detail.value?.can_confirm&&state.value?.write_gate?.state==='open'&&!attempted.value&&!restored.value&&!busy.value)
const displayedState=computed(()=>{const result=detail.value?.result?.state,status=detail.value?.status;
 if(status==='queued'&&(!result||result==='prepared'))return 'queued';
 if(status==='cancelled'&&!['cancelled','expired','rejected','completed'].includes(result))return 'cancelling';
 return result||status})
const gateNames:Record<string,string>={open:'普通写入已开放',frozen:'维护冻结中',unknown:'状态未知 · 普通写入已保护',not_configured:'尚未安装维护写入屏障'}
const observationNames:Record<string,string>={original:'与计划前状态一致',restart_inhibited:'进程仍在运行，自动重启已禁止',restart_inhibited_marker_missing:'进程仍在运行，停止标记待核对',down_normal:'进程正常退出（不是存档验收凭据）',down_abnormal:'进程异常退出',changed:'与原计划不一致'}
const active=computed(()=>!!id.value&&!terminal.value)
function date(value:any){return typeof value==='number'?new Date(value*1000).toLocaleString('zh-CN',{hour12:false}):'未知'}
function fail(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError){if(e.status===401)emit('expired');if(e.status===403&&e.message.includes('重新认证'))emit('reauth')}}
function save(requestId:string){try{sessionStorage.setItem(storage,JSON.stringify({id:requestId}));return true}catch{error.value='浏览器无法保存待核对编号，本次未提交。请允许会话存储后再操作。';return false}}
function forget(){try{sessionStorage.removeItem(storage)}catch{}}
async function loadState(){try{const result=await api('/maintenance');if(alive)state.value=result}catch(e){if(alive){state.value=null;fail(e)}}}
async function loadHistory(reset=false){if(historyBusy.value)return;historyBusy.value=true;const at=reset?'':cursor.value;if(at===null){historyBusy.value=false;return}
 try{const result=await api('/maintenance/requests'+(at?'?cursor='+encodeURIComponent(at):''));if(alive){history.value=reset?result.items:[...history.value,...result.items];cursor.value=result.next_cursor}}
 catch(e){if(alive)fail(e)}finally{if(alive)historyBusy.value=false}}
async function inspect(target=id.value){if(busy.value)return;if(!/^[a-f0-9]{32}$/.test(target)){error.value='请输入32位维护申请编号。';return}
 if(active.value&&id.value!==target){error.value='请先核对当前未结束的申请；不会替换或丢弃原编号。';return}
 busy.value=true;error.value='';fresh.value=false
 try{const result=await api('/maintenance/requests/'+target);if(!alive)return
 if(target!==id.value){restored.value=true;attempted.value=true;id.value=target;save(target)}
 detail.value=result;fresh.value=true;if(terminal.value)forget()
 }catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}}
async function prepare(){if(busy.value||active.value)return;reasonError.value='';error.value=''
 if(reason.value.trim().length<2){reasonError.value='请填写至少两个字的维护原因。';return}
 const next=crypto.randomUUID().replaceAll('-','');if(!save(next))return
 id.value=next;attempted.value=true;restored.value=false;detail.value=null;fresh.value=false;busy.value=true
 try{const result=await api('/maintenance/requests','POST',{request_id:next,reason:reason.value.trim()});if(alive){detail.value=result;fresh.value=true;attempted.value=false;key.value=crypto.randomUUID().replaceAll('-','')}}
 catch(e){if(alive){fail(e);error.value+='；编号已保留，请只查询原申请，不要重复新建。'}}
 finally{if(alive){busy.value=false;void loadHistory(true)}}}
function openConfirm(){if(!canConfirm.value)return;ack.value=false;ackError.value='';dialog.value=true}
async function confirm(){if(!canConfirm.value)return;if(!ack.value){ackError.value='请先确认会断开当前游戏玩家。';return}
 if(!save(id.value))return
 const fingerprint=detail.value.result.fingerprint;attempted.value=true;dialog.value=false;busy.value=true;error.value='';fresh.value=false
 try{const result=await api('/maintenance/requests/'+id.value+'/confirm','POST',{idempotency_key:key.value,fingerprint,acknowledge_disconnect:true});if(alive){detail.value=result;fresh.value=true}}
 catch(e){if(alive){fail(e);error.value+='；确认结果可能未知，只查询原编号，不自动重发。'}}
 finally{if(alive){busy.value=false;void loadHistory(true)}}}
async function cancel(){if(busy.value||!detail.value?.can_cancel)return;busy.value=true;error.value='';fresh.value=false
 try{const result=await api('/maintenance/requests/'+id.value+'/cancel','POST');if(alive){detail.value=result;fresh.value=true;attempted.value=true;if(terminal.value)forget()}}
 catch(e){if(alive)fail(e)}finally{if(alive){busy.value=false;void loadHistory(true)}}}
async function dispatch(){if(busy.value||!detail.value?.retry_dispatch_allowed)return;busy.value=true;error.value='';fresh.value=false
 try{const result=await api('/maintenance/requests/'+id.value+'/dispatch','POST');if(alive){detail.value=result;fresh.value=true}}
 catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}}
async function observe(){if(busy.value||!detail.value?.can_observe)return;busy.value=true;error.value=''
 try{const result=await api('/maintenance/requests/'+id.value+'/observe','POST');if(alive){detail.value=result;fresh.value=true}}
 catch(e){if(alive)fail(e)}finally{if(alive)busy.value=false}}
function reset(){if(busy.value||active.value)return;forget();id.value='';detail.value=null;lookup.value='';attempted.value=false;restored.value=false;fresh.value=false;error.value=''}
onMounted(async()=>{void loadState();void loadHistory(true)
 try{const saved=JSON.parse(sessionStorage.getItem(storage)||'null');if(/^[a-f0-9]{32}$/.test(saved?.id)){id.value=saved.id;attempted.value=true;restored.value=true;await inspect(saved.id)}}catch{}
 timer=setInterval(()=>{if(!document.hidden&&!busy.value){if(active.value)void inspect();void loadState()}},10000)
})
onBeforeUnmount(()=>{alive=false;if(timer)clearInterval(timer)})
</script>
<template>
<section class="panel maintenance-center" aria-label="维护中心">
 <div class="section-title"><div><h2>维护中心</h2><p class="field-hint">先核对计划，再确认执行。维护影响游戏玩家，不操作 mihomo、cliproxyapi 或共享 Docker。</p></div><button :disabled="busy" @click="loadState">刷新执行器状态</button></div>
 <div class="maintenance-summary"><div><span>管理员开关</span><strong>{{state?.enabled?'已开启':state?'已关闭':'未知'}}</strong></div><div><span>完整执行与恢复</span><strong>{{state?.execute_supported?'执行器已接通':'尚未接通 / 未核实'}}</strong></div><button @click="emit('navigate','capabilities')">网页管理功能开关</button></div>
 <div v-if="state?.write_gate" class="maintenance-write-gate" role="status"><strong>{{gateNames[state.write_gate.state]||'写入屏障未知'}}</strong><p v-if="state.write_gate.state==='frozen'">正在维护，充值、邮件、批量奖励、提前解锁和游戏内指令暂停。历史查询仍可用；功能权限无需重新开启，完成恢复后解除冻结。</p><p v-else-if="state.write_gate.state==='unknown'">屏障记录不可核验，新的普通游戏写入暂停。不要通过切换功能权限绕过；请核对原维护申请。</p><small v-if="state.write_gate.operation_id">关联维护：{{state.write_gate.operation_id}}</small></div>
 <p class="notice" role="status">{{state?.message||'正在读取执行器状态；未知不等于正常。'}}</p>
 <p v-if="error&&!id" class="submit-error" role="alert">{{error}}</p>
 <form v-if="!active" class="maintenance-request-form" @submit.prevent="prepare" novalidate>
  <label for="maintenance-reason">维护原因<input id="maintenance-reason" v-model="reason" maxlength="200" :disabled="busy" :aria-invalid="!!reasonError" :aria-describedby="reasonError?'maintenance-reason-error':undefined" placeholder="例如：调整测试角色装备并核对恢复"></label>
  <FieldError id="maintenance-reason-error" :message="reasonError"/>
  <button class="primary" :disabled="busy||!state?.enabled||!state?.prepare_supported">生成只读维护计划</button><small class="field-hint">申请计划本身不会停服。执行器尚未接通时不会出现可执行的停服确认。</small>
 </form>
 <section v-if="id" class="maintenance-request-result" aria-label="维护申请与执行记录">
  <h3>{{names[displayedState]||'申请结果待核对'}}</h3><p v-if="error" class="submit-error" role="alert">{{error}}</p><p class="mono">申请编号：{{id}}</p>
  <p v-if="!fresh" class="notice">当前查询尚未确认；下方仅显示上次记录，不代表执行器仍在运行。</p>
  <template v-if="detail"><p>{{detail.reason}}</p><p v-if="!detail.worker_fresh" class="notice">执行器状态过期或不可读；仅展示已有记录。</p><p v-if="detail.receipt_error" class="submit-error">{{detail.receipt_error}}</p>
   <p v-if="detail.result?.games?.length">本计划涉及：{{detail.result.games.join('、')}}</p><p v-if="detail.result?.expires_at">计划有效期至 {{date(detail.result.expires_at)}}</p>
   <p v-if="detail.status==='cancelled'&&!terminal" class="notice">取消已保存，正在等待执行器释放原计划；这不是停服后的恢复。</p>
   <p v-if="detail.result?.error" class="submit-error">执行记录：{{detail.result.error}}。不要换编号重复执行。</p>
   <p v-if="restored" class="field-hint">从历史或刷新恢复的申请只做查询，不自动恢复确认按钮。尚未确认的计划可以取消后重新申请。</p>
   <section v-if="detail.result?.observation||detail.observation_pending" class="maintenance-observation" aria-label="实际状态核对">
    <h4>实际状态核对（只读）</h4><p v-if="detail.observation_pending" role="status">核对请求已排队；下方如有记录，仅代表上次核对。</p>
    <template v-if="detail.result?.observation"><p>采集时间：{{date(detail.result.observation.collected_at)}} · {{detail.result.observation.state==='observed'?'已取得状态快照':'状态未知 / 无法完成核对'}}</p>
     <p v-if="detail.result.observation.error" class="notice">{{detail.result.observation.error}}</p>
     <ul><li v-for="game in detail.result.observation.games" :key="game.service">{{game.service}}：{{observationNames[game.state]||'未知'}}</li></ul>
     <small>这是采集时的进程状态，不证明游戏存档完整，不开放装备写入，也不会重发退出命令或恢复服务。</small>
    </template>
   </section>
   <ol v-if="detail.result?.events?.length" class="maintenance-events"><li v-for="event in detail.result.events" :key="event.sequence"><b>{{phases[event.phase]||event.phase}}</b><span>{{event.service||'维护流程'}} · {{date(event.at)}}</span></li></ol>
  </template>
  <div class="toolbar"><button :disabled="busy" @click="inspect()">只查询原申请</button><button v-if="detail?.can_observe" :disabled="busy||detail?.observation_pending" @click="observe">核对实际状态（只读）</button><button v-if="canConfirm" class="danger" @click="openConfirm">核对并确认维护</button><button v-if="detail?.can_cancel" :disabled="busy" @click="cancel">取消尚未执行的计划</button><button v-if="detail?.retry_dispatch_allowed&&!detail?.receipt_error" :disabled="busy" @click="dispatch">补投递原申请</button><button v-if="terminal" :disabled="busy" @click="reset">结束查看</button></div>
 </section>
 <form class="toolbar" @submit.prevent="inspect(lookup)" novalidate><input v-model="lookup" aria-label="维护申请编号" placeholder="粘贴32位原申请编号"><button :disabled="busy">按编号查询</button></form>
 <div class="section-title"><h3>维护申请历史</h3><button :disabled="historyBusy" @click="loadHistory(true)">刷新历史</button></div>
 <p v-if="!history.length" class="empty">尚无已读取的维护申请。</p><div class="table-wrap" v-else><table><thead><tr><th>申请时间</th><th>原因</th><th>提交状态</th><th>操作</th></tr></thead><tbody><tr v-for="row in history" :key="row.operation_id"><td>{{date(row.created_at)}}</td><td>{{row.reason}}</td><td>{{names[row.status]||row.status}}</td><td><button :disabled="busy" @click="inspect(row.operation_id)">查看记录</button></td></tr></tbody></table></div><button v-if="cursor" :disabled="historyBusy" @click="loadHistory()">加载更早申请</button>
 <Modal v-if="dialog" title="确认游戏维护" :busy="busy" @close="dialog=false"><p class="warning">将按已核对的计划断开游戏玩家并退出游戏组件。MySQL保留运行。退出阶段完成不等于维护已完成，也不会自动恢复或重复发送退出信号。</p><p>原因：{{detail?.reason}}</p><p>申请编号：{{id}}</p><p>游戏组件：{{detail?.result?.games?.join('、')||'以计划为准'}}</p><label class="maintenance-ack"><input v-model="ack" type="checkbox" aria-label="确认断开当前游戏玩家" :aria-invalid="!!ackError" :aria-describedby="ackError?'maintenance-ack-error':undefined">我确认会断开当前游戏玩家，并按原申请跟踪维护与恢复。</label><FieldError id="maintenance-ack-error" :message="ackError"/><template #footer><button @click="dialog=false">返回核对</button><button class="danger" :disabled="!canConfirm" @click="confirm">确认执行一次</button></template></Modal>
</section>
</template>
<style scoped>
.maintenance-write-gate{padding:12px 16px;border:1px solid var(--border-color);border-radius:12px;margin:12px 0;background:var(--bg-secondary);overflow-wrap:anywhere}.maintenance-write-gate p{margin:8px 0;font-weight:400}.maintenance-summary{display:flex;flex-wrap:wrap;align-items:center;gap:1rem;padding:1rem;border:1px solid var(--border-color,#d9dde3);border-radius:12px;margin:1rem 0}.maintenance-summary>div{display:grid;gap:.4rem;min-width:180px}.maintenance-summary span{font-size:.85rem;opacity:.7}.maintenance-request-form{display:grid;gap:.6rem;max-width:760px}.maintenance-request-form label{display:grid;gap:.4rem}.maintenance-request-result{margin:1rem 0;padding:1rem;border:1px solid var(--border-color,#d9dde3);border-radius:12px;overflow-wrap:anywhere}.maintenance-events{padding-left:1.3rem}.maintenance-events li{padding:.5rem 0}.maintenance-events span{display:block;font-size:.85rem;opacity:.75}.maintenance-ack{display:flex;flex-direction:row;align-items:flex-start;gap:.5rem}.maintenance-ack input{width:18px;height:18px;flex:none;accent-color:var(--primary-color)}.maintenance-center .toolbar{flex-wrap:wrap}@media(max-width:640px){.maintenance-summary{align-items:stretch}.maintenance-summary>div{min-width:0;width:100%}.maintenance-center .toolbar>input{min-width:0;width:100%}}
</style>
