# Masterpiece variants — separate from master + rename

**Status:** SPEC — building now · **Date:** 2026-07-24 · Ships as **2.189.0**

> Rhys, in Masterpieces: *"i need a method to seperate from master and a way to rename varients"*. Both are genuine
> gaps in the 2.158 variants feature — merging a variant IN is a one-way door, and a variant's label can't be edited
> at all.

## The gaps (verified against the current code)

Existing variant surface (`routes/masterpieces_api.py` §Variants, `docs/specs/masterpiece_variants.md`):

| Endpoint | What it does |
|---|---|
| `POST /merge-as-variant` | folds masterpiece B into A as a labeled variant (**deletes B's folder**) |
| `POST /{name}/variants` | declares an existing folder image as a variant |
| `DELETE /{name}/variants/{key}` | **demotes** to an unlabeled alt image *in the same folder*; members re-key to `''` |
| `PATCH /{name}/members/variant` | attributes one site-upload to a variant |

1. **No way back out.** `DELETE` only un-labels — the image stays in the parent folder and the variant can never
   become its own Masterpiece again. `merge-as-variant` is therefore irreversible: it deletes the absorbed folder and
   nothing reconstitutes it. If you fold the wrong piece in (easy — the title-based variant suggester is explicitly
   fuzzy and "suggests, never auto-merges"), you're stuck.
2. **No rename.** Nothing edits a variant's `label`. Today renaming means `DELETE` + re-`POST`, and `DELETE` calls
   `clear_variant_members` — so **you silently lose every per-variant stat attribution**. That's a data-losing
   workaround for a cosmetic edit.

## 1. Rename — `PATCH /api/masterpieces/{name}/variants/{key}`
Body `{label?, key?, rating?}` — all optional, at least one required.
- `label` / `rating`: metadata-only edit of the `masterpiece.json` `variants` entry.
- `key`: slug-validated (`_VARIANT_KEY_RE`), **409** on collision with another variant, and migrates
  `masterpiece_members.variant_key` old→new so per-variant stats follow the rename. New
  `masterpiece_queries.rename_variant_key`.
- The **primary** entry (`key === ''`) may have its label/rating edited but **not its key** — `''` is the anchor the
  whole scheme keys off (400).
- 404 when the variant doesn't exist. Never touches image files.

## 2. Separate from master — `POST /api/masterpieces/{name}/variants/{key}/split`
The true inverse of `merge-as-variant`. Body `{new_name?}` (optional; else derived).
- **Refuses `key === ''`** (400) — the primary *is* the master.
- Mints a new Masterpiece via `artwork_reader.create_artwork` from the variant's image bytes, inheriting the parent's
  description / author / tags / characters, with `rating` = the variant's own rating else the parent's. Title =
  `"<parent title> (<variant label>)"` — deliberately the shape `variant_suggest` recognises, so the pair reads as a
  family again rather than as two unrelated pieces.
- Moves that variant's members parent → new record, **re-keyed to `''`** (they're the new record's primary now):
  new `masterpiece_queries.move_variant_members`. Stats attribution survives the round-trip.
- Drops the variants entry from the parent and **deletes the variant's image file from the parent folder** (it moved
  out). Guarded: never deletes the parent's hero image. If only the lone `''` primary entry remains, collapse
  `variants` to `[]` (a one-entry set is meaningless — mirrors how merge only seeds it at ≥2).
- Indexes the new name (`ensure_indexed`) and stores its hero dHash (`image_hash.store` under the synthetic `__mp__`
  platform), matching what promote does — so the de-dup/variant finders see it immediately.
- Returns `{status, new_name, members_moved}`.

## 3. Frontend (`masterpieces.js` detail)
A **Variants** admin list under the existing chip gallery, shown only when declared variants exist — the chips stay
a *viewer*, this is the *manager*. One row per variant: label · member/stat summary · **✎ Rename** (inline
input + Save/Cancel, no modal) · **⤴ Separate** (confirm → toast → offer to open the new record). The primary row
shows its label and rename control but **no Separate**. CSP-safe `data-mp-v*` hooks on the existing document-level
click delegate. `api.js`: `renameMasterpieceVariant`, `splitMasterpieceVariant`.

## Tests (`tests/test_masterpiece_variant_split.py`)
Rename: label-only edit; key change migrates member `variant_key`; collision → 409; primary key change → 400; unknown
→ 404. Split: creates a new Masterpiece with the image; members move re-keyed to `''`; parent loses the entry and the
file; primary → 400; lone-primary collapse; **round-trip** (`merge-as-variant` → `split` restores a standalone record
with its members) — the property that makes merging safe to undo.
