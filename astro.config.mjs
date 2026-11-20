import { defineConfig } from 'astro/config';

// GitHub Pages: SITE y BASE los define el workflow; en local se usa la raíz.
export default defineConfig({
  site: process.env.SITE || 'http://localhost:4321',
  base: process.env.BASE || '/',
  output: 'static',
});
