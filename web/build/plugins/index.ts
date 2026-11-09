import type { PluginOption } from 'vite';
import vue from '@vitejs/plugin-vue';
import vueJsx from '@vitejs/plugin-vue-jsx';
import progress from 'vite-plugin-progress';
import vueRootValidator from 'vite-plugin-vue-transition-root-validator';
import Components from 'unplugin-vue-components/vite';
import { NaiveUiResolver } from 'unplugin-vue-components/resolvers';
import { setupElegantRouter } from './router';
import { setupDevtoolsPlugin } from './devtools';
import { setupHtmlPlugin } from './html';
import { setupUnocss } from './unocss';
import { setupUnplugin } from './unplugin';
import { setupOfflineIcons } from './offline-icons';

export function setupVitePlugins(viteEnv: Env.ImportMeta, buildTime: string, options: { test?: boolean } = {}) {
  // Unit tests compile Vue and Naive components without starting application
  // devtools/router generators, SVG injection or declaration-file watchers.
  if (options.test) return [vue(), vueJsx(), setupOfflineIcons(), Components({ dts: false, dirs: [], resolvers: [NaiveUiResolver()] })];

  const plugins: PluginOption = [
    vue(),
    vueJsx(),
    setupOfflineIcons(),
    setupDevtoolsPlugin(viteEnv),
    setupElegantRouter(),
    setupUnocss(viteEnv),
    ...setupUnplugin(viteEnv),
    progress(),
    setupHtmlPlugin(buildTime),
    vueRootValidator()
  ];

  return plugins;
}
