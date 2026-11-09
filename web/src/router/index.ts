import type { App } from 'vue';
import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/store/modules/auth';
import { useTabStore } from '@/store/modules/tab';
import { gmRoutes } from './gm-routes';

export const router = createRouter({
  history: createWebHistory('/dnf-gm/'),
  routes: [
    { path: '/login/:module?', name: 'login', component: () => import('@/views/gm/LoginView.vue'), meta: { title: '登录 DNF GM', constant: true } },
    { path: '/', name: 'root', component: () => import('@/layouts/base-layout/index.vue'), redirect: '/home', children: gmRoutes }
  ],
  scrollBehavior: () => ({ top: 0 })
});

export async function setupRouter(app: App) {
  router.beforeEach(async to => {
    const auth = useAuthStore();
    await auth.initialize();
    if (!auth.isLogin && to.name !== 'login') return { name: 'login', query: { redirect: to.fullPath } };
    if (auth.isLogin && to.name === 'login') return '/home';
    window.NProgress?.start?.();
    return true;
  });
  router.afterEach(to => {
    document.title = `${String(to.meta.title || '工作台')} · DNF GM`;
    window.NProgress?.done?.();
    if (to.name !== 'login') {
      const tabs = useTabStore();
      if (!tabs.homeTab) { tabs.initHomeTab(); tabs.initTabStore(to); }
      else tabs.addTab(to);
    }
  });
  app.use(router);
  await router.isReady();
}
