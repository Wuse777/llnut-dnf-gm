import {useGmDraftsStore,type RewardDraft} from './drafts'
import {useGmPlayersStore} from './players'
import {useGmCatalogStore} from './catalog'
import {useGmConfirmation} from './confirmation'
import {ref,computed,watch,nextTick,onScopeDispose} from 'vue'
import {readPendingOperation,usePendingOperation} from '../../pendingOperation'
import {api,setCsrf,uncertainMessage,ApiError,requests} from '../../api'
import {createReadQuery,invalidateReadQueries,isReadAbort} from '../../readQuery'
import {supportNames,inventoryNames,nativeNames,operationStatus} from '../../nativeStatus'
import {FormValidationError,assertValid,operationErrors,giftErrors,serverFieldErrors,type FieldErrors} from '../../validation'
import {defineStore,storeToRefs} from 'pinia'
import {router} from '@/router'
export const GM_ROUTE_PATHS:Record<string,string>={overview:'/home',accounts:'/players',online:'/players/online',support:'/players/support',economy:'/rewards/statistics',capabilities:'/system/capabilities',maintenance:'/system/maintenance',compatibility:'/system/upgrades',mail:'/rewards/compose','mail-center':'/rewards/deliveries','reward-jobs':'/rewards/batches',schedules:'/rewards/schedules','unlock-center':'/players/unlocks',catalog:'/items/catalog',gifts:'/rewards/templates',audit:'/system/audit','native-controls':'/rewards/control','operations-dashboard':'/system/diagnostics'}
export const useGmWorkspace=defineStore('gm-workspace',()=>{
const catalogState=useGmCatalogStore(),drafts=useGmDraftsStore(),players=useGmPlayersStore(),confirmation=useGmConfirmation()
function field<K extends keyof RewardDraft>(key:K){return computed({get:()=>drafts.current[key],set:(value:RewardDraft[K])=>{drafts.current[key]=value}})}

const supportDesk=ref<any>(null)
const supportUid=ref(0),supportCase=ref<any>(null),mailCenterUid=ref(0),mailCenterOperation=ref('')
const mailPane=ref<'items'|'draft'>('draft'),mailTextOpen=ref(false)
const detailSection=ref('basic')
const giftHistory=ref(0)
const catalogRevision=ref(0)
const policyDialog=ref<any>(null),catalogTotal=ref(0),catalogFilters=ref<Record<string,unknown>>({})
const catalogFacets=ref<any>(null),advancedFilters=ref<Record<string,any>>({part:'',rarity:'',min_level:'',max_level:'',sort:'id'}),compareItems=ref<any[]>([]),compareWarning=ref('')
const fullCatalogFilters=computed(()=>({...advancedFilters.value,q:search.value,category:category.value,allowed_only:tab.value==='mail'?mailAllowedOnly.value:catalogAllowedOnly.value}))
function updateCatalogFilters(value:Record<string,any>){
 advancedFilters.value={part:value.part??'',rarity:value.rarity??'',min_level:value.min_level??'',max_level:value.max_level??'',sort:value.sort||'id'}
 if(typeof value.q==='string')search.value=value.q
 if(typeof value.category==='string')category.value=value.category
 if(typeof value.allowed_only==='boolean'){if(tab.value==='mail')mailAllowedOnly.value=value.allowed_only;else catalogAllowedOnly.value=value.allowed_only}
}
function toggleCompare(item:any){
 const existing=compareItems.value.find(i=>i.id===item.id)
 if(existing){compareItems.value=compareItems.value.filter(i=>i.id!==item.id);compareWarning.value='';return}
 if(compareItems.value.length>=4){compareWarning.value='最多同时对比4件物品，请先移出一件。';return}
 compareItems.value=[...compareItems.value,{...item,pvf_sha256:catalogMeta.value?.pvf_sha256}];compareWarning.value=''
}
function editPolicy(item?:any){policyDialog.value={item,filters:{...catalogFilters.value}}}
function policyReauth(){policyDialog.value=null;reauthOpen.value=true}
async function policyChanged(){preview.value=null;catalogRevision.value++}
const policyLabels:Record<string,string>={trial:'允许试发、未验证',verified:'已验证',blocked:'禁止发放'}
function policyLabel(i:any){return policyLabels[i.policy_state]||(sendable(i)?'允许试发、未验证':'禁止发放')}
const detailCharacNo=ref(0)
const totpRequired=ref(false),lookupId=ref(''),lookedUp=ref<any>(null)
const initializing=ref(true)
const fieldErrors=ref<FieldErrors>({}),feedbackScope=ref(''),toastDismissed=ref(false)
const logged=ref(false),writeBusy=ref(false),targetBusy=ref(false),error=ref(''),notice=ref(''),tab=ref('overview'),page=ref(1),search=ref('')
// Only writes and target changes lock the active draft. Independent reads have local loading states.
const busy=computed(()=>writeBusy.value||targetBusy.value)
const readBusy=ref<Record<string,boolean>>({})
const reads=createReadQuery()
type ReadContext={signal:AbortSignal,current:()=>boolean}
const readControllers=new Map<string,AbortController>()
const readJobs=new Map<string,{key:string,promise:Promise<any>}>()
function cancelRead(scope:string){readControllers.get(scope)?.abort();readControllers.delete(scope);readJobs.delete(scope);readBusy.value={...readBusy.value,[scope]:false}}
function cancelReads(){for(const scope of [...readControllers.keys()])cancelRead(scope);reads.cancel()}
function runRead<T>(scope:string,fn:(context:ReadContext)=>Promise<T>,feedback=scope,key?:string):Promise<T|undefined>{
 const existing=readJobs.get(scope)
 if(key&&existing?.key===key)return existing.promise
 const promise=executeRead(scope,fn,feedback)
 if(key){readJobs.set(scope,{key,promise});void promise.finally(()=>{if(readJobs.get(scope)?.promise===promise)readJobs.delete(scope)})}
 return promise
}
async function executeRead<T>(scope:string,fn:(context:ReadContext)=>Promise<T>,feedback:string):Promise<T|undefined>{
 cancelRead(scope)
 const controller=new AbortController(),generation=sessionGeneration,activeTab=tab.value
 readControllers.set(scope,controller);readBusy.value={...readBusy.value,[scope]:true}
 const current=()=>generation===sessionGeneration&&readControllers.get(scope)===controller&&!controller.signal.aborted
 error.value='';fieldErrors.value={};feedbackScope.value=feedback
 try{return await fn({signal:controller.signal,current})}
 catch(e){
  if(!current()||isReadAbort(e))return
  if(e instanceof ApiError&&e.status===401){clearSession();return}
  if(tab.value===activeTab||scope==='lookup'){
   error.value=uncertainMessage(e);feedbackScope.value=feedback
   if(e instanceof FormValidationError)fieldErrors.value=e.fields
   else if(e instanceof ApiError&&e.status===422)fieldErrors.value=serverFieldErrors(e.detail,feedback)
   await focusProblem()
  }
 }finally{if(readControllers.get(scope)===controller){readControllers.delete(scope);readBusy.value={...readBusy.value,[scope]:false}}}
}
const rows=ref<any[]>([]),overview=ref<any>(null),account=ref<any>(null),roles=ref<any[]>([]),roleResults=ref<any[]>([]),rolePage=ref(1),roleQuery=ref(''),roleMode=ref(false),catalogMeta=ref<any>(null)
const playerRevision=ref(0),playerPreferenceError=ref('')
let sessionGeneration=0
const currentPlayerTarget=computed(()=>account.value?{uid:account.value.uid,charac_no:selectedRole.value||0,
 label:roles.value.find(r=>r.charac_no===selectedRole.value)?.charac_name||account.value.accountname}:null)
const playerViews=ref<Record<number,{tab:string,page:number}>>({})
async function visitPlayer(value:{uid:number,charac_no:number}){
 const generation=sessionGeneration
 try{await api('/players/visit','POST',value);if(generation!==sessionGeneration)return;playerRevision.value++;playerPreferenceError.value=''}
 catch(e){if(generation!==sessionGeneration)return;playerPreferenceError.value='目标已打开，但最近访问未保存：'+uncertainMessage(e);if(e instanceof ApiError&&e.status===401)clearSession()}
}
async function chooseSavedPlayer(value:{uid:number,charac_no:number}){
 if(writeBusy.value||pendingId.value)return
 if(await setTarget(value.uid,value.charac_no)&&value.charac_no&&tab.value==='accounts')openCharacter(value.charac_no)
}
const username=ref('admin'),password=ref(''),code=ref(''),reauthOpen=ref(false)
const action=field('action'),currency=field('currency'),delta=field('delta'),reason=field('reason'),message=field('message')
const selectedRole=computed({get:()=>drafts.current.characNo,set:(value:number)=>{drafts.activate(account.value?.uid??0,value,true)}})
const mailGold=field('gold')
const mailCurrencies=field('currencies'),giftCurrencies=ref<Record<string,number>>({})
const mailTitle=field('title'),giftTitle=ref('')
const templateAdjusted=field('templateAdjusted')
const hasMailCurrencies=computed(()=>Object.values(mailCurrencies.value).some(Boolean))
const mailAttachments=field('items'),giftAttachments=ref<any[]>([])
const attachments=computed({get:()=>tab.value==='gifts'?giftAttachments.value:mailAttachments.value,set:(v:any[])=>{if(tab.value==='gifts')giftAttachments.value=v;else mailAttachments.value=v}})
const operationOpen=ref(false)
const pendingId=ref(readPendingOperation())
const preview=ref<any>(null),operationResult=ref<any>(null),idemKey=ref(''),uncertain=ref(false),category=ref('')
const {pendingStatus,pendingChecked}=usePendingOperation(pendingId,logged,busy,(result)=>{operationResult.value=result;lookedUp.value=result;lookupId.value=result.operation_id;confirmOpen.value=false;notice.value='自动核对原操作：数据库已提交，没有重发。'})
const giftGold=ref(0),giftMessage=ref('GM rewards'),giftCategory=ref('')
const giftName=ref(''),giftId=ref(0),giftVersion=ref(0),giftEnabled=ref(true),templateId=field('templateId'),templateVersion=field('templateVersion')
const icons:Record<string,string>={overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',accounts:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M20 8v6 M17 11h6',online:'M3 12h4l3-8 4 16 3-8h4',catalog:'M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h4',gifts:'M3 8h18v4H3z M5 12v9h14v-9 M12 8v13 M12 8C3 8 5 0 9 3z M12 8c9 0 7-8 3-5z',audit:'M6 3h12v18H6z M9 8h6 M9 12h6 M9 16h4'}
icons['mail-center']='M3 5h18v14H3z M3 5l9 7 9-7'
icons['schedules']='M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20 M12 6v6l4 3'
icons['reward-jobs']='M3 3h18v18H3z M7 8h10 M7 12h10 M7 16h6'
icons.mail='M3 5h18v14H3z M3 5l9 7 9-7'
icons['unlock-center']='M5 10h14v11H5z M8 10V6a4 4 0 0 1 8 0 M12 14v3'
icons.maintenance='M12 3v5 M12 16v5 M3 12h5 M16 12h5 M7 7l3 3 M14 14l3 3 M7 17l3-3 M14 10l3-3'
icons.capabilities='M4 3h16v18H4z M8 7h8 M8 12h8 M8 17h5'
icons.compatibility='M5 4h14v16H5z M8 8h8 M8 12h5 M8 16h3'
icons.economy='M4 20V12h3v8 M10 20V7h3v13 M16 20V3h3v17'
icons.support='M4 3h16v14H9l-5 4V3z M8 7h8 M8 11h5'
icons['native-controls']='M3 11h4l10-6v14L7 13H3z M7 13v7h4'
icons['operations-dashboard']='M3 12h4l3-8 4 16 3-8h4'
const tabs=[['overview','服务器概览'],['operations-dashboard','运维诊断'],['accounts','账号与角色'],['support','玩家问题'],['economy','发放统计'],['capabilities','功能与版本'],['maintenance','维护中心'],['compatibility','升级检查'],['online','在线账号'],['native-controls','游戏内控制'],['mail','邮件发放'],['mail-center','邮件中心'],['reward-jobs','批量奖励'],['schedules','定时运营'],['unlock-center','装备解锁'],['catalog','物品索引'],['gifts','礼包模板'],['audit','操作审计']]
const cleanupStates:Record<string,string>={executing:'执行中',completed:'所选旧GM目录已删除',rejected:'执行端拒绝，未开始删除',needs_review:'可能部分完成，需要人工核对'}
const cleanupFileStates:Record<string,string>={prepared:'未执行',deleting:'执行中',removed:'已删除',interrupted_unknown:'中断，结果未知',partial_or_unknown:'可能部分删除，需核对'}
const actionNames:Record<string,string>={...nativeNames,...inventoryNames,...supportNames,'maintenance':'维护申请','maintenance-reconcile':'维护前操作核对','maintenance-prepare':'申请维护计划','maintenance-confirm':'确认维护','maintenance-close':'结束维护并恢复原服务','maintenance-recover':'核对中断并继续恢复','maint-recover':'维护中断恢复请求','maint-close':'结束维护请求','maintenance-cancel':'取消维护计划','capability-policy':'管理员权限调整','cleanup-release':'旧GM产物清理','unlock-batch':'批量提前解锁',reward:'组合奖励',currency:'余额变更',mail:'奖励邮件',ban:'封禁后续登录',unban:'解除封禁','equipment-unlock':'装备提前解锁','catalog-policy':'物品发放策略','gift-template':'礼包模板','role-soft-delete':'维护：角色软删除','test-fixture-cleanup':'维护：测试夹具归档'}
const currencyNames:Record<string,string>={cera:'点券',cera_point:'代币券',mileage:'积分'}
const categoryNames:Record<string,string>={equipment:'装备',material:'材料',consumable:'消耗品',special:'特殊'}
function sendable(i:any){return i.sendable??!!i.allowed}
function loginState(a:any){return a?.online?.login_status??a?.login_status??null}
function onlineLabel(a:any){return loginState(a)===1?'在线':loginState(a)===0?'离线':'未知'}
function money(n:unknown){return n==null?'未知':Number(n).toLocaleString('zh-CN')}
function localTime(s:string){return s?new Date(s.replace(' ','T')+'Z').toLocaleString('zh-CN',{hour12:false}):'未知'}
async function reveal(selector:string){await nextTick();document.querySelector(selector)?.scrollIntoView?.({block:'start'})}
function openCharacter(id:number){notice.value='';error.value='';toastDismissed.value=true;void router.push({path:'/characters/'+id,query:{section:detailSection.value||'basic'}})}
function clearTarget(){supportCase.value=null;detailCharacNo.value=0;confirmOpen.value=false;account.value=null;roles.value=[];selectedRole.value=0;preview.value=null;operationResult.value=null}
function clearSession(){sessionGeneration++;cancelTarget();cancelReads();invalidateReadQueries();confirmation.release('ordinary');operationOpen.value=false;catalogState.clear();drafts.clear();players.clear();mailPane.value='draft';mailTextOpen.value=false;mailTitle.value='';giftTitle.value='';mailCurrencies.value={};giftCurrencies.value={};giftHistory.value=0;giftGold.value=0;giftMessage.value='GM rewards';giftCategory.value='';detailCharacNo.value=0;policyDialog.value=null;toastDismissed.value=false;fieldErrors.value={};feedbackScope.value='';tableState.clear();playerViews.value={};mailCenterOperation.value='';mailCenterUid.value=0;playerPreferenceError.value='';logged.value=false;setCsrf('');clearTarget();rows.value=[];roleResults.value=[];mailAttachments.value=[];mailGold.value=0;giftAttachments.value=[];templateId.value=null;templateVersion.value=null;giftId.value=0;giftVersion.value=0;giftName.value='';giftEnabled.value=true;lookupId.value='';lookedUp.value=null;password.value='';code.value='';reason.value='';reauthOpen.value=false;notice.value='';requests.value=[];recipientResults.value=[];recipientSearch.value='';giftEditing.value=false;pickerOpen.value=false;reauthOpen.value=false;confirmOpen.value=false;mobileMenu.value=false}
function requestBody(){const mail=action.value==='mail';return {...(supportCase.value&&['currency','mail'].includes(action.value)?{support_case_id:supportCase.value.case_id}:{}),action:mail&&hasMailCurrencies.value?'reward':action.value,...(mail&&hasMailCurrencies.value?{currency_rewards:mailCurrencies.value}:{}),uid:account.value?.uid,charac_no:mail||action.value==='currency'?selectedRole.value||null:null,currency:action.value==='currency'?currency.value:null,delta:action.value==='currency'?delta.value:null,reason:reason.value.trim(),items:mail&&templateId.value===null?mailAttachments.value.map(({id,quantity})=>({id,quantity})):[],gold:mail?mailGold.value:0,message:mail?message.value:'GM rewards',mail_title:mail?mailTitle.value:'',template_id:mail?templateId.value:null,template_version:mail?templateVersion.value:null,...(mail&&templateId.value!==null&&templateAdjusted.value?{template_overrides:{items:mailAttachments.value.map(({id,quantity})=>({id,quantity})),gold:mailGold.value,message:message.value,mail_title:mailTitle.value,currency_rewards:mailCurrencies.value}}:{})}}
const draft=computed(()=>JSON.stringify(requestBody()))
watch(draft,()=>{operationResult.value=null;if(preview.value){preview.value=null;confirmOpen.value=false;confirmation.release('ordinary');notice.value='参数已变化，旧预览已失效；请重新生成。原编号仍可查询。'}},{flush:'sync'})
watch([()=>drafts.activeKey,mailAttachments,mailGold,message,mailCurrencies,mailTitle],(value,previous)=>{if(value[0]===previous[0]&&templateId.value!==null)templateAdjusted.value=true},{deep:true,flush:'sync'})
async function focusProblem(){
 if(tab.value==='mail'){mailPane.value='draft';if(fieldErrors.value['mail-title']||fieldErrors.value['mail-message'])mailTextOpen.value=true}
 await nextTick()
 const invalid=Array.from(document.querySelectorAll<HTMLElement>('[aria-invalid="true"]')).find(el=>!(el as HTMLInputElement).disabled)
 const target=(invalid?.id==='mail-recipient'?document.querySelector<HTMLElement>('#recipient-query'):invalid)??document.querySelector<HTMLElement>('[data-modal-error]')
 target?.scrollIntoView?.({block:'center',behavior:'instant'});target?.focus({preventScroll:true})
}
function validationFor(scope:string):FieldErrors{
 if(scope==='operation')return operationErrors({action:requestBody().action,currencyRewards:mailCurrencies.value,account:account.value,delta:delta.value,reason:reason.value,message:message.value,mailTitle:mailTitle.value,roleValid:roles.value.some(r=>r.charac_no===selectedRole.value&&!r.delete_flag),items:mailAttachments.value,gold:mailGold.value})
 if(scope==='gift')return giftErrors(giftName.value,giftAttachments.value,giftGold.value,giftMessage.value,giftCurrencies.value,giftTitle.value)
 if(scope==='audit')return search.value&&!/^[1-9]\d{0,9}$/.test(search.value)?{'audit-uid':'审计筛选请填写正整数 UID，或留空查看全部。'}:{}
 if(scope==='lookup')return !/^[a-f0-9]{32}$/.test(lookupId.value)?{'lookup-id':'请填写32位小写十六进制操作编号。'}:{}
 if(scope==='recipient')return !recipientSearch.value.trim()?{'recipient-query':'请填写账号、UID或角色搜索条件。'}:{}
 return {}
}
async function run(fn:()=>Promise<void>,scope?:string){
 if(busy.value)return
 const generation=sessionGeneration
 writeBusy.value=true;error.value='';notice.value='';toastDismissed.value=false;fieldErrors.value={};feedbackScope.value=scope??(pickerOpen.value?'picker':tab.value)
 let failed=false
 try{await fn()}catch(e){
  if(generation!==sessionGeneration)return
  failed=true;error.value=uncertainMessage(e)
  if(e instanceof FormValidationError)fieldErrors.value=e.fields
  else if(e instanceof ApiError&&e.status===422)fieldErrors.value=serverFieldErrors(e.detail,feedbackScope.value)
  if(e instanceof ApiError&&e.status===401)clearSession()
  else if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))reauthOpen.value=true
 }finally{writeBusy.value=false;if(failed&&generation===sessionGeneration)await focusProblem()}
}
async function login(){await run(async()=>{const d=await api('/auth/login','POST',{username:username.value,password:password.value,code:code.value});sessionGeneration++;setCsrf(d.csrf);drafts.clear();await drafts.bindSession(d.csrf);password.value='';code.value='';logged.value=true;tab.value='overview'})}
async function logout(){await run(async()=>{await api('/auth/logout','POST');clearSession()})}
async function reauth(){await run(async()=>{await api('/auth/reauth','POST',{username:username.value,password:password.value,code:code.value});password.value='';code.value='';reauthOpen.value=false;notice.value='重新认证成功，有效期5分钟'})}
let listEpoch=0
async function load(context?:ReadContext):Promise<void>{
 if(!context){await runRead('list',value=>load(value),tab.value,JSON.stringify([tab.value,page.value,search.value,category.value,roleMode.value,roleQuery.value,rolePage.value,advancedFilters.value,mailAllowedOnly.value,catalogAllowedOnly.value]));return}
 const current=++listEpoch,activeTab=tab.value
 if(activeTab==='overview'){
  const result=await reads.get('/overview',{signal:context.signal});if(context.current()&&current===listEpoch&&tab.value===activeTab)overview.value=result;return
 }
 if(tab.value==='accounts'&&roleMode.value){await loadRoles(context);return}
 const paths:Record<string,string>={accounts:'/accounts',online:'/online',catalog:'/catalog',mail:'/catalog',gifts:'/gift-templates',audit:'/audit'}
 let path=paths[tab.value]
 if(!path)return
 if(tab.value==='audit'){assertValid(validationFor('audit'));path+='?page='+page.value+'&uid='+(search.value||0)}
 else {path+='?page='+page.value;if(tab.value!=='online')path+='&q='+encodeURIComponent(search.value);if(['catalog','mail'].includes(tab.value)){path+='&category='+encodeURIComponent(category.value);if(tab.value==='mail'?mailAllowedOnly.value:catalogAllowedOnly.value)path+='&allowed_only=1'}}
 if(tab.value==='gifts')path+='&category='+encodeURIComponent(category.value)
 if(['catalog','mail'].includes(tab.value))for(const [key,value] of Object.entries(advancedFilters.value)){if(value!==''&&value!=null)path+='&'+key+'='+encodeURIComponent(String(value))}
 const d=await reads.get<any>(path,{signal:context.signal});if(!context.current()||current!==listEpoch||tab.value!==activeTab)return;rows.value=d.items??[];catalogMeta.value=d.metadata??null;catalogTotal.value=d.total??0;catalogFacets.value=d.facets??null
 if(d.metadata?.pvf_sha256&&compareItems.value.some(i=>i.pvf_sha256!==d.metadata.pvf_sha256)){compareItems.value=[];compareWarning.value='PVF 版本已变化，原对比已清空。'}
 if(tab.value==='catalog'){
  const params=new URLSearchParams(path.split('?')[1]);catalogFilters.value={q:params.get('q')||'',category:params.get('category')||'',allowed_only:params.get('allowed_only')==='1'}
  for(const key of ['part','rarity','min_level','max_level']){const value=params.get(key);if(value!==null)catalogFilters.value[key]=key==='part'?value:Number(value)}
 }
}
async function searchRows(){page.value=1;roleMode.value=false;roleResults.value=[];await load()}
const tableState=new Map<string,{search:string,page:number,category:string,roleMode:boolean,rolePage:number,roleQuery:string,accountMode:string,scrollY:number}>()
async function activate(t:string,loadList=true){
 if(tab.value==='support'&&t!=='support'&&supportDesk.value&&!supportDesk.value.canNavigate()){mobileMenu.value=false;await nextTick();document.querySelector('.support-desk [role=alert]')?.scrollIntoView?.({block:'center'});return}
 if(tab.value!==t){for(const scope of ['list','recipient','picker','account-refresh'])cancelRead(scope);if(!['accounts','mail'].includes(t))cancelTarget()}
 tableState.set(tab.value,{search:search.value,page:page.value,category:category.value,roleMode:roleMode.value,rolePage:rolePage.value,roleQuery:roleQuery.value,accountMode:accountMode.value,scrollY:window.scrollY})
 const saved=tableState.get(t)
 tab.value=t;if(t==='mail')mailPane.value='draft';page.value=saved?.page??1;search.value=saved?.search??'';category.value=saved?.category??'';rows.value=[];catalogMeta.value=null
 roleMode.value=saved?.roleMode??false;rolePage.value=saved?.rolePage??1;roleQuery.value=saved?.roleQuery??'';accountMode.value=saved?.accountMode??'account';roleResults.value=[]
 notice.value='';mobileMenu.value=false;confirmOpen.value=false;if(t==='mail')action.value='mail'
 if(loadList)await load()
 await nextTick();if(!pickerOpen.value)window.scrollTo?.({top:saved?.scrollY??0,behavior:'instant'})
}
async function go(t:string){const target=GM_ROUTE_PATHS[t]||t;await router.push(target)}
let targetEpoch=0
function cancelTarget(){targetEpoch++;cancelRead('target');targetBusy.value=false}
async function setTarget(uid:number,role=0,signal?:AbortSignal):Promise<boolean>{
 if(writeBusy.value||pendingId.value){if(account.value?.uid===uid&&selectedRole.value===role)return true;error.value='当前操作尚未完成，请先按原编号核对结果后再切换目标。';return false}
 const epoch=++targetEpoch
 targetBusy.value=true;preview.value=null;confirmOpen.value=false;confirmation.release('ordinary')
 const cancel=()=>{if(epoch===targetEpoch)cancelTarget()}
 signal?.addEventListener('abort',cancel,{once:true})
 try{
  if(signal?.aborted)return false
  const changed=await runRead('target',async context=>{
   const workspace=await players.open(uid,role,context.signal)
   if(!context.current()||epoch!==targetEpoch)return false
   supportCase.value=null;account.value=workspace.account;roles.value=workspace.roles;drafts.activate(uid,role,true)
   if(['accounts','online'].includes(tab.value)&&action.value==='mail')action.value='currency'
   preview.value=null;operationResult.value=null;recipientResults.value=[];void visitPlayer({uid,charac_no:role})
   return true
  },'target')
  return changed===true
 }finally{signal?.removeEventListener('abort',cancel);if(epoch===targetEpoch)targetBusy.value=false}
}

async function copyMailDraft(data:any){
 if(busy.value||pendingId.value){error.value='当前有未完成的操作，请先查询其结果。';return false}
 await router.push({path:GM_ROUTE_PATHS.mail,query:{uid:String(data.uid),charac_no:String(data.charac_no)}})
 if(!await setTarget(data.uid,data.charac_no))return false
 {
  mailAttachments.value=data.items.map((i:any)=>({...i,name:'#'+i.id}))
  mailCurrencies.value={...(data.currency_rewards||{})};mailGold.value=data.gold||0;message.value=data.message??'GM rewards';mailTitle.value=data.mail_title??'';reason.value=data.reason||''
  templateId.value=null;templateVersion.value=null;action.value='mail';preview.value=null
  notice.value='已生成新的发放草稿，尚未发送；请核对目标、数量和原因后预览确认。'
 }
 return true
}
async function correctOperation(record:any){
 if(busy.value||pendingId.value)return
 const data=record.request
 if(['mail','reward'].includes(data.action)){if(await copyMailDraft(data))reason.value='纠正操作 '+record.operation_id;return}
 await router.push({path:'/players/'+data.uid,query:{charac_no:data.charac_no?String(data.charac_no):undefined}})
 if(!await setTarget(data.uid,data.charac_no||0))return
 action.value=data.action;if(data.action==='currency'){currency.value=data.currency;delta.value=0}reason.value='纠正操作 '+record.operation_id;notice.value='已建立纠正草稿，不会撤销旧记录。请自行填写正确的变更金额或操作，再预览确认。'
}
async function detailAction(data:{action:string,uid:number,charac_no:number}){
 if(busy.value||pendingId.value)return
 detailCharacNo.value=0
 await playerAction(data)
}
async function detailDraft(data:any){if(busy.value||pendingId.value)return;detailCharacNo.value=0;await copyMailDraft(data)}
async function detailInspect(id:string){if(busy.value||pendingId.value)return;detailCharacNo.value=0;await inspectOperation(id)}
async function playerAction(data:{action:string,uid:number,charac_no?:number}){
 if(busy.value||pendingId.value)return
 if(data.action==='support'){supportUid.value=data.uid;await go('support');return}
 if(data.action==='support-mail'){mailCenterOperation.value='';mailCenterUid.value=data.uid;await go('mail-center');return}
 if(data.action==='detail'||data.action==='unlock'){detailSection.value=data.action==='unlock'?'unlock':'basic';openCharacter(data.charac_no||0);return}
 await router.push({path:data.action==='mail'?GM_ROUTE_PATHS.mail:'/players/'+data.uid,query:{...(data.action==='mail'?{uid:String(data.uid)}:{}),charac_no:data.charac_no?String(data.charac_no):undefined}})
 if(!await setTarget(data.uid,data.charac_no||0))return
 action.value=data.action;await reveal(data.action==='mail'?'#recipient':'[data-testid=account-operations]')
}
async function supportCompensation(data:any){
 if(busy.value||pendingId.value)return
 await router.push({path:data.kind==='mail'?GM_ROUTE_PATHS.mail:'/players/'+data.uid,query:{...(data.kind==='mail'?{uid:String(data.uid)}:{}),charac_no:data.charac_no?String(data.charac_no):undefined}})
 if(!await setTarget(data.uid,data.charac_no||0))return
 {
  supportCase.value={case_id:data.case_id,title:data.title,uid:data.uid,charac_no:data.charac_no,compensation_count:data.compensation_count}
  action.value=data.kind;delta.value=0;reason.value=('问题 #'+data.case_id+'：'+data.title).slice(0,200)
  if(data.kind==='mail'){mailAttachments.value=[];mailGold.value=0;mailCurrencies.value={};templateId.value=null;templateVersion.value=null;mailTitle.value='';message.value='问题补偿'}
  notice.value='已建立关联问题的草稿，尚未发奖。请填写正确的金额或物品后预览。'
 }
}
async function refreshAccount(){
 const uid=account.value?.uid,epoch=targetEpoch
 if(!uid)return
 await runRead('account-refresh',async context=>{
  const result=await reads.get<any>('/accounts/'+uid,{signal:context.signal,force:true})
  if(context.current()&&account.value?.uid===uid&&targetEpoch===epoch){account.value=result;notice.value='账号余额与在线状态已刷新'}
 },'accounts')
}
async function select(a:any){await router.push('/players/'+a.uid)}
let rolesEpoch=0
async function loadRoles(context?:ReadContext):Promise<void>{
 if(!context){await runRead('list',value=>loadRoles(value),tab.value);return}
 const current=++rolesEpoch,query=roleQuery.value,p=rolePage.value
 const result=await reads.get<any>('/characters?q='+encodeURIComponent(query)+'&page='+p,{signal:context.signal})
 if(context.current()&&current===rolesEpoch&&roleQuery.value===query&&rolePage.value===p&&['accounts','online'].includes(tab.value))roleResults.value=result.items
}
async function queryCharacters(){roleMode.value=true;rolePage.value=1;roleQuery.value=search.value;rows.value=[];await loadRoles()}
async function selectRole(r:any){if(r.delete_flag)return;await router.push('/characters/'+r.charac_no)}
const preferenceRevision=ref(0),preferenceWarning=ref('')
function preferenceChanged(value:{id:number,pvf_sha256:string,favorite:boolean}){
 for(const list of [rows.value,pickerRows.value])for(const item of list)if(item.id===value.id&&item.pvf_sha256===value.pvf_sha256)item.favorite=value.favorite
 preferenceRevision.value++
}
async function rememberSelection(item:any){
 if(!item.pvf_sha256)return
 try{await api('/catalog/'+item.id+'/selection','POST',{pvf_sha256:item.pvf_sha256});preferenceRevision.value++}
 catch(e){preferenceWarning.value='物品已加入本地草稿，但最近选择未保存：'+uncertainMessage(e)+'。没有发放物品，无需重复加入。'}
}
function addItem(i:any){if(busy.value)return;toastDismissed.value=false;if(!sendable(i)){error.value=i.policy_reason||'该物品已停用，不能加入发放清单';return}if(attachments.value.length>=20){error.value='最多20条附件';return}attachments.value.push({...i,quantity:1});preferenceWarning.value='';void rememberSelection(i);if(tab.value!=='gifts')action.value='mail';notice.value='已加入清单：'+i.name+'；共 '+attachments.value.length+' 条附件'}

async function makePreview(){if(!confirmation.acquire('ordinary')){error.value='请先完成或关闭当前确认面板。';return}await run(async()=>{if(pendingId.value)throw new Error('上一笔提交结果尚未确认，请先按原编号查询，不要创建替代操作');preview.value=null;assertValid(validationFor('operation'));const fingerprint=draft.value;const d=await api('/operations/preview','POST',requestBody());if(fingerprint!==draft.value)throw new Error('等待期间表单已变化，请重新预览');preview.value=d;lookupId.value=d.operation_id;idemKey.value=crypto.randomUUID();uncertain.value=false;operationResult.value=null;confirmOpen.value=true},'operation');if(!confirmOpen.value)confirmation.release('ordinary')}
async function confirmOperation(){
 if(uncertain.value||!preview.value)return
 await run(async()=>{
  const op=preview.value.operation_id,generation=sessionGeneration,uid=account.value?.uid;uncertain.value=true;pendingId.value=op
  try{
   const result=await api('/operations/'+op+'/confirm','POST',{idempotency_key:idemKey.value})
   if(generation!==sessionGeneration)return
   operationResult.value=result;pendingId.value=''
  }catch(e){
   if(generation!==sessionGeneration)return
   if(e instanceof ApiError&&e.status>=400&&e.status<500){pendingId.value='';uncertain.value=false;if(e.status===409)preview.value=null}
   throw e
  }
  confirmOpen.value=false;notice.value='操作已提交并记录审计。未验证游戏内效果，不会自动重发。'
  try{const refreshed=await api('/accounts/'+uid);if(generation===sessionGeneration&&account.value?.uid===uid)account.value=refreshed}catch{if(generation===sessionGeneration)notice.value+='余额快照刷新失败，可手动刷新。'}
 },'operation')
}
async function viewDeliveredMail(){
 if(busy.value||pendingId.value||!operationResult.value?.operation_id)return
 operationOpen.value=false;mailCenterOperation.value=operationResult.value.operation_id;mailCenterUid.value=account.value?.uid||0
 await go('mail-center')
}
async function nextMailDraft(){
 if(busy.value||pendingId.value)return
 operationOpen.value=false;preview.value=null;operationResult.value=null;uncertain.value=false
 mailAttachments.value=[];mailGold.value=0;mailCurrencies.value={};mailTitle.value='';message.value='GM rewards';reason.value='';templateId.value=null;templateVersion.value=null
 await go('mail');notice.value='已保留收件目标，新草稿尚未发放，请重新填写奖励及原因。';await reveal('#recipient')
}
async function inspectOperation(id:string){lookupId.value=id;operationOpen.value=true;await runRead('lookup',async context=>{
 assertValid(validationFor('lookup'));lookedUp.value=null
 const result=await reads.get<any>('/operations/'+id,{signal:context.signal,force:true})
 if(!context.current())return
 lookedUp.value=result;lookupId.value=id;if(result.status==='committed'&&pendingId.value===id)pendingId.value=''
 notice.value='已读取原操作结果，没有重放写入';await reveal('#operation-lookup')
 },'lookup')}
async function queryResult(){
 const id=preview.value?.operation_id
 if(!id)return
 await runRead('result',async context=>{
  const result=await reads.get<any>('/operations/'+id,{signal:context.signal,force:true})
  if(!context.current()||preview.value?.operation_id!==id)return
  operationResult.value=result
  if(result.status==='committed'){if(pendingId.value===id)pendingId.value='';confirmOpen.value=false}
  notice.value='已查询原编号；未重放操作'
 },'operation')
}
async function saveGift(){await run(async()=>{const generation=sessionGeneration;assertValid(validationFor('gift'));const p=giftId.value?'/gift-templates/'+giftId.value:'/gift-templates';const saved=await api(p,giftId.value?'PUT':'POST',{...(Object.values(giftCurrencies.value).some(Boolean)?{currency_rewards:giftCurrencies.value}:{}),gold:giftGold.value,message:giftMessage.value,mail_title:giftTitle.value,category:giftCategory.value,name:giftName.value.trim(),enabled:giftEnabled.value,expected_version:giftVersion.value,items:giftAttachments.value.map(({id,quantity})=>({id,quantity}))});if(generation!==sessionGeneration)return;giftId.value=saved.id;giftVersion.value=saved.version;notice.value='模板 #'+saved.id+' 已保存为 v'+saved.version+'；历史版本保留';if(tab.value==='gifts')await load()},'gift')}
function resetGift(){if(busy.value||pendingId.value)return;giftCurrencies.value={};giftEditing.value=true;giftId.value=0;giftVersion.value=0;giftName.value='';giftGold.value=0;giftMessage.value='GM rewards';giftTitle.value='';giftCategory.value='';giftEnabled.value=true;giftAttachments.value=[];notice.value='新模板已重置，请点“添加物品”组合礼包附件'}
function editGift(g:any){if(busy.value||pendingId.value)return;giftCurrencies.value={...(g.rewards.currency_rewards||{})};giftEditing.value=true;giftId.value=g.id;giftVersion.value=g.current_version;giftName.value=g.name;giftGold.value=g.rewards.gold??0;giftMessage.value=g.rewards.message??'GM rewards';giftTitle.value=g.rewards.mail_title??'';giftCategory.value=g.rewards.category??'';giftEnabled.value=!!g.enabled;giftAttachments.value=g.rewards.items.map((i:any)=>({...i}));notice.value='正在编辑模板 #'+g.id+' v'+g.current_version}
function copyGift(g:any){if(busy.value||pendingId.value)return;editGift(g);giftId.value=0;giftVersion.value=0;giftName.value=(g.name+' 副本').slice(0,80);notice.value='已复制为独立模板草稿，保存后生效。'}
function copyGiftVersion(payload:any){copyGift({id:0,current_version:0,name:payload.name||'历史礼包',enabled:true,rewards:payload});giftHistory.value=0}
async function useGift(g:any){if(busy.value||pendingId.value||!g.enabled)return;mailCurrencies.value={...(g.rewards.currency_rewards||{})};mailGold.value=g.rewards.gold??0;message.value=g.rewards.message??'GM rewards';mailTitle.value=g.rewards.mail_title??'';mailAttachments.value=g.rewards.items.map((i:any)=>({...i}));templateId.value=g.id;templateVersion.value=g.current_version;templateAdjusted.value=false;action.value='mail';notice.value='已绑定礼包 #'+g.id+' v'+g.current_version+'，选择收件账号与角色后预览；可以临时调整奖励，保留来源且不修改原模板';await go('mail')}

const mobileViewport=ref(window.matchMedia?.('(max-width: 768px)').matches??false)
const confirmOpen=ref(false),mobileMenu=ref(false),collapsed=ref(false),giftEditing=ref(false),pickerOpen=ref(false)
const recipientSearchType=ref('account')
const recipientSearch=ref(''),recipientResults=ref<any[]>([]),recipientQueried=ref(false),pickerQuery=ref(''),pickerRows=ref<any[]>([]),pickerPage=ref(1),pickerCategory=ref('')
const mailAllowedOnly=ref(true),catalogAllowedOnly=ref(false),pickerAllowedOnly=ref(true)
const theme=ref('light'),accountMode=ref('account')
const healthTask=ref(''),healthSchedule=ref('')
function openHealthTask(kind:string,id:string){
 if(kind==='reward'){healthTask.value=id;go('reward-jobs')}
 else{healthSchedule.value=id;go('schedules')}
}
function openScheduledChild(kind:string,id:string){
 if(kind==='reward'){sessionStorage.setItem('dnfgm.pending-reward-job',JSON.stringify({id,uncertain:false}));go('reward-jobs')}
 else{sessionStorage.setItem('dnfgm-native-operation',id);go('native-controls')}
}
const descriptions:Record<string,string>={compatibility:'升级前对照候选索引检查保存引用；只读核对，不自动切换版本。',economy:'GM发放与扣减、邮件积压和补偿线索；不是全服经济流水。',support:'玩家备注、问题处理与补偿追踪；不把记录保存当成游戏操作。','schedules':'北京时间定时奖励与公告，按期冻结名单；错过不补发，异常不重放。','native-controls':'预览确认后发送公告或账号控制；不把传输成功当成游戏生效。','operations-dashboard':'资源历史、占用分类、保护原因与发布信息；不把过期数据当成正常。','unlock-center':'查找保存的申请、关联物品与倒计时，明确选择后整批设为到期。','reward-jobs':'固定名单、账号奖励去重与持久任务；异常时核对原任务，不重复发奖。','mail-center':'查找每一笔投递和全部附件；从历史记录生成新草稿。',overview:'服务健康与玩家数据，一眼掌握。',accounts:'先选账号，再管理余额、角色与登录权限。',online:'按游戏登录状态查看在线账号。',mail:'选定收件角色，组合奖励，核对后投递。',catalog:'搜索当前 PVF，管理物品的发放策略。',gifts:'把常用奖励保存成礼包，版本与历史发放可追溯。',audit:'追踪每一笔操作；查询历史结果不会重复执行。'}
const feedbackMessage=computed(()=>{const fields=Object.values(fieldErrors.value);return error.value?(fields.length?fields[0]+(fields.length>1?' 另有 '+(fields.length-1)+' 项需检查。':''):error.value):notice.value})
watch([error,notice],()=>{toastDismissed.value=false})
const shownResult=computed(()=>operationResult.value?.result??operationResult.value)
const resultCommitted=computed(()=>operationResult.value?.status==='committed'||!!operationResult.value?.state)
const role=computed(()=>roles.value.find(r=>r.charac_no===selectedRole.value))
const totalQuantity=computed(()=>attachments.value.reduce((s,i)=>s+Number(i.quantity||0),0))
function applyTheme(value:string){theme.value=value}
function quickAmount(n:number){delta.value=(delta.value<0?-1:1)*n}
function changeDirection(negative:boolean){delta.value=(negative?-1:1)*Math.abs(delta.value||100)}
function chooseOperation(value:string){if(busy.value||pendingId.value)return;action.value=value;confirmOpen.value=false;if(value==='mail')void toMail()}
async function findRecipient(){await runRead('recipient',async context=>{
 recipientResults.value=[];recipientQueried.value=false;assertValid(validationFor('recipient'))
 const query=recipientSearch.value.trim(),mode=recipientSearchType.value
 const result=await reads.get<any>((mode==='role'?'/characters':'/accounts')+'?q='+encodeURIComponent(query)+'&page=1',{signal:context.signal})
 if(context.current()&&query===recipientSearch.value.trim()&&mode===recipientSearchType.value){recipientResults.value=result.items;recipientQueried.value=true}
 },'recipient')}
async function searchAccounts(){if(accountMode.value==='role')await queryCharacters();else await searchRows()}
async function pickRecipient(a:any){if(a.delete_flag)return;if(await setTarget(a.uid,a.charac_no||0))recipientQueried.value=false}
async function openPicker(){pickerOpen.value=true}
async function loadPicker(){await runRead('picker',async context=>{const result=await reads.get<any>('/catalog?q='+encodeURIComponent(pickerQuery.value)+'&category='+pickerCategory.value+'&page='+pickerPage.value+(pickerAllowedOnly.value?'&allowed_only=1':''),{signal:context.signal});if(context.current())pickerRows.value=result.items},'picker')}
async function searchPicker(){pickerPage.value=1;await loadPicker()}
async function toMail(){await router.push({path:GM_ROUTE_PATHS.mail,query:{uid:account.value?.uid?String(account.value.uid):undefined,charac_no:selectedRole.value?String(selectedRole.value):undefined}})}
async function saveAsTemplate(){giftCurrencies.value={...mailCurrencies.value};giftEditing.value=true;giftId.value=0;giftVersion.value=0;giftName.value='';giftEnabled.value=true;giftGold.value=mailGold.value;giftMessage.value=message.value;giftTitle.value=mailTitle.value;giftCategory.value='';giftAttachments.value=mailAttachments.value.map(i=>({...i}));await go('gifts');await reveal('#gift-editor')}
async function inspectFromAudit(id:string){await inspectOperation(id)}
function closePreview(){if(!busy.value){confirmOpen.value=false;confirmation.release('ordinary')}}
watch(confirmOpen,value=>{if(!value)confirmation.release('ordinary')})
watch(operationResult,value=>{if(value&&!confirmOpen.value)operationOpen.value=true})
watch(confirmOpen,value=>{if(!value&&operationResult.value)operationOpen.value=true})
function restoreTheme(){}
function dismissMobile(e:KeyboardEvent){
 if(!mobileMenu.value)return
 if(e.key==='Escape'){mobileMenu.value=false;return}
 if(e.key==='Tab'){const buttons=Array.from(document.querySelectorAll<HTMLElement>('aside button:not(:disabled)'));const first=buttons[0],last=buttons[buttons.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}
}
watch(mobileMenu,async(open)=>{await nextTick();(document.querySelector(open?'aside .mobile-close':'.mobile-toggle') as HTMLElement|null)?.focus()})
const viewportMedia=window.matchMedia?.('(max-width: 768px)')
function viewportChanged(){mobileViewport.value=viewportMedia?.matches??false;if(!mobileViewport.value)mobileMenu.value=false}




function followSystem(){}
const themeMedia=window.matchMedia?.('(prefers-color-scheme: dark)')


function feedbackValues(){
 const values:Record<string,string>={
  'operation-reason':reason.value,'operation-delta':String(delta.value),
  'mail-recipient':String(account.value?.uid??''),'mail-role':JSON.stringify([selectedRole.value,mailAttachments.value.length,mailGold.value,mailCurrencies.value]),
  'mail-gold':String(mailGold.value),'mail-message':message.value,'mail-title':mailTitle.value,'mail-items':JSON.stringify([mailAttachments.value.length,mailGold.value,mailCurrencies.value]),
  'gift-name':giftName.value,'gift-items':JSON.stringify([giftAttachments.value.length,giftGold.value,giftCurrencies.value]),'gift-gold':String(giftGold.value),'gift-message':giftMessage.value,'gift-title':giftTitle.value,
  'recipient-query':recipientSearch.value,'audit-uid':search.value,'lookup-id':lookupId.value,
 }
 for(const key of ['cera','cera_point','mileage']){values['mail-reward-'+key]=String(mailCurrencies.value[key]||0);values['gift-reward-'+key]=String(giftCurrencies.value[key]||0)}
 mailAttachments.value.forEach((item,index)=>values['mail-quantity-'+index]=JSON.stringify([item.id,item.quantity]))
 giftAttachments.value.forEach((item,index)=>values['gift-quantity-'+index]=JSON.stringify([item.id,item.quantity]))
 return values
}
watch(feedbackValues,(values,previous)=>{
 if(!Object.keys(fieldErrors.value).length)return
 const current=validationFor(feedbackScope.value)
 fieldErrors.value=Object.fromEntries(Object.entries(fieldErrors.value).flatMap(([key,message])=>{
  if(values[key]===previous[key])return [[key,message]]
  return current[key]?[[key,current[key]]]:[]
 }))
 if(!Object.keys(fieldErrors.value).length)error.value=''
 else error.value=new FormValidationError(fieldErrors.value).message
})

let timer:ReturnType<typeof setInterval>|undefined
let initialization:Promise<void>|undefined
let refreshingOverview=false
async function refreshOverview(){
 if(!logged.value||document.hidden||tab.value!=='overview'||busy.value||refreshingOverview)return
 const generation=sessionGeneration
 refreshingOverview=true
 try{await load()}catch(e){if(generation!==sessionGeneration)return;if(e instanceof ApiError&&e.status===401)clearSession();else if(tab.value==='overview')error.value=uncertainMessage(e)}
 finally{refreshingOverview=false}
}
function initialize(){
 if(initialization)return initialization
 if(!initializing.value)return Promise.resolve()
 initialization=(async()=>{
  try{
   const [methods,session]=await Promise.allSettled([api('/auth/methods'),api('/auth/me')])
   if(methods.status==='rejected')throw methods.reason
   totpRequired.value=methods.value.totp_required
   if(session.status==='rejected')throw session.reason
   sessionGeneration++;setCsrf(session.value.csrf);await drafts.bindSession(session.value.csrf);logged.value=true
   // Each route loads its own data. Authentication must not wait for the dashboard.
  }catch(e){if(!(e instanceof ApiError&&e.status===401))error.value=uncertainMessage(e)}
  finally{initializing.value=false}
  timer=setInterval(()=>{void refreshOverview()},30000)
 })()
 return initialization
}
onScopeDispose(()=>{clearInterval(timer);cancelTarget();cancelReads();reads.dispose();confirmation.release('ordinary')})


return {writeBusy,targetBusy,readBusy,runRead,cancelRead,cancelTarget,catalogRevision,operationOpen,activate,drafts,players,confirmation,supportDesk,supportUid,supportCase,mailCenterUid,mailCenterOperation,mailPane,mailTextOpen,detailSection,giftHistory,policyDialog,catalogTotal,catalogFilters,catalogFacets,advancedFilters,compareItems,compareWarning,fullCatalogFilters,updateCatalogFilters,toggleCompare,editPolicy,policyReauth,policyChanged,policyLabels,policyLabel,detailCharacNo,totpRequired,lookupId,lookedUp,initializing,fieldErrors,feedbackScope,toastDismissed,logged,busy,error,notice,tab,page,search,rows,overview,account,roles,roleResults,rolePage,roleQuery,roleMode,selectedRole,catalogMeta,playerRevision,playerPreferenceError,currentPlayerTarget,playerViews,visitPlayer,chooseSavedPlayer,username,password,code,reauthOpen,action,currency,delta,reason,message,mailGold,mailCurrencies,giftCurrencies,mailTitle,giftTitle,templateAdjusted,hasMailCurrencies,mailAttachments,giftAttachments,attachments,pendingId,preview,operationResult,idemKey,uncertain,category,pendingStatus,pendingChecked,giftGold,giftMessage,giftCategory,giftName,giftId,giftVersion,giftEnabled,templateId,templateVersion,icons,tabs,cleanupStates,cleanupFileStates,actionNames,currencyNames,categoryNames,sendable,loginState,onlineLabel,money,localTime,reveal,openCharacter,clearTarget,clearSession,requestBody,draft,focusProblem,validationFor,run,login,logout,reauth,load,searchRows,tableState,go,setTarget,copyMailDraft,correctOperation,detailAction,detailDraft,detailInspect,playerAction,supportCompensation,refreshAccount,select,loadRoles,queryCharacters,selectRole,preferenceRevision,preferenceWarning,preferenceChanged,rememberSelection,addItem,makePreview,confirmOperation,viewDeliveredMail,nextMailDraft,inspectOperation,queryResult,saveGift,resetGift,editGift,copyGift,copyGiftVersion,useGift,mobileViewport,confirmOpen,mobileMenu,collapsed,giftEditing,pickerOpen,recipientSearchType,recipientSearch,recipientResults,recipientQueried,pickerQuery,pickerRows,pickerPage,pickerCategory,mailAllowedOnly,catalogAllowedOnly,pickerAllowedOnly,theme,accountMode,healthTask,healthSchedule,openHealthTask,openScheduledChild,descriptions,feedbackMessage,shownResult,resultCommitted,role,totalQuantity,applyTheme,quickAmount,changeDirection,chooseOperation,findRecipient,searchAccounts,pickRecipient,openPicker,loadPicker,searchPicker,toMail,saveAsTemplate,inspectFromAudit,closePreview,restoreTheme,dismissMobile,viewportMedia,viewportChanged,followSystem,themeMedia,feedbackValues,timer,initialize}
})
export function useGmWorkspaceBindings(){const store=useGmWorkspace();return {...storeToRefs(store),runRead:store.runRead,cancelRead:store.cancelRead,cancelTarget:store.cancelTarget,activate:store.activate,updateCatalogFilters:store.updateCatalogFilters,toggleCompare:store.toggleCompare,editPolicy:store.editPolicy,policyReauth:store.policyReauth,policyChanged:store.policyChanged,policyLabel:store.policyLabel,visitPlayer:store.visitPlayer,chooseSavedPlayer:store.chooseSavedPlayer,sendable:store.sendable,loginState:store.loginState,onlineLabel:store.onlineLabel,money:store.money,localTime:store.localTime,reveal:store.reveal,openCharacter:store.openCharacter,clearTarget:store.clearTarget,clearSession:store.clearSession,requestBody:store.requestBody,focusProblem:store.focusProblem,validationFor:store.validationFor,run:store.run,login:store.login,logout:store.logout,reauth:store.reauth,load:store.load,searchRows:store.searchRows,go:store.go,setTarget:store.setTarget,copyMailDraft:store.copyMailDraft,correctOperation:store.correctOperation,detailAction:store.detailAction,detailDraft:store.detailDraft,detailInspect:store.detailInspect,playerAction:store.playerAction,supportCompensation:store.supportCompensation,refreshAccount:store.refreshAccount,select:store.select,loadRoles:store.loadRoles,queryCharacters:store.queryCharacters,selectRole:store.selectRole,preferenceChanged:store.preferenceChanged,rememberSelection:store.rememberSelection,addItem:store.addItem,makePreview:store.makePreview,confirmOperation:store.confirmOperation,viewDeliveredMail:store.viewDeliveredMail,nextMailDraft:store.nextMailDraft,inspectOperation:store.inspectOperation,queryResult:store.queryResult,saveGift:store.saveGift,resetGift:store.resetGift,editGift:store.editGift,copyGift:store.copyGift,copyGiftVersion:store.copyGiftVersion,useGift:store.useGift,openHealthTask:store.openHealthTask,openScheduledChild:store.openScheduledChild,applyTheme:store.applyTheme,quickAmount:store.quickAmount,changeDirection:store.changeDirection,chooseOperation:store.chooseOperation,findRecipient:store.findRecipient,searchAccounts:store.searchAccounts,pickRecipient:store.pickRecipient,openPicker:store.openPicker,loadPicker:store.loadPicker,searchPicker:store.searchPicker,toMail:store.toMail,saveAsTemplate:store.saveAsTemplate,inspectFromAudit:store.inspectFromAudit,closePreview:store.closePreview,restoreTheme:store.restoreTheme,dismissMobile:store.dismissMobile,viewportChanged:store.viewportChanged,followSystem:store.followSystem,feedbackValues:store.feedbackValues,initialize:store.initialize}}
