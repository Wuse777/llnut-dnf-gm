import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import type { Plugin } from 'vite';
import { getIconData } from '@iconify/utils/lib/icon-set/get-icon';
import type { IconifyIcon, IconifyJSON } from '@iconify/vue/offline';

const moduleId = 'virtual:dnfgm-offline-icons';
const resolvedId = `\0${moduleId}`;
const require = createRequire(import.meta.url);
const collectionsPath = path.join(path.dirname(require.resolve('@iconify/json/package.json')), 'json');

/** Package only literal icons used by the app, never the complete icon collections. */
export function collectOfflineIcons(sourceRoot: string) {
  const names = new Set<string>();
  function visit(directory: string) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(filename);
      else if (/\.(?:vue|tsx?)$/.test(entry.name) && !/\.(?:test|spec)\./.test(entry.name)) {
        const source = fs.readFileSync(filename, 'utf8');
        for (const match of source.matchAll(/['"]([a-z][a-z0-9-]*):([a-z0-9][a-z0-9-]*)['"]/g)) {
          if (fs.existsSync(path.join(collectionsPath, `${match[1]}.json`))) names.add(`${match[1]}:${match[2]}`);
        }
      }
    }
  }
  visit(sourceRoot);
  const collections = new Map<string, IconifyJSON>();
  const icons: Record<string, IconifyIcon> = {};
  for (const name of [...names].sort()) {
    const [prefix, key] = name.split(':');
    if (!collections.has(prefix)) {
      collections.set(prefix, JSON.parse(fs.readFileSync(path.join(collectionsPath, `${prefix}.json`), 'utf8')));
    }
    const icon = getIconData(collections.get(prefix)!, key);
    if (!icon) throw new Error(`Missing offline UI icon: ${name}`);
    icons[name] = icon;
  }
  return icons;
}

export function setupOfflineIcons(): Plugin {
  let sourceRoot = '';
  return {
    name: 'dnfgm-offline-icons',
    configResolved(config) { sourceRoot = path.join(config.root, 'src'); },
    resolveId(id) { if (id === moduleId) return resolvedId; },
    load(id) {
      if (id === resolvedId) return `export default ${JSON.stringify(collectOfflineIcons(sourceRoot))};`;
    },
    handleHotUpdate(context) {
      if (context.file.startsWith(sourceRoot) && /\.(?:vue|tsx?)$/.test(context.file)) {
        const module = context.server.moduleGraph.getModuleById(resolvedId);
        if (module) {
          context.server.moduleGraph.invalidateModule(module);
          return [module, ...context.modules];
        }
      }
    }
  };
}
