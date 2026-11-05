<script setup lang="ts">
import {computed,ref,watch} from 'vue'
export type AssetImage={state:string,url?:string|null,note?:string,width?:number,height?:number,source_kind?:string,source_label?:string,focus_x?:number,focus_y?:number}
const props=withDefaults(defineProps<{image?:AssetImage|null,label:string,portrait?:boolean}>(),{portrait:false})
const failed=ref(false)
const focus=computed(()=>[props.image?.focus_x,props.image?.focus_y].every(v=>typeof v==='number'&&v>=0&&v<=100)?`${props.image!.focus_x}% ${props.image!.focus_y}%`:'50% 50%')
const src=computed(()=>props.image?.state==='ready'&&/^\/dnf-gm\/api\/v1\/assets\/[a-f0-9]{64}\/[a-f0-9]{64}\.png$/.test(props.image.url??'')?props.image!.url!:null)
watch(src,()=>{failed.value=false})
const note=computed(()=>failed.value?'图片读取失败，文字信息仍可使用':props.image?.note??'未安装图片包，文字信息仍可使用')
</script>
<template>
 <span class="game-image" :class="{'game-portrait':portrait,'illustration-portrait':portrait&&image?.source_kind==='official_promotional'}" :title="label+' · '+note">
  <img v-if="src&&!failed" :src="src" :alt="label" :style="portrait?{objectPosition:focus}:undefined" loading="lazy" decoding="async" @error="failed=true">
  <span v-else class="game-image-fallback" role="img" :aria-label="label+'：'+note">{{portrait?'头像':'无图'}}</span>
 </span>
</template>
