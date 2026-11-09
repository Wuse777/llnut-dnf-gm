import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import type { LastLevelRouteKey, RouteKey } from '@elegant-router/types';
import { useSvgIcon } from '@/hooks/common/icon';
import { router } from '@/router';
import { gmRoutes, navigationGroups } from '@/router/gm-routes';

export const useRouteStore = defineStore('route-store', () => {
  const { SvgIconVNode } = useSvgIcon();
  const routeHome = ref<LastLevelRouteKey>('home');
  const cacheRoutes = ref<RouteKey[]>([]);
  const excludeCacheRoutes = ref<RouteKey[]>([]);
  function item(key: string): App.Global.Menu {
    const route = gmRoutes.find(entry => entry.name === key)!;
    return { key: key as RouteKey, label: String(route.meta?.title || key), routeKey: key as LastLevelRouteKey,
      routePath: `/${route.path}` as App.Global.Menu['routePath'], icon: SvgIconVNode({ icon: String(route.meta?.icon || 'ph:circle') }) };
  }
  const menus = computed<App.Global.Menu[]>(() => navigationGroups.map(group => group.pages.length === 1 ? item(group.pages[0]) : {
    key: group.key as RouteKey, label: group.label, routeKey: group.key as LastLevelRouteKey,
    routePath: '/' as App.Global.Menu['routePath'], icon: SvgIconVNode({ icon: group.icon }), children: group.pages.map(item)
  }));
  const searchMenus = computed(() => menus.value.flatMap(menu => menu.children || [menu]));
  const breadcrumbs = computed(() => {
    const route = router.currentRoute.value;
    const key = String(route.meta.activeMenu || route.name);
    const group = menus.value.find(menu => menu.key === key || menu.children?.some(child => child.key === key));
    const child = group?.children?.find(menu => menu.key === key);
    return child ? [{ ...group!, children: undefined }, { ...child }] : group ? [group] : [];
  });
  function getSelectedMenuKeyPath(key: string) {
    const group = menus.value.find(menu => menu.children?.some(child => child.key === key));
    return group ? [String(group.key)] : [];
  }
  return { routeHome, menus, searchMenus, breadcrumbs, cacheRoutes, excludeCacheRoutes, getSelectedMenuKeyPath,
    resetRouteCache: (_routeKey?: RouteKey) => {}, updateGlobalMenusByLocale: () => {}, resetStore: async () => {} };
});
