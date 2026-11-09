import { ref, watch } from 'vue';
import { defineStore } from 'pinia';
import { api, uncertainMessage } from '@/api';
import { useThemeStore } from '@/store/modules/theme';
import { useAppStore } from '@/store/modules/app';

interface LayoutPreference {
  theme: 'light' | 'dark' | 'auto';
  layout: UnionKey.ThemeLayoutMode;
  density: 'comfortable' | 'compact';
  sidebar_collapsed: boolean;
  show_job_art: boolean;
  tab_visible: boolean;
}

/** Versioned UI settings only. Loading never submits a game operation. */
export const useGmPreferencesStore = defineStore('gm-layout-preferences', () => {
  const theme = useThemeStore();
  const app = useAppStore();
  const showJobArt = ref(true);
  const density = ref<LayoutPreference['density']>('comfortable');
  const version = ref(0);
  const pvf = ref('');
  const busy = ref(false);
  const loaded = ref(false);
  const message = ref('');
  let generation = 0;

  watch(density, value => { document.documentElement.dataset.gmDensity = value; }, { immediate: true });

  function apply(payload: LayoutPreference) {
    theme.setThemeScheme(payload.theme);
    if (!app.isMobile) {
      theme.setThemeLayout(payload.layout);
      app.setSiderCollapse(payload.sidebar_collapsed);
    }
    density.value = payload.density;
    showJobArt.value = payload.show_job_art;
    theme.tab.visible = payload.tab_visible;
  }

  async function load() {
    if (busy.value) return;
    busy.value = true;
    message.value = '';
    const epoch = ++generation;
    try {
      const result = await api('/ui-preferences/layout/default');
      if (epoch !== generation) return;
      pvf.value = result.pvf_sha256;
      version.value = result.version;
      loaded.value = true;
      if (result.payload) apply(result.payload);
      message.value = result.payload ? `已读取布局版本 ${version.value}` : '尚未保存布局；可保存当前设置。';
    } catch (error) {
      if (epoch === generation) message.value = uncertainMessage(error);
    } finally {
      if (epoch === generation) busy.value = false;
    }
  }

  async function save() {
    if (!loaded.value || busy.value) return;
    busy.value = true;
    message.value = '';
    const epoch = generation;
    const payload: LayoutPreference = {
      theme: theme.themeScheme,
      layout: theme.layout.mode,
      density: density.value,
      sidebar_collapsed: app.siderCollapse,
      show_job_art: showJobArt.value,
      tab_visible: theme.tab.visible
    };
    try {
      const result = await api('/ui-preferences/layout/default', 'PUT', {
        pvf_sha256: pvf.value, expected_version: version.value, payload
      });
      if (epoch !== generation) return;
      version.value = result.version;
      message.value = `已保存布局版本 ${version.value}`;
    } catch (error) {
      if (epoch === generation) message.value = uncertainMessage(error);
    } finally {
      if (epoch === generation) busy.value = false;
    }
  }

  function reset() {
    generation++;
    loaded.value = false;
    busy.value = false;
    pvf.value = '';
    version.value = 0;
    message.value = '';
    showJobArt.value = true;
    density.value = 'comfortable';
  }

  return { showJobArt, density, version, busy, loaded, message, load, save, reset };
});
