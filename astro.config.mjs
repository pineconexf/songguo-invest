// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  // 部署后替换为实际域名
  site: 'https://songguo-invest.pages.dev',
  output: 'static',
  compressHTML: true,
});
