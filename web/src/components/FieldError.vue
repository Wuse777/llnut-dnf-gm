<script setup lang="ts">
defineProps<{id:string,message?:string}>()
</script>
<template><span v-if="message" :id="id" class="field-error"><span aria-hidden="true">!</span>{{message}}</span></template>
