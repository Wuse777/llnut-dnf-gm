import type { App } from 'vue';
import { createApp, watch } from 'vue';
import { setupDayjs, setupIconifyOffline, setupNProgress } from './plugins';
import './plugins/assets';
import './style.css';
import './styles/gm-theme.css';
import { setupI18n } from './locales';
import { setupStore } from './store';
import { setupRouter, router } from './router';
import { useAuthStore } from './store/modules/auth';
import AppRoot from './App.vue';

async function setupApp() {
 setupNProgress(); setupIconifyOffline(); setupDayjs();
 const app: App = createApp(AppRoot);
 setupStore(app); setupI18n(app);
 await setupRouter(app);
 watch(() => useAuthStore().isLogin, logged => {
  if (!logged && router.currentRoute.value.name !== 'login') void router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } });
 });
 app.mount('#app');
}
void setupApp();
