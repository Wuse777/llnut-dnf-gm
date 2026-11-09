<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,watch} from 'vue'
import {api,uncertainMessage,ApiError} from '../api'
import ItemCard from './ItemCard.vue'
import {useGmCatalogStore} from '../stores/gm/catalog'
import CatalogFilters from './CatalogFilters.vue'
import ItemCompare from './ItemCompare.vue'
import FavoriteButton from './FavoriteButton.vue'
import ItemCollection from './ItemCollection.vue'
const props=withDefaults(defineProps<{contextKey?:string,revision?:number,disabled?:boolean,allowedOnly?:boolean,managePolicy?:boolean,selectedCount?:number}>(),{allowedOnly:true})
const emit=defineEmits<{select:[item:any],policy:[item?:any],loaded:[value:{metadata:any,total:number,filters:Record<string,any>}],expired:[]}>()
const stateStore=props.contextKey?useGmCatalogStore():undefined
const saved=props.contextKey?stateStore?.contexts[props.contextKey]:undefined
const filters=ref<Record<string,any>>({q:'',category:'',allowed_only:props.allowedOnly,part:'',rarity:'',min_level:'',max_level:'',sort:'id',job:'',weapon_type:'',set_id:''})
const rows=ref<any[]>([]),facets=ref<any>(null),metadata=ref<any>(null),page=ref(1),total=ref(0),loading=ref(false),error=ref(''),warning=ref(''),comparison=ref<any[]>([]),favoriteRevision=ref(0)
const disabled=computed(()=>props.disabled||loading.value)
if(saved){filters.value={...saved.filters};page.value=saved.page;comparison.value=saved.comparison.map(item=>({...item}));metadata.value={pvf_sha256:saved.pvf}}
type ItemView='grid'|'list'
const view=ref<ItemView>('grid')
const viewStorageKey=computed(()=>typeof metadata.value?.pvf_sha256==='string'&&/^[a-f0-9]{64}$/.test(metadata.value.pvf_sha256)?'dnfgm.catalog-view.v1.'+metadata.value.pvf_sha256:null)
watch(viewStorageKey,key=>{view.value='grid';if(key)try{if(localStorage.getItem(key)==='list')view.value='list'}catch{/* Layout remains usable when browser storage is unavailable. */}},{immediate:true})
function changeView(value:ItemView){view.value=value;const key=viewStorageKey.value;if(key)try{localStorage.setItem(key,value)}catch{/* Do not block item selection for a local preference. */}}
let generation=0
function canSend(item:any){return item.sendable!==undefined?item.sendable:!!item.allowed&&(item.supported!==false)}
async function load(reset=false){
 if(reset)page.value=1
 const current=++generation;loading.value=true;error.value=''
 const snapshot={...filters.value}
 const query=new URLSearchParams({page:String(page.value)})
 for(const [key,value] of Object.entries(snapshot)){if(value===''||value==null||value===false)continue;query.set(key,value===true?'1':String(value))}
 try{const result=await api('/catalog?'+query);if(current!==generation)return
  const previous=metadata.value?.pvf_sha256
  metadata.value=result.metadata;facets.value=result.facets;total.value=result.total??0
  rows.value=(result.items||[]).map((item:any)=>({...item,pvf_sha256:item.pvf_sha256||result.metadata?.pvf_sha256}))
  if(previous&&previous!==metadata.value?.pvf_sha256){comparison.value=[];warning.value='PVF 已更新，原有对比已清空。'}
  const applied:Record<string,any>={q:snapshot.q||'',category:snapshot.category||'',allowed_only:!!snapshot.allowed_only,sort:snapshot.sort||'id'};for(const key of ['part','rarity','min_level','max_level','job','weapon_type','set_id'])if(snapshot[key]!==''&&snapshot[key]!=null)applied[key]=['rarity','min_level','max_level','set_id'].includes(key)?Number(snapshot[key]):snapshot[key]
  emit('loaded',{metadata:metadata.value,total:total.value,filters:applied})
 }catch(e){if(current===generation){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}}finally{if(current===generation)loading.value=false}
}
function compare(item:any){if(comparison.value.some(i=>i.id===item.id)){comparison.value=comparison.value.filter(i=>i.id!==item.id);warning.value='';return}if(comparison.value.length>=4){warning.value='最多同时对比4件物品，请先移出一件。';return}comparison.value.push({...item});warning.value=''}
function favorite(value:{id:number,pvf_sha256:string,favorite:boolean}){for(const item of [...rows.value,...comparison.value])if(item.id===value.id&&item.pvf_sha256===value.pvf_sha256)item.favorite=value.favorite;favoriteRevision.value++}
function select(item:any){if(!props.disabled&&canSend(item)){emit('select',item);favoriteRevision.value++}}
watch(()=>props.revision,()=>load())
onMounted(()=>load())
onUnmounted(()=>{generation++;if(props.contextKey&&stateStore)stateStore.contexts[props.contextKey]={filters:{...filters.value},page:page.value,comparison:comparison.value,pvf:metadata.value?.pvf_sha256||''}})
defineExpose({refresh:()=>load()})
</script>
<template><section class="gm-item-picker" aria-label="物品选择器">
 <ItemCollection :revision="favoriteRevision" :disabled="disabled" @select="select" @changed="favorite"/>
 <form class="toolbar" @submit.prevent="load(true)"><input v-model="filters.q" aria-label="物品搜索" placeholder="物品名称或编号" :disabled="disabled"><select v-model="filters.category" aria-label="物品分类" :disabled="disabled" @change="load(true)"><option value="">全部类型</option><option value="equipment">装备</option><option value="material">材料</option><option value="consumable">消耗品</option><option value="special">特殊 / 时装 / 宠物</option></select><button type="submit" class="primary" :disabled="disabled">查询</button></form>
 <CatalogFilters v-model="filters" :facets="facets" :pvf="metadata?.pvf_sha256" :disabled="disabled" @apply="load(true)"/>
 <div class="picker-controls"><label class="checkbox-field"><input v-model="filters.allowed_only" type="checkbox" :disabled="disabled" @change="load(true)">仅看可发放物品</label><button v-if="managePolicy" type="button" :disabled="disabled" @click="emit('policy')">调整当前筛选策略 · {{total}} 项</button><span v-if="selectedCount!==undefined" class="pill">已选 {{selectedCount}} / 20 条</span><div class="picker-view-switch" role="group" aria-label="物品排列方式" title="只改变排列方式，按 PVF 在此浏览器保存"><button type="button" :aria-pressed="view==='grid'" :disabled="props.disabled" @click="changeView('grid')"><SvgIcon icon="lucide:layout-grid" aria-hidden="true"/>图标网格</button><button type="button" :aria-pressed="view==='list'" :disabled="props.disabled" @click="changeView('list')"><SvgIcon icon="lucide:list" aria-hidden="true"/>紧凑列表</button></div></div>
 <ItemCompare :items="comparison" @remove="id=>comparison=comparison.filter(i=>i.id!==id)" @clear="comparison=[]"/>
 <p v-if="warning" role="status" class="field-hint">{{warning}}</p><p v-if="error" role="alert" class="submit-error">{{error}} <button type="button" :disabled="disabled" @click="load()">重试查询</button></p>
 <p v-if="loading" role="status" class="field-hint">正在读取物品…</p>
 <div class="picker-card-grid" :class="{'picker-card-grid--list':view==='list'}"><article v-for="item in rows" :key="item.id" class="picker-item"><ItemCard :item="item"><small :class="canSend(item)?'':'policy-blocked'">{{item.policy_state==='verified'?'已验证':canSend(item)?'允许试发，未验证':'不可发放'}}<template v-if="item.part_name"> · {{item.part_name}}</template></small><small v-if="item.policy_reason">{{item.policy_reason}}</small></ItemCard><div class="picker-item-actions"><FavoriteButton :item="item" :disabled="disabled" @changed="favorite"/><button type="button" :disabled="disabled" :aria-pressed="comparison.some(i=>i.id===item.id)" @click="compare(item)">{{comparison.some(i=>i.id===item.id)?'移出对比':'对比'}}</button><button v-if="managePolicy" type="button" :disabled="disabled||item.supported===false" @click="emit('policy',item)">策略</button><button type="button" class="primary" :disabled="disabled||!canSend(item)" @click="select(item)">{{canSend(item)?'加入清单':'不可发放'}}</button></div></article></div>
 <p v-if="!rows.length&&!loading&&!error" class="empty">未找到物品，请调整名称、编号或组合筛选。</p>
 <div class="pagination"><button type="button" :disabled="disabled||page===1" @click="page--;load()">上一页物品</button><span>第 {{page}} 页 · 共 {{total}} 项</span><button type="button" :disabled="disabled||page*50>=total" @click="page++;load()">下一页物品</button></div>
 <details v-if="metadata"><summary>索引版本与发放说明</summary><p class="field-hint">查看详情、筛选与对比只读取数据。加入清单不会发放；预览后还需显式确认。数量不按 PVF 堆叠限制，装备等逐件投递。</p><pre>{{JSON.stringify(metadata,null,2)}}</pre></details>
</section></template>
<style scoped>
.gm-item-picker{min-width:0}.picker-controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:12px 0}.picker-card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:12px}.picker-item{padding:14px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-primary);display:flex;flex-direction:column;gap:14px;min-width:0}.picker-item-actions{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:auto}.picker-item-actions>button:last-child{margin-left:auto}.policy-blocked{color:var(--danger-color,#b42318)}.picker-item :deep(.shared-item-copy){min-width:0}.picker-item :deep(.shared-item-copy small){overflow-wrap:anywhere}.picker-item :deep(.item-inspect){white-space:normal;text-align:left}@media(max-width:600px){.picker-card-grid{grid-template-columns:1fr}.picker-item{padding:12px}.picker-item-actions>button,.picker-item-actions :deep(.favorite-control button){min-height:36px;padding:7px 9px;font-size:12px}.pagination{gap:8px;flex-wrap:wrap;justify-content:center}.pagination span{font-size:12px}}
</style>
<style scoped>
.picker-view-switch{display:flex;align-items:center;gap:3px;margin-left:auto;padding:3px;border:1px solid var(--border-color);border-radius:10px;background:var(--bg-secondary)}
.picker-view-switch>button{display:inline-flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid transparent;border-radius:7px;background:transparent;font-size:12px;white-space:nowrap}
.picker-view-switch>button[aria-pressed=true]{border-color:var(--border-color);background:var(--bg-primary);color:var(--primary-color);box-shadow:0 1px 3px #00000006}
.picker-view-switch>button:focus-visible{outline:2px solid var(--primary-color);outline-offset:1px}
.picker-card-grid--list{grid-template-columns:minmax(0,1fr);gap:8px}
.picker-card-grid--list>.picker-item{display:flex;flex-direction:row;flex-wrap:wrap;align-items:center;gap:12px 20px;padding:10px 14px}
.picker-card-grid--list :deep(.shared-item-card){flex:1 1 280px;min-width:0}
.picker-card-grid--list .picker-item-actions{max-width:100%;margin-top:0;margin-left:auto;justify-content:flex-end}
.picker-card-grid--list .picker-item-actions>button:last-child{margin-left:0}
@media(max-width:800px){.picker-card-grid--list>.picker-item{gap:9px}.picker-card-grid--list :deep(.shared-item-card){flex-basis:100%}.picker-card-grid--list .picker-item-actions{width:100%;padding-top:9px;border-top:1px solid var(--border-color)}}
@media(max-width:600px){.picker-controls{gap:10px}.picker-view-switch{margin-left:0}.picker-view-switch>button{min-height:34px}.picker-card-grid--list>.picker-item{padding:10px 12px}}
</style>
