<script setup lang="ts">
import {ref,computed,watch,onBeforeUnmount} from 'vue'
import {api,uncertainMessage} from '../api'
import Modal from './Modal.vue'
const props=defineProps<{templateId:number}>()
const emit=defineEmits<{close:[],copy:[payload:any]}>()
const versions=ref<any[]>([]),left=ref(0),right=ref(0),page=ref(1),more=ref(false),error=ref(''),loading=ref(false)
let generation=0
async function load(){const g=++generation;loading.value=true;error.value='';versions.value=[];try{const d=await api('/gift-templates/'+props.templateId+'/versions?page='+page.value);if(g!==generation)return;versions.value=d.items;more.value=d.has_more;left.value=d.items[0]?.version??0;right.value=d.items[1]?.version??left.value}catch(e){if(g===generation)error.value=uncertainMessage(e)}finally{if(g===generation)loading.value=false}}
const a=computed(()=>versions.value.find(v=>v.version===left.value)?.payload),b=computed(()=>versions.value.find(v=>v.version===right.value)?.payload)
const fields=[['name','模板名称'],['enabled','状态'],['category','分类'],['mail_title','邮件标题（正文首行）'],['message','邮件文字'],['gold','金币附件'],['currency_rewards','账号货币'],['items','物品附件']]
function value(p:any,k:string){if(!p)return '—';if(k==='currency_rewards')return Object.entries(p.currency_rewards||{}).filter(([,v])=>v).map(([key,v])=>({cera:'点券',cera_point:'代币券',mileage:'商城积分'}[key]||key)+' × '+v).join('\n')||'无账号货币';if(k==='items')return (p.items||[]).map((i:any)=>'#'+i.id+' × '+i.quantity).join('\n')||'无物品附件';if(k==='enabled')return p[k]===undefined?'旧版本未记录':p[k]?'启用':'停用';return p[k]===undefined?'旧版本未记录':String(p[k])}
watch(()=>props.templateId,()=>{page.value=1;void load()},{immediate:true})
onBeforeUnmount(()=>generation++)
</script>
<template><Modal :title="'礼包版本对比 #'+templateId" @close="emit('close')"><p v-if="error" class="submit-error" role="alert">{{error}} <button @click="load">重试读取</button></p><p v-if="loading" role="status">正在读取版本…</p><template v-else-if="versions.length"><div class="form-grid"><label>版本 A<select v-model.number="left"><option v-for="v in versions" :key="v.version" :value="v.version">v{{v.version}}</option></select></label><label>版本 B<select v-model.number="right"><option v-for="v in versions" :key="v.version" :value="v.version">v{{v.version}}</option></select></label></div><div class="table-wrap"><table><thead><tr><th>字段</th><th>v{{left}}</th><th>v{{right}}</th></tr></thead><tbody><tr v-for="[key,label] in fields" :key="key"><th>{{label}}<small v-if="value(a,key)!==value(b,key)" class="cell-note">有变化</small></th><td class="version-value">{{value(a,key)}}</td><td class="version-value">{{value(b,key)}}</td></tr></tbody></table></div><p class="field-hint">历史版本不可变。复制只生成独立模板草稿，不会修改原模板或发送奖励。</p></template><p v-else-if="!error" class="empty">没有可读取的版本。</p><div class="pagination"><button :disabled="loading||page<=1" @click="page--;load()">上一页版本</button><span>第 {{page}} 页</span><button :disabled="loading||!more" @click="page++;load()">下一页版本</button></div><template #footer><button :disabled="loading||!a" @click="emit('copy',a)">复制版本 A 为新模板</button><button @click="emit('close')">关闭</button></template></Modal></template>
<style scoped>.version-value{white-space:pre-wrap;overflow-wrap:anywhere;max-width:20rem}</style>
