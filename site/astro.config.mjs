import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// Served from Cloudflare Pages at the project root (e.g.
// pawpoller-xyz.pages.dev or a custom domain). No base path needed
// because CF Pages serves the site at /, not /PawPoller/.
// If we ever move back to a subpath host, set `base: '/whatever'`
// here and re-render — every Astro link uses import.meta.env.BASE_URL.
export default defineConfig({
  site: 'https://pawpoller.pages.dev',
  trailingSlash: 'ignore',
  integrations: [tailwind({ applyBaseStyles: false })],
});
