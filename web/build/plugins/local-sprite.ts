import path from 'node:path';
import type { Plugin } from 'vite';
import { compilerIcon } from 'vite-plugin-svg-icons';
import { LOCAL_SPRITE_ICONS } from '../../src/utils/icon';

const registerId = 'virtual:svg-icons-register';
const namesId = 'virtual:svg-icons-names';

/** Keep the template's unused illustrations out of the first page and strict-CSP SVG markup. */
export async function compileLocalSprite(iconPath: string, prefix: string) {
  const symbols: string[] = [];
  for (const name of LOCAL_SPRITE_ICONS) {
    if (!/^[a-z0-9-]+$/.test(name)) throw new Error(`Invalid registered local icon: ${name}`);
    const symbol = await compilerIcon(path.join(iconPath, `${name}.svg`), `${prefix}-${name}`, {
      plugins: [{ name: 'preset-default' }, { name: 'convertStyleToAttrs' }]
    });
    if (!symbol || /\bstyle\s*=|<style\b/i.test(symbol)) {
      throw new Error(`Local icon must compile without inline styles: ${name}`);
    }
    symbols.push(symbol);
  }
  return symbols.join('');
}

export function setupLocalSprite(iconPath: string, prefix: string): Plugin {
  return {
    name: 'dnfgm-local-svg-sprite',
    resolveId(id) { if (id === registerId || id === namesId) return `\0${id}`; },
    async load(id) {
      if (id === `\0${namesId}`) return `export default ${JSON.stringify(LOCAL_SPRITE_ICONS.map(name => `${prefix}-${name}`))};`;
      if (id !== `\0${registerId}`) return;
      for (const name of LOCAL_SPRITE_ICONS) this.addWatchFile(path.join(iconPath, `${name}.svg`));
      const sprite = await compileLocalSprite(iconPath, prefix);
      return `
        if (typeof document !== 'undefined') {
          function mountLocalIcons() {
            if (document.getElementById('__SVG_ICON_LOCAL__')) return;
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.id = '__SVG_ICON_LOCAL__';
            svg.setAttribute('aria-hidden', 'true');
            svg.style.position = 'absolute';
            svg.style.width = '0';
            svg.style.height = '0';
            svg.style.overflow = 'hidden';
            svg.innerHTML = ${JSON.stringify(sprite)};
            document.body.appendChild(svg);
          }
          if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountLocalIcons, { once: true });
          else mountLocalIcons();
        }
        export default {};
      `;
    }
  };
}
