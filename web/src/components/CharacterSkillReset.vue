<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount,watch,nextTick} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import {useGmConfirmation} from '../stores/gm/confirmation'
const confirmationLease=useGmConfirmation()
import {inventoryStates as states} from '../nativeStatus'
const props=defineProps<{characNo:number,disabled?:boolean}>()
const emit=defineEmits(['busy','pending','reauth','expired','changed'])
const base='/character-skill-reset',storage='dnfgm-character-skill-reset-operation'
const current=ref<any>(null),operation=ref<any>(null),records=ref<any[]>([]),page=ref(1),more=ref(false)
const busy=ref(false),error=ref(''),reason=ref(''),reasonError=ref(''),valueError=ref(''),lookup=ref('')
const trees=ref<number[]>([0]),key=ref(''),attempted=ref(false),root=ref<HTMLElement|null>(null)
const unfinished=computed(()=>operation.value?.status==='preview'||operation.value?.status==='executing')
const pending=computed(()=>operation.value?.status==='executing'||attempted.value&&operation.value?.status==='preview')

let alive=true,timer:ReturnType<typeof setInterval>|undefined
watch(busy,v=>emit('busy',v));watch(unfinished,v=>emit('pending',v))
function failure(e:unknown){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired');if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))emit('reauth')}
function remember(id:string){try{sessionStorage.setItem(storage,id)}catch{/* history lookup remains available */}}
async function run(fn:()=>Promise<void>){if(busy.value)return;busy.value=true;error.value='';try{await fn()}catch(e){if(alive)failure(e)}finally{if(alive)busy.value=false;if(operation.value?.status!=='preview')confirmationLease.release('character-characterskillreset')}}
async function refresh(){await run(async()=>{const r=await api(`${base}/characters/${props.characNo}`);if(alive){current.value=r}})}
async function history(){await run(async()=>{const r=await api(`${base}/operations?charac_no=${props.characNo}&page=${page.value}`);if(alive){records.value=r.items;more.value=r.has_more}})}
function received(r:any){if(!alive)return;operation.value=r;remember(r.operation_id);if(r.status==='committed')emit('changed')}
async function inspect(id=operation.value?.operation_id){if(!id||!/^[a-f0-9]{32}$/.test(id)){error.value='请输入32位操作编号';return}await run(async()=>{received(await api(`${base}/operations/${id}`));attempted.value=true})}
async function preview(){
 if(props.disabled||busy.value||operation.value||!current.value)return
 reasonError.value=reason.value.trim()?'':'请填写操作原因';valueError.value=''
 if(!trees.value.length)valueError.value='请选择至少一套技能树。'
 if(reasonError.value||valueError.value){await nextTick();root.value?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();return}
 if(!confirmationLease.acquire('character-characterskillreset')){error.value='请先完成或关闭当前确认面板。';return}
 await run(async()=>{const r=await api(base+'/preview','POST',{action:'char-skill-reset',uid:current.value.target.uid,charac_no:props.characNo,reference:current.value.reference,trees:trees.value,reason:reason.value.trim()});key.value=crypto.randomUUID().replaceAll('-','');attempted.value=false;received(r);await nextTick();root.value?.querySelector<HTMLElement>('.skill-reset-preview')?.scrollIntoView?.({block:'nearest'})})
}
async function confirm(){if(props.disabled||!operation.value||attempted.value||!key.value)return;if(!confirmationLease.acquire('character-characterskillreset')){error.value='请先完成或关闭当前确认面板。';return};attempted.value=true;await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/confirm`,'POST',{idempotency_key:key.value})))}
async function cancel(){await run(async()=>received(await api(`${base}/operations/${operation.value.operation_id}/cancel-preview`,'POST',{})))}
async function finish(){operation.value=null;attempted.value=false;key.value='';try{sessionStorage.removeItem(storage)}catch{}await refresh();await history()}
onMounted(async()=>{await refresh();if(!alive)return;await history();if(!alive)return;let id='';try{id=sessionStorage.getItem(storage)||''}catch{}if(id)await inspect(id);timer=setInterval(()=>{if(alive&&pending.value&&!document.hidden&&!busy.value)void inspect()},10000)})
watch(()=>operation.value?.status,status=>{if(status==='preview')confirmationLease.acquire('character-characterskillreset');else confirmationLease.release('character-characterskillreset')})
onBeforeUnmount(()=>{confirmationLease.release('character-characterskillreset');alive=false;if(timer)clearInterval(timer);emit('busy',false);emit('pending',false)})
</script>
<template><section ref="root" class="skill-reset-maintenance">
 <div class="section-heading"><div><span class="eyebrow">SKILL RESET</span><h3>已学技能与重置</h3></div><button :disabled="busy||unfinished||disabled" @click="refresh">刷新技能存档</button></div>
 <p class="field-hint">与下方「调整剩余SP／TP」不同，这里会移除选中技能树的自学技能，并重建对应职业的默认技能。请先在维护中心开启维护窗口。</p>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p>
 <template v-if="current">
  <p><b>{{current.target.accountname}}</b> / UID {{current.target.uid}} · {{current.target.character.charac_name}} / #{{current.target.character.charac_no}}</p>
  <div class="skill-tree-cards"><article v-for="t in current.trees" :key="t.tree" class="skill-tree-card">
   <h4>技能树{{t.tree===0?'一':'二'}} <span class="field-hint">{{t.skills.length}} 个存档技能</span></h4><p>剩余 SP {{t.sp.toLocaleString('zh-CN')}} · TP {{t.tp.toLocaleString('zh-CN')}}</p>
   <p v-if="t.temporary_reset_active" class="warning">存在临时洗点标记：重置时会同步对应备份，防止旧技能再次恢复；不会取消付费权益。</p>
   <div class="skill-chip-list"><span v-for="s in t.skills" :key="s.slot" class="skill-chip" :title="'技能 #'+s.skill_id+' · 槽位 '+s.slot">{{s.name}} <b>Lv.{{s.level}}</b></span><span v-if="!t.skills.length">暂无已学技能</span></div>
  </article></div>
  <details><summary>重置后的默认技能（{{current.reset_defaults.length}} 个）</summary><p>每套重置后 SP {{current.reset_points.sp}} · TP {{current.reset_points.tp}}。按固定镜像原生规则重算，不保留人工额外赠点。</p><div class="skill-chip-list"><span v-for="s in current.reset_defaults" :key="s.slot" class="skill-chip">{{s.name}} <b>Lv.{{s.level}}</b></span></div></details>
  <p class="field-hint">{{current.note}}</p>
  <p v-if="!current.enabled" class="warning">可在「功能与权限」直接开启「PvE技能重置」。</p>
  <p v-if="!current.maintenance.available" class="warning">{{current.maintenance.note}}</p>
  <form v-if="!operation" @submit.prevent="preview" novalidate>
   <fieldset :disabled="busy||disabled" :aria-invalid="!!valueError"><legend>要重置的技能树</legend><label v-for="i in [0,1]" :key="i" class="tree-option"><input type="checkbox" v-model="trees" :value="i">技能树{{i===0?'一':'二'}}</label></fieldset>
   <p v-if="valueError" class="submit-error" role="alert">{{valueError}}</p>
   <label>重置原因<input v-model="reason" :disabled="busy||disabled" maxlength="200" :aria-invalid="!!reasonError" aria-describedby="skill-reset-reason-error" @input="reasonError=''" placeholder="例如：修复角色加点异常"></label>
   <p v-if="reasonError" id="skill-reset-reason-error" class="submit-error" role="alert">{{reasonError}}</p>
   <button class="primary" :disabled="busy||disabled||!current.enabled||!current.maintenance.available" type="submit">生成技能重置预览</button>
  </form>
 </template>
 <section v-if="operation" class="skill-reset-preview" tabindex="-1">
  <h4>{{states[operation.status]||operation.status}} · PvE技能重置</h4>
  <p>目标：{{operation.preview.target.accountname}} / UID {{operation.preview.target.uid}} · {{operation.preview.target.character.charac_name}} / #{{operation.preview.target.character.charac_no}}</p>
  <p>操作编号：{{operation.operation_id}}</p><p>原因：{{operation.preview.reason}}</p>
  <article v-for="c in operation.preview.changes" :key="(c as any).tree"><h4>技能树{{(c as any).tree===0?'一':'二'}}</h4>
   <p>SP {{(c as any).before.sp}} → {{(c as any).after.sp}} · TP {{(c as any).before.tp}} → {{(c as any).after.tp}}</p>
   <div class="skill-tree-cards"><div><h5>修改前</h5><div class="skill-chip-list"><span v-for="s in (c as any).before.skills" :key="s.slot" class="skill-chip">{{s.name}} Lv.{{s.level}}</span></div></div><div><h5>重建后</h5><div class="skill-chip-list"><span v-for="s in (c as any).after.skills" :key="s.slot" class="skill-chip">{{s.name}} Lv.{{s.level}}</span></div></div></div>
   <p v-if="(c as any).temporary_backup_reset" class="warning">对应临时洗点备份也将重置。</p>
   <p v-for="s in (c as any).skipped_defaults" :key="s.skill_id" class="warning">#{{s.skill_id}}：{{s.reason}}</p>
  </article>
  <p v-if="pending" class="notice">结果待确认，正在查询原编号，不会自动重复提交。</p>
  <p v-if="operation.status==='committed'" class="notice">技能存档、快照与审计已提交。结束维护后由游戏加载；本结果不代表客户端效果已验证。</p>
  <div class="button-row"><button v-if="operation.status==='preview'&&!attempted&&key" class="danger" :disabled="busy||disabled" @click="confirm">确认重置所选技能树</button><button :disabled="busy||disabled" @click="inspect()">查询原操作结果</button><button v-if="operation.status==='preview'&&!pending" :disabled="busy||disabled" @click="cancel">取消预览</button><button v-if="['committed','cancelled','aborted'].includes(operation.status)" :disabled="busy||disabled" @click="finish">结束查看</button></div>
 </section>
 <details><summary>技能重置历史与编号查询</summary><div class="button-row"><input v-model="lookup" aria-label="技能重置操作编号"><button :disabled="busy||disabled||!!operation" @click="inspect(lookup.trim())">查询技能重置操作</button></div><p v-if="!records.length">暂无重置记录</p>
 <article v-for="r in records" :key="r.operation_id" class="history-row"><span>{{states[r.status]||r.status}} · {{r.preview.reason}}</span><button :disabled="busy||disabled||!!operation" @click="inspect(r.operation_id)">查看记录</button></article>
 <div class="button-row"><button :disabled="busy||disabled||page<=1" @click="page--;history()">上一页</button><span>第 {{page}} 页</span><button :disabled="busy||disabled||!more" @click="page++;history()">下一页</button></div></details>
 <p v-if="busy" role="status">正在处理…</p>
</section></template>
<style scoped>
.skill-reset-maintenance{display:grid;gap:14px;padding-bottom:24px;margin-bottom:24px;border-bottom:1px solid var(--border-color)}.section-heading,.button-row,.history-row{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}.section-heading h3{margin:4px 0}.eyebrow{font-size:11px;letter-spacing:.12em;color:var(--text-secondary)}form,label{display:grid;gap:8px}form{gap:12px}.skill-tree-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.skill-tree-card,.skill-reset-preview{padding:16px;background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:12px}.skill-chip-list{display:flex;flex-wrap:wrap;gap:6px}.skill-chip{padding:4px 8px;border:1px solid var(--border-color);border-radius:6px;font-size:12px;overflow-wrap:anywhere}.skill-chip b{color:var(--text-secondary);font-weight:500}.tree-option{display:inline-flex;align-items:center;margin:4px 20px 4px 0}.tree-option input{width:auto}fieldset{border:1px solid var(--border-color);border-radius:8px}p{overflow-wrap:anywhere}@media(max-width:650px){.skill-tree-cards{grid-template-columns:1fr}}
</style>
