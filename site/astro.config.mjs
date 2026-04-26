import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// Live at https://pawpoller.pages.dev (Cloudflare Pages, auto-deploy
// from master). CF Pages serves at the project root, so no base path.
// If we ever move back to a subpath host, set `base: '/whatever'`
// here and re-render — every Astro link uses import.meta.env.BASE_URL.
export default defineConfig({
  site: 'https://pawpoller.pages.dev',
  trailingSlash: 'ignore',
  integrations: [tailwind({ applyBaseStyles: false })],
});
