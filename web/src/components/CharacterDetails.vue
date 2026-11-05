<script setup lang="ts">
import {ref,computed,watch,onUnmounted,nextTick} from 'vue'
import {api,uncertainMessage} from '../api'
import Modal from './Modal.vue'
import GameImage from './GameImage.vue'
import InventoryGrid from './InventoryGrid.vue'
import InventoryEditor from './InventoryEditor.vue'
import CharacterMaintenance from './CharacterMaintenance.vue'
import CharacterRename from './CharacterRename.vue'
import CharacterRescue from './CharacterRescue.vue'
import CharacterQuests from './CharacterQuests.vue'
const rescueBusy=ref(false),rescuePending=ref(false),rescueVisited=ref(false)
const renameBusy=ref(false),renamePending=ref(false),renameVisited=ref(false)
import MailCenter from './MailCenter.vue'
import CharacterActivity from './CharacterActivity.vue'
const fatigueBusy=ref(false),fatiguePending=ref(false),fatigueVisited=ref(false)
const visual=ref(true)
import UnlockRequests from './UnlockRequests.vue'
const props=withDefaults(defineProps<{characNo:number,initialSection?:string}>(),{initialSection:'basic'})
const emit=defineEmits<{close:[],reauth:[],expired:[],action:[value:{action:string,uid:number,charac_no:number}],draft:[value:any],inspect:[id:string]}>()
const inventoryPending=ref(false),inventoryStale=ref(false)
const inventoryBusy=ref(false),inventoryVisited=ref(false),inventorySelection=ref<{container:string,slot:number}|null>(null)
const actionBusy=computed(()=>unlockBusy.value||inventoryBusy.value||fatigueBusy.value||renameBusy.value||rescueBusy.value)
function manageItem(item:any){if(inventoryPending.value||actionBusy.value){section.value='manage';return}inventorySelection.value={container:section.value==='backpack'?'inventory':section.value,slot:item.slot};inventoryVisited.value=true;section.value='manage'}
const unlockBusy=ref(false),unlockVisited=ref(false),unlockPending=ref(false)
const root=ref<HTMLElement|null>(null)
const data=ref<any>(null),loading=ref(false),error=ref(''),section=ref('basic'),search=ref(''),kind=ref(''),page=ref(1)
let generation=0
const tabGroups=[
 {label:'角色资料',tabs:[['basic','基本信息'],['attributes','属性存档']]},
 {label:'装备与仓储',tabs:[['equipment','穿戴装备'],['backpack','背包道具'],['warehouse','角色仓库'],['account_warehouse','账号仓库'],['unlock','装备解锁']]},
 {label:'维护与排查',tabs:[['manage','装备维护'],['fatigue','角色维护'],['rename','角色改名'],['rescue','位置救援'],['quests','任务排查']]},
 {label:'邮件与记录',tabs:[['mail','角色邮件'],['activity','管理记录']]}
]
const tabs=tabGroups.flatMap(group=>group.tabs)
const separatePanels=['manage','fatigue','rename','rescue','quests']
const navigationLocked=computed(()=>actionBusy.value||inventoryPending.value||fatiguePending.value||renamePending.value||rescuePending.value||unlockPending.value)
function shortcut(action:string){if(navigationLocked.value||!data.value?.account||data.value.character.delete_flag)return;emit('action',{action,uid:data.value.character.uid,charac_no:props.characNo})}
function mailDraft(value:any){if(!navigationLocked.value)emit('draft',value)}
function inspect(id:string){if(!navigationLocked.value)emit('inspect',id)}
function number(n:unknown){return n===null||n===undefined?'未知':Number(n).toLocaleString('zh-CN')}
function date(s:unknown){if(typeof s!=='string'||s.startsWith('0000-'))return '未记录';const d=new Date(s.replace(' ','T')+'Z');return Number.isNaN(d.getTime())?'未记录':d.toLocaleString('zh-CN',{hour12:false})}
async function load(){
 const current=++generation;loading.value=true;error.value='';data.value=null
 try{const result=await api('/characters/'+props.characNo);if(current===generation){data.value=result;page.value=1;inventoryStale.value=false}}
 catch(e){if(current===generation)error.value=uncertainMessage(e)}
 finally{if(current===generation)loading.value=false}
}
watch(()=>[props.characNo,props.initialSection],()=>{section.value=tabs.some(t=>t[0]===props.initialSection)?props.initialSection:'basic';search.value='';kind.value='';page.value=1;void load()},{immediate:true})
watch(()=>props.characNo,()=>{inventorySelection.value=null;inventoryPending.value=false;inventoryBusy.value=false})
onUnmounted(()=>generation++)
const container=computed(()=>data.value?.[section.value]??{state:'missing',items:[],slot_count:null,message:'未返回此容器记录，不能视为空仓库'})
const storageNotes:Record<string,string>={
 equipment:'普通穿戴槽，不含独立时装栏或宠物栏。',
 backpack:'仅本角色背包，不含仓库、时装栏、宠物栏或未领取邮件。',
 warehouse:'本角色独立仓库；不含账号共享仓库、换装栏或未领取邮件。',
 account_warehouse:'同一账号下角色共享的仓库；不与角色背包或角色金币合并。'
}
const items=computed(()=>container.value?.items??[])
const filtered=computed(()=>items.value.filter((i:any)=>(!kind.value||String(i.type)===kind.value)&&(!search.value.trim()||i.name.includes(search.value.trim())||String(i.id).includes(search.value.trim()))))
const pages=computed(()=>Math.max(1,Math.ceil(filtered.value.length/30)))
const visible=computed(()=>filtered.value.slice((page.value-1)*30,page.value*30))
const kinds=computed(()=>Array.from(new Map(items.value.map((i:any)=>[String(i.type),i.type_name])).entries()) as [string,string][])
watch([section,search,kind],()=>{page.value=1})
watch(section,async()=>{if(section.value==='unlock')unlockVisited.value=true;if(section.value==='manage')inventoryVisited.value=true;if(section.value==='fatigue')fatigueVisited.value=true;if(section.value==='rename')renameVisited.value=true;if(section.value==='rescue')rescueVisited.value=true;await nextTick();root.value?.closest('.modal-body')?.scrollTo?.({top:0})},{immediate:true})
function tabKey(e:KeyboardEvent){if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=tabs.findIndex(t=>t[0]===section.value),index=e.key==='Home'?0:e.key==='End'?tabs.length-1:(n+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tab(tabs[index][0]);void nextTick(()=>root.value?.querySelector<HTMLButtonElement>('#character-tab-'+section.value)?.focus())}
function tab(id:string){if(actionBusy.value)return;section.value=id;search.value='';kind.value=''}
</script>
<template>
 <Modal title="角色详情" :busy="actionBusy" @close="emit('close')">
  <div ref="root" class="character-detail" data-testid="character-detail">
   <div class="section-title character-toolbar"><span class="pill">角色详情 · #{{characNo}}</span><button :disabled="loading||actionBusy||unlockPending||inventoryPending||fatiguePending||renamePending||rescuePending||section==='unlock'||section==='manage'||section==='fatigue'||section==='rename'||section==='rescue'" @click="load">{{loading?'正在读取…':'刷新角色存档'}}</button></div>
   <p v-if="inventoryStale" class="notice" role="status">存档操作已提交；下方角色资料仍是旧快照。结束操作后切换到物品页，点击“刷新角色存档”。</p>
   <p v-if="loading" role="status" class="empty"><span class="spinner"/> 正在读取角色资料、装备、背包与仓库…</p>
   <div v-else-if="error" class="submit-error" role="alert"><b>无法读取角色详情</b><p>{{error}}</p><button @click="load">重试查询</button></div>
   <template v-else-if="data">
    <div class="character-identity"><GameImage :image="data.portrait" :label="data.profession.name" portrait/><div><h3>{{data.character.charac_name}}</h3><p>{{data.profession.name}} · Lv.{{data.character.lev}} · {{data.account?.accountname??'归属账号缺失'}} / UID {{data.character.uid}}</p></div><span class="status-badge" :class="data.character.delete_flag?'neutral':'success'">{{data.character.delete_flag?'已删除（仅查看存档）':'未删除'}}</span></div>
    <div class="button-row character-shortcuts" role="group" aria-label="当前角色快捷操作"><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('currency')">调整所属账号余额</button><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('mail')">给此角色发奖励</button><button :disabled="navigationLocked" @click="tab('unlock')">查看解锁申请</button><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('ban')">封禁所属账号</button><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('unban')">解除账号封禁</button></div>
    <p v-if="navigationLocked" class="field-hint">请先完成或查询当前维护／解锁操作，再使用快捷跳转。</p>
    <details class="character-guidance"><summary>存档说明与图片状态</summary>
    <p v-if="data.assets&&data.assets.state!=='ready'" class="field-hint">图片：{{data.assets.note}}；文字查询不受影响。</p><p class="field-hint snapshot-note">{{data.snapshot_note}}<br>读取时间：{{new Date(data.collected_at*1000).toLocaleString('zh-CN',{hour12:false})}}。资料、金币及物品为只读查询；装备解锁需在专页单独预览确认。</p>
    </details>
    <p v-if="data.account_online?.login_status===1" class="warning">所属账号在线；不代表当前角色在线。背包、仓库、金币和属性可能等待游戏进程保存，刷新网页不会强制保存。</p>
    <p v-if="data.catalog_state!=='ok'" class="submit-error" role="status">物品索引不可用或版本不匹配：仍显示存档编号，但物品名称、等级及职业名称可能未知。</p>
    <label class="character-mobile-section">查看内容<select :value="section" :disabled="actionBusy" aria-label="切换角色详情内容" @change="tab(($event.target as HTMLSelectElement).value)"><optgroup v-for="group in tabGroups" :key="group.label" :label="group.label"><option v-for="[id,label] in group.tabs" :key="id" :value="id">{{label}}</option></optgroup></select></label>
    <div class="detail-tabs" role="tablist" aria-label="角色详情分类" @keydown="tabKey"><div v-for="group in tabGroups" :key="group.label" class="detail-tab-group" role="presentation"><span class="detail-group-label" aria-hidden="true">{{group.label}}</span><button v-for="[id,label] in group.tabs" :id="'character-tab-'+id" :key="id" role="tab" :disabled="actionBusy" :aria-selected="section===id" :tabindex="section===id?0:-1" :aria-controls="'character-section-'+id" :class="{active:section===id}" @click="tab(id)">{{label}}<span v-if="id==='equipment'||id==='backpack'"> · {{data[id].state==='ok'?data[id].items.length:'未知'}}</span></button></div></div>
    <section v-show="!separatePanels.includes(section)" :id="separatePanels.includes(section)?undefined:'character-section-'+section" role="tabpanel" :aria-labelledby="'character-tab-'+section" tabindex="0">
     <UnlockRequests v-if="unlockVisited" v-show="section==='unlock'" :charac-no="characNo" @busy="unlockBusy=$event" @pending="unlockPending=$event" @reauth="emit('reauth')" @expired="emit('expired')"/>
     <MailCenter v-if="section==='mail'" :uid="data.character.uid" :charac-no="characNo" locked-target @draft="mailDraft"/>
     <CharacterActivity v-if="section==='activity'" :charac-no="characNo" :busy="navigationLocked" @inspect="inspect" @expired="emit('expired')"/>
     <template v-if="section==='basic'">
      <div class="character-metrics"><article><span>角色携带金币</span><strong>{{number(data.wealth.gold)}}</strong><small>{{data.wealth.state==='ok'?'不含仓库金币、点券或代币券':'金币存档缺失，不能视为0'}}</small></article><article><span>等级</span><strong>{{data.character.lev}}</strong><small>角色存档等级</small></article><article><span>复活币 coin 原始值</span><strong>{{number(data.wealth.revival_coin_raw)}}</strong><small>非多种复活币合计</small></article></div>
      <dl class="character-facts"><div><dt>角色名 / 编号</dt><dd>{{data.character.charac_name}} / #{{data.character.charac_no}}</dd></div><div><dt>所属账号</dt><dd>{{data.account?.accountname??'缺失'}} / UID {{data.character.uid}}</dd></div><div><dt>职业 / 转职</dt><dd>{{data.profession.base_name}} / {{data.profession.name}}<small>job={{data.character.job}}，grow_type={{data.character.grow_type}}；{{data.profession.note}}</small></dd></div><div><dt>账号登录状态 / 频道</dt><dd>{{data.account_online?.login_status===1?'在线':data.account_online?.login_status===0?'离线':'未知'}} / {{data.account_online?.channel??'未知'}}</dd></div><div><dt>经验存档</dt><dd>{{number(data.play_state?.exp??data.character.exp)}}<small>{{data.play_state?'来源：charac_stat':'来源：charac_info（无独立状态记录）'}}</small></dd></div><div><dt>疲劳存档 / 上限</dt><dd>{{number(data.play_state?.fatigue??data.character.fatigue)}} / {{number(data.character.max_fatigue)}}<small>不据此推算客户端剩余疲劳</small></dd></div><div><dt>已用疲劳存档</dt><dd>{{number(data.play_state?.used_fatigue)}}</dd></div><div><dt>公会编号</dt><dd>{{data.character.guild_id||'无公会'}}</dd></div><div><dt>创建时间</dt><dd>{{date(data.character.create_time)}}</dd></div><div><dt>最近游戏存档时间</dt><dd>{{date(data.play_state?.last_play_time??data.character.last_play_time)}}</dd></div></dl>
     </template>
     <template v-else-if="section==='attributes'">
      <p class="field-hint">下列是数据库字段原始存档值，不是游戏内最终面板。速度未擅自换算为百分比；力量、智力、体力、精神及元素抗性等未确认字段映射，暂不猜测显示。</p>
      <dl class="character-facts attribute-grid"><div v-for="a in data.attributes" :key="a.key"><dt>{{a.label}}<small>{{a.key}}</small></dt><dd>{{number(a.value)}}</dd></div></dl>
     </template>
     <template v-else-if="['unlock',...separatePanels,'mail','activity'].includes(section)"></template>
     <template v-else>
      <div v-if="section==='warehouse'||section==='account_warehouse'" class="warehouse-summary">
       <p class="field-hint">{{storageNotes[section]}}所属 UID：{{container.owner_uid??data.character.uid}}<span v-if="section==='warehouse'"> · 角色 #{{data.character.charac_no}}</span></p>
       <dl class="character-facts">
        <div v-if="section==='account_warehouse'"><dt>账号仓库金币</dt><dd>{{number(container.gold)}}<small>{{container.gold_state==='ok'?'独立存档，不包含角色携带金币':'无金币存档记录，不能视为0'}}</small></dd></div>
        <div><dt>仓库容量原始值</dt><dd>{{number(container.capacity_raw)}}<small>不据此推断实际已开放格数</small></dd></div>
        <div v-if="section==='account_warehouse'"><dt>仓库存档时间</dt><dd>{{date(container.stored_at)}}<small>不是在线实时保存时间保证</small></dd></div>
       </dl>
      </div>
      <div v-if="container.state!=='ok'" class="submit-error" role="status">{{container.message}}</div>
      <template v-else>
       <form class="toolbar" @submit.prevent><input v-model="search" aria-label="筛选角色物品" placeholder="当前容器内搜索名称或物品编号"><select v-model="kind" aria-label="角色物品类型"><option value="">全部类型</option><option v-for="[id,label] in kinds" :key="id" :value="id">{{label}}</option></select><button type="button" @click="search='';kind=''">清除筛选</button></form>
       <p class="field-hint">共 {{items.length}} 个非空槽位，筛选后 {{filtered.length}} 条；容器共 {{container.slot_count}} 个存档槽位（不代表已解锁格数）。{{storageNotes[section]}}物品可查看不代表可通过邮件发放。</p>
       <div class="button-row inventory-view-switch" role="group" aria-label="物品展示方式"><button type="button" :aria-pressed="!visual" @click="visual=false">列表视图</button><button type="button" :aria-pressed="visual" @click="visual=true">格子视图</button></div>
       <InventoryGrid v-if="visual" :items="filtered" :slot-count="container.slot_count" :equipment="section==='equipment'" :filtered="!!search.trim()||!!kind" manageable @manage="manageItem"/>
       <template v-else>
       <div v-if="visible.length" class="table-wrap character-items"><table><thead><tr><th>槽位</th><th>物品 / 编号</th><th>类型</th><th>数量</th><th>装备信息</th><th>维护</th></tr></thead><tbody><tr v-for="i in visible" :key="i.slot"><td>{{i.slot_label}}<small class="cell-note">#{{i.slot}}</small></td><td><GameImage :image="i.image" :label="i.name"/><b>{{i.name}}</b><small class="cell-note">#{{i.id}} · {{i.level===null?'等级未知':'Lv.'+i.level}}</small></td><td>{{i.type_name}}</td><td>{{number(i.quantity)}}</td><td v-if="i.enhancement!==null"><span>强化 +{{i.enhancement}} · 锻造 +{{i.forge}}</span><small class="cell-note">耐久 {{i.durability}} · 增幅类型 {{i.amplify_type}} / 数值 {{i.amplify_value}}</small><small class="cell-note">附魔 ID {{i.orb_id}} · 封装原始标记 {{i.sealed_raw}}</small></td><td v-else>—</td><td><button type="button" @click="manageItem(i)">维护此物品</button></td></tr></tbody></table></div>
       <div v-if="visible.length" class="inventory-mobile-cards"><article v-for="i in visible" :key="i.slot">
        <div class="section-title"><GameImage :image="i.image" :label="i.name"/><b>{{i.name}}</b><span class="pill">{{i.slot_label}} / #{{i.slot}}</span></div>
        <p class="field-hint">物品 #{{i.id}} · {{i.type_name}} · {{i.level===null?'等级未知':'Lv.'+i.level}}</p>
        <dl class="character-facts"><div><dt>数量</dt><dd>{{number(i.quantity)}}</dd></div><template v-if="i.enhancement!==null"><div><dt>强化 / 锻造</dt><dd>+{{i.enhancement}} / +{{i.forge}}</dd></div><div><dt>耐久</dt><dd>{{i.durability}}</dd></div><div><dt>增幅类型 / 数值</dt><dd>{{i.amplify_type}} / {{i.amplify_value}}</dd></div><div><dt>附魔 ID</dt><dd>{{i.orb_id}}</dd></div><div><dt>封装原始标记</dt><dd>{{i.sealed_raw}}</dd></div></template></dl>
       <button type="button" @click="manageItem(i)">维护此物品</button></article></div>
       <p v-else class="empty">{{items.length?'没有匹配的物品，请调整筛选条件。':'该容器存档没有非空物品。'}}</p>
       <div class="pagination"><button :disabled="page<=1" @click="page--">上一页物品</button><span>第 {{page}} / {{pages}} 页 · 每页30条</span><button :disabled="page>=pages" @click="page++">下一页物品</button></div>
       </template>
      </template>
     </template>
    </section>
   </template>
   <section v-if="renameVisited" v-show="section==='rename'" id="character-section-rename" role="tabpanel" aria-labelledby="character-tab-rename" tabindex="0"><CharacterRename :key="characNo" :charac-no="characNo" @busy="renameBusy=$event" @pending="renamePending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="section==='quests'" id="character-section-quests" role="tabpanel" aria-labelledby="character-tab-quests" tabindex="0"><CharacterQuests :key="characNo" :charac-no="characNo" @expired="emit('expired')"/></section>
   <section v-if="rescueVisited" v-show="section==='rescue'" id="character-section-rescue" role="tabpanel" aria-labelledby="character-tab-rescue" tabindex="0"><CharacterRescue :key="characNo" :charac-no="characNo" @busy="rescueBusy=$event" @pending="rescuePending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="fatigueVisited" v-show="section==='fatigue'" id="character-section-fatigue" role="tabpanel" aria-labelledby="character-tab-fatigue" tabindex="0"><CharacterMaintenance :key="characNo" :charac-no="characNo" @busy="fatigueBusy=$event" @pending="fatiguePending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="inventoryVisited" v-show="section==='manage'" id="character-section-manage" role="tabpanel" aria-labelledby="character-tab-manage" tabindex="0"><InventoryEditor :key="characNo" :charac-no="characNo" :selection="inventorySelection" @busy="inventoryBusy=$event" @pending="inventoryPending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
  </div>
  <template #footer><span class="muted">展示为存档快照 · 装备修改需要显式维护窗口与预览确认</span><button class="primary" :disabled="actionBusy" @click="emit('close')">关闭详情</button></template>
 </Modal>
</template>

<style scoped>
.detail-tabs{display:grid;grid-template-columns:.9fr 1.25fr 1.15fr 1fr;gap:12px;margin:16px 0 20px;padding:16px;background:var(--bg-primary);border:1px solid var(--border-color);border-radius:12px}.detail-tab-group{display:flex;flex-direction:column;gap:3px;min-width:0}.detail-group-label{font-size:11px;color:var(--text-secondary);padding:0 8px 8px;letter-spacing:.04em}.detail-tab-group button{text-align:left;background:transparent;border:1px solid transparent;padding:7px 9px;font-size:12px;white-space:normal}.detail-tab-group button.active{background:var(--bg-tertiary);border-color:var(--border-color);font-weight:600;color:var(--text-primary)}.detail-tab-group button:hover:not(:disabled){background:var(--bg-secondary)}.detail-tab-group button:focus-visible{outline:2px solid var(--primary-color);outline-offset:1px}

.character-mobile-section{display:none}.character-guidance{margin:12px 0}.character-guidance summary{cursor:pointer;color:var(--text-secondary)}@media(max-width:768px){.character-mobile-section{display:grid;gap:8px;margin:16px 0}.detail-tabs{display:none}.character-identity{display:grid;grid-template-columns:48px minmax(0,1fr);gap:8px 12px}.character-identity>:first-child{grid-row:1/3}.character-identity>.status-badge{grid-column:2;justify-self:start}.character-identity h3{font-size:20px}}
.character-shortcuts{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.character-shortcuts button{flex:1 1 150px}
</style>
