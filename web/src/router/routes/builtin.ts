import type { RouteRecordRaw } from 'vue-router';
export const ROOT_ROUTE: RouteRecordRaw = { name: 'root', path: '/', redirect: '/home' };
export function createBuiltinVueRoutes(): RouteRecordRaw[] { return [ROOT_ROUTE]; }
