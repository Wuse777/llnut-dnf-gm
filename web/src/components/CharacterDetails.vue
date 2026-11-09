<script setup lang="ts">
import {ref,computed,watch,onMounted,onUnmounted,nextTick} from 'vue'
import {api,uncertainMessage} from '../api'
import Modal from './Modal.vue'
import {onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router'
const AppearanceWorkspace=asyncPanel(()=>import('./AppearanceWorkspace.vue'))
import {asyncPanel} from '../asyncPanel'
import GameImage from './GameImage.vue'
import InventoryGrid from './InventoryGrid.vue'
import CharacterOverview from './CharacterOverview.vue'
import {useRouter} from 'vue-router'
const router=useRouter()
const InventoryEditor=asyncPanel(()=>import('./InventoryEditor.vue'))
const CharacterMaintenance=asyncPanel(()=>import('./CharacterMaintenance.vue'))
const CharacterSkills=asyncPanel(()=>import('./CharacterSkills.vue'))
const CharacterRename=asyncPanel(()=>import('./CharacterRename.vue'))
const CharacterRescue=asyncPanel(()=>import('./CharacterRescue.vue'))
const CharacterQuests=asyncPanel(()=>import('./CharacterQuests.vue'))
const CharacterProgression=asyncPanel(()=>import('./CharacterProgression.vue'))
const CharacterLevels=asyncPanel(()=>import('./CharacterLevels.vue'))
const CharacterProfession=asyncPanel(()=>import('./CharacterProfession.vue'))
const professionBusy=ref(false),professionPending=ref(false),professionVisited=ref(false)
const levelsBusy=ref(false),levelsPending=ref(false),levelsVisited=ref(false),progressionRefresh=ref(0)
const questBusy=ref(false),questPending=ref(false),questVisited=ref(false)
const rescueBusy=ref(false),rescuePending=ref(false),rescueVisited=ref(false)
const renameBusy=ref(false),renamePending=ref(false),renameVisited=ref(false)
const MailCenter=asyncPanel(()=>import('./MailCenter.vue'))
const CharacterActivity=asyncPanel(()=>import('./CharacterActivity.vue'))
const fatigueBusy=ref(false),fatiguePending=ref(false),fatigueVisited=ref(false)
const skillsBusy=ref(false),skillsPending=ref(false),skillsVisited=ref(false)
const visual=ref(true),equipmentLayout=ref(true),moreOpen=ref(false)
const UnlockRequests=asyncPanel(()=>import('./UnlockRequests.vue'))
const props=withDefaults(defineProps<{characNo:number,initialSection?:string,embedded?:boolean}>(),{initialSection:'basic'})
const emit=defineEmits<{close:[],reauth:[],expired:[],visited:[value:{uid:number,charac_no:number}],action:[value:{action:string,uid:number,charac_no:number}],draft:[value:any],inspect:[id:string],loaded:[value:any]}>()
const inventoryPending=ref(false),inventoryStale=ref(false)
const inventoryBusy=ref(false),inventoryVisited=ref(false),inventorySelection=ref<{container:string,slot:number}|null>(null)
const actionBusy=computed(()=>unlockBusy.value||inventoryBusy.value||levelsBusy.value||professionBusy.value||skillsBusy.value||fatigueBusy.value||renameBusy.value||rescueBusy.value||questBusy.value)
function manageItem(item:any){if(inventoryPending.value||actionBusy.value){section.value='manage';return}inventorySelection.value={container:section.value==='backpack'?'inventory':section.value,slot:item.slot};inventoryVisited.value=true;section.value='manage'}
const unlockBusy=ref(false),unlockVisited=ref(false),unlockPending=ref(false)
const root=ref<HTMLElement|null>(null),identity=ref<HTMLElement|null>(null)
let releaseIdentity=()=>{}
watch(identity,node=>{
 releaseIdentity();releaseIdentity=()=>{}
 const body=root.value?.closest<HTMLElement>('.modal-body')
 if(!node||!body)return
 const previous=body.style.scrollPaddingTop
 const update=()=>{body.style.scrollPaddingTop=`${Math.ceil(node.getBoundingClientRect().height)+(parseFloat(getComputedStyle(body).paddingTop)||0)+12}px`}
 update();const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(update):null;observer?.observe(node)
 releaseIdentity=()=>{observer?.disconnect();body.style.scrollPaddingTop=previous}
},{flush:'post'})
onUnmounted(()=>releaseIdentity())
const data=ref<any>(null),loading=ref(false),error=ref(''),section=ref('basic'),search=ref(''),kind=ref(''),page=ref(1)
const detailLoading=ref(false),detailError=ref(''),fullDetailLoaded=ref(false)
const detailedSections=['facts','attributes','appearance','equipment','backpack','warehouse','account_warehouse']
const portraitAttribution=computed(()=>{
 const image=data.value?.portrait;if(image?.state!=='ready')return ''
 const source=image.source_label||({client:'客户端职业图',official_promotional:'官方职业插画',custom:'维护者示意图'} as Record<string,string>)[image.source_kind]||'职业插画'
 const match=({base:'基础职业示意',profession:'同转职示意（觉醒未匹配）',growth:'精确转职映射'} as Record<string,string>)[image.match_level]||'映射范围待核验'
 return source+' · '+match+' · 非角色实际外观'
})
const basicPreviewExpanded=ref(typeof window.matchMedia!=='function'||!window.matchMedia('(max-width: 768px)').matches)
let basicPreviewMedia:MediaQueryList|null=null
function syncBasicPreview(){if(basicPreviewMedia)basicPreviewExpanded.value=!basicPreviewMedia.matches}
onMounted(()=>{
 if(typeof window.matchMedia!=='function')return
 basicPreviewMedia=window.matchMedia('(max-width: 768px)')
 basicPreviewMedia.addEventListener('change',syncBasicPreview)
})
onUnmounted(()=>basicPreviewMedia?.removeEventListener('change',syncBasicPreview))
const failedBasicImages=ref<string[]>([])
const basicPreview=computed(()=>{
 const usable=(image:any,source?:string)=>image?.state==='ready'&&(!source||image.source_kind===source)&&
  /^\/dnf-gm\/api\/v1\/assets\/[a-f0-9]{64}\/[a-f0-9]{64}\.png$/.test(image.url??'')&&!failedBasicImages.value.includes(image.url)
 const outfit=data.value?.outfit_preview
 if(usable(outfit,'saved_avatar_outfit')&&outfit.pose==='waiting_first_frame')return {image:outfit,kind:'outfit',label:'服装存档首帧',note:'服装存档 · 非实时外观；不含武器、染色或变身效果。'}
 const pose=data.value?.job_preview
 if(usable(pose,'client_default_pose'))return {image:pose,kind:'default',label:'基础职业默认站姿',note:'客户端职业首帧 · 默认示意；不代表当前穿戴、转职或觉醒形态。'}
 const portrait=data.value?.portrait
 if(usable(portrait))return {image:portrait,kind:'portrait',label:'职业插画示意',note:portraitAttribution.value}
 return null
})
watch(()=>[props.characNo,data.value?.outfit_preview?.url,data.value?.job_preview?.url,data.value?.portrait?.url],()=>{failedBasicImages.value=[]})
function failBasicPreview(){if(basicPreview.value)failedBasicImages.value=[...failedBasicImages.value,basicPreview.value.image.url]}
let generation=0
const tabGroups=[
 {label:'角色资料',tabs:[['basic','角色工作台'],['facts','详细资料'],['attributes','属性存档'],['appearance','角色外观']]},
 {label:'装备与仓储',tabs:[['equipment','穿戴装备'],['backpack','背包道具'],['warehouse','角色仓库'],['account_warehouse','账号仓库'],['unlock','装备解锁']]},
 {label:'维护与排查',tabs:[['manage','装备维护'],['fatigue','疲劳调整'],['skills','技能与SP／TP'],['profession','转职与觉醒'],['rename','角色改名'],['rescue','位置救援'],['quests','任务检索与修复'],['progression','等级与经验']]},
 {label:'邮件与记录',tabs:[['mail','角色邮件'],['activity','管理记录']]}
]
const tabs=tabGroups.flatMap(group=>group.tabs)
const activeGroup=computed(()=>tabGroups.find(group=>group.tabs.some(([id])=>id===section.value))?.label??tabGroups[0].label)
const recentGroupSections=ref<Record<string,string>>({})
function groupTab(label:string){const group=tabGroups.find(group=>group.label===label);if(group)tab(recentGroupSections.value[label]||group.tabs[0][0])}
const separatePanels=['manage','fatigue','skills','rename','rescue','quests','progression','profession']
const navigationLocked=computed(()=>actionBusy.value||inventoryPending.value||levelsPending.value||professionPending.value||skillsPending.value||fatiguePending.value||renamePending.value||rescuePending.value||questPending.value||unlockPending.value)
function shortcut(action:string){if(navigationLocked.value||!data.value?.account||data.value.character.delete_flag)return;moreOpen.value=false;emit('action',{action,uid:data.value.character.uid,charac_no:props.characNo})}
function mailDraft(value:any){if(!navigationLocked.value)emit('draft',value)}
function inspect(id:string){if(!navigationLocked.value)emit('inspect',id)}
function number(n:unknown){return n===null||n===undefined?'未知':Number(n).toLocaleString('zh-CN')}
function date(s:unknown){if(typeof s!=='string'||s.startsWith('0000-'))return '未记录';const d=new Date(s.replace(' ','T')+'Z');return Number.isNaN(d.getTime())?'未记录':d.toLocaleString('zh-CN',{hour12:false})}
function openSupport(value:{uid:number,case_id?:string}){if(!navigationLocked.value)void router?.push({path:'/players/support',query:{uid:String(value.uid),case_id:value.case_id}})}
async function ensureDetail(){
 if(!data.value||fullDetailLoaded.value||detailLoading.value)return
 const current=generation;detailLoading.value=true;detailError.value=''
 try{const result=await api('/characters/'+props.characNo);if(current===generation){data.value={...data.value,...result};fullDetailLoaded.value=true;emit('loaded',data.value)}}
 catch(e){if(current===generation)detailError.value=uncertainMessage(e)}
 finally{if(current===generation)detailLoading.value=false}
}
async function load(){
 const current=++generation;loading.value=true;error.value='';data.value=null;fullDetailLoaded.value=false;detailLoading.value=false;detailError.value=''
 try{const result=await api('/characters/'+props.characNo+'/overview');if(current===generation){data.value=result;fullDetailLoaded.value=!!result.backpack;emit('loaded',result);if(result.account&&!result.character.delete_flag)emit('visited',{uid:result.character.uid,charac_no:props.characNo});page.value=1;inventoryStale.value=false;if(detailedSections.includes(section.value))await ensureDetail()}}
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
watch(section,async()=>{recentGroupSections.value[activeGroup.value]=section.value;if(detailedSections.includes(section.value))void ensureDetail();if(section.value==='unlock')unlockVisited.value=true;if(section.value==='manage')inventoryVisited.value=true;if(section.value==='fatigue')fatigueVisited.value=true;if(section.value==='skills')skillsVisited.value=true;if(section.value==='progression')levelsVisited.value=true;if(section.value==='profession')professionVisited.value=true;if(section.value==='rename')renameVisited.value=true;if(section.value==='quests')questVisited.value=true;if(section.value==='rescue')rescueVisited.value=true;await nextTick();root.value?.closest('.modal-body')?.scrollTo?.({top:0})},{immediate:true})
function tabKey(e:KeyboardEvent){if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=tabs.findIndex(t=>t[0]===section.value),index=e.key==='Home'?0:e.key==='End'?tabs.length-1:(n+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tab(tabs[index][0]);void nextTick(()=>root.value?.querySelector<HTMLButtonElement>('#character-tab-'+section.value)?.focus())}
function tab(id:string){if(actionBusy.value)return;section.value=id;search.value='';kind.value=''}
onBeforeRouteLeave(()=>!props.embedded||!navigationLocked.value)
onBeforeRouteUpdate(()=>!props.embedded||!navigationLocked.value)
</script>
<template>
 <component :is="embedded?'section':Modal" :class="{'embedded-character':embedded}" title="角色详情" :busy="actionBusy" @close="emit('close')">
  <div ref="root" class="character-detail" data-testid="character-detail">
   <div class="section-title character-toolbar"><span class="pill">角色详情 · #{{characNo}}</span><button :disabled="loading||navigationLocked||['unlock','manage','fatigue','skills','rename','rescue','quests','profession','progression'].includes(section)" @click="load">{{loading?'正在读取…':'刷新角色存档'}}</button></div>
   <p v-if="inventoryStale" class="notice" role="status">存档操作已提交；下方角色资料仍是旧快照。结束操作后切换到物品页，点击“刷新角色存档”。</p>
   <p v-if="loading" role="status" class="empty"><span class="spinner"/> 正在读取角色工作台…</p>
   <div v-else-if="error" class="submit-error" role="alert"><b>无法读取角色详情</b><p>{{error}}</p><button @click="load">重试查询</button></div>
   <template v-else-if="data">
    <div ref="identity" class="character-identity sticky-character-identity"><GameImage :image="data.portrait" :label="data.profession.name" portrait/><div class="character-identity-main"><h3>{{data.character.charac_name}}</h3><p>{{data.profession.name}} · Lv.{{data.character.lev}} · {{data.account?.accountname??'归属账号缺失'}} / UID {{data.character.uid}}</p><small v-if="portraitAttribution" class="portrait-attribution">{{portraitAttribution}} <a v-if="data.portrait.source_page" :href="data.portrait.source_page" target="_blank" rel="noopener noreferrer">素材出处 ↗</a></small></div><div class="character-status" role="group" aria-label="角色状态"><span class="status-badge">登录表：{{data.account_online?.login_status===1?'在线':data.account_online?.login_status===0?'离线':'未知'}}</span><span class="status-badge" :class="data.character.delete_flag?'neutral':'success'">{{data.character.delete_flag?'已删除（仅查看存档）':'未删除'}}</span></div></div>
    <div class="character-shortcuts" role="group" aria-label="当前角色快捷操作"><div class="character-primary-actions"><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('currency')">调整所属账号余额</button><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('mail')">给此角色发奖励</button></div>
     <details class="character-more" :open="moreOpen" @toggle="moreOpen=($event.target as HTMLDetailsElement).open"><summary>更多操作 <span>解锁／账号封禁</span></summary><div class="button-row"><button :disabled="navigationLocked" @click="tab('unlock');moreOpen=false">查看解锁申请</button><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('ban')">封禁所属账号</button><button :disabled="navigationLocked||!data.account||!!data.character.delete_flag" @click="shortcut('unban')">解除账号封禁</button></div></details>
    </div>
    <p v-if="navigationLocked" class="field-hint">请先完成或查询当前维护／解锁操作，再使用快捷跳转。</p>
    <details class="character-guidance"><summary>存档说明与图片状态</summary>
    <p v-if="data.assets&&data.assets.state!=='ready'" class="field-hint">图片：{{data.assets.note}}；文字查询不受影响。</p><p class="field-hint">背包、仓库、金币和属性可能等待游戏进程保存；刷新网页不会强制保存，查询结果不等于实时战斗面板。</p><p class="field-hint snapshot-note">{{data.snapshot_note}}<br>读取时间：{{new Date(data.collected_at*1000).toLocaleString('zh-CN',{hour12:false})}}。资料、金币及物品为只读查询；装备解锁需在专页单独预览确认。</p>
    </details>
    <p v-if="data.account_online?.login_status===1" class="warning">所属账号在线；不代表当前角色在线。存档可能未更新，详见存档说明。</p>
    <p v-if="data.catalog_state!=='ok'" class="submit-error" role="status">物品索引不可用或版本不匹配：仍显示存档编号，但物品名称、等级及职业名称可能未知。</p>
    <label class="character-mobile-section">查看内容<select :value="section" :disabled="actionBusy" aria-label="切换角色详情内容" @change="tab(($event.target as HTMLSelectElement).value)"><optgroup v-for="group in tabGroups" :key="group.label" :label="group.label"><option v-for="[id,label] in group.tabs" :key="id" :value="id">{{label}}</option></optgroup></select></label>
    <div class="detail-navigation">
     <div class="detail-categories" role="group" aria-label="角色详情分组"><button v-for="group in tabGroups" :key="group.label" :disabled="actionBusy" :aria-pressed="activeGroup===group.label" :class="{'selected-group':activeGroup===group.label}" @click="groupTab(group.label)">{{group.label}}<small>{{group.tabs.length}} 项</small></button></div>
     <div class="detail-tabs" role="tablist" aria-label="角色详情分类" @keydown="tabKey"><div v-for="group in tabGroups" v-show="activeGroup===group.label" :key="group.label" class="detail-tab-group" role="presentation"><button v-for="[id,label] in group.tabs" :id="'character-tab-'+id" :key="id" role="tab" :disabled="actionBusy" :aria-selected="section===id" :tabindex="section===id?0:-1" :aria-controls="'character-section-'+id" :class="{active:section===id}" @click="tab(id)">{{label}}<span v-if="id==='equipment'||id==='backpack'"> · {{id==='backpack'&&data.backpack_summary?data.backpack_summary.occupied_slots:data[id]?.state==='ok'?data[id].items.length:'未知'}}</span></button></div></div>
    </div>
    <p v-if="detailLoading&&detailedSections.includes(section)" role="status" class="field-hint">正在按需读取此页的完整存档…</p><p v-if="detailError&&detailedSections.includes(section)" role="alert" class="submit-error">{{detailError}} <button type="button" @click="ensureDetail">重试读取详情</button></p>
    <section v-show="!separatePanels.includes(section)&&!(detailedSections.includes(section)&&(detailLoading||detailError))" :id="separatePanels.includes(section)?undefined:'character-section-'+section" role="tabpanel" :aria-labelledby="'character-tab-'+section" tabindex="0">
     <UnlockRequests v-if="unlockVisited" v-show="section==='unlock'" :charac-no="characNo" @busy="unlockBusy=$event" @pending="unlockPending=$event" @reauth="emit('reauth')" @expired="emit('expired')"/>
     <MailCenter v-if="section==='mail'" :uid="data.character.uid" :charac-no="characNo" locked-target @draft="mailDraft"/>
     <CharacterActivity v-if="section==='activity'" :charac-no="characNo" :busy="navigationLocked" @inspect="inspect" @expired="emit('expired')"/>
     <AppearanceWorkspace v-if="section==='appearance'" :detail="data"/>
     <CharacterOverview v-if="section==='basic'" :detail="data" :locked="navigationLocked" @section="tab" @support="openSupport"/>
     <template v-if="section==='facts'">
      <div class="character-basic-layout">
       <details class="character-basic-visual" :open="basicPreviewExpanded" @toggle="basicPreviewExpanded=($event.target as HTMLDetailsElement).open">
        <summary><span>人物预览</span><small>{{basicPreview?.label||'素材暂不可用'}}</small></summary>
        <div v-if="basicPreviewExpanded" class="character-basic-visual-body">
         <figure class="character-basic-figure">
          <div class="character-basic-stage" :class="{'is-portrait':basicPreview?.kind==='portrait'}">
           <img v-if="basicPreview" :src="basicPreview.image.url" :alt="basicPreview.label" loading="lazy" decoding="async" @error="failBasicPreview">
           <div v-else class="character-basic-placeholder"><svg viewBox="0 0 120 200" fill="none" aria-hidden="true"><circle cx="60" cy="29" r="18"/><path d="M39 59L22 113L36 120L47 91L43 139L35 188H52L60 145L68 188H85L77 139L73 91L84 120L98 113L81 59Z"/></svg><span>暂无可用人物图片</span></div>
          </div>
          <figcaption><span class="status-badge">{{basicPreview?.label||'缺少预览素材'}}</span><strong>{{data.profession.name}}</strong><p>{{basicPreview?.note||'未返回可用服装首帧、默认站姿或职业插画，文字资料仍可查看。'}}</p><p v-if="basicPreview?.image.note" class="character-basic-image-note">{{basicPreview.image.note}}</p><a v-if="basicPreview?.kind==='portrait'&&data.portrait.source_page" :href="data.portrait.source_page" target="_blank" rel="noopener noreferrer">素材出处 ↗</a></figcaption>
         </figure>
         <div class="character-basic-preview-actions"><button type="button" :disabled="navigationLocked" @click="tab('appearance')">查看外观详情</button><button type="button" :disabled="navigationLocked" @click="tab('equipment')">穿戴装备</button></div>
        </div>
       </details>
       <div class="character-basic-data">
      <div class="character-metrics"><article><span>角色携带金币</span><strong>{{number(data.wealth.gold)}}</strong><small>{{data.wealth.state==='ok'?'不含仓库金币、点券或代币券':'金币存档缺失，不能视为0'}}</small></article><article><span>等级</span><strong>{{data.character.lev}}</strong><small>角色存档等级</small></article><article><span>复活币 coin 原始值</span><strong>{{number(data.wealth.revival_coin_raw)}}</strong><small>非多种复活币合计</small></article></div>
      <dl class="character-facts"><div><dt>角色名 / 编号</dt><dd>{{data.character.charac_name}} / #{{data.character.charac_no}}</dd></div><div><dt>所属账号</dt><dd>{{data.account?.accountname??'缺失'}} / UID {{data.character.uid}}</dd></div><div><dt>职业 / 转职</dt><dd>{{data.profession.base_name}} / {{data.profession.name}}<small>job={{data.character.job}}，grow_type={{data.character.grow_type}}；{{data.profession.note}}</small></dd></div><div><dt>账号登录状态 / 频道</dt><dd>{{data.account_online?.login_status===1?'在线':data.account_online?.login_status===0?'离线':'未知'}} / {{data.account_online?.channel??'未知'}}</dd></div><div><dt>经验存档</dt><dd>{{number(data.play_state?.exp??data.character.exp)}}<small>{{data.play_state?'来源：charac_stat':'来源：charac_info（无独立状态记录）'}}</small></dd></div><div><dt>疲劳存档 / 上限</dt><dd>{{number(data.play_state?.fatigue??data.character.fatigue)}} / {{number(data.character.max_fatigue)}}<small>不据此推算客户端剩余疲劳</small></dd></div><div><dt>已用疲劳存档</dt><dd>{{number(data.play_state?.used_fatigue)}}</dd></div><div><dt>公会编号</dt><dd>{{data.character.guild_id||'无公会'}}</dd></div><div><dt>创建时间</dt><dd>{{date(data.character.create_time)}}</dd></div><div><dt>最近游戏存档时间</dt><dd>{{date(data.play_state?.last_play_time??data.character.last_play_time)}}</dd></div></dl>
       </div>
      </div>
     </template>
     <template v-else-if="section==='attributes'">
      <p class="field-hint">下列是数据库字段原始存档值，不是游戏内最终面板。速度未擅自换算为百分比；力量、智力、体力、精神及元素抗性等未确认字段映射，暂不猜测显示。</p>
      <dl class="character-facts attribute-grid"><div v-for="a in data.attributes" :key="a.key"><dt>{{a.label}}<small>{{a.key}}</small></dt><dd>{{number(a.value)}}</dd></div></dl>
     </template>
     <template v-else-if="['basic','unlock',...separatePanels,'mail','activity','appearance'].includes(section)"></template>
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
       <div class="button-row inventory-view-switch" role="group" aria-label="物品展示方式"><button v-if="section==='equipment'" type="button" :aria-pressed="visual&&equipmentLayout" @click="visual=true;equipmentLayout=true">装备槽位图</button><button type="button" :aria-pressed="visual&&(section!=='equipment'||!equipmentLayout)" @click="visual=true;equipmentLayout=false">格子视图</button><button type="button" :aria-pressed="!visual" @click="visual=false">列表视图</button></div>
       <InventoryGrid v-if="visual" :items="filtered" :slot-count="container.slot_count" :equipment="section==='equipment'" :anatomy="section==='equipment'&&equipmentLayout" :job-preview="section==='equipment'?data.job_preview:null" :outfit-preview="section==='equipment'?data.outfit_preview:null" :filtered="!!search.trim()||!!kind" manageable @manage="manageItem"/>
       <template v-else>
       <div v-if="visible.length" class="table-wrap character-items"><table><thead><tr><th>槽位</th><th>物品 / 编号</th><th>类型</th><th>数量</th><th>装备信息</th><th>维护</th></tr></thead><tbody><tr v-for="i in visible" :key="i.slot"><td>{{i.slot_label}}<small class="cell-note">#{{i.slot}}</small></td><td><GameImage :image="i.image" :label="i.name" :rarity-name="i.rarity_name" :rarity="i.rarity"/><b>{{i.name}}</b><small class="cell-note">#{{i.id}} · {{i.level===null?'等级未知':'Lv.'+i.level}}</small></td><td>{{i.type_name}}</td><td>{{number(i.quantity)}}</td><td v-if="i.enhancement!==null"><span>强化 +{{i.enhancement}} · 锻造 +{{i.forge}}</span><small class="cell-note">耐久 {{i.durability}} · 增幅类型 {{i.amplify_type}} / 数值 {{i.amplify_value}}</small><small class="cell-note" :title="i.enchantment?.summary">{{i.enchantment?.name||'附魔 #'+i.orb_id}}<template v-if="i.orb_id"> · #{{i.orb_id}}</template> · 封装原始标记 {{i.sealed_raw}}</small></td><td v-else>—</td><td><button type="button" @click="manageItem(i)">维护此物品</button></td></tr></tbody></table></div>
       <div v-if="visible.length" class="inventory-mobile-cards"><article v-for="i in visible" :key="i.slot">
        <div class="section-title"><GameImage :image="i.image" :label="i.name" :rarity-name="i.rarity_name" :rarity="i.rarity"/><b>{{i.name}}</b><span class="pill">{{i.slot_label}} / #{{i.slot}}</span></div>
        <p class="field-hint">物品 #{{i.id}} · {{i.type_name}} · {{i.level===null?'等级未知':'Lv.'+i.level}}</p>
        <dl class="character-facts"><div><dt>数量</dt><dd>{{number(i.quantity)}}</dd></div><template v-if="i.enhancement!==null"><div><dt>强化 / 锻造</dt><dd>+{{i.enhancement}} / +{{i.forge}}</dd></div><div><dt>耐久</dt><dd>{{i.durability}}</dd></div><div><dt>增幅类型 / 数值</dt><dd>{{i.amplify_type}} / {{i.amplify_value}}</dd></div><div><dt>附魔</dt><dd>{{i.enchantment?.name||i.orb_id}}<small v-if="i.orb_id">#{{i.orb_id}}</small><small v-if="i.enchantment?.summary">{{i.enchantment.summary}}</small></dd></div><div><dt>封装原始标记</dt><dd>{{i.sealed_raw}}</dd></div></template></dl>
       <button type="button" @click="manageItem(i)">维护此物品</button></article></div>
       <p v-else class="empty">{{items.length?'没有匹配的物品，请调整筛选条件。':'该容器存档没有非空物品。'}}</p>
       <div class="pagination"><button :disabled="page<=1" @click="page--">上一页物品</button><span>第 {{page}} / {{pages}} 页 · 每页30条</span><button :disabled="page>=pages" @click="page++">下一页物品</button></div>
       </template>
      </template>
     </template>
    </section>
   </template>
   <section v-if="renameVisited" v-show="section==='rename'" id="character-section-rename" role="tabpanel" aria-labelledby="character-tab-rename" tabindex="0"><CharacterRename :key="characNo" :charac-no="characNo" @busy="renameBusy=$event" @pending="renamePending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="levelsVisited" v-show="section==='progression'" id="character-section-progression" role="tabpanel" aria-labelledby="character-tab-progression" tabindex="0"><CharacterProgression :key="characNo+'-'+progressionRefresh" :charac-no="characNo" @expired="emit('expired')"/><CharacterLevels :key="characNo" :charac-no="characNo" @busy="levelsBusy=$event" @pending="levelsPending=$event" @changed="inventoryStale=true;progressionRefresh++" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="questVisited" v-show="section==='quests'" id="character-section-quests" role="tabpanel" aria-labelledby="character-tab-quests" tabindex="0"><CharacterQuests :key="characNo" :charac-no="characNo" @busy="questBusy=$event" @pending="questPending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="rescueVisited" v-show="section==='rescue'" id="character-section-rescue" role="tabpanel" aria-labelledby="character-tab-rescue" tabindex="0"><CharacterRescue :key="characNo" :charac-no="characNo" @busy="rescueBusy=$event" @pending="rescuePending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="professionVisited" v-show="section==='profession'" id="character-section-profession" role="tabpanel" aria-labelledby="character-tab-profession" tabindex="0"><CharacterProfession :key="characNo" :charac-no="characNo" @busy="professionBusy=$event" @pending="professionPending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="skillsVisited" v-show="section==='skills'" id="character-section-skills" role="tabpanel" aria-labelledby="character-tab-skills" tabindex="0"><CharacterSkills :key="characNo" :charac-no="characNo" @busy="skillsBusy=$event" @pending="skillsPending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="fatigueVisited" v-show="section==='fatigue'" id="character-section-fatigue" role="tabpanel" aria-labelledby="character-tab-fatigue" tabindex="0"><CharacterMaintenance :key="characNo" :charac-no="characNo" @busy="fatigueBusy=$event" @pending="fatiguePending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
   <section v-if="inventoryVisited" v-show="section==='manage'" id="character-section-manage" role="tabpanel" aria-labelledby="character-tab-manage" tabindex="0"><InventoryEditor :key="characNo" :charac-no="characNo" :selection="inventorySelection" @busy="inventoryBusy=$event" @pending="inventoryPending=$event" @changed="inventoryStale=true" @reauth="emit('reauth')" @expired="emit('expired')"/></section>
  </div>
  <template v-if="!embedded" #footer><span class="muted">展示为存档快照 · 装备修改需要显式维护窗口与预览确认</span><button class="primary" :disabled="actionBusy" @click="emit('close')">关闭详情</button></template>
 </component>
</template>

<style scoped>
.character-basic-layout{display:grid;grid-template-columns:240px minmax(0,1fr);align-items:start;gap:24px;min-width:0}
.character-basic-visual{min-width:0;margin:0;padding:0;border:1px solid var(--border-color);border-radius:14px;background:var(--bg-primary);overflow:hidden}
.character-basic-visual>summary{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 8px;list-style:none;margin:0;padding:14px 16px;cursor:pointer;font-size:13px;font-weight:600;color:var(--text-primary)}
.character-basic-visual>summary::-webkit-details-marker{display:none}
.character-basic-visual>summary small{grid-column:1;font-size:11px;font-weight:400;overflow-wrap:anywhere;color:var(--text-secondary)}
.character-basic-visual>summary:after{content:'＋';grid-column:2;grid-row:1/3;align-self:center;color:var(--text-secondary);font-size:18px;font-weight:400}
.character-basic-visual[open]>summary{border-bottom:1px solid var(--border-color)}
.character-basic-visual[open]>summary:after{content:'−'}
.character-basic-visual>summary:focus-visible{outline:2px solid var(--primary-color);outline-offset:-3px}
.character-basic-visual-body{padding:14px}
.character-basic-figure{min-width:0;margin:0;text-align:center}
.character-basic-stage{height:240px;display:flex;align-items:center;justify-content:center;overflow:hidden;border-radius:10px;background:radial-gradient(ellipse at 50% 70%,var(--bg-tertiary),var(--bg-secondary) 75%)}
.character-basic-stage>img{width:100%;height:100%;object-fit:contain;image-rendering:pixelated}
.character-basic-stage.is-portrait>img{object-fit:cover;object-position:center 22%;image-rendering:auto}
.character-basic-placeholder{display:flex;flex-direction:column;align-items:center;gap:12px;font-size:12px;color:var(--text-secondary)}
.character-basic-placeholder svg{width:96px;height:160px;stroke:var(--border-primary);stroke-width:1.5;fill:var(--bg-primary)}
.character-basic-figure figcaption{padding-top:14px;overflow-wrap:anywhere}
.character-basic-figure figcaption>strong{display:block;margin-top:10px;font-size:15px}
.character-basic-figure figcaption>p{margin:8px 0 0;font-size:11px;line-height:1.7;color:var(--text-secondary)}
.character-basic-figure figcaption>a{display:inline-block;margin-top:8px;font-size:11px}
.character-basic-preview-actions{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:8px;margin-top:16px}
.character-basic-preview-actions>button{min-width:0;padding:8px 5px;font-size:11px}
.character-basic-data{min-width:0}
.character-basic-data .character-metrics{margin:0 0 16px;gap:10px}
.character-basic-data .character-metrics article{min-width:0;padding:14px}
.character-basic-data .character-metrics strong{font-size:24px;overflow-wrap:anywhere}
.character-basic-data .character-facts{gap:0 20px}
@media(max-width:1000px){.character-basic-layout{grid-template-columns:220px minmax(0,1fr);gap:18px}.character-basic-data .character-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.character-basic-data .character-metrics article:first-child{grid-column:1/-1}}
@media(max-width:768px){.character-basic-layout{grid-template-columns:minmax(0,1fr);gap:16px}.character-basic-visual>summary{grid-template-columns:minmax(0,1fr) auto;padding:11px 14px}.character-basic-visual>summary small{font-size:10px}.character-basic-stage{height:220px;max-width:250px;margin-inline:auto}.character-basic-visual-body{padding:12px}.character-basic-figure figcaption{padding-top:10px}.character-basic-preview-actions{max-width:300px;margin:12px auto 0}.character-basic-data .character-metrics{gap:8px;margin-bottom:12px}.character-basic-data .character-metrics article{padding:12px;gap:5px}.character-basic-data .character-metrics strong{font-size:22px}}
.character-identity-main{flex:1;min-width:0}.character-status{display:flex;flex-wrap:wrap;justify-content:flex-end;align-items:center;gap:8px;flex:0 1 auto}
.portrait-attribution{display:block;font-size:10px;color:var(--text-secondary);margin-top:5px}
.sticky-character-identity{position:sticky;top:-1px;z-index:3;background:var(--bg-primary);padding:12px;border-bottom:1px solid var(--border-color);box-shadow:0 6px 12px #00000008}

.detail-navigation{margin:16px 0 22px;border:1px solid var(--border-color);border-radius:12px;overflow:hidden;background:var(--bg-secondary)}
.detail-categories{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;padding:6px;background:var(--bg-primary);border-bottom:1px solid var(--border-color)}
.detail-categories button{display:flex;align-items:center;justify-content:center;gap:8px;padding:11px 8px;background:transparent;border:1px solid transparent;color:var(--text-secondary);font-size:12px;border-radius:8px;min-width:0}
.detail-categories small{font-size:10px;opacity:.75;white-space:nowrap}.detail-categories button.selected-group{background:var(--bg-secondary);border-color:var(--border-color);box-shadow:0 1px 3px #00000006;color:var(--text-primary);font-weight:600}
.detail-tabs{display:block;margin:0;padding:10px 12px;background:transparent;border:0;border-radius:0}.detail-tab-group{display:flex;align-items:center;flex-wrap:wrap;gap:6px;min-width:0}.detail-tab-group button{position:relative;text-align:left;background:transparent;border:1px solid transparent;padding:8px 11px;font-size:12px;white-space:normal;color:var(--text-secondary);border-radius:7px}.detail-tab-group button.active{background:var(--bg-tertiary);border-color:var(--border-color);font-weight:600;color:var(--text-primary)}.detail-tab-group button:hover:not(:disabled),.detail-categories button:hover:not(:disabled){background:var(--bg-hover)}.detail-tab-group button:focus-visible,.detail-categories button:focus-visible{outline:2px solid var(--primary-color);outline-offset:-2px}

.character-mobile-section{display:none}.character-guidance{margin:12px 0}.character-guidance summary{cursor:pointer;color:var(--text-secondary)}@media(max-width:768px){.character-mobile-section{display:grid;gap:8px;margin:16px 0}.detail-navigation{display:none}.character-identity{display:grid;grid-template-columns:48px minmax(0,1fr);gap:8px 12px}.character-identity>:first-child{grid-row:1/3}.character-identity>.character-status{grid-column:2;justify-self:start;justify-content:flex-start}.character-identity h3{font-size:20px}}
.character-shortcuts{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}.character-shortcuts button{flex:1 1 150px}
</style>

<style scoped>
.character-shortcuts{display:grid;gap:6px}.character-primary-actions{display:flex;flex-wrap:wrap;gap:8px}.character-more{margin:0}.character-more>summary{font-size:12px;min-height:28px;padding:4px 0;color:var(--text-primary)}.character-more>summary span{color:var(--text-secondary);font-weight:400;margin-left:8px}.character-more[open]>.button-row{padding:8px 0}.character-more[open]>summary{margin-bottom:0}
@media(max-width:680px){.character-primary-actions{display:grid;grid-template-columns:1fr 1fr}.character-primary-actions>button{padding:8px;font-size:12px;min-height:36px}.character-more>summary{min-height:26px}.character-more .button-row{display:grid;grid-template-columns:1fr 1fr}.character-more .button-row>button{font-size:12px;padding:8px}.character-guidance{margin-top:6px}}
</style>
