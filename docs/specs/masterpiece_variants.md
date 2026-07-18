# Masterpiece Variants + XMB Showcase — spec

**Status:** DRAFT (2026-07-19) · mockup at `art_audit/xmb_mockup.html` (workspace root, outside repo)
**Origin:** Rhys, after the full art audit: "some pieces have variants — we could introduce variants to
masterpieces, each one tracked in its stats but part as the one cohort of a single masterpiece. And a way to
animate the piece as we select the art, similar to how the PS3 system scrolled through its apps."

## 0. Problem

The audit surfaced a real shape the current model can't hold: **one piece of art, several renders** —
SFW/NSFW ref sheets, censored/uncensored (the "Nope cat" daki), clean/aftermath (Franubis), dedication
variants (the Bread2Garlic birthday set), noBG exports. Today each variant is either (a) a separate
Masterpiece (ref sheets — stats fragmented across two records), or (b) an unlabeled `image_N.ext` alt file
(2.152 gallery — visible but untracked). Neither gives what's wanted: **per-variant stats, one cohort**.

## 1. Data model (Phase 1)

### masterpiece.json gains `variants`
```json
"variants": [
  {"key": "sfw",  "label": "SFW",        "image": "image.png",   "rating": "mature"},
  {"key": "nsfw", "label": "NSFW",       "image": "image_2.png", "rating": "adult"}
]
```
- `key` — stable slug, unique within the piece. `image` — a file in the SAME folder (variants share the
  folder, like alt images do today). `rating` — optional override; the piece's rating = MAX of variants.
- No `variants` field ⇒ implicit single variant `{"key": "", image: <hero>}` — **full back-compat**, nothing
  migrates on day one.
- The hero (`image` key) stays the canonical/posting/pHash image = the first variant by convention.

### masterpiece_members gains `variant_key TEXT NOT NULL DEFAULT ''`
Guarded ADD COLUMN. Each site-upload can be attributed to a variant (`''` = unattributed/primary). This is
what makes "each one tracked in its stats but part of the one cohort" true: per-variant stats = the normal
member rollup filtered by `variant_key`; cohort totals = all members, exactly today's rollup (unchanged).

### Queries (`masterpiece_queries`)
- `rollup_members(conn, name, variant_key=None)` — existing behaviour when None; filtered when set.
- `summarize` returns `variants: [{key, label, image, rating, totals, member_count}]` alongside the
  existing cohort totals.

## 2. Getting variants INTO the model (Phase 2)

1. **"Same piece, different variants"** — a third option in the 2.144 duplicate finder, beside
   "Merge into one" and "✗ Not the same". The near-identical-hash groups the finder already surfaces ARE
   mostly variant pairs (SFW/NSFW hash near-identically — the exact reason 2.151's auto-link is a prompt).
   Action: fold Masterpiece B into A as a new variant — copy B's image into A's folder, append a `variants`
   entry, re-key B's members with the new `variant_key` (they keep their stats), delete B's record. This is
   `merge_masterpieces` with attribution instead of amnesia.
2. **Declare from an existing alt image** — detail page: "make this gallery image a variant" (label+rating
   prompt). Upgrades the 2.152 unlabeled alts (cat-censor, test render, set images) in place.
3. **Upload a new variant** — reuses the 2.153 replace-image plumbing with `variant` mode.

### API
- `GET /{name}` → `variants` incl. per-variant stats.
- `POST /{name}/variants` `{from_image | upload, key, label, rating}` · `PATCH /{name}/variants/{key}` ·
  `DELETE /{name}/variants/{key}` (demotes to plain alt image; members re-key to '').
- `POST /merge-as-variant` `{keep, absorb, key, label}`.
- Publishing (Phase 5, LATER): per-platform variant routing — SFW variant → IG, full → e621. Big; separate.

## 3. XMB Showcase (Phases 3–4)

New view **`#/showcase`** (button on the Masterpieces grid: "▶ Showcase"), XMB-style:
- **Horizontal axis:** Masterpieces as large covers; focused cover centred + scaled, neighbours recede with
  smooth transform transitions (~300ms cubic-bezier). Wheel / ←→ / click / swipe to move.
- **Vertical axis:** when the focused piece has variants, they fan out BELOW the cover (labeled chips);
  ↑↓ cycles, the big cover swaps to the selected variant in place.
- **Info panel:** title · artist · rating · per-variant stat rows + cohort total row.
- Pure CSS transforms + the existing `/api/masterpieces` + `/api/artwork/image` — no new backend.
  Lazy-load covers; cap DOM to ±6 neighbours. Respect `prefers-reduced-motion`.
- Junked pieces excluded; honours grid filters (persona/search) when entered from the grid.

## 4. What to do with the 181-piece collection (companion plan)

1. Import the ~130 pieces PawPoller doesn't have as new Masterpieces — folders + masterpiece.json written
   straight from `art_audit/full_metadata.json` (titles/descs/tags/ratings already uniform).
2. The audit's variant families import as ONE Masterpiece with variants each (this spec is the prerequisite).
3. pHash auto-suggest then links any discovered site-uploads to the imports; the 14 junk entries go to the
   2.149 bin; the process video/HEIC stay archive-only files.

## 5. Phases

| Phase | Scope | Risk |
|---|---|---|
| 0 | Spec + mockup (done) | — |
| 1 | Data model: json `variants`, `variant_key` column, filtered rollup + summarize | Low — additive, back-compat |
| 2 | API + merge-as-variant + dup-finder third option + detail-page variant management | Med |
| 3 | Detail page: labeled variant strip w/ per-variant stats | Low |
| 4 | `#/showcase` XMB view | Low — frontend-only |
| 5 | Per-variant publish routing | High — LATER, own spec |
| 6 | Collection import (§4) | Med — data op |

## 6. Open questions
- Variant stats for platforms where both variants were posted to the SAME site (e.g. FA clean + FA explicit):
  works naturally (two members, different variant_key) — no issue, noted for tests.
- Should junk status apply per-variant? NO — piece-level only (keep it simple).
- Showcase as default Masterpieces view? Start opt-in; revisit.
