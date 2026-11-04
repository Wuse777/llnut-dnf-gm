<script setup lang="ts">
import {ref,watch,onUnmounted} from 'vue'
import {api,uncertainMessage} from '../api'
import FavoriteButton from './FavoriteButton.vue'
const props=defineProps<{revision?:number,disabled?:boolean}>()
const emit=defineEmits<{select:[item:any],changed:[value:{id:number,pvf_sha256:string,favorite:boolean}]}>()
const open=ref(false),collection=ref('favorites'),page=ref(1),rows=ref<any[]>([]),total=ref(0),loading=ref(false),error=ref('')
let generation=0
async function load(){
 if(!open.value)return
 const ticket=++generation;loading.value=true;error.value='';rows.value=[]
 try{const result=await api('/catalog/collections?collection='+collection.value+'&page='+page.value);if(ticket===generation){rows.value=result.items;total.value=result.total}}
 catch(e){if(ticket===generation)error.value=uncertainMessage(e)}
 finally{if(ticket===generation)loading.value=false}
}
function toggle(e:Event){const next=(e.target as HTMLDetailsElement).open;if(next===open.value)return;open.value=next;if(open.value)void load();else{generation++;loading.value=false}}
function switchCollection(value:string){collection.value=value;page.value=1;void load()}
watch(()=>props.revision,()=>{if(open.value)void load()})
onUnmounted(()=>generation++)
</script>
<template>
 <details class="item-collection" @toggle="toggle">
  <summary>常用物品 · 收藏 / 最近选择</summary>
  <div class="button-row collection-controls"><button type="button" :aria-pressed="collection==='favorites'" :class="{primary:collection==='favorites'}" @click="switchCollection('favorites')">我的收藏</button><button type="button" :aria-pressed="collection==='recent'" :class="{primary:collection==='recent'}" @click="switchCollection('recent')">最近选择</button><button type="button" :disabled="loading" @click="load">刷新常用物品</button></div>
  <p class="field-hint">按当前 PVF 版本独立保存。最近选择仅表示加入过草稿，不代表发放或领取；收藏不会启用被停用的物品。</p>
  <p v-if="error" class="submit-error" role="alert">{{error}} <button type="button" @click="load">重试常用物品查询</button></p>
  <p v-if="loading" role="status">正在读取常用物品…</p>
  <div v-else-if="rows.length" class="collection-items"><article v-for="item in rows" :key="item.id"><div><b>{{item.name}}</b><small class="cell-note">#{{item.id}} · {{item.sendable?'可加入草稿':'不可发放'}}</small><small v-if="!item.sendable" class="cell-note">{{item.policy_reason}}</small></div><div class="button-row"><FavoriteButton :item="item" :disabled="disabled" @changed="emit('changed',$event)"/><button type="button" :disabled="disabled||!item.sendable" @click="emit('select',item)">加入清单</button></div></article></div>
  <p v-else-if="!error" class="empty">{{collection==='favorites'?'当前 PVF 下没有收藏，在物品旁点击“收藏”即可保存。':'当前 PVF 下还没有最近选择记录。'}}</p>
  <div v-if="!error" class="pagination"><button type="button" aria-label="上一页常用物品" :disabled="loading||page<=1" @click="page--;load()">上一页</button><span>第 {{page}} 页 · 共 {{total}} 项</span><button type="button" aria-label="下一页常用物品" :disabled="loading||page*50>=total" @click="page++;load()">下一页</button></div>
 </details>
</template>
