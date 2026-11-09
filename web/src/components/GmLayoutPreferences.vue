<script setup lang="ts">
import { NAlert, NButton, NSelect, NSwitch } from 'naive-ui';
import { useGmPreferencesStore } from '@/store/modules/gm-preferences';
const prefs = useGmPreferencesStore();
const densities = [{ label: '舒适', value: 'comfortable' }, { label: '紧凑', value: 'compact' }];
</script>

<template>
  <section class="gm-layout-settings">
    <h3>GM 工作台偏好</h3>
    <label><span>DNF 职业背景图</span><NSwitch v-model:value="prefs.showJobArt" aria-label="显示 DNF 职业背景图" /></label>
    <label><span>业务面板密度</span><NSelect v-model:value="prefs.density" :options="densities" aria-label="业务面板密度" /></label>
    <p>保存主题、布局、页签与背景显示；按当前 PVF 隔离。重新读取会替换本页设置。</p>
    <div><NButton size="small" :loading="prefs.busy" @click="prefs.load">重新读取</NButton><NButton size="small" type="primary" :disabled="!prefs.loaded" :loading="prefs.busy" @click="prefs.save">保存到管理库</NButton></div>
    <NAlert v-if="prefs.message" :show-icon="false" class="mt-12px">{{ prefs.message }}</NAlert>
  </section>
</template>

<style scoped>
.gm-layout-settings{border-top:1px solid var(--n-border-color,#e5e7eb);padding-top:18px;margin-top:20px}.gm-layout-settings h3{font-size:14px;margin-bottom:16px}.gm-layout-settings label{display:flex;align-items:center;justify-content:space-between;gap:18px;margin:12px 0}.gm-layout-settings label .n-select{width:112px}.gm-layout-settings p{font-size:12px;color:#808593;line-height:1.7;margin:16px 0}.gm-layout-settings>div{display:flex;gap:10px}
</style>
