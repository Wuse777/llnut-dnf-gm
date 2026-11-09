import ElegantVueRouter from '@elegant-router/vue/vite';

const names: Record<string, string> = {
 home: 'home', players: 'players', playerworkspace: 'player', characterworkspace: 'character',
 rewardcomposer: 'reward', catalog: 'catalog', templates: 'templates', audit: 'audit',
 appearance: 'appearance', login: 'login', notfound: 'not-found', panel: 'panel'
};
const paths: Record<string, string> = {
 home: '/home', players: '/players', player: '/players/:uid([0-9]+)', character: '/characters/:characNo([0-9]+)',
 reward: '/rewards/compose', catalog: '/items/catalog', templates: '/rewards/templates', audit: '/system/audit',
 appearance: '/items/appearance', login: '/login/:module?', 'not-found': '/:pathMatch(.*)*', panel: '/panel',
 support: '/players/support', online: '/players/online', 'unlock-center': '/players/unlocks',
 'mail-center': '/rewards/deliveries', 'reward-jobs': '/rewards/batches', schedules: '/rewards/schedules',
 'native-controls': '/rewards/control', economy: '/rewards/statistics', 'operations-dashboard': '/system/diagnostics',
 maintenance: '/system/maintenance', capabilities: '/system/capabilities', compatibility: '/system/upgrades',
 'players-group': '/players', 'rewards-group': '/rewards', 'items-group': '/items', 'system-group': '/system',
 '403': '/403', '404': '/404', '500': '/500', 'iframe-page': '/iframe-page/:url'
};

/** Generate the template's route type map while GM owns explicit target-aware runtime records. */
export function setupElegantRouter() {
 return ElegantVueRouter({
  pageDir: 'src/views/gm-routes', pagePatterns: ['**/index.vue'],
  layouts: { base: 'src/layouts/base-layout/index.vue', blank: 'src/layouts/blank-layout/index.vue' },
  routeNameTransformer(name) { return names[name.toLowerCase().replace(/^gm_/, '').replace(/[-_]/g, '').replace(/view$/, '')] || name; },
  routePathTransformer(name, path) { return paths[name] || path; },
  customRoutes: { map: Object.fromEntries(Object.entries({ root: '/', ...paths }).filter(([key]) => !['home','players','player','character','reward','catalog','templates','audit','appearance','login'].includes(key))), names: [] },
  onRouteMetaGen(name) { return { title: name, constant: name === 'login' }; }
 });
}



