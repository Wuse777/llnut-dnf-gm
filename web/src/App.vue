<script setup lang="ts">
import WorkspaceNavigation from './components/WorkspaceNavigation.vue'
import WorkbenchHero from './components/WorkbenchHero.vue'
import UnlockCenter from './components/UnlockCenter.vue'
import OperationsDashboard from './components/OperationsDashboard.vue'
import ItemCard from './components/ItemCard.vue'
import {ref,computed,watch,nextTick,onMounted,onUnmounted} from 'vue'
import {readPendingOperation,usePendingOperation} from './pendingOperation'
import {api,setCsrf,uncertainMessage,ApiError,requests} from './api'
import Modal from './components/Modal.vue'
import MailCenter from './components/MailCenter.vue'
import RewardJobs from './components/RewardJobs.vue'
import Schedules from './components/Schedules.vue'
import SupportDesk from './components/SupportDesk.vue'
import EconomyReports from './components/EconomyReports.vue'
import UpgradeCheck from './components/UpgradeCheck.vue'
import Capabilities from './components/Capabilities.vue'
import MaintenanceCenter from './components/MaintenanceCenter.vue'
const supportDesk=ref<InstanceType<typeof SupportDesk>|null>(null)
const supportUid=ref(0),supportCase=ref<any>(null),mailCenterUid=ref(0)
import CurrencyRewardInputs from './components/CurrencyRewardInputs.vue'
import FavoriteButton from './components/FavoriteButton.vue'
import ItemCollection from './components/ItemCollection.vue'
import GiftVersions from './components/GiftVersions.vue'
import PlayerCenter from './components/PlayerCenter.vue'
import LiveSession from './components/LiveSession.vue'
import NativeControls from './components/NativeControls.vue'
import {supportNames,inventoryNames,nativeNames,operationStatus} from './nativeStatus'
const detailSection=ref('basic')
const giftHistory=ref(0)
import CharacterDetails from './components/CharacterDetails.vue'
import CatalogPolicy from './components/CatalogPolicy.vue'
const policyDialog=ref<any>(null),catalogTotal=ref(0),catalogFilters=ref<Record<string,unknown>>({})
function editPolicy(item?:any){policyDialog.value={item,filters:{...catalogFilters.value}}}
function policyReauth(){policyDialog.value=null;reauthOpen.value=true}
async function policyChanged(){preview.value=null;await run(load)}
const policyLabels:Record<string,string>={trial:'允许试发、未验证',verified:'已验证',blocked:'禁止发放'}
function policyLabel(i:any){return policyLabels[i.policy_state]||(sendable(i)?'允许试发、未验证':'禁止发放')}
const detailCharacNo=ref(0)
import ItemQueue from './components/ItemQueue.vue'
import FieldError from './components/FieldError.vue'
import FeedbackToast from './components/FeedbackToast.vue'
import {FormValidationError,assertValid,operationErrors,giftErrors,serverFieldErrors,type FieldErrors} from './validation'
const totpRequired=ref(false),lookupId=ref(''),lookedUp=ref<any>(null)
const initializing=ref(true)
const fieldErrors=ref<FieldErrors>({}),feedbackScope=ref(''),toastDismissed=ref(false)
const logged=ref(false),busy=ref(false),error=ref(''),notice=ref(''),tab=ref('overview'),page=ref(1),search=ref('')
const rows=ref<any[]>([]),overview=ref<any>(null),account=ref<any>(null),roles=ref<any[]>([]),roleResults=ref<any[]>([]),rolePage=ref(1),roleQuery=ref(''),roleMode=ref(false),selectedRole=ref(0),catalogMeta=ref<any>(null)
const username=ref('admin'),password=ref(''),code=ref(''),reauthOpen=ref(false)
const action=ref('currency'),currency=ref('cera'),delta=ref(100),reason=ref(''),message=ref('GM rewards')
const mailGold=ref(0)
const mailCurrencies=ref<Record<string,number>>({}),giftCurrencies=ref<Record<string,number>>({})
const mailTitle=ref(''),giftTitle=ref('')
const templateAdjusted=ref(false)
const hasMailCurrencies=computed(()=>Object.values(mailCurrencies.value).some(Boolean))
const mailAttachments=ref<any[]>([]),giftAttachments=ref<any[]>([])
const attachments=computed({get:()=>tab.value==='gifts'?giftAttachments.value:mailAttachments.value,set:(v:any[])=>{if(tab.value==='gifts')giftAttachments.value=v;else mailAttachments.value=v}})
const pendingId=ref(readPendingOperation())
const preview=ref<any>(null),operationResult=ref<any>(null),idemKey=ref(''),uncertain=ref(false),category=ref('')
const {pendingStatus,pendingChecked}=usePendingOperation(pendingId,logged,busy,(result)=>{operationResult.value=result;lookedUp.value=result;lookupId.value=result.operation_id;confirmOpen.value=false;notice.value='自动核对原操作：数据库已提交，没有重发。'})
const giftGold=ref(0),giftMessage=ref('GM rewards'),giftCategory=ref('')
const giftName=ref(''),giftId=ref(0),giftVersion=ref(0),giftEnabled=ref(true),templateId=ref<number|null>(null),templateVersion=ref<number|null>(null)
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
function openCharacter(id:number){detailSection.value='basic';notice.value='';error.value='';toastDismissed.value=true;detailCharacNo.value=id}
function clearTarget(){supportCase.value=null;detailCharacNo.value=0;confirmOpen.value=false;account.value=null;roles.value=[];selectedRole.value=0;preview.value=null;operationResult.value=null}
function clearSession(){mailTitle.value='';giftTitle.value='';mailCurrencies.value={};giftCurrencies.value={};giftHistory.value=0;giftGold.value=0;giftMessage.value='GM rewards';giftCategory.value='';detailCharacNo.value=0;policyDialog.value=null;toastDismissed.value=false;fieldErrors.value={};feedbackScope.value='';tableState.clear();logged.value=false;setCsrf('');clearTarget();rows.value=[];roleResults.value=[];mailAttachments.value=[];mailGold.value=0;giftAttachments.value=[];templateId.value=null;templateVersion.value=null;giftId.value=0;giftVersion.value=0;giftName.value='';giftEnabled.value=true;lookupId.value='';lookedUp.value=null;password.value='';code.value='';reason.value='';reauthOpen.value=false;notice.value='';requests.value=[];recipientResults.value=[];recipientSearch.value='';giftEditing.value=false;pickerOpen.value=false;reauthOpen.value=false;confirmOpen.value=false;mobileMenu.value=false}
function requestBody(){const mail=action.value==='mail';return {...(supportCase.value&&['currency','mail'].includes(action.value)?{support_case_id:supportCase.value.case_id}:{}),action:mail&&hasMailCurrencies.value?'reward':action.value,...(mail&&hasMailCurrencies.value?{currency_rewards:mailCurrencies.value}:{}),uid:account.value?.uid,charac_no:mail||action.value==='currency'?selectedRole.value||null:null,currency:action.value==='currency'?currency.value:null,delta:action.value==='currency'?delta.value:null,reason:reason.value.trim(),items:mail&&templateId.value===null?mailAttachments.value.map(({id,quantity})=>({id,quantity})):[],gold:mail?mailGold.value:0,message:mail?message.value:'GM rewards',mail_title:mail?mailTitle.value:'',template_id:mail?templateId.value:null,template_version:mail?templateVersion.value:null,...(mail&&templateId.value!==null&&templateAdjusted.value?{template_overrides:{items:mailAttachments.value.map(({id,quantity})=>({id,quantity})),gold:mailGold.value,message:message.value,mail_title:mailTitle.value,currency_rewards:mailCurrencies.value}}:{})}}
const draft=computed(()=>JSON.stringify(requestBody()))
watch(draft,()=>{operationResult.value=null;if(preview.value){preview.value=null;notice.value='参数已变化，旧预览已失效；请重新生成。原编号仍可查询。'}},{flush:'sync'})
watch([mailAttachments,mailGold,message,mailCurrencies,mailTitle],()=>{if(templateId.value!==null)templateAdjusted.value=true},{deep:true,flush:'sync'})
async function focusProblem(){
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
 busy.value=true;error.value='';notice.value='';toastDismissed.value=false;fieldErrors.value={};feedbackScope.value=scope??(pickerOpen.value?'picker':tab.value)
 let failed=false
 try{await fn()}catch(e){
  failed=true;error.value=uncertainMessage(e)
  if(e instanceof FormValidationError)fieldErrors.value=e.fields
  else if(e instanceof ApiError&&e.status===422)fieldErrors.value=serverFieldErrors(e.detail,feedbackScope.value)
  if(e instanceof ApiError&&e.status===401)clearSession()
  else if(e instanceof ApiError&&e.status===403&&e.message.includes('重新认证'))reauthOpen.value=true
 }finally{busy.value=false;if(failed)await focusProblem()}
}
async function login(){await run(async()=>{const d=await api('/auth/login','POST',{username:username.value,password:password.value,code:code.value});setCsrf(d.csrf);password.value='';code.value='';logged.value=true;tab.value='overview';await load()})}
async function logout(){await run(async()=>{await api('/auth/logout','POST');clearSession()})}
async function reauth(){await run(async()=>{await api('/auth/reauth','POST',{username:username.value,password:password.value,code:code.value});password.value='';code.value='';reauthOpen.value=false;notice.value='重新认证成功，有效期5分钟'})}
async function load(){
 if(tab.value==='overview'){overview.value=await api('/overview');return}
 if(tab.value==='accounts'&&roleMode.value){await loadRoles();return}
 const paths:Record<string,string>={accounts:'/accounts',online:'/online',catalog:'/catalog',mail:'/catalog',gifts:'/gift-templates',audit:'/audit'}
 let path=paths[tab.value]
 if(!path)return
 if(tab.value==='audit'){assertValid(validationFor('audit'));path+='?page='+page.value+'&uid='+(search.value||0)}
 else {path+='?page='+page.value;if(tab.value!=='online')path+='&q='+encodeURIComponent(search.value);if(['catalog','mail'].includes(tab.value)){path+='&category='+encodeURIComponent(category.value);if(tab.value==='mail'?mailAllowedOnly.value:catalogAllowedOnly.value)path+='&allowed_only=1'}}
 if(tab.value==='gifts')path+='&category='+encodeURIComponent(category.value)
 const d=await api(path);rows.value=d.items??[];catalogMeta.value=d.metadata??null;catalogTotal.value=d.total??0;if(tab.value==='catalog')catalogFilters.value={q:new URLSearchParams(path.split('?')[1]).get('q')||'',category:new URLSearchParams(path.split('?')[1]).get('category')||'',allowed_only:path.includes('allowed_only=1')}
}
async function searchRows(){page.value=1;roleMode.value=false;roleResults.value=[];await run(load)}
const tableState=new Map<string,{search:string,page:number,category:string,roleMode:boolean,rolePage:number,roleQuery:string,accountMode:string}>()
async function go(t:string){
 if(busy.value)return
 if(tab.value==='support'&&t!=='support'&&supportDesk.value&&!supportDesk.value.canNavigate()){mobileMenu.value=false;await nextTick();document.querySelector('.support-desk [role=alert]')?.scrollIntoView?.({block:'center'});return}
 tableState.set(tab.value,{search:search.value,page:page.value,category:category.value,roleMode:roleMode.value,rolePage:rolePage.value,roleQuery:roleQuery.value,accountMode:accountMode.value})
 const saved=tableState.get(t)
 tab.value=t;page.value=saved?.page??1;search.value=saved?.search??'';category.value=saved?.category??'';rows.value=[];catalogMeta.value=null
 roleMode.value=saved?.roleMode??false;rolePage.value=saved?.rolePage??1;roleQuery.value=saved?.roleQuery??'';accountMode.value=saved?.accountMode??'account';roleResults.value=[]
 notice.value='';mobileMenu.value=false;confirmOpen.value=false;if(t==='mail')action.value='mail'
 await run(load)
 await nextTick();if(!pickerOpen.value)window.scrollTo?.({top:0,behavior:'instant'})
}
async function setTarget(uid:number,role=0){supportCase.value=null;const a=await api('/accounts/'+uid);const r=(await api('/characters?uid='+uid)).items;account.value=a;roles.value=r;selectedRole.value=role;if(['accounts','online'].includes(tab.value))action.value='currency';preview.value=null;operationResult.value=null;notice.value='已选择账号 #'+uid+' '+a.accountname;recipientResults.value=[];await reveal(tab.value==='mail'?'#recipient':'[data-testid=account-operations]')}
async function copyMailDraft(data:any){
 if(busy.value||pendingId.value){error.value='当前有未完成的操作，请先查询其结果。';return}
 await go('mail')
 await run(async()=>{
  await setTarget(data.uid,data.charac_no)
  mailAttachments.value=data.items.map((i:any)=>({...i,name:'#'+i.id}))
  mailCurrencies.value={...(data.currency_rewards||{})};mailGold.value=data.gold||0;message.value=data.message??'GM rewards';mailTitle.value=data.mail_title??'';reason.value=data.reason||''
  templateId.value=null;templateVersion.value=null;action.value='mail';preview.value=null
  notice.value='已生成新的发放草稿，尚未发送；请核对目标、数量和原因后预览确认。'
 })
}
async function correctOperation(record:any){
 if(busy.value||pendingId.value)return
 const data=record.request
 if(['mail','reward'].includes(data.action)){await copyMailDraft(data);reason.value='纠正操作 '+record.operation_id;return}
 await go('accounts')
 await run(async()=>{await setTarget(data.uid,data.charac_no||0);action.value=data.action;if(data.action==='currency'){currency.value=data.currency;delta.value=0}reason.value='纠正操作 '+record.operation_id;notice.value='已建立纠正草稿，不会撤销旧记录。请自行填写正确的变更金额或操作，再预览确认。'})
}
async function detailAction(data:{action:string,uid:number,charac_no:number}){
 if(busy.value||pendingId.value)return
 detailCharacNo.value=0
 await go(data.action==='mail'?'mail':'accounts')
 await playerAction(data)
}
async function detailDraft(data:any){if(busy.value||pendingId.value)return;detailCharacNo.value=0;await copyMailDraft(data)}
async function detailInspect(id:string){if(busy.value||pendingId.value)return;detailCharacNo.value=0;await inspectOperation(id)}
async function playerAction(data:{action:string,uid:number,charac_no?:number}){
 if(busy.value||pendingId.value)return
 if(data.action==='support'){supportUid.value=data.uid;await go('support');return}
 if(data.action==='support-mail'){mailCenterUid.value=data.uid;await go('mail-center');return}
 if(data.action==='detail'||data.action==='unlock'){detailSection.value=data.action==='unlock'?'unlock':'basic';detailCharacNo.value=data.charac_no||0;return}
 if(data.action==='mail')await go('mail')
 else if(['support','economy'].includes(tab.value))await go('accounts')
 await run(async()=>{await setTarget(data.uid,data.charac_no||0);action.value=data.action;await reveal(data.action==='mail'?'#recipient':'[data-testid=account-operations]')})
}
async function supportCompensation(data:any){
 if(busy.value||pendingId.value)return
 await go(data.kind==='mail'?'mail':'accounts')
 await run(async()=>{
  await setTarget(data.uid,data.charac_no||0)
  supportCase.value={case_id:data.case_id,title:data.title,uid:data.uid,charac_no:data.charac_no,compensation_count:data.compensation_count}
  action.value=data.kind;delta.value=0;reason.value=('问题 #'+data.case_id+'：'+data.title).slice(0,200)
  if(data.kind==='mail'){mailAttachments.value=[];mailGold.value=0;mailCurrencies.value={};templateId.value=null;templateVersion.value=null;mailTitle.value='';message.value='问题补偿'}
  notice.value='已建立关联问题的草稿，尚未发奖。请填写正确的金额或物品后预览。'
 })
}
async function refreshAccount(){if(account.value)await run(async()=>{account.value=await api('/accounts/'+account.value.uid);notice.value='账号余额与在线状态已刷新'})}
async function select(a:any){await run(()=>setTarget(a.uid))}
async function loadRoles(){roleResults.value=(await api('/characters?q='+encodeURIComponent(roleQuery.value)+'&page='+rolePage.value)).items}
async function queryCharacters(){await run(async()=>{roleMode.value=true;rolePage.value=1;roleQuery.value=search.value;rows.value=[];await loadRoles();notice.value='角色搜索结果：点击未删除角色可管理所属账号'})}
async function selectRole(r:any){if(r.delete_flag)return;await run(()=>setTarget(r.uid,r.charac_no))}
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

async function makePreview(){await run(async()=>{if(pendingId.value)throw new Error('上一笔提交结果尚未确认，请先按原编号查询，不要创建替代操作');preview.value=null;assertValid(validationFor('operation'));const fingerprint=draft.value;const d=await api('/operations/preview','POST',requestBody());if(fingerprint!==draft.value)throw new Error('等待期间表单已变化，请重新预览');preview.value=d;lookupId.value=d.operation_id;idemKey.value=crypto.randomUUID();uncertain.value=false;operationResult.value=null;confirmOpen.value=true},'operation')}
async function confirmOperation(){
 if(uncertain.value||!preview.value)return
 await run(async()=>{
  const op=preview.value.operation_id;uncertain.value=true;pendingId.value=op
  try{
   operationResult.value=await api('/operations/'+op+'/confirm','POST',{idempotency_key:idemKey.value});pendingId.value=''
  }catch(e){
   if(e instanceof ApiError&&e.status>=400&&e.status<500){pendingId.value='';uncertain.value=false;if(e.status===409)preview.value=null}
   throw e
  }
  confirmOpen.value=false;notice.value='操作已提交并记录审计。未验证游戏内效果，不会自动重发。'
  try{account.value=await api('/accounts/'+account.value.uid)}catch{notice.value+='余额快照刷新失败，可手动刷新。'}
 },'operation')
}
async function inspectOperation(id:string){lookupId.value=id;await run(async()=>{assertValid(validationFor('lookup'));lookedUp.value=null;lookedUp.value=await api('/operations/'+id);lookupId.value=id;if(lookedUp.value.status==='committed'&&pendingId.value===id)pendingId.value='';notice.value='已读取原操作结果，没有重放写入';await reveal('#operation-lookup')},'lookup')}
async function queryResult(){if(!preview.value)return;await run(async()=>{operationResult.value=await api('/operations/'+preview.value.operation_id);if(operationResult.value.status==='committed'){if(pendingId.value===preview.value.operation_id)pendingId.value='';confirmOpen.value=false;}notice.value='已查询原编号；未重放操作'})}
async function saveGift(){await run(async()=>{assertValid(validationFor('gift'));const p=giftId.value?'/gift-templates/'+giftId.value:'/gift-templates';const saved=await api(p,giftId.value?'PUT':'POST',{...(Object.values(giftCurrencies.value).some(Boolean)?{currency_rewards:giftCurrencies.value}:{}),gold:giftGold.value,message:giftMessage.value,mail_title:giftTitle.value,category:giftCategory.value,name:giftName.value.trim(),enabled:giftEnabled.value,expected_version:giftVersion.value,items:giftAttachments.value.map(({id,quantity})=>({id,quantity}))});giftId.value=saved.id;giftVersion.value=saved.version;notice.value='模板 #'+saved.id+' 已保存为 v'+saved.version+'；历史版本保留';if(tab.value==='gifts')await load()},'gift')}
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
function applyTheme(value:string){theme.value=value;const resolved=value==='system'?(window.matchMedia?.('(prefers-color-scheme: dark)').matches?'dark':'light'):value;document.documentElement.dataset.theme=resolved;try{localStorage.setItem('dnf-gm.theme',value)}catch{}}
function quickAmount(n:number){delta.value=(delta.value<0?-1:1)*n}
function changeDirection(negative:boolean){delta.value=(negative?-1:1)*Math.abs(delta.value||100)}
function chooseOperation(value:string){if(busy.value||pendingId.value)return;action.value=value;confirmOpen.value=false;if(value==='mail')void go('mail')}
async function findRecipient(){await run(async()=>{recipientResults.value=[];recipientQueried.value=false;assertValid(validationFor('recipient'));recipientResults.value=(await api((recipientSearchType.value==='role'?'/characters':'/accounts')+'?q='+encodeURIComponent(recipientSearch.value.trim())+'&page=1')).items;recipientQueried.value=true},'recipient')}
async function searchAccounts(){if(accountMode.value==='role')await queryCharacters();else await searchRows()}
async function pickRecipient(a:any){if(a.delete_flag)return;await run(()=>setTarget(a.uid,a.charac_no||0));recipientQueried.value=false}
async function openPicker(){pickerOpen.value=true;pickerQuery.value='';pickerPage.value=1;await run(loadPicker)}
async function loadPicker(){pickerRows.value=(await api('/catalog?q='+encodeURIComponent(pickerQuery.value)+'&category='+pickerCategory.value+'&page='+pickerPage.value+(pickerAllowedOnly.value?'&allowed_only=1':''))).items}
async function searchPicker(){pickerPage.value=1;await run(loadPicker)}
async function toMail(){await go('mail')}
async function saveAsTemplate(){giftCurrencies.value={...mailCurrencies.value};giftEditing.value=true;giftId.value=0;giftVersion.value=0;giftName.value='';giftEnabled.value=true;giftGold.value=mailGold.value;giftMessage.value=message.value;giftTitle.value=mailTitle.value;giftCategory.value='';giftAttachments.value=mailAttachments.value.map(i=>({...i}));await go('gifts');await reveal('#gift-editor')}
async function inspectFromAudit(id:string){await inspectOperation(id)}
function closePreview(){if(!busy.value)confirmOpen.value=false}
function restoreTheme(){let t='light';try{t=localStorage.getItem('dnf-gm.theme')||'light'}catch{}applyTheme(['light','white','dark','system'].includes(t)?t:'light')}
function dismissMobile(e:KeyboardEvent){
 if(!mobileMenu.value)return
 if(e.key==='Escape'){mobileMenu.value=false;return}
 if(e.key==='Tab'){const buttons=Array.from(document.querySelectorAll<HTMLElement>('aside button:not(:disabled)'));const first=buttons[0],last=buttons[buttons.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}
}
watch(mobileMenu,async(open)=>{await nextTick();(document.querySelector(open?'aside .mobile-close':'.mobile-toggle') as HTMLElement|null)?.focus()})
const viewportMedia=window.matchMedia?.('(max-width: 768px)')
function viewportChanged(){mobileViewport.value=viewportMedia?.matches??false;if(!mobileViewport.value)mobileMenu.value=false}
onMounted(()=>viewportMedia?.addEventListener?.('change',viewportChanged))
onUnmounted(()=>viewportMedia?.removeEventListener?.('change',viewportChanged))
onMounted(()=>window.addEventListener('keydown',dismissMobile))
onUnmounted(()=>window.removeEventListener('keydown',dismissMobile))
function followSystem(){if(theme.value==='system')applyTheme('system')}
restoreTheme()
const themeMedia=window.matchMedia?.('(prefers-color-scheme: dark)')
onMounted(()=>themeMedia?.addEventListener?.('change',followSystem))
onUnmounted(()=>themeMedia?.removeEventListener?.('change',followSystem))

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
onMounted(async()=>{try{totpRequired.value=(await api('/auth/methods')).totp_required;const d=await api('/auth/me');setCsrf(d.csrf);logged.value=true;await run(load)}catch(e){if(!(e instanceof ApiError&&e.status===401))error.value=uncertainMessage(e)}finally{initializing.value=false}timer=setInterval(()=>{if(logged.value&&!document.hidden&&tab.value==='overview'&&!busy.value)void run(load)},30000)})
onUnmounted(()=>clearInterval(timer))

</script>

<template>
<div v-if="initializing" class="login-shell"><section class="login-card" role="status"><span class="spinner"/> 正在恢复安全会话…</section></div>
<div v-else-if="!logged" class="login-shell login-illustrated">
  <div class="login-theme"><select aria-label="界面主题" :value="theme" @change="applyTheme(($event.target as HTMLSelectElement).value)"><option value="light">浅色 · 暖灰</option><option value="white">纯白</option><option value="dark">深色</option><option value="system">跟随系统</option></select></div>
  <form class="login-card" @submit.prevent="login"><div class="login-mark">G</div><h1>DNF GM 控制台</h1><p>清风 1031 · 服务器管理</p><label>管理员账号<input v-model="username" autocomplete="username" required></label><label>管理员密码<input v-model="password" type="password" autocomplete="current-password" required></label><label v-if="totpRequired">动态验证码 / 恢复码<input v-model="code" autocomplete="one-time-code" required></label><button class="primary full" :disabled="busy">{{busy?'正在认证…':'安全登录 →'}}</button><p v-if="error" role="alert" class="error">{{error}}</p><small>独立管理员 · 密码登录 · 操作审计</small></form>
</div>
<div v-else class="shell" :class="{'is-collapsed':collapsed,'mobile-open':mobileMenu}">
  <button v-if="mobileMenu" class="sidebar-backdrop" aria-label="关闭导航" @click="mobileMenu=false"/>
  <aside aria-label="主导航" :inert="(mobileViewport&&!mobileMenu)||undefined"><div class="brand"><div class="brand-mark">G</div><div class="brand-copy"><b>DNF GM</b><small>清风 1031 管理控制台</small></div><button class="mobile-close icon-button ghost" aria-label="收起移动导航" @click="mobileMenu=false">×</button></div><WorkspaceNavigation :tabs="tabs" :icons="icons" :current="tab" :collapsed="collapsed" :busy="busy" :mail-count="mailAttachments.length" @choose="go"/><div class="sidebar-foot"><div class="admin-badge"><span class="avatar">A</span><div><b>admin</b><small>超级管理员 · 密码登录</small></div></div><button class="ghost" @click="reauthOpen=true" :disabled="busy">重新认证</button><button class="ghost" @click="logout" :disabled="busy">退出登录</button><small class="sidebar-note">写入留痕 · 无通用 SQL / Shell</small></div></aside>
  <button class="collapse-handle" :aria-label="collapsed?'展开侧栏':'收起侧栏'" :aria-expanded="!collapsed" @click="collapsed=!collapsed">{{collapsed?'›':'‹'}}</button>
  <div class="top-controls"><button class="icon-button mobile-toggle" aria-label="打开导航" @click="mobileMenu=true">☰</button><span class="shell-label">DNF / 管理工作空间</span><div class="header-actions"><select aria-label="界面主题" :value="theme" @change="applyTheme(($event.target as HTMLSelectElement).value)"><option value="light">浅色 · 暖灰</option><option value="white">纯白</option><option value="dark">深色</option><option value="system">跟随系统</option></select><button v-if="tab!=='reward-jobs'" class="ghost refresh-control" @click="run(load)" :disabled="busy">{{busy?'处理中…':'↻ 刷新数据'}}</button></div></div>
  <main :aria-busy="busy" :inert="mobileMenu||undefined"><header class="page-header"><div><h1>{{tabs.find(x=>x[0]===tab)?.[1]}}</h1><p>{{descriptions[tab]}}</p></div><button v-if="account&&tab!=='accounts'&&tab!=='mail'" class="target-chip" :disabled="busy" @click="go('accounts')">当前目标：{{account.accountname}} #{{account.uid}} ↗</button></header>
  <details class="release-disclosure"><summary><span class="pill">公开测试版</span><span>数据库结果与游戏内效果可能不同</span><span class="disclosure-toggle">使用说明</span></summary><p>未经完整游戏客户端验收；数据库提交不等于客户端已领取或生效。索引物品按策略开放试发，不代表已验证；批量任务逐角色提交；存档回收使用专用维护流程；玩家私信仍待适配。</p></details>
<div v-if="pendingId" class="warning banner"><div><b>提交结果待确认</b><p class="mono">{{pendingId}}</p><small>禁止新建替代操作；自动核对原编号，不重发。刷新网页后仍保留待确认编号。</small><p v-if="pendingStatus">{{pendingStatus}}<small v-if="pendingChecked"> · {{new Date(pendingChecked).toLocaleTimeString()}}</small></p></div><button :disabled="busy" @click="inspectOperation(pendingId)">查询待确认操作</button></div>

  <p v-if="supportCase&&['accounts','mail'].includes(tab)" class="notice" role="status">关联问题：{{supportCase.title}} · #{{supportCase.case_id}}。已关联补偿 {{supportCase.compensation_count}} 笔，请先核对历史。提交成功后会在同一事务内记录关联，不自动解决问题。<button :disabled="busy||!!pendingId" @click="supportCase=null">解除此草稿关联</button></p>
  <div class="page-body" :key="tab">
  <GiftVersions v-if="giftHistory" :template-id="giftHistory" @close="giftHistory=0" @copy="copyGiftVersion" />
  <MaintenanceCenter v-if="tab==='maintenance'" @expired="clearSession" @reauth="reauthOpen=true" @navigate="go($event)"/>
  <Capabilities v-if="tab==='capabilities'" @expired="clearSession" @reauth="reauthOpen=true" @navigate="go($event)"/>
  <UpgradeCheck v-if="tab==='compatibility'" @expired="clearSession" @navigate="go($event)" @inspect="inspectOperation"/>
  <EconomyReports v-if="tab==='economy'" @expired="clearSession" @inspect="inspectOperation" @player="playerAction({action:'currency',uid:$event})" @support="playerAction({action:'support',uid:$event})"/>
  <SupportDesk ref="supportDesk" v-if="tab==='support'" :uid="supportUid" @reauth="reauthOpen=true" @expired="clearSession" @action="playerAction" @inspect="inspectOperation" @compensate="supportCompensation"/>
  <NativeControls v-if="tab==='native-controls'" :account="account" @reauth="reauthOpen=true" @expired="clearSession" @select-player="go('accounts')"/>
  <OperationsDashboard v-if="tab==='operations-dashboard'" @reauth="reauthOpen=true" @task="openHealthTask"/>
  <UnlockCenter v-if="tab==='unlock-center'" @reauth="reauthOpen=true" @inspect="inspectOperation"/>
  <Schedules v-if="tab==='schedules'" :initial-schedule="healthSchedule" @opened="healthSchedule=''" @reauth="reauthOpen=true" @expired="clearSession" @child="openScheduledChild" />
  <RewardJobs v-if="tab==='reward-jobs'" :initial-job="healthTask" @opened="healthTask=''" @reauth="reauthOpen=true" @inspect="inspectOperation" />
  <MailCenter v-if="tab==='mail-center'" :uid="mailCenterUid" @draft="copyMailDraft" />
  <template v-if="tab==='overview'">
    <WorkbenchHero :busy="busy" @navigate="go"/>
    <template v-if="overview"><div class="metrics"><article><span>注册账号</span><strong>{{money(overview.counts.accounts)}}</strong><small>累计注册</small></article><article><span>游戏角色</span><strong>{{money(overview.counts.characters)}}</strong><small>未删除角色</small></article><article><span>当前在线</span><strong class="mint">{{money(overview.counts.online_accounts)}}</strong><small>登录状态表统计</small></article><article><span>状态采集</span><strong :class="overview.server.fresh?'mint':'amber'">{{overview.server.fresh?'实时':'未知'}}</strong><small>{{overview.server.collected_at?new Date(overview.server.collected_at*1000).toLocaleString('zh-CN'):'无有效快照'}}</small></article></div>
    <div class="two-col"><section class="panel"><div class="section-title"><h2>服务器资源</h2><span class="pill">15s 采集 · 30s 刷新</span></div><template v-if="overview.server.fresh"><div class="resource" v-for="[key,label,unit] in [['cpu_percent','CPU 使用率','%'],['mem_available_mib','可用物理内存','MiB'],['swap_free_mib','Swap 剩余','MiB'],['disk_free_gib','磁盘剩余','GiB']]" :key="key"><span>{{label}}</span><b>{{overview.server[key]??'未知'}} <small>{{unit}}</small></b></div></template><p v-else class="empty">{{overview.server.reason}}。过期数据不显示为正常。</p></section><section class="panel"><div class="section-title"><h2>核心服务</h2><span class="pill">只读监控</span></div><div v-if="overview.server.fresh" class="service-grid"><div v-for="(v,k) in overview.server.services??{}" :key="k" class="service-item"><span>{{k}}</span><span class="status-badge" :class="v?'success':'failure'">{{v?'运行中':'异常 / 未知'}}</span></div></div><p class="empty" v-else>状态未知，等待有效快照。</p></section></div>
    <section class="panel"><div class="section-title"><h2>常用操作</h2><span class="muted">先确认目标，再提交</span></div><div class="shortcut-grid"><button @click="go('accounts')"><b>管理玩家账号 →</b><small>查角色、增减余额、管理封禁</small></button><button @click="go('mail')"><b>发放物品邮件 →</b><small>指定收件人，组合奖励附件</small></button><button @click="go('audit')"><b>核对操作记录 →</b><small>查流水与邮件数据库状态</small></button></div><details><summary>运行边界与目标范围</summary><p>已启用：{{overview.enabled_writes?.map((x:string)=>actionNames[x]||x).join(' / ')||'全部关闭'}} · 目标：{{overview.test_uids?.length?overview.test_uids.join(', '):'全部账号'}}</p><p class="muted">{{overview.online_definition}}。后台无 Docker、Mihomo、CPA 重启权限。</p></details></section></template><div v-else class="empty">正在读取服务器概览…</div>
  </template>

  <template v-if="tab==='accounts'||tab==='online'">
    <section class="panel" id="player-search"><div class="section-title"><h2>{{tab==='online'?'在线账号列表':'查找玩家'}}</h2><span class="muted">{{tab==='online'?'在线以登录状态表为准':'支持账号名、UID、角色名或角色编号'}}</span></div><form v-if="tab==='accounts'" class="toolbar" @submit.prevent="searchAccounts"><select v-model="accountMode" aria-label="搜索类型" :disabled="busy"><option value="account">账号 / UID</option><option value="role">角色名 / 编号</option></select><input v-model="search" aria-label="搜索条件" :placeholder="accountMode==='role'?'输入角色名或角色编号':'输入账号名或 UID'" :disabled="busy"><button class="primary" :disabled="busy">查询</button><button type="button" :disabled="busy" @click="accountMode='role';queryCharacters()">按角色搜索</button></form>
    <div v-if="roleMode" class="role-grid"><article v-for="r in roleResults" :key="r.charac_no" class="role-card"><b>{{r.charac_name}}</b><small>#{{r.charac_no}} · UID {{r.uid}} · Lv.{{r.lev}}</small><span v-if="r.delete_flag" class="status-badge failure">已删除（不可操作）</span><div class="role-actions"><button :disabled="busy" @click="openCharacter(r.charac_no)">查看详情</button><button :disabled="busy||!!r.delete_flag" @click="selectRole(r)">管理所属账号 →</button></div></article><p v-if="!roleResults.length&&!busy" class="empty">未找到角色，请换一个关键词。</p></div>
    <div class="table-wrap" v-else><table><thead><tr><th>UID / 账号</th><th>点券</th><th>代币券</th><th>积分</th><th>状态 / 频道</th><th class="align-right">操作</th></tr></thead><tbody><tr v-for="r in rows" :key="r.uid" :class="{'selected-row':account?.uid===r.uid}"><td><b>{{r.accountname}}</b><small class="cell-note">UID {{r.uid}}</small></td><td class="numeric">{{money(r.cera)}}</td><td class="numeric">{{money(r.cera_point)}}</td><td class="numeric">{{money(r.mileage)}}</td><td><span class="status-badge" :class="r.login_status===1?'success':'neutral'">{{r.login_status===1?'在线':r.login_status===0?'离线':'未知'}}</span><small class="cell-note">频道 {{r.channel??'—'}}</small></td><td class="align-right"><button :disabled="busy" @click="select(r)">管理 →</button></td></tr></tbody></table><p v-if="!rows.length&&!busy" class="empty">{{tab==='online'?'当前没有在线账号':'未找到账号，试试角色搜索或其他关键词。'}}</p></div>
    <div class="pagination"><button :disabled="busy||(roleMode?rolePage:page)===1" @click="roleMode?(rolePage--,run(loadRoles)):(page--,run(load))">上一页</button><span>第 {{roleMode?rolePage:page}} 页 · 本页 {{roleMode?roleResults.length:rows.length}} 条</span><button :disabled="busy||(roleMode?roleResults:rows).length<50" @click="roleMode?(rolePage++,run(loadRoles)):(page++,run(load))">下一页</button></div></section>
    <section v-if="account" class="panel account-workspace" data-testid="account-operations"><div class="account-heading"><div class="avatar large">{{account.accountname?.slice(0,1).toUpperCase()}}</div><div><h2>{{account.accountname}} <span class="pill">UID {{account.uid}}</span></h2><p class="muted">账号级余额与登录权限 · 角色邮件在邮件工作区发放</p></div><button class="ghost" :disabled="busy" @click="refreshAccount">刷新余额</button></div><div class="balance-strip"><div><span>点券</span><strong>{{money(account.cera)}}</strong></div><div><span>代币券</span><strong>{{money(account.cera_point)}}</strong></div><div><span>积分</span><strong>{{money(account.mileage)}}</strong></div><div><span>登录表状态</span><b>{{onlineLabel(account)}}</b></div></div><LiveSession :uid="account.uid" /><button class="ghost" @click="go('native-controls')">管理此账号的游戏内控制</button><div class="operation-tabs" aria-label="账号操作"><button :class="{active:action==='currency'}" :disabled="busy||!!pendingId" @click="chooseOperation('currency')">余额变更</button><button :disabled="busy||!!pendingId" @click="chooseOperation('mail')">发送物品邮件 ↗</button><button :class="{active:action==='ban'||action==='unban'}" :disabled="busy||!!pendingId" @click="chooseOperation('ban')">封禁管理</button></div>
    <div class="form-grid" v-if="action==='currency'"><label>币种<select v-model="currency" :disabled="busy"><option value="cera">点券</option><option value="cera_point">代币券</option><option value="mileage">积分</option></select></label><div class="field"><span class="field-label">变更方向</span><div class="segmented"><button :class="{active:delta>=0}" :disabled="busy" @click="changeDirection(false)">充值 +</button><button :class="{active:delta<0}" :disabled="busy" @click="changeDirection(true)">扣减 −</button></div></div><label><span>变更金额 <em class="required-tag">必填</em></span><input id="operation-delta" v-model.number="delta" type="number" step="1" aria-required="true" :aria-invalid="!!fieldErrors['operation-delta']" :aria-describedby="fieldErrors['operation-delta']?'operation-delta-error':undefined" :disabled="busy"><small>正数充值，负数扣减</small><FieldError id="operation-delta-error" :message="fieldErrors['operation-delta']"/></label><div class="wide quick-amounts"><span>快捷金额</span><button v-for="n in [100,1000,10000,100000]" :key="n" :disabled="busy" @click="quickAmount(n)">{{money(n)}}</button></div></div>
    <div v-else-if="action==='ban'||action==='unban'" class="form-grid"><label>处罚操作<select v-model="action" aria-label="处罚操作" :disabled="busy"><option value="ban">封禁后续登录</option><option value="unban">解除本后台封禁</option></select></label><p class="field-hint wide">不立即踢出在线玩家；不能覆盖或解除其他来源处罚。</p></div>
    <template v-if="action==='currency'||action==='ban'||action==='unban'"><label class="reason-field"><span>操作原因 <em class="required-tag">必填</em></span><input id="operation-reason" v-model="reason" aria-required="true" :aria-invalid="!!fieldErrors['operation-reason']" :aria-describedby="fieldErrors['operation-reason']?'operation-reason-error':undefined" placeholder="必填，写入不可删除审计" maxlength="200" :disabled="busy"><FieldError id="operation-reason-error" :message="fieldErrors['operation-reason']"/><span class="button-row"><button v-for="preset in ['活动奖励','问题补偿','管理员测试','纠正先前操作']" :key="preset" type="button" :disabled="busy||!!pendingId" @click="reason=preset">{{preset}}</button></span></label><p v-if="error&&feedbackScope==='operation'" class="submit-error">{{error}}</p><p v-else-if="notice&&feedbackScope==='operation'" class="submit-success">{{notice}}</p><div class="action-footer"><span class="muted">下一步只生成预览，不会立即写入。</span><button class="primary" :disabled="busy" @click="makePreview">生成预览 →</button></div></template><button v-else class="primary" :disabled="busy" @click="toMail">前往邮件工作区 →</button>
    <PlayerCenter v-if="account" :account="account" :busy="busy||!!pendingId" @action="playerAction" @draft="copyMailDraft" @inspect="inspectOperation" @correction="correctOperation" /></section><section v-else class="selection-guide"><h3>先选择一位玩家</h3><p>点击列表中的“管理”，余额变更与封禁操作将在这里展开。</p></section>
  </template>

  <template v-if="tab==='mail'">
    <div class="workflow-steps"><span :class="{done:account&&role}"><b>1</b>选择收件人</span><i>—</i><span :class="{done:mailAttachments.length}"><b>2</b>组合奖励</span><i>—</i><span><b>3</b>预览并确认</span></div>
    <section class="panel recipient-panel" id="recipient"><div id="mail-recipient" tabindex="-1" :aria-invalid="!!fieldErrors['mail-recipient']" :aria-describedby="fieldErrors['mail-recipient']?'mail-recipient-error':undefined"><FieldError id="mail-recipient-error" :message="fieldErrors['mail-recipient']"/></div><div class="section-title"><h2>收件人</h2><span class="pill">指定单角色 · 不群发</span></div><form class="toolbar" @submit.prevent="findRecipient"><select v-model="recipientSearchType" aria-label="收件人搜索类型" :disabled="busy" @change="recipientResults=[];recipientQueried=false"><option value="account">账号 / UID</option><option value="role">角色名 / 编号</option></select><input id="recipient-query" v-model="recipientSearch" :aria-invalid="!!(fieldErrors['recipient-query']||fieldErrors['mail-recipient'])" :aria-describedby="fieldErrors['recipient-query']?'recipient-query-error':fieldErrors['mail-recipient']?'mail-recipient-error':undefined" aria-label="查找收件账号" :placeholder="recipientSearchType==='role'?'输入角色名或编号':'输入账号名或 UID'" :disabled="busy"><button :disabled="busy">{{recipientSearchType==='role'?'查找角色':'查找账号'}}</button><button type="button" class="ghost" :disabled="busy" @click="go('accounts')">按角色查找 ↗</button></form><FieldError id="recipient-query-error" :message="fieldErrors['recipient-query']"/><p v-if="error&&feedbackScope==='recipient'" class="submit-error">{{error}}</p><div v-if="recipientQueried" class="recipient-options"><button v-for="r in recipientResults" :key="r.uid" :disabled="busy||!!r.delete_flag" @click="pickRecipient(r)">{{r.charac_no?r.charac_name+' #'+r.charac_no:r.accountname}} · UID {{r.uid}}{{r.delete_flag?'（已删除）':''}}</button><p v-if="!recipientResults.length" class="empty">未找到账号，请换一个关键词。</p></div><div v-if="account" class="recipient-context"><div><span class="muted">当前账号</span><b>{{account.accountname}} <small>UID {{account.uid}}</small></b><span class="status-badge" :class="loginState(account)===1?'success':'neutral'">{{onlineLabel(account)}}</span></div><label><span>收件角色 <em class="required-tag">必填</em></span><select id="mail-role" v-model.number="selectedRole" aria-required="true" :aria-invalid="!!fieldErrors['mail-role']" :aria-describedby="fieldErrors['mail-role']?'mail-role-error':undefined" aria-label="收件角色" :disabled="busy"><option :value="0">请选择收件角色</option><option v-for="r in roles" :key="r.charac_no" :value="r.charac_no" :disabled="!!r.delete_flag">{{r.charac_name}} #{{r.charac_no}} · Lv.{{r.lev}}{{r.delete_flag?'（已删除）':''}}</option></select><FieldError id="mail-role-error" :message="fieldErrors['mail-role']"/><button v-if="selectedRole" type="button" class="ghost" :disabled="busy" @click="openCharacter(selectedRole)">查看收件角色详情</button></label></div><p v-else class="field-hint">尚未选择收件账号。可直接搜索，也可从“账号与角色”带入目标。</p><p v-if="account&&!roles.some(r=>!r.delete_flag)" class="warning">该账号没有可用角色，不能发送物品邮件。</p></section>
    <div class="mail-workbench"><section class="panel catalog-panel"><div class="section-title"><h2>选择物品</h2><button class="ghost" :disabled="busy" @click="go('gifts')">使用礼包模板 ↗</button></div><ItemCollection :revision="preferenceRevision" :disabled="busy" @select="addItem" @changed="preferenceChanged"/><p v-if="preferenceWarning" class="submit-error" role="status">{{preferenceWarning}}</p><form class="toolbar" @submit.prevent="searchRows"><input v-model="search" aria-label="物品搜索" placeholder="物品名称或编号" :disabled="busy"><select v-model="category" aria-label="物品分类" :disabled="busy" @change="searchRows"><option value="">全部类型</option><option value="equipment">装备</option><option value="material">材料</option><option value="consumable">消耗品</option><option value="special">特殊 / 时装 / 宠物</option></select><button class="primary" :disabled="busy">查询</button></form><label class="checkbox-field"><input type="checkbox" v-model="mailAllowedOnly" :disabled="busy" @change="searchRows">仅看可发放物品</label><p class="field-hint">发放数量不按PVF堆叠上限限制；装备、时装和宠物按数量逐件投递。全部索引物品默认可发放，可在物品索引中单独停用；游戏内领取效果需自行核对。</p><div class="table-wrap"><table><thead><tr><th>物品 / 编号</th><th>类型</th><th>发放数量</th><th></th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td><ItemCard :item="r"/></td><td>{{categoryNames[r.category]||r.category}}<small class="cell-note">{{policyLabel(r)}}</small></td><td>不限（字段范围内）</td><td class="align-right"><FavoriteButton :item="r" :disabled="busy" @changed="preferenceChanged"/><button :disabled="busy||!sendable(r)" :title="sendable(r)?'加入待发清单':r.policy_reason||'策略禁止或不支持'" @click="addItem(r)">{{sendable(r)?'加入清单':'不可发放'}}</button></td></tr></tbody></table><p v-if="!rows.length&&!busy" class="empty">未找到物品，试试名称、编号或其他分类。</p></div><div class="pagination"><button :disabled="page===1||busy" @click="page--;run(load)">上一页</button><span>第 {{page}} 页</span><button :disabled="rows.length<50||busy" @click="page++;run(load)">下一页</button></div></section>
    <section class="panel queue-panel"><div class="section-title"><h2>待发放清单 <small>物品、金币或账号货币至少一项</small></h2><span class="count-badge">{{mailAttachments.length}} / 20</span></div><div v-if="templateId!==null" class="template-binding">绑定模板 #{{templateId}} v{{templateVersion}}<small>{{templateAdjusted?'已临时调整本次奖励；保留来源版本，不修改原模板。':'修改下方奖励只影响本次发放，不修改原模板。'}}</small><button type="button" class="ghost" :disabled="busy||!!pendingId" @click="templateId=null;templateVersion=null;templateAdjusted=false">解除来源绑定</button></div><CurrencyRewardInputs v-model="mailCurrencies" prefix="mail" :busy="busy||!!pendingId" :errors="fieldErrors"/><div id="mail-items" tabindex="-1" :aria-invalid="!!fieldErrors['mail-items']" :aria-describedby="fieldErrors['mail-items']?'mail-items-error':undefined"><FieldError id="mail-items-error" :message="fieldErrors['mail-items']"/><ItemQueue prefix="mail" :errors="fieldErrors" :items="mailAttachments" :busy="busy" @quantity="(n,v)=>mailAttachments[n].quantity=v" @remove="n=>mailAttachments.splice(n,1)"/></div><button v-if="mailAttachments.length" class="ghost full" :disabled="busy" @click="mailAttachments=[]">清空待发清单</button><div class="mail-fields"><label><span>金币附件 <small>可选</small></span><input id="mail-gold" v-model.number="mailGold" type="number" min="0" max="1000000000" step="1" inputmode="numeric" :disabled="busy||!!pendingId" :aria-invalid="!!fieldErrors['mail-gold']" :aria-describedby="fieldErrors['mail-gold']?'mail-gold-error':'mail-gold-hint'"><FieldError id="mail-gold-error" :message="fieldErrors['mail-gold']"/><small id="mail-gold-hint" class="field-hint">0 表示不附金币；每封最多10亿，可只发金币或与物品同发，整封只计一次。大额领取受游戏持币上限影响，客户端领取效果未验收。金币和邮件文字可随礼包模板一起保存。</small></label><label><span>邮件标题 <small>可选，作为正文首行发送</small></span><input id="mail-title" v-model="mailTitle" maxlength="40" aria-label="邮件标题" :disabled="busy||!!pendingId" :aria-invalid="!!fieldErrors['mail-title']" :aria-describedby="fieldErrors['mail-title']?'mail-title-error':undefined"><FieldError id="mail-title-error" :message="fieldErrors['mail-title']"/></label><label>邮件文字<input id="mail-message" v-model="message" maxlength="60" :aria-invalid="!!fieldErrors['mail-message']" :aria-describedby="fieldErrors['mail-message']?'mail-message-error':undefined" :disabled="busy" placeholder="例如 GM rewards"><small>部分中文受镜像编码限制；预览拒绝时可改用英文。</small><FieldError id="mail-message-error" :message="fieldErrors['mail-message']"/></label><label><span>操作原因 <em class="required-tag">必填</em></span><input id="operation-reason" v-model="reason" aria-required="true" :aria-invalid="!!fieldErrors['operation-reason']" :aria-describedby="fieldErrors['operation-reason']?'operation-reason-error':undefined" placeholder="必填，写入不可删除审计" maxlength="200" :disabled="busy"><FieldError id="operation-reason-error" :message="fieldErrors['operation-reason']"/><span class="button-row"><button v-for="preset in ['活动奖励','问题补偿','管理员测试','纠正先前操作']" :key="preset" type="button" :disabled="busy||!!pendingId" @click="reason=preset">{{preset}}</button></span></label></div><div class="queue-summary"><span>合计 {{mailAttachments.length}} 条附件</span><b>{{totalQuantity}} 件 · {{money(mailGold)}} 金币</b></div><p v-if="error&&feedbackScope==='operation'" class="submit-error">{{error}}</p><p v-else-if="notice&&feedbackScope==='operation'" class="submit-success">{{notice}}</p><button class="primary full" :disabled="busy" @click="action='mail';makePreview()">生成预览 →</button><button class="ghost full" :disabled="busy||(!mailAttachments.length&&!(mailGold>0)&&!hasMailCurrencies)||!!pendingId" @click="saveAsTemplate">另存为礼包模板</button><small class="field-hint">仅预览不投递。发送需在确认单中再次确认；可只发金币，或物品＋金币；纯文字邮件仍不支持。</small></section></div>
  </template>

  <template v-if="tab==='catalog'"><section class="panel"><div class="section-title"><h2>PVF 物品目录</h2><button :disabled="busy" @click="editPolicy()">批量调整当前筛选（全部 {{catalogTotal}} 项）</button><button class="primary" :disabled="busy" @click="toMail">前往邮件工作区 · {{mailAttachments.length}} 条附件 →</button></div><ItemCollection :revision="preferenceRevision" :disabled="busy" @select="addItem" @changed="preferenceChanged"/><p v-if="preferenceWarning" class="submit-error" role="status">{{preferenceWarning}}</p><form class="toolbar" @submit.prevent="searchRows"><input v-model="search" aria-label="搜索条件" placeholder="物品名称或编号" :disabled="busy"><select v-model="category" aria-label="物品分类" :disabled="busy" @change="searchRows"><option value="">全部类型</option><option value="equipment">装备</option><option value="material">材料</option><option value="consumable">消耗品</option><option value="special">特殊 / 时装 / 宠物</option></select><button class="primary" :disabled="busy">查询</button></form><label class="checkbox-field"><input type="checkbox" v-model="catalogAllowedOnly" :disabled="busy" @change="searchRows">仅看可发放物品</label><p class="field-hint">全部索引物品默认可发放，支持单项或按完整筛选结果停用、重新启用。发放数量不受PVF堆叠上限限制，加入后在“邮件发放”编辑清单。</p><details v-if="catalogMeta"><summary>索引版本与 PVF 校验信息</summary><pre>{{JSON.stringify(catalogMeta,null,2)}}</pre></details><div class="table-wrap"><table><thead><tr><th>物品 / 编号</th><th>类型</th><th>等级</th><th>发放数量</th><th>发放策略 / 原因</th><th></th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td><ItemCard :item="r"/></td><td>{{categoryNames[r.category]||r.category}}</td><td>{{r.level??'—'}}</td><td>不限（字段范围内）</td><td><span class="status-badge" :class="r.policy_state==='verified'?'success':'neutral'">{{policyLabel(r)}}</span><small class="cell-note policy-reason">{{r.policy_reason}}</small></td><td class="align-right"><FavoriteButton :item="r" :disabled="busy" @changed="preferenceChanged"/><button :disabled="busy||r.supported===false" :title="r.policy_reason" @click="editPolicy(r)">调整策略</button><button :disabled="busy||!sendable(r)" @click="addItem(r)">{{sendable(r)?'加入清单':'不可发放'}}</button></td></tr></tbody></table><p v-if="!rows.length&&!busy" class="empty">未找到物品。</p></div><div class="pagination"><button :disabled="page===1||busy" @click="page--;run(load)">上一页</button><span>第 {{page}} 页 · 共 {{catalogTotal}} 项 · 每页最多50条</span><button :disabled="rows.length<50||busy" @click="page++;run(load)">下一页</button></div></section><div v-if="mailAttachments.length" class="basket-bar"><span><b>{{mailAttachments.length}} 条附件已加入邮件草稿</b><small>尚未发送，接下来选择收件角色并预览。</small></span><button :disabled="busy" @click="toMail">编辑待发清单 →</button></div></template>

  <template v-if="tab==='gifts'"><section class="panel"><div class="section-title"><h2>礼包模板</h2><button class="primary" :disabled="busy||!!pendingId" @click="resetGift">新建礼包</button></div><form class="toolbar" @submit.prevent="searchRows"><input v-model="search" aria-label="搜索条件" placeholder="模板名称或编号" :disabled="busy"><input v-model="category" aria-label="礼包分类筛选" placeholder="分类（留空显示全部）" maxlength="32" :disabled="busy"><button :disabled="busy">查询</button></form><div class="gift-grid"><article v-for="r in rows" :key="r.id" class="gift-card"><div class="section-title"><span class="gift-icon">◇</span><span class="status-badge" :class="r.enabled?'success':'neutral'">{{r.enabled?'已启用':'已停用'}}</span></div><h3>{{r.name}}</h3><small class="muted">#{{r.id}} · v{{r.current_version}} · {{r.rewards?.items?.length||0}} 条附件</small><p v-for="(value,coin) in r.rewards?.currency_rewards||{}" :key="coin">{{currencyNames[coin]||coin}} {{money(value)}}</p><p v-if="r.rewards?.gold">金币 {{money(r.rewards.gold)}}</p><small v-if="r.rewards?.category" class="pill">{{r.rewards.category}}</small><ul class="gift-items"><li v-for="i in r.rewards?.items||[]" :key="i.id"><ItemCard :item="i"/><b>×{{i.quantity}}</b></li></ul><div class="button-row"><button :disabled="busy||!!pendingId" @click="editGift(r)">编辑版本</button><button :disabled="busy||!!pendingId" @click="copyGift(r)">复制模板</button><button :disabled="busy" @click="giftHistory=r.id">版本对比</button><button class="primary" :disabled="busy||!r.enabled||!!pendingId" @click="useGift(r)">用于发放</button></div></article></div><p v-if="!rows.length&&!busy" class="empty">暂无模板。新建一个礼包，将常用奖励组合保存。</p><div class="pagination"><button :disabled="page===1||busy" @click="page--;run(load)">上一页</button><span>第 {{page}} 页</span><button :disabled="rows.length<50||busy" @click="page++;run(load)">下一页</button></div></section>
    <section v-if="giftEditing" class="panel" id="gift-editor"><div class="section-title"><h2>{{giftId?'编辑礼包 #'+giftId:'新建礼包模板'}}</h2><span class="pill">{{giftId?'当前 v'+giftVersion:'独立模板草稿'}}</span></div><p class="field-hint">模板草稿与邮件草稿分别保存，不会互相覆盖。每次修改生成不可变版本，停用不删除历史。</p><div class="form-grid"><label><span>模板名称 <em class="required-tag">必填</em></span><input id="gift-name" v-model="giftName" maxlength="80" aria-required="true" :aria-invalid="!!fieldErrors['gift-name']" :aria-describedby="fieldErrors['gift-name']?'gift-name-error':undefined" :disabled="busy"><FieldError id="gift-name-error" :message="fieldErrors['gift-name']"/></label><label>模板状态<select v-model="giftEnabled" :disabled="busy"><option :value="true">启用</option><option :value="false">停用</option></select></label></div><div class="form-grid"><label>金币附件<input id="gift-gold" v-model.number="giftGold" type="number" min="0" max="1000000000" :disabled="busy"><FieldError id="gift-gold-error" :message="fieldErrors['gift-gold']"/></label><label><span>邮件标题 <small>可选，作为正文首行发送</small></span><input id="gift-title" v-model="giftTitle" maxlength="40" aria-label="礼包邮件标题" :disabled="busy||!!pendingId" :aria-invalid="!!fieldErrors['gift-title']" :aria-describedby="fieldErrors['gift-title']?'gift-title-error':undefined"><FieldError id="gift-title-error" :message="fieldErrors['gift-title']"/></label><label>邮件文字<input id="gift-message" v-model="giftMessage" maxlength="60" :disabled="busy"><FieldError id="gift-message-error" :message="fieldErrors['gift-message']"/></label><label>分类<input v-model="giftCategory" maxlength="32" placeholder="新手 / 活动 / 补偿 / 测试" :disabled="busy"></label></div><p class="field-hint">可保存纯金币礼包；邮件文字和金币一起绑定版本。修改发放草稿时解除绑定，不改动原模板。</p><div class="section-title"><h3>礼包附件 · {{giftAttachments.length}} / 20</h3><button :disabled="busy" @click="openPicker">添加物品</button></div><CurrencyRewardInputs v-model="giftCurrencies" prefix="gift" :busy="busy||!!pendingId" :errors="fieldErrors"/><div id="gift-items" tabindex="-1" :aria-invalid="!!fieldErrors['gift-items']" :aria-describedby="fieldErrors['gift-items']?'gift-items-error':undefined"><FieldError id="gift-items-error" :message="fieldErrors['gift-items']"/><ItemQueue prefix="gift" :errors="fieldErrors" :items="giftAttachments" :busy="busy" @quantity="(n,v)=>giftAttachments[n].quantity=v" @remove="n=>giftAttachments.splice(n,1)"/></div><p v-if="error&&feedbackScope==='gift'" class="submit-error">{{error}}</p><p v-else-if="notice&&feedbackScope==='gift'" class="submit-success">{{notice}}</p><div class="action-footer"><span class="muted">保存模板不会发放物品。</span><div class="button-row"><button :disabled="busy||!!pendingId" @click="resetGift">重置为新模板</button><button class="primary" :disabled="busy" @click="saveGift">{{giftId?'保存为新版本':'创建礼包模板'}}</button></div></div></section></template>

  <template v-if="tab==='audit'"><section class="panel"><div class="section-title"><h2>审计流水</h2><span class="pill">只读 · 不可删除</span><a v-if="!search||/^[1-9]\d{0,9}$/.test(search)" :href="'/dnf-gm/api/v1/audit/export?uid='+(search||0)" download>导出筛选后的全部记录</a></div><form class="toolbar" @submit.prevent="searchRows"><input id="audit-uid" v-model="search" :aria-invalid="!!fieldErrors['audit-uid']" :aria-describedby="fieldErrors['audit-uid']?'audit-uid-error':undefined" aria-label="筛选 UID" placeholder="按目标 UID 筛选，留空查看全部" :disabled="busy"><button :disabled="busy">查询</button></form><FieldError id="audit-uid-error" :message="fieldErrors['audit-uid']"/><p v-if="error&&feedbackScope==='audit'" class="submit-error">{{error}}</p><div class="audit-list"><article v-for="r in rows" :key="r.id"><div class="audit-row"><span class="audit-dot"/><div class="audit-main"><div class="section-title"><h3>{{actionNames[r.action]||r.action}}</h3><time>{{localTime(r.created_at)}}</time></div><p>{{r.reason}}</p><small>操作人 {{r.actor||'admin'}} · 目标 UID {{r.target_uid??'—'}}</small><code>{{r.operation_id}}</code><details><summary>展开请求与结果</summary><pre>{{JSON.stringify(r,null,2)}}</pre></details></div><button v-if="r.action!=='gift-template'&&/^[a-f0-9]{32}$/.test(r.operation_id)" :disabled="busy" @click="inspectFromAudit(r.operation_id)">{{r.action==='mail'?'查询结果 / 邮件领取标记':'查询结果'}}</button></div></article><p v-if="!rows.length&&!busy" class="empty">没有匹配的审计记录。</p></div><div class="pagination"><button :disabled="page===1||busy" @click="page--;run(load)">上一页</button><span>第 {{page}} 页</span><button :disabled="rows.length<50||busy" @click="page++;run(load)">下一页</button></div></section></template>

  <section v-if="operationResult&&(tab==='accounts'||tab==='online'||tab==='mail')" class="panel result"><div class="section-title"><h2>操作结果</h2><span class="status-badge" :class="resultCommitted?'success':'neutral'">{{resultCommitted?'数据库已提交':'尚未提交 / 仅预览'}}</span></div><code>操作编号 {{operationResult.operation_id}}</code><p v-if="shownResult.after!==undefined">最新变更：{{money(shownResult.before)}} → {{money(shownResult.after)}}</p><p v-for="(balance,coin) in shownResult.currency_rewards||{}" :key="coin">{{currencyNames[coin]||coin}}：{{money(balance.before)}} → {{money(balance.after)}}</p><p v-if="shownResult.blocked!==undefined">{{shownResult.blocked?'已限制后续登录':'已解除本后台封禁'}}（不自动踢出在线玩家）</p><p v-if="shownResult.gold!==undefined">金币附件合计：{{money(shownResult.gold)}} · 仅已投递，不代表已领取</p><p v-if="shownResult.postal_ids">邮件 ID：{{shownResult.postal_ids.join(', ')}} · 已投递不代表已领取</p><details><summary>完整操作结果</summary><pre>{{JSON.stringify(operationResult,null,2)}}</pre></details><button class="ghost" :disabled="busy" @click="inspectOperation(operationResult.operation_id)">查看原编号记录 →</button></section>
  <section v-if="tab==='audit'||lookedUp" class="panel" id="operation-lookup"><div class="section-title"><h2>按操作编号核对结果</h2><span class="muted">只读查询，不重放</span></div><form class="toolbar" novalidate @submit.prevent="inspectOperation(lookupId)"><input id="lookup-id" v-model="lookupId" aria-label="操作编号" aria-required="true" :aria-invalid="!!fieldErrors['lookup-id']" :aria-describedby="fieldErrors['lookup-id']?'lookup-id-error':undefined" placeholder="32位操作编号；用于断线、重登后核对" pattern="[a-f0-9]{32}" required><button :disabled="busy">只查询，不重放</button></form><FieldError id="lookup-id-error" :message="fieldErrors['lookup-id']"/><p v-if="error&&feedbackScope==='lookup'" class="submit-error">{{error}}</p><div v-if="lookedUp" class="lookup-result"><b>{{actionNames[lookedUp.action]||lookedUp.action}} · {{operationStatus(lookedUp)}}</b><p>操作编号 {{lookedUp.operation_id}}<span v-if="lookedUp.preview?.target?.uid"> · UID {{lookedUp.preview.target.uid}}</span></p><p v-if="lookedUp.action==='maintenance'" class="notice">维护申请已保存不代表已经退出游戏。请到维护中心按原编号核对执行记录。<button @click="go('maintenance')">前往维护中心</button></p><template v-if="lookedUp.action==='cleanup-release'"><p class="warning">{{lookedUp.cleanup?.receipt_error||cleanupStates[lookedUp.cleanup?.result?.state]||(lookedUp.status==='cancelled'?'此预览不会执行删除':'以专用执行器结果为准，不把入队当作已释放空间。')}}</p><ul v-if="lookedUp.cleanup?.result?.items"><li v-for="item in lookedUp.cleanup.result.items" :key="item.name">{{item.name}} · {{cleanupFileStates[item.state]||item.state}}</li></ul><button @click="go('operations-dashboard')">前往运维诊断核对清理</button></template><p v-if="lookedUp.action==='capability-policy'&&lookedUp.result">管理员权限已保存 · 修订 {{lookedUp.result.revision}} · 全部账号 · 已开启 {{lookedUp.result.enabled?.length??0}} 项。此操作仅调整功能开关，没有发放奖励。<button @click="go('capabilities')">前往功能与版本</button></p><p v-if="lookedUp.action==='catalog-policy'&&lookedUp.result">物品策略：{{lookedUp.result.enabled?'允许试发':'禁止发放'}} · 实际变更 {{lookedUp.result.affected}} 项 · 策略版本 {{lookedUp.result.policy_revision}}。此操作没有发放物品。</p><p v-if="lookedUp.result?.after!==undefined">{{currencyNames[lookedUp.result.currency]||lookedUp.result.currency}}：{{money(lookedUp.result.before)}} → {{money(lookedUp.result.after)}}</p><p v-if="lookedUp.action==='mail'">金币附件合计：{{money(lookedUp.result?.gold??lookedUp.preview?.gold??0)}}（仅投递记录，非背包余额）</p><p v-if="lookedUp.action?.startsWith('native-')" class="warning">原生控制没有游戏业务回执；不要按数据库提交判断公告或踢人生效。<span v-if="lookedUp.result?.ban_status==='committed_login_test_pending'">封禁数据库已提交，登录阻断效果待核验；踢人结果独立显示。</span><button @click="go('native-controls')">前往游戏内控制</button></p><p v-if="lookedUp.result?.blocked!==undefined">{{lookedUp.result.blocked?'已限制后续登录':'已解除本后台封禁'}}；不自动踢出在线玩家</p><ul v-if="lookedUp.delivery_records"><li v-for="m in lookedUp.delivery_records" :key="m.postal_id">邮件 #{{m.postal_id}} · 金币 {{money(m.gold??0)}} · 删除标记 {{m.delete_flag}} · 数据库领取时间 {{m.receive_time}}</li></ul><p v-if="lookedUp.delivery_note" class="muted">{{lookedUp.delivery_note}}</p><details><summary>完整查询结果</summary><pre>{{JSON.stringify(lookedUp,null,2)}}</pre></details></div></section>
  </div>
  <details class="request-log"><summary>诊断 · 最近接口调用（仅页面内存，不含凭据）</summary><ol><li v-for="(r,i) in requests" :key="i"><code>{{r.method}} {{r.path}}</code><span>{{r.status}} · {{r.ms}}ms</span></li></ol></details><footer class="page-footer"><span>DNF GM · 清风 1031</span><span>192 MiB 内存硬限 · 所有游戏写入留痕</span></footer>
  </main>
  <FeedbackToast v-if="(error||notice)&&!toastDismissed&&!mobileMenu&&!reauthOpen&&!(confirmOpen&&preview)&&!pickerOpen&&!detailCharacNo&&!policyDialog&&!giftHistory" :message="feedbackMessage" :error="!!error" :can-locate="!!error&&!!Object.keys(fieldErrors).length" @dismiss="toastDismissed=true" @locate="focusProblem"/>

  <Modal v-if="confirmOpen&&preview&&!reauthOpen" title="确认操作预览" :busy="busy" @close="closePreview"><div class="confirmation-title"><span class="pill">{{actionNames[preview.preview.action]}}</span><h3>{{preview.preview.target.accountname}} <small>UID {{preview.preview.target.uid}}</small></h3></div><dl class="confirmation-details"><div v-if="preview.preview.mail_title"><dt>邮件正文预览</dt><dd style="white-space:pre-wrap">{{preview.preview.mail_text}}</dd></div><div v-if="preview.preview.template_source"><dt>奖励来源</dt><dd>礼包 #{{preview.preview.template_source.id}} / v{{preview.preview.template_source.version}} · {{preview.preview.template_source.adjusted?'临时调整，不修改原模板':'模板原内容'}}</dd></div><div><dt>操作原因</dt><dd>{{preview.preview.reason||reason}}</dd></div><div v-if="preview.preview.action==='currency'"><dt>{{currencyNames[preview.preview.currency]||preview.preview.currency}}</dt><dd class="balance-change">{{money(preview.preview.before)}} <span>→</span> <strong>{{money(preview.preview.after)}}</strong></dd></div><div v-if="preview.preview.target.character"><dt>收件角色</dt><dd>{{preview.preview.target.character.charac_name}} #{{preview.preview.target.character.charac_no}}</dd></div></dl><p v-if="preview.preview.support_case" class="notice" role="status">关联问题：{{preview.preview.support_case.title}} · 已有 {{preview.preview.support_case.compensation_count}} 笔补偿；请核对是否重复。问题记录变化时必须重新预览。</p><p v-if="['mail','reward'].includes(preview.preview.action)" class="balance-change" data-testid="preview-gold">金币附件：<strong>{{money(preview.preview.gold??0)}}</strong><small> · 整封合计一次，领取效果未验收</small></p><dl v-if="preview.preview.balances" class="confirmation-details"><div v-for="(balance,coin) in preview.preview.balances" :key="coin"><dt>{{currencyNames[coin]||coin}}</dt><dd>{{money(balance.before)}} → <strong>{{money(balance.after)}}</strong></dd></div></dl><ul v-if="preview.preview.rewards" class="preview-rewards"><li v-for="(i,n) in preview.preview.rewards.items" :key="n"><ItemCard :item="i"/><b>×{{i.quantity}}</b></li></ul><p v-if="['ban','unban'].includes(preview.preview.action)" class="warning">仅影响后续登录，不立即踢出在线玩家。只操作本后台处罚。</p><p class="field-hint">5分钟内有效。修改参数、余额、模板或 PVF 版本变化时须重新预览。{{preview.write_enabled?'':'该能力未激活，确认将被拒绝。'}}</p><p class="mono operation-number">操作编号 {{preview.operation_id}}</p><details><summary>完整服务端预览</summary><pre>{{JSON.stringify(preview.preview,null,2)}}</pre></details><p v-if="uncertain" class="warning">本编号已提交或结果待确认，不再允许直接重发。请先查询结果。</p><template #footer><p v-if="error" class="submit-error" role="alert" tabindex="-1" data-modal-error>{{error}}</p><button :disabled="busy" @click="closePreview">返回修改</button><button :disabled="busy" @click="queryResult">按原编号查询结果</button><button :class="['primary',{danger:['ban','unban'].includes(preview.preview.action)||preview.preview.after<preview.preview.before}]" :disabled="busy||uncertain||!preview.write_enabled" @click="confirmOperation">{{busy?'正在提交…':'确认执行一次'}}</button></template></Modal>
  <Modal v-if="reauthOpen" title="敏感操作重新认证" :busy="busy" @close="reauthOpen=false"><form id="reauth-form" @submit.prevent="reauth"><p class="muted">安全认证已超过5分钟，请重新输入管理员密码。验证不会自动重放任何操作。</p><label>管理员账号<input v-model="username" autocomplete="username" required></label><label>管理员密码<input v-model="password" type="password" autocomplete="current-password" required></label><label v-if="totpRequired">新动态码或恢复码<input v-model="code" autocomplete="one-time-code" required></label></form><template #footer><p v-if="error" class="submit-error" role="alert" tabindex="-1" data-modal-error>{{error}}</p><button :disabled="busy" @click="reauthOpen=false">取消</button><button class="primary" form="reauth-form" :disabled="busy">验证</button></template></Modal>
  <CatalogPolicy v-if="policyDialog" :item="policyDialog.item" :filters="policyDialog.filters" @close="policyDialog=null" @changed="policyChanged" @reauth="policyReauth" @expired="clearSession"/>
  <CharacterDetails v-if="detailCharacNo" :key="detailCharacNo" :charac-no="detailCharacNo" :initial-section="detailSection" @action="detailAction" @draft="detailDraft" @inspect="detailInspect" @close="detailCharacNo=0" @reauth="detailCharacNo=0;reauthOpen=true" @expired="detailCharacNo=0;clearSession()"/>
  <Modal v-if="pickerOpen" title="为礼包选择物品" :busy="busy" @close="pickerOpen=false"><ItemCollection :revision="preferenceRevision" :disabled="busy" @select="addItem" @changed="preferenceChanged"/><p v-if="preferenceWarning" class="submit-error" role="status">{{preferenceWarning}}</p><form class="toolbar" @submit.prevent="searchPicker"><input v-model="pickerQuery" aria-label="礼包物品搜索" placeholder="物品名称或编号" :disabled="busy"><select v-model="pickerCategory" aria-label="礼包物品分类" @change="searchPicker"><option value="">全部类型</option><option value="equipment">装备</option><option value="material">材料</option><option value="consumable">消耗品</option><option value="special">特殊 / 时装 / 宠物</option></select><button class="primary" :disabled="busy">查询物品</button></form><label class="checkbox-field"><input type="checkbox" v-model="pickerAllowedOnly" :disabled="busy" @change="searchPicker">仅看可发放物品</label><div class="picker-list"><div v-for="r in pickerRows" :key="r.id"><ItemCard :item="r"><small>发放数量不限（字段范围内） · {{policyLabel(r)}}</small><small>{{r.policy_reason}}</small></ItemCard><FavoriteButton :item="r" :disabled="busy" @changed="preferenceChanged"/><button :disabled="busy||!sendable(r)" @click="addItem(r)">{{sendable(r)?'加入清单':'不可发放'}}</button></div><p v-if="!pickerRows.length&&!busy" class="empty">未找到物品。</p></div><div class="pagination"><button :disabled="busy||pickerPage===1" @click="pickerPage--;run(loadPicker)">上一页物品</button><span>第 {{pickerPage}} 页 · 已选 {{giftAttachments.length}} 条</span><button :disabled="busy||pickerRows.length<50" @click="pickerPage++;run(loadPicker)">下一页物品</button></div><template #footer><p v-if="notice" class="submit-success">{{notice}}</p><p v-if="error" class="submit-error" role="alert" tabindex="-1" data-modal-error>{{error}}</p><span class="muted">索引中的所有类型均可加入，最多20条；已手动停用的物品需先启用。</span><button class="primary" :disabled="busy" @click="pickerOpen=false">完成选择</button></template></Modal>
</div>
</template>
