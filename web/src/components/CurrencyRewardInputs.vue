<script setup lang="ts">
import FieldError from './FieldError.vue'
import type {FieldErrors} from '../validation'
const props=defineProps<{modelValue:Record<string,number>,prefix:string,busy:boolean,errors:FieldErrors}>()
const emit=defineEmits<{ 'update:modelValue':[value:Record<string,number>] }>()
const names:Record<string,string>={cera:'点券',cera_point:'代币券',mileage:'商城积分'}
function change(key:string,event:Event){emit('update:modelValue',{...props.modelValue,[key]:Number((event.target as HTMLInputElement).value)})}
</script>
<template><fieldset class="currency-reward-inputs" :disabled="busy"><legend>账号货币奖励（可与邮件合并，0表示不发放）</legend><div class="form-grid"><label v-for="(name,key) in names" :key="key">{{name}}<input :id="prefix+'-reward-'+key" type="number" min="0" max="1000000000" :value="modelValue[key]||0" :aria-label="(prefix==='gift'?'礼包':'奖励')+name" :aria-invalid="!!errors[prefix+'-reward-'+key]" :aria-describedby="errors[prefix+'-reward-'+key]?prefix+'-reward-'+key+'-error':undefined" @input="change(key,$event)"><FieldError :id="prefix+'-reward-'+key+'-error'" :message="errors[prefix+'-reward-'+key]"/></label></div><p class="field-hint">货币进入账号余额，物品和金币进入角色邮件。纯账号货币奖励不创建空邮件。</p></fieldset></template>
<style scoped>.currency-reward-inputs{min-width:0;border:1px solid var(--border-color);border-radius:10px;padding:12px;margin:12px 0}.currency-reward-inputs legend{padding:0 4px;font-size:.85rem}</style>
