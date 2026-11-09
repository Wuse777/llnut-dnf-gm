<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {onBeforeRouteLeave,onBeforeRouteUpdate,useRoute,useRouter} from 'vue-router'
import {useGmWorkspace,useGmWorkspaceBindings,GM_ROUTE_PATHS} from '../../stores/gm/useGmWorkspace'
import {asyncPanel} from '../../asyncPanel'
import {api,uncertainMessage} from '../../api'
const UnlockCenter=asyncPanel(()=>import('../../components/UnlockCenter.vue'))
const OperationsDashboard=asyncPanel(()=>import('../../components/OperationsDashboard.vue'))
const MailCenter=asyncPanel(()=>import('../../components/MailCenter.vue'))
const RewardJobs=asyncPanel(()=>import('../../components/RewardJobs.vue'))
const Campaigns=asyncPanel(()=>import('../../components/Campaigns.vue'))
const GameBackupControls=asyncPanel(()=>import('../../components/GameBackupControls.vue'))
const Schedules=asyncPanel(()=>import('../../components/Schedules.vue'))
const SupportDesk=asyncPanel(()=>import('../../components/SupportDesk.vue'))
const EconomyReports=asyncPanel(()=>import('../../components/EconomyReports.vue'))
const UpgradeCheck=asyncPanel(()=>import('../../components/UpgradeCheck.vue'))
const Capabilities=asyncPanel(()=>import('../../components/Capabilities.vue'))
const MaintenanceCenter=asyncPanel(()=>import('../../components/MaintenanceCenter.vue'))
const NativeControls=asyncPanel(()=>import('../../components/NativeControls.vue'))
const {supportDesk,supportUid,mailCenterUid,mailCenterOperation,tab,account,reauthOpen,clearSession,go,copyMailDraft,playerAction,supportCompensation,inspectOperation,healthTask,healthSchedule,openHealthTask,openScheduledChild}=useGmWorkspaceBindings()
const props=defineProps<{page:string}>(),workspace=useGmWorkspace(),route=useRoute(),router=useRouter()
const campaignDraft=ref<any>(null),campaignError=ref('')
function numberQuery(key:string,fallback=0){const value=String(route.query[key]||'');return /^[1-9]\d{0,9}$/.test(value)&&Number(value)<=2147483647?Number(value):fallback}
function idQuery(key:string){const value=String(route.query[key]||'');return /^[a-f0-9]{32}$/.test(value)?value:''}
const supportTarget=computed(()=>numberQuery('uid',supportUid.value)),mailTarget=computed(()=>numberQuery('uid',mailCenterUid.value))
let campaignEpoch=0
watch(()=>[props.page,route.query.campaign_id],async()=>{const epoch=++campaignEpoch;campaignDraft.value=null;campaignError.value='';if(!['schedules','reward-jobs'].includes(props.page)||!idQuery('campaign_id'))return;try{const r=await api('/campaigns/'+idQuery('campaign_id'));if(epoch===campaignEpoch)campaignDraft.value=r.job_draft}catch(e){if(epoch===campaignEpoch)campaignError.value=uncertainMessage(e)}},{immediate:true})
function campaignPlan(kind:string,draft:any){void router.push({path:GM_ROUTE_PATHS[kind],query:{campaign_id:draft.campaign_id}})}
function campaignRecord(target:{page:'reward-jobs'|'schedules',id:string}){void router.push({path:GM_ROUTE_PATHS[target.page],query:{[target.page==='reward-jobs'?'job_id':'schedule_id']:target.id}})}
watch(()=>props.page,value=>workspace.activate(value,false),{immediate:true})
onBeforeRouteLeave(()=>props.page!=='support'||!supportDesk.value||supportDesk.value.canNavigate())
onBeforeRouteUpdate(()=>props.page!=='support'||!supportDesk.value||supportDesk.value.canNavigate())
</script>
<template><div class="gm-workspace"><p v-if="campaignError" class="submit-error" role="alert">活动草稿读取失败：{{campaignError}}</p>
<MaintenanceCenter v-if="tab==='maintenance'" @expired="clearSession" @reauth="reauthOpen=true" @navigate="go($event)"/>
<GameBackupControls v-if="tab==='game-backups'" :initial-run="idQuery('run_id')" @expired="clearSession" @reauth="reauthOpen=true" @navigate="go($event)"/>
<Campaigns v-if="tab==='campaigns'" :initial-campaign="idQuery('campaign_id')" @batch="campaignPlan('reward-jobs',$event)" @schedule="campaignPlan('schedules',$event)" @navigate="campaignRecord" @inspect="inspectOperation" @reauth="reauthOpen=true"/>
<Capabilities v-if="tab==='capabilities'" @expired="clearSession" @reauth="reauthOpen=true" @navigate="go($event)"/>
<UpgradeCheck v-if="tab==='compatibility'" @expired="clearSession" @navigate="go($event)" @inspect="inspectOperation"/>
<EconomyReports v-if="tab==='economy'" @expired="clearSession" @inspect="inspectOperation" @player="playerAction({action:'currency',uid:$event})" @support="playerAction({action:'support',uid:$event})"/>
<SupportDesk ref="supportDesk" v-if="tab==='support'" :uid="supportTarget" :initial-case="idQuery('case_id')" @reauth="reauthOpen=true" @expired="clearSession" @action="playerAction" @inspect="inspectOperation" @compensate="supportCompensation"/>
<NativeControls v-if="tab==='native-controls'" :account="account" @reauth="reauthOpen=true" @expired="clearSession" @select-player="go('accounts')"/>
<OperationsDashboard v-if="tab==='operations-dashboard'" @reauth="reauthOpen=true" @task="openHealthTask"/>
<UnlockCenter v-if="tab==='unlock-center'" @reauth="reauthOpen=true" @inspect="inspectOperation"/>
<Schedules v-if="tab==='schedules'&&(!idQuery('campaign_id')||campaignDraft)" :initial-draft="campaignDraft" :initial-schedule="idQuery('schedule_id')||healthSchedule" @opened="healthSchedule=''" @reauth="reauthOpen=true" @expired="clearSession" @child="openScheduledChild"/>
<RewardJobs v-if="tab==='reward-jobs'&&(!idQuery('campaign_id')||campaignDraft)" :initial-draft="campaignDraft" :initial-job="idQuery('job_id')||healthTask" :initial-status="String(route.query.status||'')" @opened="healthTask=''" @reauth="reauthOpen=true" @inspect="inspectOperation"/>
<MailCenter v-if="tab==='mail-center'" :uid="mailTarget" :charac-no="numberQuery('charac_no')" :operation-id="idQuery('operation_id')||mailCenterOperation" @draft="copyMailDraft"/>
</div></template>
