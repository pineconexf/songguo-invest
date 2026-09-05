// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  // 双环境部署（2026-09-05）：
  //  - GitHub Pages（默认）   site=GH · base=/songguo-invest/（子路径）
  //  - 云端正式站（根路径）   ASTRO_SITE=https://pinecone-lab.cn ASTRO_BASE=/ npm run build
  site: process.env.ASTRO_SITE ?? 'https://pineconexf.github.io',
  base: process.env.ASTRO_BASE ?? '/songguo-invest/',
  output: 'static',
  compressHTML: true,
});
