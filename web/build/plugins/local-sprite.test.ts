import fs from 'node:fs';
import path from 'node:path';
import { expect, it } from 'vitest';
import { compileLocalSprite } from './local-sprite';
import { LOCAL_SPRITE_ICONS } from '../../src/utils/icon';

it('ships the fallback without legacy illustrations or CSP-blocked SVG styles', async () => {
  const html = await compileLocalSprite(path.resolve('src/assets/svg-icon'), 'icon-local');
  expect(html).toContain('id="icon-local-no-icon"');
  expect(html).not.toMatch(/\bstyle\s*=|<style\b/i);
  expect(html).not.toMatch(/icon-local-(expectation|empty-data|service-error|no-permission|not-found|banner)/);
  expect(Buffer.byteLength(html)).toBeLessThan(12_000);
});

it('retains all local icons declared by GM routes and the default fallback', () => {
  const routes = fs.readFileSync(path.resolve('src/router/gm-routes.ts'), 'utf8');
  const declared = [...routes.matchAll(/\blocalIcon\s*:\s*['"]([^'"]+)['"]/g)].map(match => match[1]);
  expect(declared.filter(name => !LOCAL_SPRITE_ICONS.includes(name))).toEqual([]);
  expect(LOCAL_SPRITE_ICONS).toContain('no-icon');
});
