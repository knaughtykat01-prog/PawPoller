/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      colors: {
        // Warm-literary palette: deep slate base with copper + parchment
        ink: {
          50:  '#f5efe4',    // parchment — primary text on dark
          100: '#ece3d1',
          200: '#d8c8aa',
          400: '#9a8d74',
          500: '#6b614f',
          700: '#332e26',
          800: '#1f1c17',    // card bg
          900: '#13110e',    // body bg
          950: '#0a0907',
        },
        copper: {
          300: '#f0bd83',
          400: '#e5a05a',
          500: '#d08136',    // primary accent
          600: '#a8652a',
          700: '#7a4a20',
        },
        sage: {
          500: '#7d9a7a',    // secondary accent — subtle, for "free / open" chips
        },
      },
      fontFamily: {
        serif: ['"Crimson Pro"', 'Georgia', 'serif'],
        sans:  ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono:  ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 40px -10px rgba(208, 129, 54, 0.35)',
      },
    },
  },
  plugins: [],
};
