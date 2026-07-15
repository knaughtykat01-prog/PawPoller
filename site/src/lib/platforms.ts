// Single source of truth for the platform matrix used across the site
// (home strip, /platforms table, and the capability pages that filter by
// content kind). Keep in step with the app's poster registry
// (posting/platforms/__init__.py + manager._get_poster) and the pollers.
//
// `post: true` reflects the platforms with a live PlatformPoster:
// Inkbunny, FurAffinity, SoFurry, Weasyl, AO3, SquidgeWorld, DeviantArt,
// Itaku, Bluesky, Instagram and e621. Everything polls (17); the rest are
// read-only analytics.

export type Kind = 'fiction' | 'art' | 'social';

export interface Platform {
  name: string;
  logo: string;
  poll: boolean;
  post: boolean;
  /** Undergoing validation — shown as an amber "Testing" badge. */
  testing?: boolean;
  /** Content types this platform carries, for the capability pages. */
  kinds: Kind[];
  note: string;
}

export const PLATFORMS: Platform[] = [
  { name: 'Inkbunny',     logo: 'ib.png',   poll: true, post: true,  kinds: ['fiction', 'art'], note: 'Chaptered stories · official API' },
  { name: 'FurAffinity',  logo: 'fa.png',   poll: true, post: true,  kinds: ['fiction', 'art'], note: 'Stories + art · desktop posting' },
  { name: 'SoFurry',      logo: 'sf.png',   poll: true, post: true,  kinds: ['fiction'],        note: 'Chaptered stories' },
  { name: 'Weasyl',       logo: 'ws.svg',   poll: true, post: true,  testing: true, kinds: ['fiction', 'art'], note: 'Stories + art · official API' },
  { name: 'AO3',          logo: 'ao3.png',  poll: true, post: true,  kinds: ['fiction'],        note: 'Chaptered + work skins' },
  { name: 'SquidgeWorld', logo: 'sqw.png',  poll: true, post: true,  kinds: ['fiction'],        note: 'Chaptered + work skins' },
  { name: 'DeviantArt',   logo: 'da.png',   poll: true, post: true,  kinds: ['art'],            note: 'Artwork · Eclipse API' },
  { name: 'Wattpad',      logo: 'wp.png',   poll: true, post: false, kinds: ['fiction'],        note: 'Read-only analytics' },
  { name: 'Itaku',        logo: 'ik.svg',   poll: true, post: true,  testing: true, kinds: ['art'], note: 'Artwork' },
  { name: 'Bluesky',      logo: 'bsky.png', poll: true, post: true,  kinds: ['social'],         note: 'Posts + announcements' },
  { name: 'X / Twitter',  logo: 'tw.png',   poll: true, post: false, kinds: ['social'],         note: 'Tweets: views, likes, reposts' },
  { name: 'Mastodon',     logo: 'mast.svg', poll: true, post: false, testing: true, kinds: ['social'], note: 'Posts: favourites, boosts, replies' },
  { name: 'Tumblr',       logo: 'tum.svg',  poll: true, post: false, testing: true, kinds: ['social'], note: 'Posts: notes' },
  { name: 'Pixiv',        logo: 'pix.svg',  poll: true, post: false, testing: true, kinds: ['art', 'fiction'], note: 'Illustrations + novels' },
  { name: 'Threads',      logo: 'thr.svg',  poll: true, post: false, testing: true, kinds: ['social'], note: 'Posts: views, likes, reposts · Meta app required' },
  { name: 'Instagram',    logo: 'ig.svg',   poll: true, post: true,  testing: true, kinds: ['art', 'social'], note: 'Photos + captions · server-only, Meta app' },
  { name: 'e621',         logo: 'e621.svg', poll: true, post: true,  testing: true, kinds: ['art'], note: 'Upload art + score/faves/comments · official API' },
];

export const POST_COUNT = PLATFORMS.filter((p) => p.post).length;   // 11
export const POLL_COUNT = PLATFORMS.length;                          // 17

export const byKind = (kind: Kind): Platform[] =>
  PLATFORMS.filter((p) => p.kinds.includes(kind));
