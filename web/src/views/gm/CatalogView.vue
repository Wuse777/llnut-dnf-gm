<script setup lang="ts">
import {onMounted,ref} from 'vue'
import GmItemPicker from '../../components/GmItemPicker.vue'
import GmSceneBanner from '../../components/GmSceneBanner.vue'
import {useGmWorkspace} from '../../stores/gm/useGmWorkspace'
const gm=useGmWorkspace(),picker=ref<InstanceType<typeof GmItemPicker>|null>(null)
onMounted(()=>gm.activate('catalog',false))
function loaded(value:{metadata:any,total:number,filters:Record<string,any>}){gm.drafts.syncPvf(value.metadata?.pvf_sha256);gm.catalogMeta=value.metadata;gm.catalogTotal=value.total;gm.catalogFilters=value.filters}
</script>
<template><div class="gm-workspace"><GmSceneBanner eyebrow="道具与外观" title="PVF 物品目录" description="组合筛选、查看属性与装备对比，再加入奖励草稿。"><button class="primary" :disabled="gm.busy" @click="gm.toMail">编辑邮件清单 · {{gm.mailAttachments.length}} 条 →</button></GmSceneBanner><section class="panel"><GmItemPicker ref="picker" context-key="catalog" :allowed-only="false" :revision="gm.catalogRevision" manage-policy :disabled="gm.busy" :selected-count="gm.mailAttachments.length" @select="gm.addItem" @policy="gm.editPolicy" @loaded="loaded" @expired="gm.clearSession"/></section><div v-if="gm.mailAttachments.length" class="basket-bar"><span><b>{{gm.mailAttachments.length}} 条附件已加入草稿</b><small>尚未发送，请选择收件角色并预览确认。</small></span><button @click="gm.toMail">编辑待发清单 →</button></div></div></template>
