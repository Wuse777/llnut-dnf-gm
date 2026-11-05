<script setup lang="ts">
import {ref,onMounted,onUnmounted} from 'vue'
import {pushDialog,topDialog,removeDialog} from '../dialogStack'
const props=defineProps<{title:string,busy?:boolean,drawer?:boolean}>()
const emit=defineEmits<{close:[]}>()
const panel=ref<HTMLElement|null>(null)
let previous:Element|null=null
const identity=Symbol('dialog'),depth=ref(1)
function focusables(){return Array.from(panel.value?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')??[])}
function keys(e:KeyboardEvent){if(!topDialog(identity))return;if(e.key==='Escape'&&e.target instanceof Element&&e.target.closest('[data-escape-local]'))return;if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();if(!props.busy)emit('close')}if(e.key==='Tab'){const a=focusables();if(!a.length){e.preventDefault();panel.value?.focus();return}const first=a[0],last=a[a.length-1];if(e.shiftKey&&(document.activeElement===first||document.activeElement===panel.value||!panel.value?.contains(document.activeElement))){e.preventDefault();last.focus()}else if(!e.shiftKey&&(document.activeElement===last||!panel.value?.contains(document.activeElement))){e.preventDefault();first.focus()}}}
onMounted(()=>{previous=document.activeElement;depth.value=pushDialog(identity);panel.value?.focus();document.addEventListener('keydown',keys,true)})
onUnmounted(()=>{document.removeEventListener('keydown',keys,true);const restore=topDialog(identity);removeDialog(identity);if(restore&&previous instanceof HTMLElement&&previous.isConnected)previous.focus()})
</script>
<template><div class="modal-overlay" :class="{'item-drawer-overlay':drawer}" :style="{zIndex:2000+depth*100}" @click.self="drawer&&!busy&&emit('close')"><section ref="panel" class="modal" :class="{'item-drawer':drawer}" role="dialog" aria-modal="true" :aria-label="title" tabindex="-1"><header class="modal-header"><h2>{{title}}</h2><button class="icon-button ghost" aria-label="关闭对话框" :disabled="busy" @click="emit('close')">×</button></header><div class="modal-body"><slot/></div><footer v-if="$slots.footer" class="modal-footer"><slot name="footer"/></footer></section></div></template>
