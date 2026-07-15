// Shared FAQ bank. Each entry has a stable `key` so pages can surface just
// the questions relevant to them (e.g. /security shows credential/posting
// answers, /download shows the platform/pricing ones) via FAQ.astro's
// `show` prop. No `show` = every question, in this order.

export interface Faq {
  key: string;
  q: string;
  a: string;
}

export const FAQS: Faq[] = [
  {
    key: 'free',
    q: 'Is it free?',
    a: 'Yes. MIT licensed, no accounts, no telemetry, no feature gates. Fork it, audit it, run it forever.',
  },
  {
    key: 'credentials',
    q: 'Where do my platform passwords live?',
    a: 'On your own machine or your own server. The optional encrypted vault (Fernet + OS keyring or a dotfile key) stores credentials separately from your plaintext settings.json. No PawPoller-operated service ever sees them.',
  },
  {
    key: 'auto-post',
    q: 'Does it post things automatically?',
    a: 'Only when you confirm. Every publish action has an explicit confirmation dialog; live (non-draft) posts require a second confirmation. There is also a full dry-run mode that shows exactly what would be submitted without submitting it.',
  },
  {
    key: 'os',
    q: 'Does it work on Mac or Linux?',
    a: 'Windows and Linux both have native desktop builds: a one-click .exe installer (or portable zip) for Windows, and a single-file .AppImage for Linux that runs on Ubuntu 22.04+ / Fedora 37+ / Debian 12+ / Arch with no install. macOS is on the public roadmap; the Apple Developer cert plus notarization decision is the open question. In the meantime macOS users can run the headless Docker mode and access the dashboard from any browser.',
  },
  {
    key: 'why-nine',
    q: 'Why post to eleven platforms but poll seventeen?',
    a: 'The other six — Wattpad, Pixiv, X/Twitter, Mastodon, Tumblr and Threads — are polled for analytics but not used as full submission targets; several have posting APIs that discourage third-party automation, so PawPoller reads their stats without posting where it shouldn\'t. (Short microblog posts to Bluesky, X, Mastodon, Tumblr, Threads and Instagram live in the Posts module.) Some platforms are marked as undergoing testing while we validate them — see the table.',
  },
  {
    key: 'cloud',
    q: 'Can I eventually use it from the browser without self-hosting?',
    a: 'That\'s the plan for the Cloud tier: a one-click hosted instance owned by you, not a shared service. A true multi-tenant SaaS tier is possible further out but needs real demand first; holding credentials for many users at once is a serious responsibility.',
  },
  {
    key: 'contribute',
    q: 'Can I help?',
    a: 'Yes. Bug reports, feature requests, and platform additions are all welcome via GitHub Issues. CONTRIBUTING.md has the platform-adding walkthrough.',
  },
];
