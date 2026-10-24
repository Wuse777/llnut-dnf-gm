<script setup lang="ts">
import {ref,onMounted,onUnmounted} from 'vue'
const props=defineProps<{title:string,busy?:boolean}>()
const emit=defineEmits<{close:[]}>()
const panel=ref<HTMLElement|null>(null)
let previous:Element|null=null
function focusables(){return Array.from(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')??[])}
function keys(e:KeyboardEvent){if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();if(!props.busy)emit('close')}if(e.key==='Tab'){const a=focusables();if(!a.length){e.preventDefault();panel.value?.focus();return}const first=a[0],last=a[a.length-1];if(e.shiftKey&&(document.activeElement===first||document.activeElement===panel.value)){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}}
onMounted(()=>{previous=document.activeElement;panel.value?.focus();document.addEventListener('keydown',keys,true)})
onUnmounted(()=>{document.removeEventListener('keydown',keys,true);if(previous instanceof HTMLElement&&previous.isConnected)previous.focus()})
</script>
<template><div class="modal-overlay"><section ref="panel" class="modal" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1"><header class="modal-header"><h2>{{title}}</h2><button class="icon-button ghost" aria-label="关闭对话框" :disabled="busy" @click="emit('close')">×</button></header><div class="modal-body"><slot/></div><footer v-if="$slots.footer" class="modal-footer"><slot name="footer"/></footer></section></div></template>
