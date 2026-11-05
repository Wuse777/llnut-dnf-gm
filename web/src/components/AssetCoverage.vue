<script setup lang="ts">
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
import GameImage from './GameImage.vue'
const emit=defineEmits<{expired:[]}>()
const data=ref<any>(null),state=ref('missing'),page=ref(1),busy=ref(false),error=ref(''),copied=ref('')
let alive=true
const labels:Record<string,string>={ready:'图标可读取',missing:'缺少客户端素材',missing_reference:'没有PVF引用',ambiguous:'来源冲突',unsupported:'格式待适配'}
const kinds:Record<string,string>={official_promotional:'官方职业插画',client:'客户端职业图',custom:'维护者示意图'}
const total=computed(()=>Object.values(data.value?.item_states||{}).reduce((sum:number,n:any)=>sum+(typeof n==='number'?n:0),0))
const coverage=computed(()=>total.value?((data.value?.item_states?.ready||0)/total.value*100).toFixed(1):'0.0')
async function load(reset=false){
 if(busy.value)return;if(reset)page.value=1;busy.value=true;error.value='';copied.value=''
 try{const result=await api(`/assets/coverage?state=${state.value}&page=${page.value}`);if(alive)data.value=result}
 catch(e){if(alive){data.value=null;error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}}finally{if(alive)busy.value=false}
}
async function copy(id:number){try{await navigator.clipboard.writeText(String(id));copied.value='已复制物品编号 '+id}catch{copied.value='无法自动复制，请选择编号手动复制。'}}
onMounted(()=>void load());onBeforeUnmount(()=>{alive=false})
</script>
<template><section class="panel asset-coverage">
 <div class="section-title"><div><h2>图片与职业头像</h2><p class="muted">区分真实可用图片、缺失素材与官方宣传插画</p></div><button :disabled="busy" @click="load()">刷新图片覆盖</button></div>
 <p v-if="error" class="submit-error" role="alert">{{error}}</p><p v-if="busy" role="status">正在读取图片包…</p>
 <template v-if="data">
  <div class="asset-metrics"><article><small>物品图标覆盖</small><strong>{{coverage}}<span>%</span></strong><p>{{data.item_states.ready||0}} / {{total}} 项可读取</p></article><article><small>职业头像映射</small><strong>{{data.portrait_total}}</strong><p>基础职业示意与精确转职映射分别标注</p></article><article><small>版本绑定</small><strong class="asset-bound">PVF已匹配</strong><p>不是客户端像素一致性验证</p></article></div>
  <p class="field-hint">职业插画不能代替角色实际外观；头像可用也不代表物品图标已补齐。官方宣传插画不是从当前客户端NPK提取。</p>
  <div v-if="data.portraits.length" class="portrait-gallery"><article v-for="p in data.portraits" :key="`${p.job}-${p.grow_type}-${p.sex}`"><GameImage :image="p.image" :label="p.name" portrait/><div><b>{{p.name}}</b><small>{{p.image.source_label||kinds[p.image.source_kind]||'维护者映射'}}</small><small>{{p.image.match_level==='base'?'基础职业示意':'转职精确映射'}} · job {{p.job}}</small><a v-if="p.image.source_page" :href="p.image.source_page" target="_blank" rel="noopener noreferrer">查看素材出处 ↗</a></div></article></div>
  <p v-if="data.portrait_total>data.portraits.length" class="field-hint">当前展示前 {{data.portraits.length}} 条映射，共 {{data.portrait_total}} 条。</p>
  <details class="asset-reference"><summary>当前图片包PVF指纹</summary><code>{{data.pvf_sha256}}</code></details>
  <div class="asset-list-title"><h3>物品图标明细</h3><label>图片状态<select v-model="state" :disabled="busy" @change="load(true)"><option value="all">全部物品</option><option v-for="(label,id) in labels" :key="id" :value="id">{{label}}（{{data.item_states[id]||0}}）</option></select></label></div>
  <p v-if="copied" class="field-hint" role="status">{{copied}}</p>
  <p v-if="!data.items.length" class="empty">这个状态没有记录；不会把空列表当作全部素材已验证。</p>
  <div v-else class="asset-item-list"><article v-for="item in data.items" :key="item.id"><div><b>{{item.name}}</b><small>#{{item.id}} · {{labels[item.state]||item.note}}</small></div><button :disabled="busy" @click="copy(item.id)">复制编号</button></article></div>
  <div class="asset-pager"><button :disabled="busy||page<=1" @click="page--;load()">上一页</button><span>第 {{data.page}} 页 · 每页20项</span><button :disabled="busy||!data.has_more" @click="page++;load()">下一页</button></div>
 </template>
</section></template>
<style scoped>
.asset-coverage{display:grid;gap:18px}.asset-coverage p,.asset-coverage h3{margin:0}.asset-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.asset-metrics article{padding:18px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary)}.asset-metrics strong{display:block;font-size:30px;line-height:1.6;letter-spacing:-.03em}.asset-metrics strong span{font-size:16px;margin-left:3px}.asset-metrics .asset-bound{font-size:21px;padding-block:7px}.asset-metrics p,.asset-metrics small,.portrait-gallery small,.asset-item-list small{color:var(--text-secondary);font-size:12px}.portrait-gallery{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.portrait-gallery article{display:flex;align-items:center;gap:10px;padding:12px;border:1px solid var(--border-color);border-radius:12px;background:var(--bg-secondary)}.portrait-gallery article>div{display:grid;gap:5px;min-width:0}.portrait-gallery :deep(.game-image){margin:0;width:60px;height:72px;flex-basis:60px}.portrait-gallery small,.portrait-gallery a{font-size:11px;overflow-wrap:anywhere}.portrait-gallery a{color:var(--text-secondary)}.asset-reference code{display:block;margin-top:10px;overflow-wrap:anywhere}.asset-list-title,.asset-pager,.asset-item-list article{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.asset-list-title label{display:flex;align-items:center;gap:10px;font-size:12px}.asset-item-list{display:grid;gap:7px}.asset-item-list article{padding:11px 13px;border:1px solid var(--border-color);border-radius:9px}.asset-item-list article>div{display:grid;gap:5px;min-width:0;overflow-wrap:anywhere}.asset-item-list button{font-size:12px}.asset-pager{justify-content:flex-end;font-size:12px}@media(max-width:700px){.asset-metrics{grid-template-columns:1fr}.portrait-gallery{grid-template-columns:1fr}.asset-list-title label{width:100%;justify-content:space-between}.asset-pager{justify-content:space-between}}
</style>
