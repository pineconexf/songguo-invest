// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  // GitHub Pages 仓库子路径部署（2026-08-25）：base 必须匹配仓库名，否则资源 404 页面裸奔
  site: 'https://pineconexf.github.io',
  base: '/songguo-invest/',
  output: 'static',
  compressHTML: true,
});
