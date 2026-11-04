<script setup lang="ts">
import {ref} from 'vue'
import {api,uncertainMessage} from '../api'
const props=defineProps<{item:any,disabled?:boolean}>()
const emit=defineEmits<{changed:[value:{id:number,pvf_sha256:string,favorite:boolean}]}>()
const pending=ref(false),error=ref('')
async function toggle(){
 if(pending.value||props.disabled||!props.item.pvf_sha256)return
 const id=props.item.id,sha=props.item.pvf_sha256,favorite=!props.item.favorite
 pending.value=true;error.value=''
 try{const result=await api('/catalog/'+id+'/favorite','PUT',{pvf_sha256:sha,favorite});emit('changed',{id,pvf_sha256:sha,favorite:result.favorite})}
 catch(e){error.value='收藏状态未确认：'+uncertainMessage(e)+'。可刷新列表核对；未发放物品。'}
 finally{pending.value=false}
}
</script>
<template><span class="favorite-control"><button type="button" :disabled="disabled||pending||!item.pvf_sha256" :aria-pressed="!!item.favorite" :aria-label="(item.favorite?'取消收藏 ':'收藏 ')+item.name" @click="toggle">{{pending?'保存中…':item.favorite?'★ 已收藏':'☆ 收藏'}}</button><small v-if="error" class="submit-error" role="alert">{{error}}</small></span></template>
