"""Core-first tag ordering for the artwork catalogue.

Platforms only really use the first 20-25 tags of a submission (FurAffinity
hard-caps the whole tag string at 500 characters and REJECTS anything longer —
see posting/platforms/furaffinity.py::validate), so the tags that matter most
have to come first. This reorders each work's tag list into Rhys's core
priority:

    1 artist
    2 species & form          (anthro/feral, species, headcount, gender)
    3 character_(owner)
    4 mainstream kink         (bdsm, bondage, toys, clothing state)
    5 the act
    6 explicit anatomy        (genitalia, body fluids — cum, seed, cock, tits)
    7 niche kink + descriptive
    8 misc                    (setting, props, style, framing, meta)

It is a LOOKUP PLUS A STABLE SORT — every tag is classified by which section of
the bundled tag database it lives in, and ties keep their existing relative
order. No model is involved anywhere in this file, which is what makes it
safe to run unattended and legal to ship inside PawPoller (no AI, ever).

Usage:
    python scripts/reorder_tags.py --in tags.json [--out reordered.json]
    python scripts/reorder_tags.py --in tags.json --report

`tags.json` is a list of {"name", "title", "tags": {"default": [...]}} — the
shape posting.artwork_reader.list_artworks() produces.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TAG_DB_DIR = Path(__file__).resolve().parent.parent / "tag_database"

# Load order matters: the first file to define a tag wins. The curated files go
# before tag_database_image.txt because that one is a 12k-row e621 dump that
# would otherwise swallow species and anatomy tags into the generic bucket.
DB_FILES = [
    "tag_database_user.txt",
    "tag_database_physical.txt",
    "tag_database_acts.txt",
    "tag_database_kink.txt",
    "tag_database_meta.txt",
    "tag_database_image.txt",
]

ARTIST, SPECIES, CHARACTER, KINK_MAIN, ACT, ANATOMY, NICHE, MISC = range(1, 9)

TIER_NAMES = {
    ARTIST: "artist", SPECIES: "species/form", CHARACTER: "character",
    KINK_MAIN: "mainstream kink", ACT: "act", ANATOMY: "explicit anatomy",
    NICHE: "niche/descriptive", MISC: "misc",
}

# Section name (as it appears in the DB files) -> tier.
SECTION_TIER = {
    # 1 artist
    "ARTISTS": ARTIST,
    # 2 species & form
    "SPECIES & BODY TYPE": SPECIES,
    "BODY TYPES & FIGURES": SPECIES,
    "SPECIES": SPECIES,
    "SEX, GENDER & PAIRING": SPECIES,
    # 3 character
    "CHARACTERS & ACCOUNTS": CHARACTER,
    # 4 mainstream kink
    "BDSM, POWER & CONSENT": KINK_MAIN,
    "BONDAGE GEAR & RESTRAINTS": KINK_MAIN,
    "SEX TOYS & DEVICES": KINK_MAIN,
    "NUDITY & CLOTHING STATES": KINK_MAIN,
    # 5 the act
    "SEXUAL ACTS": ACT,
    "SEX POSITIONS": ACT,
    "GENDER & FORM PENETRATION": ACT,
    "WORSHIP ACTS": ACT,
    "TONGUEPLAY & LICKING": ACT,
    "KISSING & ORAL AFFECTION": ACT,
    # 6 explicit anatomy + fluids
    "GENITALIA (GENERAL)": ANATOMY,
    "GENITALIA (MALE)": ANATOMY,
    "GENITALIA (FEMALE)": ANATOMY,
    "ANATOMY & PHYSICAL FEATURES": ANATOMY,
    "TORSO, CHEST & LIMBS": ANATOMY,
    "BUTTOCKS & TAIL": ANATOMY,
    "NON-HUMANOID & FANTASY ANATOMY": ANATOMY,
    "INTERNAL & SKELETAL ANATOMY": ANATOMY,
    "BODY FLUIDS": ANATOMY,
    # 7 niche kink + descriptive
    "FETISH & KINK THEMES": NICHE,
    "TRANSFORMATION & SIZE": NICHE,
    "GENDER & FORM DYNAMICS": NICHE,
    "POSES & BODY LANGUAGE": NICHE,
    "ROMANCE & AFFECTION": NICHE,
    "GRAB & TOUCH ACTIONS": NICHE,
    "PHYSICAL ACTIONS": NICHE,
    "HAIR & HEAD FEATURES": NICHE,
    "EARS, MOUTH & FACIAL FEATURES": NICHE,
    "FUR, SCALE & FEATHER COLORS": NICHE,
    "EYE COLORS": NICHE,
    "FUR PATTERNS & MARKINGS": NICHE,
    "FUR & BODY TEXTURES": NICHE,
    "FACIAL EXPRESSIONS": NICHE,
    "EMOTIONAL THEMES & DYNAMICS": NICHE,
    "CHARACTER ROLES & ARCHETYPES": NICHE,
    "SOUNDS & PHYSICAL REACTIONS": NICHE,
    "ANATOMY & MARKINGS": NICHE,
    "ACTS & GESTURES": NICHE,
    "DESCRIPTIVE": NICHE,
    # 8 misc
    "SETTINGS & UNIVERSE": MISC,
    "STORY FORMAT & META": MISC,
    # Clothing and props (thong, corset, collar…) are describing the picture,
    # not filing it — they belong above style/framing/meta.
    "ACCESSORIES & OBJECTS": NICHE,
    "WEATHER & ATMOSPHERE": MISC,
    "SEASONAL & HOLIDAY": MISC,
    "MAGIC & SUPERNATURAL": MISC,
    "POSE & FRAMING": MISC,
    "STYLE & MEDIUM": MISC,
    "TEXT & PROPS": MISC,
    "COMMISSION & STATUS": MISC,
    "IMAGE TAGS (sorted by popularity, most common first)": MISC,
}

# The curated DB rows carry a THIRD field naming the tag's subtype
# (`felid | A felid character… | species:felid`). That is the most reliable
# signal available and is consulted BEFORE the section header — the big
# "E621 IMPORT" blocks have no usable section of their own, so without this
# `felid` and `pantherine` fell through to their file's fallback and got
# ordered as anatomy rather than species.
SUBTYPE_TIER = {
    "species": SPECIES, "body_type": SPECIES, "gender": SPECIES, "age": SPECIES,
    "act": ACT,
    "genitalia": ANATOMY, "anatomy": ANATOMY,
    "clothing": KINK_MAIN,          # nudity/clothing state reads as mainstream
    "coat": NICHE, "head": NICHE, "hair": NICHE, "eyes": NICHE,
    "meta": MISC,
    # `kink` deliberately absent: mainstream vs niche is decided by section.
}

# Per-file fallback, used only when neither subtype nor section resolves.
FILE_TIER = {
    "tag_database_physical.txt": NICHE,
    "tag_database_acts.txt": ACT,
    "tag_database_kink.txt": NICHE,
    "tag_database_meta.txt": MISC,
    "tag_database_image.txt": MISC,
    "tag_database_user.txt": MISC,
}

# Form + headcount words that belong with species regardless of where the DB
# happens to file them.
FORM_LITERALS = {
    "anthro", "feral", "human", "humanoid", "taur", "semi-anthro",
    "solo", "duo", "trio", "group", "male", "female", "intersex",
    "male/male", "male/female", "female/female", "gynomorph", "andromorph",
    "hermaphrodite",
}

# `name_(owner)` is the catalogue's character convention.
OC_RE = re.compile(r"^[a-z0-9_\-']+_\([a-z0-9_\-']+\)$")

# Import artifacts and scraper leftovers: never real tags, dropped rather than
# sorted. `default` is the dict key having leaked into the value list.
JUNK = {"default", "c_all", "t_all", "s_unspecified_any", "oc", "character", "art"}

# Two spellings of the same tag; keep one form so platforms don't see both.
ALIASES = {"close-up": "close_up", "fullbody": "full_body"}


def load_index() -> dict[str, tuple[str, str, str]]:
    """tag -> (file, section, subtype). First definition wins."""
    index: dict[str, tuple[str, str, str]] = {}
    for fn in DB_FILES:
        path = TAG_DB_DIR / fn
        if not path.exists():
            continue
        section = ""
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and set(stripped) == {"="}:
                nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if nxt and "|" not in nxt and set(nxt) != {"="}:
                    section = nxt
                continue
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                name = parts[0].lower()
                # `species:felid` -> `species`
                subtype = parts[2].split(":")[0].lower() if len(parts) >= 3 else ""
                if name and " " not in name:
                    index.setdefault(name, (fn, section, subtype))
    return index


def tier_of(tag: str, index) -> int:
    t = tag.lower().strip()
    if OC_RE.match(t):
        return CHARACTER
    if t in FORM_LITERALS:
        return SPECIES
    entry = index.get(t)
    if not entry:
        # Unknown to the database: park it mid-order rather than last, so a tag
        # the DB simply hasn't learned yet is never silently buried.
        return NICHE
    fn, section, subtype = entry
    # The user file's own sections are authoritative (artist / character).
    if section in ("ARTISTS", "CHARACTERS & ACCOUNTS"):
        return SECTION_TIER[section]
    # A `kink` subtype needs its section to decide mainstream vs niche.
    if subtype and subtype != "kink":
        tier = SUBTYPE_TIER.get(subtype)
        if tier:
            return tier
    if section in SECTION_TIER:
        return SECTION_TIER[section]
    return FILE_TIER.get(fn, NICHE)


# Tags a variant's LABEL implies, added on top of whatever it inherits. Purely
# a lookup on the label text — the label is user-authored metadata, not the
# image, so this stays deterministic.
VARIANT_LABEL_TAGS = {
    "sketch": ["sketch"],
    "rough": ["sketch"],
    "lined": ["line_art"],
    "clean": ["line_art"],
    "base": ["line_art"],
    "no bg": ["simple_background"],
    "nobg": ["simple_background"],
    "pfp": ["headshot", "icon"],
    "wip gif": ["animated", "wip"],
    "gif": ["animated"],
    "nude": ["nude"],
    "cum": ["cum"],
    "messy": ["messy"],
    "milk": ["lactating"],
}

# A variant labelled SFW must not inherit the parent's explicit set — these
# tiers are stripped rather than reordered.
#
# "Clean" is deliberately NOT here. In this catalogue it sits alongside Lined,
# Base, Sketch and Messy, so it means clean line art / no-cum, not
# safe-for-work — treating it as SFW stripped seven explicit tags off a piece
# that is still explicit.
SFW_LABELS = {"sfw", "censored"}
SFW_STRIPPED_TIERS = {KINK_MAIN, ACT, ANATOMY}


def variant_tag_proposal(parent_ordered, label, index):
    """(tags, note) for one variant, derived from its label.

    Inherits the parent's ordered list, strips what the label forbids, then
    adds what it implies.
    """
    low = (label or "").strip().lower()
    # Tokenise: a SUBSTRING test matches "sfw" inside "nsfw" and would strip the
    # explicit tags off the very variants that need them most.
    tokens = set(re.split(r"[^a-z0-9]+", low)) - {""}
    tags = list(parent_ordered)
    note = ""
    if tokens & SFW_LABELS:
        kept = [t for t in tags if tier_of(t, index) not in SFW_STRIPPED_TIERS]
        note = f"stripped {len(tags) - len(kept)} explicit tags (SFW variant)"
        tags = kept
    for key, extra in VARIANT_LABEL_TAGS.items():
        # Multi-word keys ("wip gif", "no bg") still need a substring test;
        # single words go through the token set so "gif" can't match "gifted".
        matched = (key in low) if " " in key else (key in tokens)
        if matched:
            for t in extra:
                if t not in tags:
                    tags.append(t)
    return tags, note


def split_core(ordered, index, core_max=25):
    """Split an already-ordered list into (core, auxiliary).

    Core is defined by TIER, not by a raw count: artist, species, character,
    mainstream kink, the act and explicit anatomy are core by definition;
    niche/descriptive and misc are the tail. A count cap is still applied
    because platforms with a tag budget only take so many — a work with 40
    act tags shouldn't push its whole budget into one tier.
    """
    core, aux = [], []
    for tag in ordered:
        if tier_of(tag, index) <= ANATOMY and len(core) < core_max:
            core.append(tag)
        else:
            aux.append(tag)
    return core, aux


def reorder(tags, index):
    """Return (ordered_tags, dropped_tags). Stable within a tier."""
    cleaned, dropped, seen = [], [], set()
    for t in tags:
        low = t.lower().strip()
        low = ALIASES.get(low, low)
        if not low or low in JUNK:
            dropped.append(t)
            continue
        if low in seen:
            dropped.append(t)
            continue
        seen.add(low)
        cleaned.append(low)
    ordered = [t for _, t in sorted(
        enumerate(cleaned), key=lambda it: (tier_of(it[1], index), it[0]))]
    return ordered, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--core-max", type=int, default=25,
                    help="cap on how many tags land in `core` (default 25)")
    args = ap.parse_args()

    index = load_index()
    works = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    result, changed, total_dropped = [], 0, 0

    for w in works:
        src = w.get("tags") or {}
        # Accept either shape: the new core/auxiliary split or the legacy flat
        # `default` list.
        tags = list(src.get("core") or []) + list(src.get("default") or []) \
            + list(src.get("auxiliary") or [])
        ordered, dropped = reorder(tags, index)
        core, aux = split_core(ordered, index, args.core_max)
        total_dropped += len(dropped)
        if ordered != [t.lower() for t in tags]:
            changed += 1

        # Variants: a render with its own label is its own content. Only emit a
        # tag set where the label actually implies a difference — otherwise the
        # variant inherits the parent and needs nothing stored.
        variants = []
        for v in (w.get("variants") or []):
            vtags, note = variant_tag_proposal(ordered, v.get("label", ""), index)
            if vtags == ordered:
                continue
            vcore, vaux = split_core(vtags, index, args.core_max)
            variants.append({
                "key": v.get("key", ""), "label": v.get("label", ""),
                "note": note, "tags_core": vcore, "tags_auxiliary": vaux,
            })

        result.append({**w, "tags_ordered": ordered, "tags_dropped": dropped,
                       "tags_core": core, "tags_auxiliary": aux,
                       "variant_tags": variants})

    if args.report:
        print(f"works: {len(works)}  reordered: {changed}  junk/dupes dropped: {total_dropped}")
        print()
        for r in result:
            if not r["tags_ordered"]:
                continue
            print(f"--- {r['title']}")
            print(f"    CORE ({len(r['tags_core'])}) {', '.join(r['tags_core'])}")
            print(f"    AUX  ({len(r['tags_auxiliary'])}) {', '.join(r['tags_auxiliary'])}")
            if r["tags_dropped"]:
                print(f"    DROPPED {', '.join(r['tags_dropped'])}")
            print(f"    core = {len(' '.join(r['tags_core']))} chars "
                  f"(FA rejects the whole submission over 500)")
            print()

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
