import { computed } from 'vue';
import { defineStore } from 'pinia';
import { useGmWorkspace } from '@/stores/gm/useGmWorkspace';

/** Cookie session adapter. No bearer storage, token refresh, or request replay. */
export const useAuthStore = defineStore('auth-store', () => {
  const gm = useGmWorkspace();
  const isLogin = computed(() => gm.logged);
  const userInfo = computed(() => ({ userId: gm.username, userName: gm.username || '管理员', roles: [] as string[], buttons: [] as string[] }));
  return { isLogin, userInfo, isStaticSuper: false, initialize: gm.initialize, resetStore: gm.logout };
});
