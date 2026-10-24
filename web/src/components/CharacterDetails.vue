<script setup lang="ts">
import {ref,computed,watch,onUnmounted,nextTick} from 'vue'
import {api,uncertainMessage} from '../api'
import Modal from './Modal.vue'
const props=defineProps<{characNo:number}>()
const emit=defineEmits<{close:[]}>()
const root=ref<HTMLElement|null>(null)
const data=ref<any>(null),loading=ref(false),error=ref(''),section=ref('basic'),search=ref(''),kind=ref(''),page=ref(1)
let generation=0
const tabs=[['basic','基本信息'],['attributes','属性存档'],['equipment','穿戴装备'],['backpack','背包道具']]
function number(n:unknown){return n===null||n===undefined?'未知':Number(n).toLocaleString('zh-CN')}
function date(s:unknown){if(typeof s!=='string'||s.startsWith('0000-'))return '未记录';const d=new Date(s.replace(' ','T')+'Z');return Number.isNaN(d.getTime())?'未记录':d.toLocaleString('zh-CN',{hour12:false})}
async function load(){
 const current=++generation;loading.value=true;error.value='';data.value=null
 try{const result=await api('/characters/'+props.characNo);if(current===generation){data.value=result;page.value=1}}
 catch(e){if(current===generation)error.value=uncertainMessage(e)}
 finally{if(current===generation)loading.value=false}
}
watch(()=>props.characNo,()=>{section.value='basic';search.value='';kind.value='';page.value=1;void load()},{immediate:true})
onUnmounted(()=>generation++)
const container=computed(()=>data.value?.[section.value])
const items=computed(()=>container.value?.items??[])
const filtered=computed(()=>items.value.filter((i:any)=>(!kind.value||String(i.type)===kind.value)&&(!search.value.trim()||i.name.includes(search.value.trim())||String(i.id).includes(search.value.trim()))))
const pages=computed(()=>Math.max(1,Math.ceil(filtered.value.length/30)))
const visible=computed(()=>filtered.value.slice((page.value-1)*30,page.value*30))
const kinds=computed(()=>Array.from(new Map(items.value.map((i:any)=>[String(i.type),i.type_name])).entries()) as [string,string][])
watch([section,search,kind],()=>{page.value=1})
watch(section,async()=>{await nextTick();root.value?.closest('.modal-body')?.scrollTo?.({top:0})})
function tabKey(e:KeyboardEvent){if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=tabs.findIndex(t=>t[0]===section.value),index=e.key==='Home'?0:e.key==='End'?tabs.length-1:(n+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tab(tabs[index][0]);void nextTick(()=>root.value?.querySelector<HTMLButtonElement>('#character-tab-'+section.value)?.focus())}
function tab(id:string){section.value=id;search.value='';kind.value=''}
</script>
<template>
 <Modal title="角色详情" @close="emit('close')">
  <div ref="root" class="character-detail" data-testid="character-detail">
   <div class="section-title character-toolbar"><span class="pill">只读查询 · 角色 #{{characNo}}</span><button :disabled="loading" @click="load">{{loading?'正在读取…':'刷新角色存档'}}</button></div>
   <p v-if="loading" role="status" class="empty"><span class="spinner"/> 正在读取角色资料、装备与背包…</p>
   <div v-else-if="error" class="submit-error" role="alert"><b>无法读取角色详情</b><p>{{error}}</p><button @click="load">重试查询</button></div>
   <template v-else-if="data">
    <div class="character-identity"><div><h3>{{data.character.charac_name}}</h3><p>{{data.profession.name}} · Lv.{{data.character.lev}} · {{data.account?.accountname??'归属账号缺失'}} / UID {{data.character.uid}}</p></div><span class="status-badge" :class="data.character.delete_flag?'neutral':'success'">{{data.character.delete_flag?'已删除（仅查看存档）':'未删除'}}</span></div>
    <p class="field-hint snapshot-note">{{data.snapshot_note}}<br>读取时间：{{new Date(data.collected_at*1000).toLocaleString('zh-CN',{hour12:false})}}。本页不修改角色、金币或物品。</p>
    <p v-if="data.account_online?.login_status===1" class="warning">所属账号在线；不代表当前角色在线。背包、金币和属性可能等待游戏进程保存，刷新网页不会强制保存。</p>
    <p v-if="data.catalog_state!=='ok'" class="submit-error" role="status">物品索引不可用或版本不匹配：仍显示存档编号，但物品名称、等级及职业名称可能未知。</p>
    <div class="operation-tabs detail-tabs" role="tablist" aria-label="角色详情分类" @keydown="tabKey"><button v-for="[id,label] in tabs" :id="'character-tab-'+id" :key="id" role="tab" :aria-selected="section===id" :tabindex="section===id?0:-1" :aria-controls="'character-section-'+id" :class="{active:section===id}" @click="tab(id)">{{label}}<span v-if="id==='equipment'||id==='backpack'"> · {{data[id].state==='ok'?data[id].items.length:'未知'}}</span></button></div>
    <section :id="'character-section-'+section" role="tabpanel" :aria-labelledby="'character-tab-'+section" tabindex="0">
     <template v-if="section==='basic'">
      <div class="character-metrics"><article><span>角色携带金币</span><strong>{{number(data.wealth.gold)}}</strong><small>{{data.wealth.state==='ok'?'不含仓库金币、点券或代币券':'金币存档缺失，不能视为0'}}</small></article><article><span>等级</span><strong>{{data.character.lev}}</strong><small>角色存档等级</small></article><article><span>复活币 coin 原始值</span><strong>{{number(data.wealth.revival_coin_raw)}}</strong><small>非多种复活币合计</small></article></div>
      <dl class="character-facts"><div><dt>角色名 / 编号</dt><dd>{{data.character.charac_name}} / #{{data.character.charac_no}}</dd></div><div><dt>所属账号</dt><dd>{{data.account?.accountname??'缺失'}} / UID {{data.character.uid}}</dd></div><div><dt>职业 / 转职</dt><dd>{{data.profession.base_name}} / {{data.profession.name}}<small>job={{data.character.job}}，grow_type={{data.character.grow_type}}；{{data.profession.note}}</small></dd></div><div><dt>账号登录状态 / 频道</dt><dd>{{data.account_online?.login_status===1?'在线':data.account_online?.login_status===0?'离线':'未知'}} / {{data.account_online?.channel??'未知'}}</dd></div><div><dt>经验存档</dt><dd>{{number(data.play_state?.exp??data.character.exp)}}<small>{{data.play_state?'来源：charac_stat':'来源：charac_info（无独立状态记录）'}}</small></dd></div><div><dt>疲劳存档 / 上限</dt><dd>{{number(data.play_state?.fatigue??data.character.fatigue)}} / {{number(data.character.max_fatigue)}}<small>不据此推算客户端剩余疲劳</small></dd></div><div><dt>已用疲劳存档</dt><dd>{{number(data.play_state?.used_fatigue)}}</dd></div><div><dt>公会编号</dt><dd>{{data.character.guild_id||'无公会'}}</dd></div><div><dt>创建时间</dt><dd>{{date(data.character.create_time)}}</dd></div><div><dt>最近游戏存档时间</dt><dd>{{date(data.play_state?.last_play_time??data.character.last_play_time)}}</dd></div></dl>
     </template>
     <template v-else-if="section==='attributes'">
      <p class="field-hint">下列是数据库字段原始存档值，不是游戏内最终面板。速度未擅自换算为百分比；力量、智力、体力、精神及元素抗性等未确认字段映射，暂不猜测显示。</p>
      <dl class="character-facts attribute-grid"><div v-for="a in data.attributes" :key="a.key"><dt>{{a.label}}<small>{{a.key}}</small></dt><dd>{{number(a.value)}}</dd></div></dl>
     </template>
     <template v-else>
      <div v-if="container.state!=='ok'" class="submit-error" role="status">{{container.message}}</div>
      <template v-else>
       <form class="toolbar" @submit.prevent><input v-model="search" aria-label="筛选角色物品" placeholder="当前容器内搜索名称或物品编号"><select v-model="kind" aria-label="角色物品类型"><option value="">全部类型</option><option v-for="[id,label] in kinds" :key="id" :value="id">{{label}}</option></select><button type="button" @click="search='';kind=''">清除筛选</button></form>
       <p class="field-hint">共 {{items.length}} 个非空槽位，筛选后 {{filtered.length}} 条；容器共 {{container.slot_count}} 个存档槽位（不代表已解锁格数）。{{section==='backpack'?'仅本角色背包，不含仓库、时装栏、宠物栏或未领取邮件。':'普通穿戴槽，不含独立时装栏或宠物栏。'}}物品可查看不代表可通过邮件发放。</p>
       <div v-if="visible.length" class="table-wrap character-items"><table><thead><tr><th>槽位</th><th>物品 / 编号</th><th>类型</th><th>数量</th><th>装备信息</th></tr></thead><tbody><tr v-for="i in visible" :key="i.slot"><td>{{i.slot_label}}<small class="cell-note">#{{i.slot}}</small></td><td><b>{{i.name}}</b><small class="cell-note">#{{i.id}} · {{i.level===null?'等级未知':'Lv.'+i.level}}</small></td><td>{{i.type_name}}</td><td>{{number(i.quantity)}}</td><td v-if="i.enhancement!==null"><span>强化 +{{i.enhancement}} · 锻造 +{{i.forge}}</span><small class="cell-note">耐久 {{i.durability}} · 增幅类型 {{i.amplify_type}} / 数值 {{i.amplify_value}}</small><small class="cell-note">附魔 ID {{i.orb_id}} · 封装原始标记 {{i.sealed_raw}}</small></td><td v-else>—</td></tr></tbody></table></div>
       <p v-else class="empty">{{items.length?'没有匹配的物品，请调整筛选条件。':'该容器存档没有非空物品。'}}</p>
       <div class="pagination"><button :disabled="page<=1" @click="page--">上一页物品</button><span>第 {{page}} / {{pages}} 页 · 每页30条</span><button :disabled="page>=pages" @click="page++">下一页物品</button></div>
      </template>
     </template>
    </section>
   </template>
  </div>
  <template #footer><span class="muted">只读 · 不会发放、回收或修改物品</span><button class="primary" @click="emit('close')">关闭详情</button></template>
 </Modal>
</template>
