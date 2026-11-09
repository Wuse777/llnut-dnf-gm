<script setup lang="ts">
import {computed} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {useTabStore} from '../../store/modules/tab'
import {asyncPanel} from '../../asyncPanel'
import {useGmWorkspace} from '../../stores/gm/useGmWorkspace'
const CharacterDetails=asyncPanel(()=>import('../../components/CharacterDetails.vue'))
const route=useRoute(),router=useRouter(),gm=useGmWorkspace(),tabStore=useTabStore()
const characNo=computed(()=>Number(route.params.characNo))
const initialSection=computed(()=>typeof route.query.section==='string'?route.query.section:'basic')
function labelCharacter(data:any){if(data.character?.charac_no===characNo.value)tabStore.setTabLabel(data.character.charac_name+' · #'+characNo.value)}
</script>
<template><div class="gm-workspace"><CharacterDetails v-if="Number.isSafeInteger(characNo)&&characNo>0" :charac-no="characNo" :initial-section="initialSection" embedded @close="router.push('/players')" @reauth="gm.reauthOpen=true" @expired="gm.clearSession" @visited="gm.visitPlayer" @loaded="labelCharacter" @action="gm.detailAction" @draft="gm.detailDraft" @inspect="gm.detailInspect"/><p v-else class="submit-error">角色编号无效，请从玩家列表重新选择。</p></div></template>
