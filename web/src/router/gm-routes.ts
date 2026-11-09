import type { RouteRecordRaw } from 'vue-router';

/** Explicit routes preserve target identity and original operation IDs on refresh. */
export const gmRoutes: RouteRecordRaw[] = [
  { path: 'home', name: 'home', component: () => import('@/views/gm/HomeView.vue'), meta: { title: '工作台', icon: 'ph:squares-four', fixedIndexInTab: 0 } },
  { path: 'players', name: 'players', component: () => import('@/views/gm/PlayersView.vue'), meta: { title: '玩家检索', icon: 'ph:users' } },
  { path: 'players/:uid([0-9]+)', name: 'player', component: () => import('@/views/gm/PlayerWorkspaceView.vue'), meta: { title: '账号工作区', icon: 'ph:user-circle', activeMenu: 'players', multiTab: true } },
  { path: 'characters/:characNo([0-9]+)', name: 'character', component: () => import('@/views/gm/CharacterWorkspaceView.vue'), meta: { title: '角色工作区', icon: 'ph:identification-card', activeMenu: 'players', multiTab: true } },
  { path: 'rewards/compose', name: 'reward', component: () => import('@/views/gm/RewardComposerView.vue'), meta: { title: '奖励编辑器', icon: 'ph:gift', multiTab: true } },
  { path: 'items/catalog', name: 'catalog', component: () => import('@/views/gm/CatalogView.vue'), meta: { title: '物品目录', icon: 'ph:diamonds-four' } },
  { path: 'rewards/templates', name: 'templates', component: () => import('@/views/gm/TemplatesView.vue'), meta: { title: '礼包模板', icon: 'ph:package' } },
  { path: 'system/audit', name: 'audit', component: () => import('@/views/gm/AuditView.vue'), meta: { title: '操作审计', icon: 'ph:clock-counter-clockwise', multiTab: true } },
  ...[
    ['players/support', 'support', '玩家问题', 'ph:chats-circle'],
    ['players/online', 'online', '在线账号', 'ph:radio'],
    ['players/unlocks', 'unlock-center', '装备解锁队列', 'ph:lock-key-open'],
    ['rewards/deliveries', 'mail-center', '投递记录', 'ph:envelope-open'],
    ['rewards/batches', 'reward-jobs', '批量奖励', 'ph:stack'],
    ['rewards/schedules', 'schedules', '定时运营', 'ph:calendar-check'],
    ['rewards/control', 'native-controls', '公告与游戏内控制', 'ph:megaphone'],
    ['rewards/statistics', 'economy', '发放统计', 'ph:chart-bar'],
    ['system/diagnostics', 'operations-dashboard', '运维诊断', 'ph:heartbeat'],
    ['system/maintenance', 'maintenance', '维护与备份', 'ph:wrench'],
    ['system/capabilities', 'capabilities', '功能权限', 'ph:shield-check'],
    ['system/upgrades', 'compatibility', '升级检查', 'ph:arrows-clockwise']
  ].map(([path, name, title, icon]) => ({ path, name, component: () => import('@/views/gm/PanelView.vue'), props: { page: name }, meta: { title, icon } })),
  { path: 'items/appearance', name: 'appearance', component: () => import('@/views/gm/AppearanceView.vue'), meta: { title: '外观与素材', icon: 'ph:t-shirt' } },
  { path: ':pathMatch(.*)*', name: 'not-found', component: () => import('@/views/gm/NotFoundView.vue'), meta: { title: '页面未找到' } }
];

export const navigationGroups = [
  { key: 'home', label: '工作台', icon: 'ph:squares-four', pages: ['home'] },
  { key: 'players-group', label: '玩家中心', icon: 'ph:users', pages: ['players', 'online', 'support', 'unlock-center'] },
  { key: 'rewards-group', label: '奖励运营', icon: 'ph:gift', pages: ['reward', 'mail-center', 'templates', 'reward-jobs', 'schedules', 'native-controls', 'economy'] },
  { key: 'items-group', label: '道具与外观', icon: 'ph:diamonds-four', pages: ['catalog', 'appearance'] },
  { key: 'system-group', label: '系统运维', icon: 'ph:gear-six', pages: ['operations-dashboard', 'maintenance', 'capabilities', 'compatibility', 'audit'] }
];

