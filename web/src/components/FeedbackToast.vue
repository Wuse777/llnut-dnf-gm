<script setup lang="ts">
defineProps<{message:string,error?:boolean,canLocate?:boolean}>()
const emit=defineEmits<{dismiss:[],locate:[]}>()
</script>
<template><section class="feedback-toast" :class="error?'is-error':'is-success'" :role="error?'alert':'status'" :aria-live="error?'assertive':'polite'" aria-atomic="true"><span class="feedback-symbol" aria-hidden="true">{{error?'!':'✓'}}</span><div class="feedback-content"><strong>{{error?'操作未完成':'操作提示'}}</strong><p>{{message}}</p><button v-if="canLocate" class="ghost" @click="emit('locate')">定位问题字段</button></div><button class="icon-button ghost" aria-label="关闭操作提示" @click="emit('dismiss')">×</button></section></template>
