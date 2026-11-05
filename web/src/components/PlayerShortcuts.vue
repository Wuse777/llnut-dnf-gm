<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {api,ApiError,uncertainMessage} from '../api'
const props=defineProps<{revision:number,busy?:boolean,current?:{uid:number,charac_no:number,label:string}|null}>()
const emit=defineEmits<{choose:[value:{uid:number,charac_no:number}],changed:[],expired:[]}>()
const collection=ref<'recent'|'favorites'>('recent'),page=ref(1),data=ref<any>(null),loading=ref(false),saving=ref(false),error=ref(''),message=ref('')
let generation=0,alive=true
async function load(){
 const epoch=++generation;loading.value=true;error.value='';data.value=null
 try{const d=await api(`/players/collections?collection=${collection.value}&page=${page.value}`);if(alive&&epoch===generation)data.value=d}
 catch(e){if(alive&&epoch===generation){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}}
 finally{if(alive&&epoch===generation)loading.value=false}
}
function switchCollection(v:'recent'|'favorites'){collection.value=v;page.value=1;message.value='';void load()}
async function favorite(target:{uid:number,charac_no:number},enabled:boolean){
 if(props.busy||saving.value)return
 saving.value=true;error.value='';message.value=''
 try{await api('/players/favorite','PUT',{uid:target.uid,charac_no:target.charac_no,favorite:enabled});if(!alive)return;message.value=enabled?'已保存常用目标；不会执行充值或发奖。':'已取消收藏，不影响历史操作。';emit('changed');await load()}
 catch(e){if(alive){error.value=uncertainMessage(e);if(e instanceof ApiError&&e.status===401)emit('expired')}}
 finally{if(alive)saving.value=false}
}
watch(()=>props.revision,()=>load(),{immediate:true});onBeforeUnmount(()=>{alive=false;generation++})
</script>
<template><section class="panel player-shortcuts" aria-label="玩家快捷目标">
 <header class="section-title"><div><h2>玩家快捷目标</h2><p class="field-hint">跨浏览器保存账号／角色编号，点击仅带入目标，不执行奖励。</p></div><button v-if="current" :disabled="busy||saving" @click="favorite(current,true)">收藏当前{{current.charac_no?'角色':'账号'}}</button></header>
 <div v-if="current" class="current-target"><span>当前目标</span><strong>{{current.label}}</strong><small>UID {{current.uid}}<template v-if="current.charac_no"> · 角色 #{{current.charac_no}}</template></small></div>
 <div class="button-row" role="group" aria-label="玩家目标集合"><button :aria-pressed="collection==='recent'" :disabled="saving" @click="switchCollection('recent')">最近访问</button><button :aria-pressed="collection==='favorites'" :disabled="saving" @click="switchCollection('favorites')">常用目标</button><button class="ghost" :disabled="loading||saving" @click="load">刷新快捷目标</button></div>
 <p v-if="error" class="submit-error" role="alert">{{error}} <button :disabled="loading||saving" @click="load">重试读取</button></p><p v-if="message" class="submit-success" role="status">{{message}}</p><p v-if="loading" role="status">正在读取快捷目标…</p>
 <div v-if="data?.items?.length" class="player-target-grid"><article v-for="r in data.items" :key="r.uid+':'+r.charac_no" :class="{unavailable:!r.available}">
  <button class="target-open" :disabled="busy||saving||!r.available" @click="emit('choose',{uid:r.uid,charac_no:r.charac_no})"><span class="target-kind">{{r.charac_no?'角色':'账号'}}</span><strong>{{r.charac_no?(r.character?.charac_name||'角色已不存在／归属变化'):(r.account?.accountname||'账号已不存在')}}</strong><small>{{r.account?.accountname||'未知账号'}} · UID {{r.uid}}<template v-if="r.charac_no"> · #{{r.charac_no}}</template></small><span v-if="!r.available" class="field-hint">不可作为新操作目标，仍可取消收藏</span></button>
  <button class="target-star ghost" :aria-label="(r.favorite?'取消收藏目标 ':'收藏目标 ')+r.uid+':'+r.charac_no" :aria-pressed="r.favorite" :disabled="busy||saving||(!r.available&&!r.favorite)" @click="favorite(r,!r.favorite)">{{r.favorite?'★':'☆'}}</button>
 </article></div>
 <p v-else-if="data&&!loading" class="empty">{{collection==='recent'?'还没有最近访问记录。选择账号或打开角色详情后会自动记录。':'还没有常用目标。可收藏当前目标，或点击最近访问卡片上的星标。'}}</p>
 <div v-if="data&&data.total>data.page_size" class="pagination"><button :disabled="loading||saving||page<=1" @click="page--;load()">上一页快捷目标</button><span>第 {{page}} 页 · 共 {{data.total}} 项</span><button :disabled="loading||saving||page*data.page_size>=data.total" @click="page++;load()">下一页快捷目标</button></div>
</section></template>
<style scoped>
.player-shortcuts{display:grid;gap:12px}.player-shortcuts h2{font-size:17px}.player-shortcuts header p{margin-bottom:0}.current-target{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 12px;border-radius:10px;background:var(--bg-secondary);border-left:3px solid var(--primary-color)}.current-target>span{color:var(--text-secondary);font-size:12px}.player-target-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.player-target-grid article{display:flex;align-items:center;border:1px solid var(--border-color);border-radius:12px;overflow:hidden;background:var(--bg-secondary)}.target-open{display:grid;gap:5px;text-align:left;border:0;background:transparent;box-shadow:none;flex:1;min-width:0;padding:13px}.target-open strong,.target-open small{overflow-wrap:anywhere}.target-open small{color:var(--text-secondary);font-size:11px}.target-kind{font-size:10px;color:var(--primary-color);letter-spacing:1px}.target-star{font-size:22px;padding:10px;flex-shrink:0}.unavailable{opacity:.7}@media(max-width:1000px){.player-target-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.player-target-grid{grid-template-columns:1fr}.player-shortcuts header{align-items:flex-start}}
</style>
