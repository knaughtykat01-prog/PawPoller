# PawPoller Changelog

All notable changes to PawPoller are documented here.

---

## [2.3.7] - 2026-04-08

### Added — SoFurry draft mode + bulk drafting

SoFurry now supports the same draft pattern as IB / SQW / AO3. SF has built-in privacy levels (1=Private, 2=Unlisted, 3=Public) so this is a real first-class draft state — owner-only visibility — not a workaround.

**6 SF drafts** (single-bulk-file convention via `HTML/<Story>_Clean.html`, all Private/owner-only):

| Story | Submission | Words |
|---|---|---|
| Tombstone | [nLrR4PBe](https://sofurry.com/s/nLrR4PBe) | 8,414 |
| Chosen | [m0KjxlKe](https://sofurry.com/s/m0KjxlKe) | 15,958 |
| Not_So_Efficient_Studying | [ePdyAZ5e](https://sofurry.com/s/ePdyAZ5e) | 13,602 |
| Overtime | [1xJGPWZm](https://sofurry.com/s/1xJGPWZm) | 11,513 |
| Ruins_of_Breeding | [nd4Pol7n](https://sofurry.com/s/nd4Pol7n) | 24,457 |
| The_Haunting_Desires | [mXB73JG1](https://sofurry.com/s/mXB73JG1) | 30,480 |

After this run, every local story is now on SF — 7 live published works + 6 new private drafts. Drafts are recorded in the publications table on the server with `status=draft`.

**SF posting was *fast*** — 2-3 seconds per submission, vs AO3's 20-150 seconds with retries. SoFurry's 3-step REST API (PUT empty → POST file → POST metadata) is much cleaner than OTW Archive's CSRF form scraping.

**`SoFurryPoster.post()` refactor:**
- New `_normalize_privacy()` helper that accepts ints (1/2/3) or strings ("private"/"unlisted"/"public") and maps to SF's numeric codes
- `package.extra["draft"] = True` → `privacy=1` (Private, owner-only) — same convention as IB/AO3
- `package.extra["privacy"] = 1|2|3` for explicit override (wins over draft)
- Default: `privacy=3` (Public) — preserves the existing behaviour for callers who don't set anything
- Post-flight verification: hits `/ui/submission/{id}` raw and confirms `privacy=1` server-side after a Private draft. Logs a warning if the server returns something else (defensive — `create_submission` has the privacy parameter wired correctly so this should never fire, but better to know).

### Fixed — `sf_client.edit_submission` was silently downgrading every edited work to Private

A pair of cascading bugs in `sf_client/client.py:edit_submission`:

1. **It used `get_submission_detail()` to fetch current state.** That helper strips the response down to public-facing fields (title, description, rating, etc) and **does not return `privacy`, `category`, `type`, or any of the other write-only metadata fields**. So `current.get("privacy")` always returned `None`.

2. **The fallback default was wrong.** When `current.get("privacy", 1)` returned the fallback, it returned **`1` (Private)** — the *least permissive* option. So every single edit silently overwrote whatever the work's actual privacy was with Private.

**Caught this the hard way:** while retrying the 4-day-old failed `Hypnotic_Claim` edit, the edit went through and reported success — then a follow-up fetch showed `privacy: 1` (Private). Hypnotic Claim had been a public live work for weeks. The script then ran an emergency restoration script that fetched the raw JSON, set `privacy=3` explicitly, and posted back, restoring the live state within 60 seconds of the regression.

**Why no other live works were affected:** the `failed` row in `publications` for Hypnotic_Claim shows the original 2026-04-04 edit failed with `"SoFurry login failed"` — i.e. it errored out at the *auth* step before reaching the metadata POST. So the buggy code path never actually fired in production, and the 7 live works on SF stayed Public. My retry today was the **first time the bug actually executed end-to-end**, and it was caught and rolled back inside the same script run.

**The fix:**
- `edit_submission` now fetches the **raw** `/ui/submission/{id}` JSON directly (not the stripped helper), so the merge sees every field on the server
- The fallback for `privacy` is now `current.get("privacy", 3)` — defaulting to Public is the safer choice when the field is somehow missing
- Added an explicit `privacy: int | None = None` parameter to `edit_submission` so callers can override (used by `SoFurryPoster.edit()` when `extra["draft"]` or `extra["privacy"]` is set)
- A long docstring on the method warns the next person not to substitute `get_submission_detail()` back in

**Audit confirmed all 13 SF works are in correct state:**
| 7 live works | privacy=3 (Public) ✓ |
| 6 new drafts | privacy=1 (Private) ✓ |

### Test files
- `tests/sf_smoke.py` — login + CSRF read-only check
- `tests/verify_sf_draft.py` — Tombstone canary draft with raw-JSON privacy verification
- `tests/bulk_sf_drafts.py` — bulk draft 5 missing stories (Tombstone already drafted)
- `tests/sf_retry_hypnotic_edit.py` — retry the 4-day-old failed edit
- `tests/sf_emergency_restore_hypnotic.py` — emergency restoration script (used once to undo the privacy regression)
- `tests/sf_audit_all_privacy.py` — full audit of expected vs actual privacy state for every known SF submission
- `tests/sf_mark_hypnotic_posted.py` — mark the publications row from `failed` back to `posted`

---

## [2.3.6] - 2026-04-08

### Fixed — `pawsync.bat` rewritten in Python after intermittent batch hang

The original `pawsync.bat` had two intermittent gotchas that survived three rounds of patching:

1. **Windows tar's `Cannot connect to C:` silent failure.** Windows tar (libarchive port) interprets `C:\\...` paths as remote SSH hosts unless given `--force-local`. Without it the pack would silently fail and the script would still upload whatever stale tarball was left in `%TEMP%` from the previous run — which we caught the hard way when [2.3.4]'s pawsync uploaded an Apr-6 archive 2 days after the fact.

2. **gcloud-from-batch hang.** When `gcloud compute scp` was invoked from inside a `.bat` file (vs interactively or via `cmd /c "..."`), it would silently hang somewhere after the upload reached 100% — never reaching the next command, never returning control to cmd.exe, no visible processes left running. The same gcloud command worked fine in every isolated test (interactive cmd, inline `cmd /c`, with or without `--quiet`, with or without `< nul` stdin redirect, with `--quiet` as top-level flag vs subcommand flag — none of those workarounds dislodged the hang in `.bat` context).

**Resolution: rewrote `deploy/pawsync.bat` in Python** as `deploy/pawsync.py` with a 3-line `.bat` wrapper that just calls `python pawsync.py %*`. Python sidesteps both bugs:

- **Pack via `tarfile` module** instead of Windows tar — cross-platform, no `--force-local` gotcha, no path interpretation surprises, and cleanly skips `Backups/`, `Drafts/`, `Styled_HTML/` via a name filter.
- **scp + ssh via `subprocess.run`** with `stdin=subprocess.DEVNULL`, `capture_output=True`, `shell=True` (needed on Windows so the OS resolves `gcloud.cmd`), explicit `timeout=600` for upload and `timeout=300` for extract. Zero ambiguity about stdio inheritance, deterministic exit code propagation, no batch context to confuse the wrapper.
- Uses `kithetiger@pawpoller` consistently for both scp and ssh (was previously mismatched — scp uploaded as `kithetiger`, default `gcloud ssh` ran as your Google identity user, which couldn't `rm` the kithetiger-owned file in `/tmp` due to the sticky bit).
- Aborts on any failure with a non-zero exit code (no silent stale uploads).

**One-time server cleanup applied during the rewrite:**
The server's `/home/kithetiger/story-archive/` files were owned by `rhysc` (my Google account user from previous extracts). After switching the new pawsync to extract as `kithetiger`, the first run hit `tar: Cannot open: File exists` because tar can't overwrite files owned by another user. Fixed with a one-shot `sudo chown -R kithetiger:kithetiger /home/kithetiger/story-archive`. All subsequent syncs work cleanly.

### File changes
- `deploy/pawsync.py` — new Python script (185 lines) that does the full pack-upload-extract-cleanup pipeline
- `deploy/pawsync.bat` — replaced 30-line batch script with 3-line wrapper that calls `python pawsync.py %*`

---

## [2.3.5] - 2026-04-08

### Added — AO3 Refactor + Bulk Drafting

Brought the Archive of Our Own client and poster up to par with the SquidgeWorld stack and bulk-drafted the entire local catalogue (13 drafts) on AO3.

**13 AO3 drafts** (every local story, all in preview/draft state, none published):

| Story | Work ID | Words |
|---|---|---|
| Tombstone | [82711601](https://archiveofourown.org/works/82711601/preview) | 8,414 |
| Chosen | [82712456](https://archiveofourown.org/works/82712456/preview) | 15,958 |
| Drumheller_Detour | [82712566](https://archiveofourown.org/works/82712566/preview) | 10,062 |
| Hypnotic_Claim | [82712801](https://archiveofourown.org/works/82712801/preview) | 9,809 |
| Not_So_Efficient_Studying | [82712821](https://archiveofourown.org/works/82712821/preview) | 13,602 |
| Overtime | [82712896](https://archiveofourown.org/works/82712896/preview) | 11,513 |
| Ruins_of_Breeding | [82712911](https://archiveofourown.org/works/82712911/preview) | 24,457 |
| The_Haunting_Desires | [82713001](https://archiveofourown.org/works/82713001/preview) | 30,480 |
| The_Silk_Threaded_Bonds | [82713066](https://archiveofourown.org/works/82713066/preview) | 13,904 |
| Velvet_And_Vice | [82713131](https://archiveofourown.org/works/82713131/preview) | 73,068 |
| Extra_Credit | [82713211](https://archiveofourown.org/works/82713211/preview) | 24,433 |
| The_Abstinent_Bet — Nice Version | [82713236](https://archiveofourown.org/works/82713236/preview) | 15,767 |
| The_Abstinent_Bet — Naughty Version | [82713271](https://archiveofourown.org/works/82713271/preview) | 9,704 |

All 13 are recorded in the publications table on the server with `status=draft`. Each is the canonical single-bulk-file shape (full story body HTML in one chapter, matching the IB convention) sourced from `HTML/<Story>_Clean.html`.

### Fixed — `ao3_client/client.py` was a pre-SQW codebase with multiple critical bugs

Before this session, the AO3 client was missing every refinement that landed on `sqw_client/client.py` over the past month. `create_work` was effectively broken — it would have failed validation if anyone tried to use it. The full list of fixes:

**1. `_get_page` retries on timeout/525.** AO3 from datacenter IPs sees frequent `ReadTimeout` and `525 origin SSL handshake fail` responses (about 1 in 5 requests). The previous implementation caught the exception, logged with an empty `str(e)` (the user saw `"AO3: Failed to fetch ...: "` with nothing after the colon), and gave up. Now retries 3 times with backoff, distinguishes 525s from timeouts in the logs, and still preserves a clean error path for hard failures (403/404/etc).

**2. `create_work` rewritten to mirror SQW's pattern.** The previous version sent:
```python
"work[archive_warning_string]": warning,    # SINGULAR — wrong field name
"work[category_string]": category,          # SINGULAR — wrong field name
# missing: work[author_attributes][ids][]   # REQUIRED — pseud_id
# missing: work[work_skin_id]
# missing: work[wip_length]
```
Now uses the correct OTW Archive form fields:
```python
"work[author_attributes][ids][]": pseud_id,            # extracted from /works/new HTML
"work[archive_warning_strings][]": warnings_array,     # plural with hidden empty value
"work[category_strings][]": categories_array,          # plural
"work[work_skin_id]": skin_id,
"work[wip_length]": "1",
"preview_button": "Preview",
```

The pseud_id extraction is critical — every OTW work must be linked to at least one author pseud via `work[author_attributes][ids][]`. Without it the form silently rejects with "Sorry! We couldn't save this work because: ...". The pseud is unique per user and is embedded in the `/works/new` HTML.

**3. `language_id="en"` was wrong.** AO3's form expects the numeric language ID (1 = English), not the ISO code "en". The previous code's "en" produced a server-side validation error: `"Language cannot be blank."` which was the first thing the new client hit even after the form-fields fix. Default is now `"1"`.

**4. Added `delete_work`, `is_work_in_drafts`, `is_work_published`.** Direct ports of the SQW versions. Critical for safety — without `delete_work` we can't auto-clean if a draft test goes wrong. Mirror the SQW confirm_delete flow (`_method=delete` + `commit=Yes, Delete Work`).

**5. State checks return tri-state (`True | False | None`).** AO3's `/users/<user>/works/drafts` page is **slow and times out frequently**. The SQW versions return `False` on fetch failure, which would cause the post-flight safety check to spuriously fire `not in_drafts` and try to delete healthy drafts. The AO3 versions distinguish:
- `True`  — fetched and present
- `False` — fetched and not present
- `None`  — fetch failed (network/timeout/CF) — caller cannot conclude

### Added — Smart safety logic in `AO3Poster.post()`

The post-flight verifier in `_verify_still_draft` was rewritten to handle AO3's flakiness:

```python
in_published = await client.is_work_published(work_id)
if in_published is True:
    # Confirmed published — abort + delete
elif in_published is None:
    # Fetch failed — trust preview_button (which guarantees draft state)
    logger.warning(...)
# in_published is False -> definitely safe
```

Before this fix, the first bulk-draft test ran into a real disaster:
1. `create_work` actually succeeded (work `82710971` created in preview state)
2. Post-flight `is_work_in_drafts` timed out 3 times → returned `None` (wrongly interpreted as `False`)
3. `is_work_published` also timed out → returned `False`
4. Safety check: `not in_drafts == True` → triggered abort
5. Auto-delete `delete_work(82710971)` was called
6. `delete_work` ALSO timed out and threw an exception with empty `str()`
7. The script reported `"DELETE FAILED: ."` and exited

The new logic only aborts on **positive** confirmation that the work is published. Since `create_work` exclusively uses `preview_button` (no `post_button` path exists in our client), publication is impossible by construction. Fetch failures are now logged-and-trusted.

### Added — `posting/platforms/ao3.py` rewritten as a SquidgeWorldPoster mirror

The previous `AO3Poster` was 187 lines of legacy minimal-viable code: no draft mode, no fandom passthrough, no warnings/categories/characters/relationships, no tag truncation, no safety checks, no publications tracking. Replaced with a 350-line implementation that mirrors `SquidgeWorldPoster`:

- Loads full StoryInfo from `story.json`
- Builds the OTW metadata bundle (fandom, warnings, categories, characters, relationships)
- Trims freeform tags to fit OTW's 75-tag total budget (`fandom + relationships + characters + freeform <= 75`)
- Reads single-bulk-file body HTML from `HTML/<story>_Clean.html` (with `SquidgeWorld/Chapter_*.html` concatenation as fallback)
- Posts via the new `create_work` with `preview_button`
- Smart post-flight safety check (see above)
- Returns standard `PostResult`

**Difference from SQW**: AO3 client doesn't yet have multi-chapter `create_chapter` or Work Skin support. For chaptered prose we use the IB-style **single bulk file** convention (`HTML/<Story>_Clean.html` is body-only HTML with all chapters as `<p>` elements in one big body). Multi-chapter `create_chapter` is the next deferred refactor if needed.

### Fixed — `_resolve_format_file` for AO3

Added `("HTML", "*_Clean.html", "html")` as the highest-priority entry in `PLATFORM_FORMAT_MAP["ao3"]`. The previous map only listed `Chapters/SoFurry_HTML/*.html` and `SquidgeWorld/*.html` — both per-chapter dirs. With the earlier `Chapters/` skip fix from 2.3.4, full-story AO3 requests now correctly resolve to `HTML/<story>_Clean.html`.

### Fixed — `StoryInfo.title` field for human display titles

`StoryInfo` was missing the `title` field from `story.json` (only `name` = folder name). `build_package` therefore derived titles via `story.name.replace("_", " ")`, which produced `"The Abstinent Bet/Nice Version"` (with a slash) when the story was loaded from a subfolder path like `The_Abstinent_Bet/Nice_Version`.

Added `title: str = ""` to `StoryInfo` and made `build_package` prefer `story.title` over the folder-name fallback. The two Abstinent Bet AO3 drafts that were posted with the slashy titles were retroactively fixed via `client.edit_work(work_id, title=...)`.

### Test files
- `tests/ao3_smoke.py` — login + list works (read-only smoke test)
- `tests/ao3_diagnose.py` — `_get_page` retry-vs-direct timing diagnostic (helped find the timeout-as-empty-error bug)
- `tests/verify_ao3_draft.py` — single-story draft test (Tombstone) with full safety verification
- `tests/bulk_ao3_drafts.py` — bulk-draft 11 missing stories (Extra_Credit + Abstinent_Bet versions failed and were retried)
- `tests/ao3_retry_failed.py` — retry script for the 3 stories that failed in bulk
- `tests/ao3_fix_abstinent_titles.py` — `edit_work` retroactive title fix for the 2 Abstinent Bet drafts
- `tests/check_ao3_pubs.py` — quick query helper

### Important: deployment status

**The refactor lives only in the running container's filesystem right now** — files were `docker cp`'d in for fast iteration, NOT pulled from a deployed git repo. The local repo has the same files. To make the refactor permanent across container rebuilds:

1. Commit the refactor (`ao3_client/client.py`, `posting/platforms/ao3.py`, `posting/story_reader.py`, the test files)
2. Push to GitHub
3. Run `pawupdate` (`gcloud ... git pull && docker compose up -d --build`)

Without that, the next `docker compose up` will pull the legacy AO3 code back from the image.

### AO3 access notes

- **Local desktop access**: shielded ("Shields are up!" CF JS challenge). No bypass via header tweaks. All AO3 testing must run from the GCP container.
- **GCP container access**: works most of the time but with frequent `ReadTimeout` and `525 origin SSL` errors. AO3's infrastructure is volunteer-run and intermittent. The new retry logic in `_get_page` handles this transparently.
- **AO3 throughput observations**: bulk-drafting 11 stories over 12 minutes hit ~1 in 6 form fetches that needed 2-3 retries to get through. One story (`Extra_Credit`) needed a full retry after exhausting all 3 attempts on the same form fetch.

---

## [2.3.4] - 2026-04-08

### Added — Inkbunny Bulk Drafting + `story_reader` Fixes

**Bulk Inkbunny upload** — Posted 5 missing stories as HIDDEN DRAFTS to KnaughtyKat's IB account in a single run via `tests/bulk_inkbunny_drafts.py`:

| Story | Submission | Words | Tags |
|---|---|---|---|
| Chosen | [3847118](https://inkbunny.net/s/3847118) | 15,958 | 105 |
| Not_So_Efficient_Studying | [3847119](https://inkbunny.net/s/3847119) | 13,602 | 57 |
| Overtime | [3847120](https://inkbunny.net/s/3847120) | 11,513 | 88 |
| Ruins_of_Breeding | [3847121](https://inkbunny.net/s/3847121) | 24,457 | 92 |
| The_Haunting_Desires | [3847122](https://inkbunny.net/s/3847122) | 30,480 | 108 |

Plus the previously-rebuilt **Tombstone** ([3847083](https://inkbunny.net/s/3847083), 8,414 words, 75 tags) which was registered into the publications table during this run.

After this run, the `publications` table holds 6 IB rows — every Tombstone, Chosen, NSE Studying, Overtime, Ruins, and Haunting record knows its IB submission_id and can be edited or replaced from the dashboard.

**Bulk-draft script safety:**
- Pulls every published submission via `client.search_user_submissions()` and aborts if any local target's display title overlaps with a live work — protects the 9 already-published stories from accidental overwrite.
- Sets `extra["draft"] = True` on every package so visibility is omitted (IB defaults hidden).
- Verifies each post via `get_submission_details()` (title, page count, keyword count) before recording.
- Records each result via `upsert_publication()` so the registry is the single source of truth.

**Empirical finding:** Inkbunny accepts at least 108 keywords on a single submission. The previously-assumed 75-keyword cap is wrong — no truncation needed. (NSE Studying sent 58 tags and IB returned 57; one duplicate or empty was silently dropped server-side, not a hard limit.)

### Fixed — `story_reader` resolved chapter file instead of full-story file

`posting/story_reader.py:_resolve_format_file()` was returning the wrong file when called with `chapter_index=0`. The IB format spec is:

```python
"ib": [
    ("Chapters/BBCode", "*.txt", "bbcode"),   # per-chapter
    ("BBCode", "*_bbcode.txt", "bbcode"),     # full story
],
```

For full-story requests, the loop iterated specs in order, hit `Chapters/BBCode` first, found that `*.txt` matched any chapter file, and returned `Chapter_1_*_bbcode.txt`. The full-story spec was never reached.

**Fix:** when `chapter_index == 0`, skip any subdir whose path contains `Chapters/`. Per-chapter directories are inherently chapter-only and should never serve full-story requests.

```python
else:
    # Full-story file — skip per-chapter subdirs (Chapters/...)
    if "Chapters" in subdir.split("/"):
        continue
    ...
```

This bug masqueraded as a successful upload — IB submission 3847080 was created from chapter 1 only and verification reported `pages=1` correctly. Caught only by inspecting `file_path` in the script output. The user-visible result: posting any story via `build_package(story, 0, "ib")` would silently upload chapter 1 instead of the full bulk file. Now fixed for IB and — by extension — every other platform with the same `Chapters/...` + `BBCode/...` spec ordering (FA, Weasyl).

### Fixed — `story_reader` thumbnail auto-detection when `images.cover` empty

Stories with thumbnails sitting at the story root but no `images.cover` entry in `story.json` (the common case — `<story>_thumbnail_full_series.png` is the convention) returned `thumbnail_path = None`. The IB poster then uploaded with no thumbnail.

**Fix:** when `images.cover` is empty, glob the story root for common thumbnail naming patterns:
- `*_thumbnail_full_series.*`
- `*_thumbnail.*`
- `*_cover.*`
- `thumbnail.*`
- `cover.*`

First match wins, restricted to `.png/.jpg/.jpeg/.gif`. Verified end-to-end: Tombstone's `tombstone_thumbnail_full_series.png` was auto-detected and attached to submission 3847083, and IB returned a populated `thumbnail_url_huge` after the post.

The 5 newly drafted stories don't have thumbnail files yet, so they posted thumbnail-less — they can be added via the IB UI later.

### Inkbunny Tombstone single-bulk-file rebuild

Replaced the experimental two-page Tombstone test (3847063 → deleted) with a clean single-file submission:
- Submission **3847083** = full Tombstone bulk file (`BBCode/Tombstone_bbcode.txt`, 49,200 bytes, all 3 chapters in one BBCode)
- Title `Tombstone`
- Description: 30-word version from `story.json`
- 75 IB keywords
- Auto-detected thumbnail attached
- Stays HIDDEN — ready for live submission whenever

This is the canonical IB shape for chaptered stories: one submission, one bulk file with chapter dividers, one thumbnail. IB's per-page navigation is for multi-image art, not for chaptered prose where the story field is a single blob anyway.

### Test files
- `tests/verify_inkbunny_bulk_rebuild.py` — Tombstone single-file rebuild verification
- `tests/bulk_inkbunny_drafts.py` — bulk-draft 5 missing stories with safety guards

---

## [2.3.3] - 2026-04-08

### Added — Work Skin CSS Auto-Refresh

`SquidgeWorldPoster._ensure_work_skin()` now **always pushes the current local CSS to SquidgeWorld** on every `post()` and `edit()` call, not just when creating a new skin. Previously, if a Work Skin already existed by title, the poster would return its skin_id and skip the update — meaning local CSS edits would never propagate.

**New behavior:**
1. If no `Work_Skin.css` for the story → return `''` (no skin applied)
2. If skin doesn't exist by title → create new with current CSS
3. **If skin exists → call `client.edit_work_skin()` to push the current CSS and description** (auto-refresh, best-effort — if the edit fails, log a warning but still return the skin_id so the work can use the existing skin)

**Verified end-to-end** with a sentinel-color test:
- Modified Tombstone's `Work_Skin.css` locally (replaced `#5a7a52` with `#abcdef`)
- Called `SquidgeWorldPoster.edit("91390", package)`
- Confirmed `#abcdef` was present in the live SQW skin CSS
- Auto-restored original

**Note:** SquidgeWorld (OTW Archive) **strips CSS comments server-side** as part of its sanitization. This is intentional on their end and doesn't affect functionality. Don't rely on string-equality comparisons between local CSS files and the live skin CSS — strip comments from local before comparing.

---

## [2.3.2] - 2026-04-08

### Added — Work Skins for the 3 Stories That Were Missing Them

Created `Work_Skin.css` for Drumheller_Detour, The_Haunting_Desires, and Velvet_And_Vice, then uploaded them as Work Skins on SquidgeWorld and applied them to the live drafts via `SquidgeWorldPoster.edit()`:

- **Drumheller_Detour Skin** (id 2827) — Badlands Dust theme: dark brown background (#1c1510), warm cream text (#e0d5c8), badlands orange accents (#c17817). Includes `.comic-panel` / `.comic-caption` rules for the story's embedded illustration images.
- **The Haunting Desires Skin** (id 2828) — Haunted Dark theme: near-black background (#08090e), warm grey text (#d0ccc8), antique gold accents (#c8a050).
- **Velvet And Vice Skin** (id 2829) — Velvet Noir theme: dark wine background (#100808), warm off-white text (#e2dad0), deep burgundy primary (#8b1a1a), copper secondary (#b87040). Handles both `<p class="chapter-heading">` and `.chapter-heading` since V&V uses the `<p>` variant.

All 3 skins were uploaded via `client.create_work_skin()` and applied through the existing `SquidgeWorldPoster.edit()` flow which auto-detects draft/published state. All 3 stories stayed in draft state throughout.

After this change, every SquidgeWorld work has a custom Work Skin matching its story's theme.

---

## [2.3.1] - 2026-04-08

### Added — SquidgeWorld Bulk Upload + Description Cleanup + Safety Hardening

**Bulk SquidgeWorld upload** — Posted 7 missing stories as DRAFTS to SquidgeWorld in a single run:
- Tombstone (91390, 3 chapters)
- Drumheller_Detour (91391, 8 chapters)
- Not_So_Efficient_Studying (91393, 3 chapters)
- Overtime (91394, 4 chapters)
- Ruins_of_Breeding (91395, 6 chapters)
- The_Haunting_Desires (91396, 8 chapters)
- Velvet_And_Vice (91397, 9 chapters)
- Total: **41 new chapters added**. All verified to stay in draft state throughout.

**Safety infrastructure** added to prevent accidental publishing:
- `SquidgeWorldClient.delete_work(work_id)` — emergency cleanup mechanism via the `/works/{id}/confirm_delete` form (POST `_method=delete` + `commit=Yes, Delete Work`).
- `SquidgeWorldClient.is_work_in_drafts(work_id)` / `is_work_published(work_id)` — state check helpers that query `/users/{user}/works/drafts` and `/users/{user}/works`.
- `SquidgeWorldPoster.post()` now has post-flight draft-state verification after `create_work` AND after every `create_chapter`. If the work ever leaves draft state, it's **automatically deleted** and the call fails. Opt out with `package.extra["allow_publish"] = True`.
- `SquidgeWorldPoster.edit()` now **auto-detects** whether the work is draft or published and uses the matching submit button (`save_button=Save As Draft` for drafts, `post_button=Post` for published), then verifies the state didn't change after the edit. Opt out with `package.extra["allow_state_change"] = True`.

**`SquidgeWorldClient.create_chapter` simplified and fixed:**
- The previous `publish=False` path was broken (tried a two-step preview→save flow that returned 400 because it didn't resend the chapter fields).
- **Verified empirically** that a single `preview_button=Preview` POST creates the chapter fully AND leaves the work in its current state. No follow-up `save_button` click is needed. Confirmed via `tests/test_chapter_after_preview_only.py` — the new chapter is present in `get_chapter_ids()` after the preview POST with no state change.
- `publish=True` still uses `post_without_preview_button=Post` which DOES publish the work (never call this on drafts).

**Description cleanup** — Updated 9 story.json `description` fields to be ≤30 words and ≤2 sentences for cleaner platform listings:
- Chosen: 40w → 30w
- Drumheller_Detour: 39w → 28w
- Not_So_Efficient_Studying: 29w → 28w (merged to 2 sentences)
- Overtime: 64w → 26w
- Ruins_of_Breeding: 31w → 23w
- The_Haunting_Desires: 31w → 29w
- The_Silk_Threaded_Bonds: 35w → 29w
- Tombstone: 56w → 30w (4 sentences → 2)
- Velvet_And_Vice: 35w → 29w (3 sentences → 2)
- Extra_Credit and Hypnotic_Claim already fit the target (28w and 27w respectively)
- All changes pushed live to SquidgeWorld via the refactored `SquidgeWorldPoster.edit()` (drafts stayed drafts, Chosen stayed published)

**Bulk upload test infrastructure (`tests/`):**
- `verify_draft_chapter_safety.py` — creates a throwaway draft, verifies draft state, adds a chapter via `publish=False`, verifies still draft, deletes. Always cleans up.
- `test_chapter_after_preview_only.py` — proved the preview POST alone is sufficient (the fix that made `create_chapter(publish=False)` actually work)
- `inspect_draft_chapter_form.py` — dumps the fields OTW Archive expects on the chapter preview page
- `post_missing_stories_to_sqw_drafts.py` — bulk-upload script with fuzzy title matching, dry-run, per-story confirmation, and post-flight safety checks
- `verify_all_drafts.py` — sequential read-only audit of all draft works, comparing each against its `story.json`
- `update_descriptions_and_push.py` — updates story.json descriptions and pushes them to SquidgeWorld

### Fixed
- **`edit_chapter`** had a silent-failure bug — the original partial-fields approach sent `_method=patch` + a few fields + a generic `commit=Update` button. This matched nothing the OTW form expected and sometimes returned 200 with no actual save. Fully refactored to the safe form-fetch pattern: GET `/works/{id}/chapters/{ch_id}/edit`, extract every `chapter[*]` field with its current value (inputs, selects, textareas), override only the requested fields, POST with the appropriate submit button (auto-detected: `save_button` for drafts, `post_without_preview_button` for published), strict success check for "successfully updated" flash.

### Known Issues / Follow-ups
- **Chosen work_skin fandom drift**: OTW Archive's tag wrangler auto-canonicalises `Kung Fu Panda` → `Kung Fu Panda - Fandom`. The story.json stays as `Kung Fu Panda` and SQW adds the suffix server-side. Not a bug, just informational.
- **Character/relationship tag canonicalisation**: OTW converts `(Original Character)` to `[Original Character]` or appends `[OC]`. Same — server-side transformation, not a client bug.
- **Missing Work_Skin.css for 3 stories**: Drumheller_Detour, The_Haunting_Desires, Velvet_And_Vice have no `Work_Skin.css` in their `SquidgeWorld/` folder. These stories were uploaded without a custom work skin (they use the default OTW styling). Create work skins for them as a follow-up if desired.
- **Tag curation** — current behavior dumbly truncates to first N tags to fit the 75-tag OTW limit. Smart prioritisation or dedicated `tags.sqw` lists in `story.json` would be better, but deferred.

### Verification
- All 8 stories on SquidgeWorld verified sequentially via `verify_all_drafts.py` — correct title, fandom, rating, warnings, categories, characters, relationships, tag counts, chapter counts, and draft/published state.
- `The Silk-Threaded Bonds` correctly matched as pre-existing via fuzzy matching (`The Silk Threaded Bonds` in story.json vs `The Silk-Threaded Bonds` on SQW — hyphen difference).
- Description updates pushed live, auto-detected draft state for each work, preserved existing state.

---

## [2.3.0] - 2026-04-07

### Added — SquidgeWorld Posting: Full Refactor + Live Verification

**SquidgeWorldClient (`sqw_client/client.py`):**
- `find_work_skin_by_title(title)` — looks up an existing Work Skin by title from `/users/<user>/skins?skin_type=WorkSkin`, returns skin_id or None
- `create_work_skin(title, css, description, public, role)` — POSTs to `/skins` to create a new Work Skin. Handles `skin_type=WorkSkin` field and the multipart form structure.
- `get_or_create_work_skin(title, css, description)` — find-or-create wrapper. Idempotent.
- `edit_work_skin(skin_id, title, description, css, public)` — safe form-fetch pattern. Extracts every `skin[*]` field from `/skins/{id}/edit`, overrides only the requested fields, POSTs back with `_method=patch` and `commit=Update`. Includes the strict success check.
- `create_work` — added `warnings: list[str]`, `categories: list[str]`, `work_skin_id`, `chapter_title` parameters. Defaults to `warnings=["No Archive Warnings Apply"]`. Now extracts the author pseud ID from the form (required field that was missing). Sends form data via `urlencode(doseq=True)` + `content=` because httpx 0.28.1 has an `AsyncClient` bug with list-of-tuples in `data=`. Backwards compat shims for old `warning`/`category` single-string parameters.
- `edit_work` — full refactor. Uses safe form-fetch pattern: GET `/works/{id}/edit`, extract every `work[*]` field with current value (handles inputs, selects, textareas, radios, checkboxes), override only the requested fields, POST back with `_method=patch` and `save_button=Save As Draft` (or `post_button=Post` if `save_as_draft=False`). Strict success check looks for explicit "successfully updated" flash and raises with the OTW error block if not present. **This was the silent-fail bug** — previous version only checked for "have not been saved" but missed cases where the form was rejected for other validation reasons.
- `edit_chapter` — full refactor. Same safe form-fetch pattern as `edit_work`. Auto-detects whether the form has `save_button=Save As Draft` (draft work) or `post_without_preview_button=Post` (published work) and uses the right one. Strict success check.
- `create_chapter` — **new**. POSTs to `/works/{id}/chapters/new`. **Safe by default**: uses `preview_button=Preview` then submits the preview's `save_button=Save As Draft` so adding a chapter to a draft work does NOT publish the work. Set `publish=True` explicitly to use `post_without_preview_button=Post` (which publishes the work for chapters added to a draft). This safety default was added after a session-mistake accidentally published Chosen.
- `_extract_work_form_fields(html)` — module-level helper that parses every `work[*]` field from a `/works/{id}/edit` page (inputs, selects, textareas with HTML entity decoding). Used by `edit_work` to safely extract current state.

**Story reader (`posting/story_reader.py`):**
- `StoryInfo` dataclass extended with: `rating`, `fandom`, `category`, `categories: list[str]`, `warnings: list[str]`, `characters: list[str]`, `relationships: list[str]`, `work_skin_path: Path | None`. The `__post_init__` ensures lists are never None and falls `categories` back to `[category]` if only the legacy single-string was set.
- `_load_from_story_json` populates all the new fields from `story.json`. Handles legacy `category: str` vs new `categories: list[str]`. Auto-detects `Work_Skin.css` at `<story>/SquidgeWorld/Work_Skin.css`.

**SquidgeWorldPoster (`posting/platforms/squidgeworld.py`) — full refactor:**
- `post()` — now multi-chapter, full-metadata, work-skin-aware. Loads `StoryInfo` via `story_reader.load_story` (just needs `package.story_name`). Finds or creates the Work Skin from `Work_Skin.css`. Trims freeform tags to fit OTW's 75-tag limit (fandom + relationship + character + freeform). Calls `client.create_work` with all metadata for chapter 1, then iterates remaining chapters and calls `client.create_chapter(publish=False)` to keep the work in draft state. Returns `PostResult` with the work_id.
- `edit()` — same shape. Refreshes the Work Skin, edits work metadata via `edit_work` with full metadata, then iterates `client.get_chapter_ids(work_id)` and calls `client.edit_chapter` for each with the corresponding archive file content.
- `_trim_freeform_tags()` — calculates the OTW 75-tag budget (75 - fandoms - relationships - characters) and trims freeform tags to fit.
- `_read_chapter_content(story, ch_idx)` — resolves chapter content by looking first in the story's `SquidgeWorld/` dir (preferred body-only HTML), then falling back to `Chapters/SoFurry_HTML/`.
- `_ensure_work_skin(client, story)` — handles the work skin lifecycle. Returns `skin_id` or empty string if no `Work_Skin.css` is present.
- `_rating_to_sqw()` — maps internal rating values to OTW canonical ("explicit" → "Explicit").

**Test scripts (under `tests/`):**
- `live_test_sqw_draft.py` — exercises the create-draft flow against Chosen Ch1
- `live_test_sqw_edit.py` — full safe form-fetch pattern reference for edits
- `live_test_sqw_full.py` — Work Skin creation + work edit pipeline
- `live_test_sqw_chapters.py` — adds chapters and updates skin metadata
- `live_test_sqw_finalize.py` — clean-up flow for taking a draft to a polished published state
- `live_test_sqw_reupload_chapters.py` — uses `edit_chapter` to update all chapters of a work
- `live_test_sqw_poster.py` — end-to-end test of `SquidgeWorldPoster.edit()` against the live work
- `regen_chosen_sqw.py` — regenerates Chosen's SquidgeWorld body HTML files using the wrapper from the existing files + paragraphs from the regenerated SoFurry HTML

### Fixed
- **httpx 0.28.1 AsyncClient + list-of-tuples bug** — `data=[(k,v),...]` raises "Attempted to send a sync request with an AsyncClient instance". Worked around in `create_work` and all new POSTs by URL-encoding manually with `urlencode(doseq=True)` and using `content=` with explicit `Content-Type: application/x-www-form-urlencoded`. The form data needs duplicate keys for `work[archive_warning_strings][]` and `work[category_strings][]` array fields, which is why a dict can't be used.
- **OTW Archive validation errors** that the previous edit_work silently ignored:
  - `Fandom, relationship, character, and additional tags must not add up to more than 75` — now caught by the strict success check; poster auto-trims freeform tags
  - `Only canonical warning tags are allowed` — fixed by sending `archive_warning_strings[]` (plural array) with canonical values like "No Archive Warnings Apply" instead of the old "Creator Chose Not To Use Archive Warnings"
  - `Work must have at least one creator` — fixed by extracting the author pseud ID from the form HTML and including it as `work[author_attributes][ids][]`
- **OTW Archive edit_work used wrong submit button** — `preview_button` only shows a preview, doesn't save. Fixed to use `save_button=Save As Draft` for drafts and `post_button=Post` for published works.
- **OTW Archive edit_chapter used wrong submit button** — same issue. Fixed to auto-detect `save_button` (draft) vs `post_without_preview_button` (published).
- **Accidentally published a draft work via `create_chapter`** during testing — `post_without_preview_button` on a chapter form publishes the entire work, not just the chapter. Fixed by making `create_chapter` safe-by-default with `publish=False` using a `preview_button` → `save_button` two-step pattern. To get the old behavior, callers must pass `publish=True` explicitly.

### Known Issues / Pending
- **Other platform posters not yet refactored** — IB, FA, SF, WS, BSKY, AO3, IK, DA still use their original implementations. IB/FA/SF were known to work in earlier sessions but haven't been retested with the new full-metadata `story.json` shape. AO3 uses the same OTW Archive software as SquidgeWorld so will likely need the same fixes.
- **Other stories' SquidgeWorld files** still need regeneration. Only Chosen has been redone for the live test. The mass regen for the other 10 stories is mechanical and pending.
- **Styled HTML files** for all stories also need regeneration since they're built from the same converter output and likely contain the same nested-asterisk bug.

### Live Verification — Chosen → SquidgeWorld
- Created draft work 91374 for Chosen via `client.create_work` (with all metadata pulled from story.json)
- Created Work Skin 2820 ("Chosen Skin") from `Chosen/SquidgeWorld/Work_Skin.css`
- Edited Work Skin metadata to add a proper title and description
- Added all 5 chapters via `create_chapter` (note: the initial test used the old `publish=True` behaviour and accidentally published the work — has been left published since the user accepted that state and the metadata was cleaned up properly)
- Verified `SquidgeWorldPoster.edit("91374", package)` end-to-end against the live work — full metadata + work skin + all 5 chapter contents updated in 23.4s in a single call

---

## [2.2.1] - 2026-04-07 — Converter Bug Fix + Mass Regeneration

### Fixed
- **Critical: nested-asterisk emphasis bug** in both `convert_md_to_sofurry_html.py` and `convert_md_to_bbcode.py`. The author convention is `*outer narration *emphasized_word* outer narration*` — single asterisks for both italic narration AND inner emphasis. The previous regex `\*(.+?)\*` matched the OUTER asterisks first (lazy regex), producing wrong-bolded paragraphs where the WHOLE paragraph became `<strong>` and the supposedly-emphasized word was the only un-bolded thing.
- The fix: added an `is_narration_wrapped(text)` check that detects single-asterisk wrappers (excluding `**` bold cases at start/end), strips the outer wrapper before running the inner emphasis regex, and re-applies `<em>` after.
- Also fixed the multi-segment dialogue path in both converters which had the same issue but only triggered when narration segments had >2 asterisks.

### Mass regeneration
- Ran the fixed converters across the entire `Archives/Complete_Stories/` tree
- 148 files regenerated (full-story BBCode + SoFurry HTML for each story, plus all per-chapter BBCode and SoFurry HTML files)
- 0 failures
- Affected stories (with the bug): Chosen, Drumheller_Detour, Extra_Credit, Hypnotic_Claim, Not_So_Efficient_Studying, Ruins_of_Breeding, The_Haunting_Desires, The_Silk_Threaded_Bonds, Velvet_And_Vice
- Unaffected: Tombstone, Overtime (recent stories that didn't use nested asterisks heavily)

### Tools
- `m_x/Scripts_Utils/test_emphasis_fix.py` — unit test demonstrating the bug and the fix
- `m_x/Scripts_Utils/regenerate_all_html_bbcode.py` — walks the archive and runs both converters on every MASTER.md and chapter .md

### Worst case before/after
- Chosen Chapter 4 had **86 `<strong>` tags** in the SquidgeWorld body file before the fix, with most paragraphs incorrectly bolded
- After the fix and regen: **49 single-word emphases** (the chapter genuinely uses lots of emphasis for intensity, but each is now a single word, not a wrongly-bolded paragraph)

---

## [2.2.0] - 2026-04-06

### Added
- **Per-chapter tag support** — story_reader.py now reads `chapter_info[].tags` from story.json and populates `chapter_tags_by_platform`. Per-chapter uploads (FA, SQW) use chapter-specific tags when available, falling back to story-level tags.
- **Platform tag limits reference** — `posting/references/platform_tag_limits.md` documenting tag limits (SF≤97, WP≤24, DA≤30), SQW/AO3 archive warnings, categories, ratings, and relationship notation.
- **Complete story.json metadata** for all 11 stories — descriptions, summaries, categories, warnings, characters, relationships, per-platform tags (from Tag_Database), per-chapter tags and descriptions for all 67 chapters.
- **Itaku posting support** (platform 8) — image gallery uploads and text posts via Django REST Framework token auth.
- **DeviantArt posting support** (platform 9) — via official OAuth2 literature API with auto-refreshing tokens.
- **AO3 posting support** (platform 7) — same OTW Archive form structure as SquidgeWorld.

### Changed
- `posting/story_reader.py` — `_load_from_story_json()` now reads per-chapter tags and populates `chapter_tags_by_platform` dict. `build_package()` tag selection chain: chapter tags → story tags → empty.
- `posting/generate_story_json.py` — generates AO3 and DeviantArt platform configs in story.json.
- `database/db.py` — SQLite timeout increased from 10s to 30s + `PRAGMA busy_timeout=30000` for concurrent poll cycle contention.

### Fixed
- **SQLite "database is locked" errors** during concurrent poll cycles — busy_timeout pragma makes writers queue instead of erroring.
- **Styled HTML title font-size** standardised to 2.8rem across all stories (was 3rem in Hypnotic Claim and NSES).

---

## [2.1.0] - 2026-04-05

### Added
- **DeviantArt posting support** (platform 9) — via official OAuth2 literature API
  - `da_client/client.py` — `oauth_create_literature()`, `oauth_update_literature()`, `oauth_refresh_token()`
  - `posting/platforms/deviantart.py` — DeviantArtPoster with post, edit, replace_file (body content)
  - Uses official OAuth2 API (not undocumented _napi) — stable, works from any IP
  - Requires app registration: `da_client_id`, `da_client_secret`, `da_refresh_token` in settings
  - Auto-refreshes access tokens (1-hour expiry, 3-month refresh tokens)
  - Title max 50 chars, max 30 tags, mature level/classification support
  - Format: reads from Markdown (MASTER.md or chapter files)

- **Itaku posting support** (platform 8) — image gallery uploads and text posts
  - `ik_client/client.py` — `upload_image()` (multipart gallery), `create_post()` (JSON text post)
  - `posting/platforms/itaku.py` — ItakuPoster with image upload and text post support
  - Auth: Django REST Framework token from browser session (`ik_auth_token` setting)
  - Min 5 tags, max 10MB images, ratings: SFW/Questionable/NSFW
  - No edit or file replacement support (Itaku API limitation)
  - Note: Itaku is primarily for art, not literature. Text posts limited to ~5000 chars.

- **AO3 posting support** (platform 7) — same OTW Archive software as SquidgeWorld
  - `ao3_client/client.py` — `create_work()`, `edit_work()`, `edit_chapter()`, `get_chapter_ids()`, HTML whitespace collapse
  - `posting/platforms/ao3.py` — AO3Poster with post, edit (metadata + chapters), replace_file
  - Uses existing `ao3_username`/`ao3_password` credentials (same account for polling and posting)
  - 3-second rate limit between requests (AO3 is volunteer-run)
  - Registered in manager, story_reader, frontend, story.json generator

### Fixed
- **SQLite "database is locked" errors** — increased timeout from 10s to 30s + added `PRAGMA busy_timeout=30000` for concurrent poll cycle contention

---

## [2.0.0] - 2026-04-04

### Added — Multi-Platform Posting Module
Complete story publishing system — upload, edit, and manage stories across 7 platforms from PawPoller.

**Core Infrastructure:**
- `posting/` module — manager, scheduler, story reader, sync, platform posters
- `database/posting_schema.sql` — 3 tables: publications, posting_queue, posting_log
- `database/posting_queries.py` — Full CRUD for all posting tables
- `routes/posting_api.py` — 12+ REST endpoints for posting operations
- `posting/scheduler.py` — Background daemon thread processing the posting queue
- Desktop/server queue mode — FA items auto-queue for desktop when server can't process

**Platform Posters (6 platforms):**
- **Inkbunny** (`posting/platforms/inkbunny.py`) — API upload + edit via `api_upload.php` / `api_editsubmission.php`. Story text uses `story` field (reading panel), `desc` for summary. BBCode text message styling (coloured, aligned sent/received).
- **FurAffinity** (`posting/platforms/furaffinity.py`) — 3-step form scrape (GET key → POST upload → POST finalize). Edit via `/controls/submissions/changeinfo/`. File replace via `/controls/submissions/changestory/`. 70s rate limit.
- **SoFurry** (`posting/platforms/sofurry.py`) — REST + CSRF (PUT create → POST content chapter → POST metadata). Chapter-based story content. Author credentials for editing.
- **Weasyl** (`posting/platforms/weasyl.py`) — CSRF + form POST to `/submit/literary`. API key auth.
- **SquidgeWorld** (`posting/platforms/squidgeworld.py`) — OTW Archive form scraping. Author credentials (separate from polling account). HTML whitespace collapse to prevent `<br />` injection. Work Skin CSS classes preserved.
- **Bluesky** (`posting/platforms/bluesky.py`) — AT Protocol `createRecord` + `uploadBlob`. Announcement posts with NSFW labels. Link facet extraction.

**Story Archive System:**
- `story.json` per story — standardised metadata (title, author, rating, warnings, tags, chapters, platforms, images)
- `posting/generate_story_json.py` — generates story.json from existing tags_upload.txt + split_manifest.json
- `posting/story_reader.py` — reads story.json (preferred) or falls back to legacy tag/manifest parsing
- Platform-specific description selection (summary for SQW/AO3, short blurb for IB/SF)
- Format file resolution per platform (BBCode→IB, PDF→FA, SoFurry HTML→SF, SquidgeWorld HTML→SQW)

**Retroactive Sync:**
- `posting/sync.py` — claim existing submissions into publications registry by title matching
- 25 publications claimed across IB, FA, SF, SQW, WP
- Fuzzy matching: full stories, per-chapter (FA), sub-stories (Abstinent Bet), part words
- `/claim` Telegram command and `/api/posting/claim` endpoint

**Change Detection:**
- `file_hash` column on publications — SHA-256 of format file at time of posting
- `detect_changes()` / `get_changed_stories()` / `get_sync_status_summary()`
- `/changes` Telegram command and `/api/posting/changes` endpoint
- After `/update`, hashes are refreshed so `/changes` shows stories as up-to-date

**Desktop Queue Mode:**
- `requires` column on posting_queue: `any`, `desktop`, `server`
- FA flagged as `requires_mode = "desktop"` (needs residential IP)
- Scheduler auto-detects runtime mode (pywebview importable = desktop)
- Failed server posts auto-queue for desktop with `requires=desktop`

**Batch Operations:**
- `/update all [platforms]` — pushes all changed stories to all platforms
- `/update all fa` — batch update on single platform
- Auto-queue fallback: failed server edits queued for desktop processing

**Dashboard UI:**
- Story card hub (`#/posting`) — grid of cards with title, words, chapters, rating, platform badges
- Story detail page (`#/posting/story/{name}`) — full metadata, publications with live stats, upload/update buttons, chapter list, format inventory
- Queue page (`#/posting/queue`) — pending items with cancel
- History page (`#/posting/log`) — audit trail
- Published page redirects to Stories hub
- Mobile responsive: single-column cards, full-width buttons, 44px touch targets
- Bottom nav: Stories link added

**Telegram Commands:**
- `/stories` — list archive stories
- `/upload <story> [platforms]` — post story to platforms
- `/update <story> [platforms]` — push updates to posted submissions
- `/update all [platforms]` — batch update all changed stories
- `/posted [story]` — show publication registry
- `/claim [platforms]` — claim existing submissions
- `/changes` — show which stories have changed since last update

**BBCode Converter Fixes:**
- Title uses `[t]` tag (IB title style) instead of `[b]`
- Subtitle detection: only `*by Author*` or `*A Something Story*` patterns, window closes on first non-subtitle content
- Text messages styled: sent (MAYA) right-aligned blue `#4a9eff`, received left-aligned grey `#aab0bc`
- Phone calls: centred with `📱` emoji and decorative lines
- No longer centres first italic body paragraph after chapter headings

**Story Sync:**
- `deploy/pawsync.bat` — syncs story archive to GCP server
- Fixed: was excluding `*/SquidgeWorld/*` — now includes all format folders
- PyInstaller spec updated with `posting_schema.sql`

### Changed
- `api_client/client.py` — added `upload_submission()`, `edit_submission()` with `story` field
- `bsky_client/client.py` — added `_post_json()`, `upload_blob()`, `create_post()`, `delete_post()`
- `weasyl_client/client.py` — added `submit_literary()`, `edit_submission()` with CSRF
- `sf_client/client.py` — added `_get_csrf_meta()`, `create_submission()` (chapter-based), `edit_submission()`
- `fa_client/client.py` — added `submit_story()` (3-step), `edit_submission()` via `changeinfo`, file replace via `changestory`
- `sqw_client/client.py` — added `create_work()`, `edit_work()`, `edit_chapter()`, `get_chapter_ids()`, `_collapse_html_whitespace()`
- `dashboard.py` — registered `posting_router`
- `database/db.py` — loads `posting_schema.sql`, migrations for `file_hash` and `requires` columns
- `main.py` + `server.py` — posting scheduler daemon thread added
- `polling/telegram_bot.py` — 7 new commands + help text updated
- `inkbunny_analytics.spec` — added `posting_schema.sql` to PyInstaller data files

---

## [1.6.0] - 2026-03-10

### Added
- **Bluesky platform support** (platform 10) — AT Protocol integration with JWT session auth via app passwords
  - `bsky_client/client.py` — `BskyClient` with login/refresh/check session chain, batch post fetching (25 URIs per call), cursor-paginated feed discovery
  - `database/bsky_schema.sql` — `bsky_submissions` (TEXT PK for AT URIs), `bsky_snapshots`, `bsky_poll_log`
  - `database/bsky_queries.py` — Full CRUD with `get_bsky_submission_by_rkey()` suffix match for AT URI resolution
  - `polling/bsky_poller.py` — Poll cycle with 🦋 emoji notifications, activity trigger on likes/reposts changes
  - `routes/bsky_api.py` — `/api/bsky/*` endpoints with `{submission_id:path}` for AT URI path params
  - Frontend: Dashboard (4 stat cards: likes, reposts, replies, quotes — no views), posts table, detail view, comparison charts
  - Metrics: likes, reposts, replies, quotes (4 metrics, no view counts)

- **X/Twitter platform support** (platform 11) — Cookie-based GraphQL scraping of internal endpoints
  - `tw_client/client.py` — `TWClient` with auth_token + ct0 cookie auth, GraphQL query endpoints (UserByScreenName, UserTweets, TweetResultByRestId), content type detection (tweet/reply/retweet/quote)
  - `database/tw_schema.sql` — `tw_submissions` (TEXT PK for tweet IDs), `tw_snapshots`, `tw_poll_log`
  - `database/tw_queries.py` — Full CRUD with 6 metrics, default sort by views DESC
  - `polling/tw_poller.py` — Poll cycle with 🐦 emoji notifications, 2s inter-request delay (aggressive rate limiting)
  - `routes/tw_api.py` — `/api/tw/*` endpoints with content_type filtering
  - Frontend: Dashboard (7 stat cards: views, likes, retweets, replies, quotes, bookmarks), tweets table with type column, detail view, comparison charts
  - Metrics: views, likes, retweets, replies, quotes, bookmarks (6 metrics — most of any platform)

- **Cross-platform integration** for both platforms:
  - Overview page: BSKY/TW included in totals, top lists, recent activity, aggregate charts, export buttons
  - Settings page: BSKY (identifier + app_password) and TW (auth_token + ct0 + target_user) credential sections with connect/disconnect/poll/resync controls
  - Telegram notifications: digest reports, milestone alerts, `/stats`, `/top`, `/poll`, `/interval`, `/notifications` bot commands
  - Analytics: trending detection, cross-platform links, group stats
  - Platform badges: `.platform-badge.bsky` (blue #0085ff) and `.platform-badge.tw` (blue #1d9bf0)
  - Navigation: Bluesky and X/Twitter sidebar groups with Dashboard/Posts/Compare links

### Changed
- Thread count increased from 12 to 14 daemon threads (added BSKY + TW pollers)
- `config.py` — Added `BSKY_REQUEST_DELAY_SECONDS = 1.0` and `TW_REQUEST_DELAY_SECONDS = 2.0`
- `database/db.py` — Schema init loads `bsky_schema.sql` and `tw_schema.sql`
- `dashboard.py` — Registers `bsky_router` and `tw_router`
- `server.py` — Added env-to-settings mappings for BSKY/TW credentials
- `polling/telegram.py` — Added BSKY/TW to platform metrics, emoji, name maps, digest reports, goal checking
- `polling/telegram_bot.py` — Added BSKY/TW to all 10+ platform maps (stats, poll, interval, notify commands)
- `database/analytics_queries.py` — Added BSKY/TW to trending and cross-platform metrics
- `database/group_queries.py` — Added BSKY/TW to group stats metrics
- `routes/api.py` — Added BSKY/TW to table maps and allowed metrics (reposts, retweets, bookmarks, quotes)
- `inkbunny_analytics.spec` — Added BSKY/TW schema files to PyInstaller datas

---

## [1.5.0] - 2026-03-09

### Added
- **Mobile-first UI overhaul** — comprehensive responsive redesign for phone and tablet use
- **Collapsible sidebar navigation** — platform sections collapse into accordion groups on mobile (<=768px), reducing 30+ links to manageable groups that expand on tap
- **Bottom navigation bar** — fixed bottom bar on mobile with quick access to Overview, Platforms (opens sidebar), Analytics, and Settings
- **Table-to-card transformation** — all 9 platform submission tables transform into stacked card layouts on mobile using `data-label` attributes for inline column headers
- **Safe area support** — `viewport-fit=cover` and `env(safe-area-inset-*)` CSS for notched devices (iPhone etc.)
- **Touch optimisation** — `touch-action: manipulation` on all interactive elements, `-webkit-tap-highlight-color: transparent`, 44px minimum touch targets
- **Responsive chart sizing** — chart heights reduce from 280px to 220px/200px at tablet/phone breakpoints
- **Mobile-friendly settings** — form inputs stack vertically with full-width fields and 44px min-height on mobile
- **Wider sidebar on mobile** — sidebar expands to 280px (up from 220px) when opened as overlay for easier tap targets
- **Date range buttons** — range buttons flex-fill and centre-align on mobile for even spacing

### Changed
- Sidebar overlay element moved from JS-created to HTML for better bottom-nav integration
- Stat cards use 10px gap on mobile (down from 16px) and single-column at 480px
- Pinned cards use smaller flex-basis (160px/140px) for better mobile scrolling
- Top list titles truncate at 55vw/60vw on mobile for consistent layout
- Comment cards reduce padding on mobile for space efficiency
- Growth rate values use smaller font (14px) at 480px

---

## [1.4.2] - 2026-03-09

### Security
- **Zip Slip prevention** — auto-updater now validates all ZIP entry paths before extraction to prevent path traversal attacks
- **XSS fix** — `escapeHtml()` now escapes single quotes (`'` -> `&#39;`) preventing attribute injection via submission titles
- **Timing attack fix** — HTTP Basic Auth now evaluates both username and password in constant time (no short-circuit)
- **Error response hardening** — global exception handler no longer leaks internal error details to clients

### Fixed
- **SqW Anubis solver** — proof-of-work implementation now correctly finds a nonce with leading zeros matching difficulty, instead of computing a single hash (which always failed)
- **WP/IK detail charts broken** — `Charts.submissionLine()` now accepts a custom metrics array; Wattpad charts correctly plot reads/votes/lists and Itaku charts plot likes/reshares
- **WP/IK missing from 5 UI components** — added Wattpad and Itaku entries to `overviewTopList`, `overviewRecentActivity`, `trendingCards`, `linkCards`, and `linkSuggestions` badge/route maps; items no longer misidentified as Inkbunny
- **Poll error logs lost** — all 9 pollers now `conn.commit()` after writing error status to poll_log; failed cycles are no longer silently rolled back
- **IB web session lock-in** — CSRF token failure no longer permanently locks the web client in a failed state; session now properly detects expiry and re-authenticates
- **IB comment truncation** — added double-quote fallback for BBCode extraction regex; comments containing apostrophes are no longer silently truncated
- **5 batch methods crash on single failure** — SqW, AO3, WP, IK, and DA `get_*_details_batch()` methods now catch per-item exceptions instead of crashing the entire batch
- **Server startup fallthrough** — main.py now exits with error code if the server fails to start within 15 seconds, instead of opening a blank native window
- **Poll interval zero spin** — poll intervals are now clamped to minimum 1 minute, preventing infinite CPU spin or crashes from zero/negative/non-numeric values
- **Telegram /notify comments** — command now toggles comment-specific setting instead of the IB master notification switch
- **Telegram /notify missing platforms** — added sqw, ao3, da, wp, ik to the notification toggle map
- **DB restore corruption** — backup restore now removes stale WAL/SHM journal files to prevent replaying old transactions against the restored database
- **SF schema incomplete** — added missing `new_watchers_found` column to `sf_poll_log` table definition
- **Update temp cleanup** — failed update downloads now clean up their temp directory instead of leaving orphaned files

---

## [1.4.1] - 2026-03-09

### Security
- **Dashboard authentication** — optional HTTP Basic Auth for server/Docker deployments (set `DASHBOARD_PASSWORD` env var)
- **Update endpoint hardened** — `/api/update/apply` now restricted to GitHub URLs only (prevents SSRF)
- **SQL injection fix** — parameterized weeks value in historical analytics query
- **Thumbnail proxy domain whitelist** — fixed substring matching bypass on IB and FA proxies (e.g. `evil-metapix.net` no longer passes)
- **Thread-safe credentials** — added mutex lock protecting credential reads/writes between web and poller threads

### Fixed
- **Poller deadlock** — all 9 pollers could permanently lock up if database connection failed at startup; restructured try/finally to guarantee lock release
- **WP/IK column name crashes** — milestones, digest, goals, and analytics now use platform-aware column mapping (Wattpad: reads/votes, Itaku: likes/reshares)
- **10 database connection leaks** — all `auth_status` endpoints now close connections in `finally` blocks
- **HTML injection in Telegram** — all titles and usernames are now HTML-escaped in notification messages across all 9 pollers
- **Poll log not committed** — "no submissions found" cycles now persist their poll log entries
- **WS/DA/WP/IK missing notifications** — notification functions were defined but never called; now wired into poll cycles
- **Telegram bot incomplete** — `/stats`, `/top`, `/poll`, `/status`, `/interval` commands now support all 9 platforms
- **table_map incomplete** — pins, goals, tags, historical analytics, groups, and links now include all 9 platforms
- **AO3 work discovery** — narrowed regex to only match works in the listing section, not sidebar/related works
- **DA cookie validation** — now checks for authenticated indicators instead of generic page words
- **IB login check** — removed overly permissive `status_code == 200` fallback
- **IB rating unlock** — response now checked for errors (prevents silent adult content filtering)
- **AO3 login detection** — changed fragile "greeting" text match to `class="greeting"` attribute check
- **SF empty CSRF** — login now fails early with clear error instead of proceeding with empty token
- **SF poll log** — `new_watchers_found` was accepted but silently dropped from SQL UPDATE
- **Rate limit constants** — AO3/DA/WP/IK/SqW clients now use config.py values instead of hardcoded local copies
- **SqW dead code** — removed unused `guest_match` variable
- **IK unused import** — removed `from urllib.parse import urlencode`
- **Frontend: compare chip IDs** — SF/SqW/AO3 now use `parseInt()` matching other platforms
- **Frontend: overview activity** — recent activity timeline now merges all 9 platforms
- **Frontend: groups dropdown** — all 9 platforms available for adding group members
- **Frontend: metric labels** — pinned submissions, growth rates, and analytics use correct platform-specific labels (reads/votes for WP, likes for IK)
- **Frontend: poll interval settings** — added UI controls for SqW/AO3/DA/WP/IK
- **Frontend: interval stacking** — auto-refresh and poll progress intervals now cleared before recreation

### Added
- **FA watcher spam protection** — 3-layer system: keyword filter, confirmation delay (must survive 2 poll cycles), profile sniff (zero-activity detection)
- **FA watcher digest mode** — `fa_watcher_notification_mode` setting: immediate, daily, or off
- **Pagination safety limits** — all client pagination loops capped at 1000 pages to prevent infinite loops
- **Async context managers** — all 9 client classes support `async with` for safe resource cleanup
- **Transport-level retries** — all HTTP clients retry on connection errors (2 retries via httpx transport)
- **Client shutdown cleanup** — atexit handlers close persistent HTTP clients on app termination
- Bullet character consistency — SF/SqW/AO3 Telegram messages now use `•` matching other platforms

---

## [1.4.0] - 2026-03-09

### Added
- **AO3 (Archive of Our Own)** platform support — dashboard, submissions, detail, compare, settings, polling, Telegram notifications
- **DeviantArt** platform support — cookie-based auth, gallery tracking, deviation stats (views, favorites, comments, downloads)
- **Wattpad** platform support — public API, story stats (reads, votes, comments, reading lists), no auth required
- **Itaku** platform support — public API, image/post tracking (likes, comments, reshares), no auth required
- Changelog file

---

## [1.3.1] - 2026-03-08

### Added
- **SquidgeWorld** platform support (full stack)
  - OTW Archive scraper with Anubis bot challenge solver
  - Login via username/password with CSRF token extraction
  - Works discovery and detail scraping (hits, kudos, comments, bookmarks, word count, chapters)
  - Individual kudos user tracking
  - Database schema, queries, poller, REST API (16 endpoints)
  - Frontend: dashboard, submissions table, detail view, compare tool, settings section
  - Overview page integration (totals, platform card, charts)
  - Poll progress bar integration
  - Telegram notifications with platform emoji
- **Headless server mode** (`server.py`) for 24/7 deployment without GUI
  - Runs pollers + dashboard on `0.0.0.0:8420`
  - Docker support with `Dockerfile` and `docker-compose.yml`
  - Environment variable credential injection
  - Graceful SIGTERM/SIGINT handling
- Docker deployment files (`.dockerignore`, `docker-compose.yml`, `Dockerfile`)
- `requirements-server.txt` for server-only dependencies
- Oracle Cloud deployment script (`deploy/setup-oracle.sh`)

---

## [1.3.0] - 2026-03-07

### Added
- **Light/dark theme toggle** with localStorage persistence
- **User-defined tags** — create colour-coded labels and assign them to submissions across platforms
- **Goals** — set metric targets (views, faves, comments) per platform or per submission, track progress with visual cards
- **Pinned submissions** — pin favourites to the top of any platform dashboard
- **Analytics page** — top fans, trending submissions, historical best periods
- **Database backup/restore** — download `.db` file or restore from upload
- **Poll progress bar** — real-time progress indicator during poll cycles
- **SoFurry** platform support (full stack)
  - Email/password + 2FA authentication
  - Gallery scraping with content type detection
  - Stats: views, likes, comments
  - Dashboard, submissions, detail, compare, settings
- `python-multipart` dependency for backup restore endpoint

---

## [1.2.0] - 2026-03-07

### Added
- **Telegram bot command handler** — two-way interaction via `/status`, `/poll`, `/stats` commands
- **Weasyl** platform support (full stack)
  - API key authentication
  - Gallery and submission stats via Weasyl REST API
  - Dashboard, submissions, detail, compare, settings
- **FurAffinity** platform support (full stack)
  - Cookie-based authentication (cookie_a, cookie_b)
  - Scraping via FAExport proxy API
  - Dashboard, submissions, detail, compare, settings
- **Cross-platform overview page** — aggregated stats, merged top lists, per-platform cards and charts
- **Submission groups** — organise submissions from any platform into named groups
- **Cross-platform links** — link the same work across platforms for combined stats
- Watcher tracking for Inkbunny and FurAffinity

---

## [1.1.1] - 2026-03-06

### Added
- Version display and update check in sidebar footer
- "Check for Updates" button in Settings page

---

## [1.1.0] - 2026-03-06

### Added
- **Comprehensive Telegram notifications**
  - Poll summaries after each cycle
  - Milestone alerts (configurable thresholds for views, faves, comments)
  - New fave/comment/watcher alerts
  - Digest reports (daily/weekly)
  - Error notifications for failed polls
- Telegram bot token and chat ID configuration in Settings

---

## [1.0.0] - 2026-03-06

### Added
- Initial release
- **Inkbunny** platform support
  - Username/password API authentication
  - Submission discovery and stats polling (views, favorites, comments)
  - Individual fave user tracking
  - Comment scraping with reply threading
- SQLite database with WAL mode for concurrent access
- FastAPI web dashboard (SPA with hash routing)
  - Dashboard with stat cards, aggregate charts, top lists, growth rates
  - Submissions table with sorting, search, and rating filters
  - Submission detail with time-series charts and date range selection
  - Compare tool (2-5 submissions side by side)
  - Settings page with credential management and preferences
- Background polling with configurable intervals
- Windows system tray integration (pystray)
- Windows toast notifications (winotify)
- PyInstaller packaging for standalone `.exe` distribution
- CSV export for submissions and snapshots
- Run-on-startup via Windows registry
- Minimize-to-tray on close
