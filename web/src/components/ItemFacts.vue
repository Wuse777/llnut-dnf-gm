<script setup lang="ts">
import {computed} from 'vue'
import GameImage from './GameImage.vue'
const props=defineProps<{item:any,stored?:boolean}>()
const categoryNames:Record<string,string>={equipment:'装备',material:'材料',consumable:'消耗品',special:'特殊物品'}
const type=computed(()=>props.item.type_name||categoryNames[props.item.category]||'类型未收录')
function number(v:unknown){return v===null||v===undefined||v===''?'未知':typeof v==='number'||/^\d+$/.test(String(v))?Number(v).toLocaleString('zh-CN'):String(v)}
const has=(key:string)=>props.item[key]!==null&&props.item[key]!==undefined
const delivery=computed(()=>props.item.single_item===true||props.item.category==='equipment'?'每件独立投递':props.item.single_item===false||props.item.mail_kind==='stackable'||['material','consumable'].includes(props.item.category)?'按数量投递':'投递方式未提供')
const policy=computed(()=>({verified:'已验证',trial:'允许试发 · 未验证',blocked:'禁止发放'} as Record<string,string>)[props.item.policy_state]||'未提供发放策略')
</script>
<template>
 <div class="item-facts">
  <div class="item-detail-hero"><GameImage :image="item.image" :label="item.name||'物品'" :rarity-name="item.rarity_name" :rarity="item.rarity" :icon-size="48"/><div><span class="item-eyebrow">{{stored?'角色存档':'物品索引'}} · #{{item.id}}</span><h3>{{item.name||'名称未收录'}}</h3><p>{{type}} · {{item.level===null||item.level===undefined?'等级未知':'Lv. '+item.level}}<template v-if="item.rarity_name"> · {{item.rarity_name}}</template></p></div></div>
  <p v-if="!stored" class="item-policy-label" :class="{'is-blocked':item.policy_state==='blocked'}">{{policy}}</p>
  <dl class="character-facts">
   <div><dt>物品编号</dt><dd>{{item.id}}</dd></div><div v-if="item.part_name"><dt>装备部位</dt><dd>{{item.part_name}}</dd></div><div><dt>品级</dt><dd>{{item.rarity_name||'未收录'}}<small v-if="has('rarity')&&!item.rarity_name">原始值 {{item.rarity}}，未推断名称</small></dd></div>
   <div v-if="stored||has('quantity')"><dt>{{stored?'存档数量':'本条数量'}}</dt><dd>{{number(item.quantity)}}</dd></div>
   <div v-if="stored"><dt>位置</dt><dd>{{item.slot_label||'存档槽位'}} / #{{item.slot}}</dd></div>
   <template v-if="stored&&has('enhancement')"><div><dt>强化 / 锻造</dt><dd>+{{item.enhancement}} / {{has('forge')?'+'+item.forge:'未知'}}</dd></div><div><dt>耐久</dt><dd>{{number(item.durability)}}<small v-if="has('base_durability')">PVF基础耐久 {{item.base_durability}}</small></dd></div><div><dt>增幅类型 / 数值</dt><dd>{{number(item.amplify_type)}} / {{number(item.amplify_value)}}</dd></div><div><dt>附魔</dt><dd>{{item.enchantment?.name||number(item.orb_id)}}<small v-if="item.orb_id">#{{item.orb_id}}</small><small v-if="item.enchantment?.summary">{{item.enchantment.summary}}</small></dd></div><div><dt>封装原始标记</dt><dd>{{number(item.sealed_raw)}}</dd></div></template>
   <template v-if="!stored"><div><dt>投递方式</dt><dd>{{delivery}}</dd></div><div><dt>发放数量</dt><dd>不按 PVF 限额<small>正整数，字段范围 1–2,147,483,647</small></dd></div></template>
  </dl>
  <details v-if="item.base_attributes?.length" class="item-source-attributes"><summary>PVF 顶层定义原值</summary><dl class="character-facts"><div v-for="attribute in item.base_attributes" :key="attribute.tag"><dt>{{attribute.label}}</dt><dd>{{attribute.values.join(' / ')}}</dd></div></dl><p class="field-hint">已排除显式成对段中的数值；不解释条件、附魔、角色加成或强化，也未换算单位。</p></details>
  <p v-if="!stored&&item.policy_reason" class="field-hint">发放策略：{{item.policy_reason}}</p>
  <p class="item-image-note">{{item.image?.note||'未安装匹配图片包，使用占位图；不影响文字查询。'}}</p>
  <p class="field-hint">{{stored?'数据库只读存档；不代表实时战斗属性、实际已开放格数或可发放状态。':'此处只查看已有索引信息；打开详情不会加入草稿、改变策略或发放物品。'}}</p>
 </div>
</template>
