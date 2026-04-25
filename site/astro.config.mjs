import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

// Served from https://knaughtykat01-prog.github.io/PawPoller/
// so every absolute link and asset needs the /PawPoller/ base prefix.
// Swap `site` + drop `base` when a custom domain is wired up.
export default defineConfig({
  site: 'https://knaughtykat01-prog.github.io',
  base: '/PawPoller',
  trailingSlash: 'ignore',
  integrations: [tailwind({ applyBaseStyles: false })],
});
