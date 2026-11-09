import process from 'node:process';
import { defineConfig, loadEnv } from 'vite-plus';
import { fmt, lint } from '@soybeanjs/oxc-config';
import { getBuildTime } from './build/config';
import { setupVitePlugins } from './build/plugins';

export default defineConfig(configEnv => {
  const viteEnv = loadEnv(configEnv.mode, process.cwd()) as unknown as Env.ImportMeta;

  const buildTime = getBuildTime();



  return {
    base: '/dnf-gm/',
    staged: {
      '*': 'vp check --fix'
    },
    lint: {
      ...lint,
      rules: {
        ...lint.rules,
        // Preserve useful diagnostics while migrating the established GM forms.
        'eslint/no-shadow': 'warn',
        'unicorn/no-useless-fallback-in-spread': 'warn'
      }
    },
    fmt: {
      ...fmt,
      ignorePatterns: [
        'CHANGELOG.md',
        'src/typings/components.d.ts',
        'src/typings/elegant-router.d.ts',
        'src/router/elegant'
      ]
    },
    resolve: {
      tsconfigPaths: true
    },
    css: {
      preprocessorOptions: {
        scss: {
          api: 'modern-compiler',
          additionalData: `@use "@/styles/scss/global.scss" as *;`
        }
      }
    },
    plugins: setupVitePlugins(viteEnv, buildTime, { test: Boolean(process.env.VITEST) }),
    define: {
      BUILD_TIME: JSON.stringify(buildTime)
    },
    server: {
      host: '127.0.0.1',
      port: 9527,
      open: false,
      proxy: { '/dnf-gm/api': 'http://127.0.0.1:8765' }
    },
    preview: {
      port: 9725
    },
    build: {
      outDir: 'dist',
      reportCompressedSize: false,
      sourcemap: viteEnv.VITE_SOURCE_MAP === 'Y',
      commonjsOptions: {
        ignoreTryCatch: false
      }
    }
  };
});

