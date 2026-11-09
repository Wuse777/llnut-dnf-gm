<script setup lang="ts">
import {computed,ref,watch} from 'vue'
export type AssetImage={state:string,url?:string|null,note?:string,width?:number,height?:number,source_kind?:string,source_label?:string,source_page?:string,match_level?:string,awakening_specific?:boolean,requested_growth?:number,mapped_growth?:number,pose?:string,focus_x?:number,focus_y?:number}
const props=withDefaults(defineProps<{image?:AssetImage|null,label:string,portrait?:boolean,rarityName?:string,rarity?:number|null,iconSize?:number}>(),{portrait:false,iconSize:32})
const failed=ref(false)
const focus=computed(()=>[props.image?.focus_x,props.image?.focus_y].every(v=>typeof v==='number'&&v>=0&&v<=100)?`${props.image!.focus_x}% ${props.image!.focus_y}%`:'50% 50%')
const src=computed(()=>props.image?.state==='ready'&&/^\/dnf-gm\/api\/v1\/assets\/[a-f0-9]{64}\/[a-f0-9]{64}\.png$/.test(props.image.url??'')?props.image!.url!:null)
watch(src,()=>{failed.value=false})
const note=computed(()=>failed.value?'图片读取失败，文字信息仍可使用':props.image?.note??'未安装图片包，文字信息仍可使用')
const quality=computed(()=>({普通:'normal',高级:'advanced',稀有:'rare',神器:'unique',史诗:'epic',勇者:'chronicle',传说:'legendary'} as Record<string,string>)[props.rarityName??''])
const rawQuality=computed(()=>typeof props.rarity==='number'&&Number.isInteger(props.rarity)&&props.rarity>=0&&props.rarity<=10?props.rarity:null)
const qualityLabel=computed(()=>props.rarityName||(rawQuality.value!==null?'PVF 品级 '+rawQuality.value:''))
const iconStyle=computed(()=>{
 if(props.portrait)return {objectPosition:focus.value}
 const max=[24,32,48,64].includes(props.iconSize)?props.iconSize:32
 const width=props.image?.width,height=props.image?.height
 if(typeof width!=='number'||typeof height!=='number'||width<1||height<1||width>512||height>512)return {width:max+'px',height:max+'px'}
 const scale=Math.min(1,max/width,max/height)
 return {width:Math.max(1,Math.round(width*scale))+'px',height:Math.max(1,Math.round(height*scale))+'px'}
})
</script>
<template>
 <span class="game-image" :class="[{'game-portrait':portrait,'illustration-portrait':portrait&&image?.source_kind==='official_promotional'},!portrait&&quality?'quality-'+quality:!portrait&&rawQuality!==null?'quality-raw-'+rawQuality:'']" :title="label+(qualityLabel?' · '+qualityLabel:'')+' · '+note">
  <img v-if="src&&!failed" :src="src" :alt="label" :style="iconStyle" loading="lazy" decoding="async" @error="failed=true">
  <span v-else class="game-image-fallback" role="img" :aria-label="label+'：'+note">{{portrait?'头像':'无图'}}</span>
 </span>
</template>
<style scoped>
.game-image:not(.game-portrait) img{flex:none;max-width:100%;max-height:100%}.quality-normal{border-color:#90939b}.quality-advanced{border-color:#7297c6}.quality-rare{border-color:#9b79ce}.quality-unique{border-color:#ca7299}.quality-epic{border-color:#bd9c44}.quality-chronicle{border-color:#a98d63}.quality-legendary{border-color:#ce8d55}
/* Raw PVF values are visual groups; no rarity name is inferred from a number. */
.quality-raw-0{border-color:#969aa1}.quality-raw-1{border-color:#778fa5}.quality-raw-2{border-color:#8d81a5}.quality-raw-3{border-color:#a57e94}.quality-raw-4{border-color:#a59362}.quality-raw-5{border-color:#91836f}.quality-raw-6{border-color:#aa8466}.quality-raw-7{border-color:#748f89}.quality-raw-8{border-color:#777fa0}.quality-raw-9{border-color:#a17676}.quality-raw-10{border-color:#6f8d76}
</style>
