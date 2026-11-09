<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { NConfigProvider, darkTheme } from 'naive-ui';
import { naiveDateLocales, naiveLocales } from './locales/naive';
import { useAppStore } from './store/modules/app';
import { useThemeStore } from './store/modules/theme';
import { asyncPanel } from './asyncPanel';
import { useGmPreferencesStore } from './store/modules/gm-preferences';
import { useGmWorkspace } from './stores/gm/useGmWorkspace';
import { useTabStore } from './store/modules/tab';
const appStore = useAppStore();
const themeStore = useThemeStore();
const preferences = useGmPreferencesStore();
const workspace = useGmWorkspace();
const tabStore = useTabStore();
const route = useRoute();
const GmOverlays = asyncPanel(() => import('./views/gm/GmOverlays.vue'));
const overlaysRequested = ref(false);
// Keep dialogs out of the login/home download until there is something to show.
watch(() => workspace.logged && Boolean(
  workspace.operationOpen || workspace.confirmOpen || workspace.reauthOpen ||
  workspace.pickerOpen || workspace.policyDialog || workspace.giftHistory ||
  ((workspace.error || workspace.notice) && !workspace.toastDismissed) ||
  route.query.operationId || route.query.operation
), needed => { if (needed) overlaysRequested.value = true; }, { immediate: true });
watch(() => workspace.logged, (logged, previous) => {
  if (logged) void preferences.load();
  else {
    overlaysRequested.value = false;
    preferences.reset();
    if (previous) tabStore.resetWorkspaceTabs();
  }
}, { immediate: true });
const naiveDarkTheme = computed(() => themeStore.darkMode ? darkTheme : undefined);
</script>
<template>
 <NConfigProvider :theme="naiveDarkTheme" :theme-overrides="themeStore.naiveTheme" :locale="naiveLocales[appStore.locale]" :date-locale="naiveDateLocales[appStore.locale]" inline-theme-disabled class="h-full">
  <AppProvider><RouterView class="bg-layout" /><GmOverlays v-if="workspace.logged && overlaysRequested" /></AppProvider>
 </NConfigProvider>
</template>
