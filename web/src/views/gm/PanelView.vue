<script setup lang="ts">
import {watch} from 'vue'
import {onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router'
import {useGmWorkspace} from '../../stores/gm/useGmWorkspace'
import {useGmWorkspaceBindings} from '../../stores/gm/useGmWorkspace'
import {asyncPanel} from '../../asyncPanel'
const UnlockCenter=asyncPanel(()=>import('../../components/UnlockCenter.vue'))
const OperationsDashboard=asyncPanel(()=>import('../../components/OperationsDashboard.vue'))
const MailCenter=asyncPanel(()=>import('../../components/MailCenter.vue'))
const RewardJobs=asyncPanel(()=>import('../../components/RewardJobs.vue'))
const Schedules=asyncPanel(()=>import('../../components/Schedules.vue'))
const SupportDesk=asyncPanel(()=>import('../../components/SupportDesk.vue'))
const EconomyReports=asyncPanel(()=>import('../../components/EconomyReports.vue'))
const UpgradeCheck=asyncPanel(()=>import('../../components/UpgradeCheck.vue'))
const Capabilities=asyncPanel(()=>import('../../components/Capabilities.vue'))
const MaintenanceCenter=asyncPanel(()=>import('../../components/MaintenanceCenter.vue'))
const NativeControls=asyncPanel(()=>import('../../components/NativeControls.vue'))
const {supportDesk,supportUid,mailCenterUid,mailCenterOperation,tab,account,reauthOpen,action,currency,clearSession,draft,reauth,go,copyMailDraft,playerAction,supportCompensation,select,inspectOperation,healthTask,healthSchedule,openHealthTask,openScheduledChild,run,load}=useGmWorkspaceBindings()
const props=defineProps<{page:string}>()
const workspace=useGmWorkspace()
watch(()=>props.page,value=>workspace.activate(value,false),{immediate:true})
onBeforeRouteLeave(()=>props.page!=='support'||!supportDesk.value||supportDesk.value.canNavigate())
onBeforeRouteUpdate(()=>props.page!=='support'||!supportDesk.value||supportDesk.value.canNavigate())
</script>
<template><div class="gm-workspace"><MaintenanceCenter v-if="tab==='maintenance'" @expired="clearSession" @reauth="reauthOpen=true" @navigate="go($event)"/>
<Capabilities v-if="tab==='capabilities'" @expired="clearSession" @reauth="reauthOpen=true" @navigate="go($event)"/>
<UpgradeCheck v-if="tab==='compatibility'" @expired="clearSession" @navigate="go($event)" @inspect="inspectOperation"/>
<EconomyReports v-if="tab==='economy'" @expired="clearSession" @inspect="inspectOperation" @player="playerAction({action:'currency',uid:$event})" @support="playerAction({action:'support',uid:$event})"/>
<SupportDesk ref="supportDesk" v-if="tab==='support'" :uid="supportUid" @reauth="reauthOpen=true" @expired="clearSession" @action="playerAction" @inspect="inspectOperation" @compensate="supportCompensation"/>
<NativeControls v-if="tab==='native-controls'" :account="account" @reauth="reauthOpen=true" @expired="clearSession" @select-player="go('accounts')"/>
<OperationsDashboard v-if="tab==='operations-dashboard'" @reauth="reauthOpen=true" @task="openHealthTask"/>
<UnlockCenter v-if="tab==='unlock-center'" @reauth="reauthOpen=true" @inspect="inspectOperation"/>
<Schedules v-if="tab==='schedules'" :initial-schedule="healthSchedule" @opened="healthSchedule=''" @reauth="reauthOpen=true" @expired="clearSession" @child="openScheduledChild" />
<RewardJobs v-if="tab==='reward-jobs'" :initial-job="healthTask" @opened="healthTask=''" @reauth="reauthOpen=true" @inspect="inspectOperation" />
<MailCenter v-if="tab==='mail-center'" :uid="mailCenterUid" :operation-id="mailCenterOperation" @draft="copyMailDraft" /></div></template>
