<script setup lang="ts">
import { computed, watch } from 'vue';
import { NConfigProvider, darkTheme } from 'naive-ui';
import { naiveDateLocales, naiveLocales } from './locales/naive';
import { useAppStore } from './store/modules/app';
import { useThemeStore } from './store/modules/theme';
import GmOverlays from './views/gm/GmOverlays.vue';
import { useGmPreferencesStore } from './store/modules/gm-preferences';
import { useGmWorkspace } from './stores/gm/useGmWorkspace';
import { useTabStore } from './store/modules/tab';
const appStore = useAppStore();
const themeStore = useThemeStore();
const preferences = useGmPreferencesStore();
const workspace = useGmWorkspace();
const tabStore = useTabStore();
watch(() => workspace.logged, (logged, previous) => {
  if (logged) void preferences.load();
  else {
    preferences.reset();
    if (previous) tabStore.resetWorkspaceTabs();
  }
}, { immediate: true });
const naiveDarkTheme = computed(() => themeStore.darkMode ? darkTheme : undefined);
</script>
<template>
 <NConfigProvider :theme="naiveDarkTheme" :theme-overrides="themeStore.naiveTheme" :locale="naiveLocales[appStore.locale]" :date-locale="naiveDateLocales[appStore.locale]" inline-theme-disabled class="h-full">
  <AppProvider><RouterView class="bg-layout" /><GmOverlays /></AppProvider>
 </NConfigProvider>
</template>
