"""Generate the Open Graph / social share card (1200x630).

A clean, brand-forward card: the copper quill logo centered on the site's
dark ink background with a soft copper glow. The name is intentionally
omitted — the link embed's title already reads "PawPoller: ...", so the
card just carries the mark. Palette matches tailwind.config.mjs.

Run from site/:  python scripts/make_og_card.py
"""
from PIL import Image, ImageDraw, ImageFilter
from pathlib import Path

# --- brand palette (tailwind.config.mjs) -------------------------------------
INK_900 = (0x13, 0x11, 0x0e)   # body bg
INK_950 = (0x0a, 0x09, 0x07)   # deepest — corners
COPPER  = (0xd0, 0x81, 0x36)   # primary accent (glow)

W, H = 1200, 630
ROOT = Path(__file__).resolve().parent.parent          # site/
LOGO = ROOT / "public" / "logo-quill.png"
OUT  = ROOT / "public" / "og-card.png"

# --- base: ink-900 with a soft radial vignette toward ink-950 at the corners -
card = Image.new("RGB", (W, H), INK_900)

# vignette: radial dark falloff from centre to corners
vig = Image.new("L", (W, H), 0)
vd = ImageDraw.Draw(vig)
cx, cy = W / 2, H / 2
maxd = (cx**2 + cy**2) ** 0.5
# build a coarse radial by drawing concentric ellipses (fast enough at this size)
for i in range(60, 0, -1):
    t = i / 60
    r = maxd * t
    val = int(90 * t)          # up to ~90/255 darkening at the corners
    vd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=val)
vig = vig.filter(ImageFilter.GaussianBlur(60))
dark = Image.new("RGB", (W, H), INK_950)
card = Image.composite(dark, card, vig)

# --- copper glow behind the logo --------------------------------------------
glow = Image.new("L", (W, H), 0)
gd = ImageDraw.Draw(glow)
gr = 260
gd.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=150)
glow = glow.filter(ImageFilter.GaussianBlur(120))
copper_layer = Image.new("RGB", (W, H), COPPER)
card = Image.composite(copper_layer, card, glow)

# --- logo, centred ----------------------------------------------------------
logo = Image.open(LOGO).convert("RGBA")
target_h = 360
scale = target_h / logo.height
logo = logo.resize((round(logo.width * scale), target_h), Image.LANCZOS)
# nudge up a touch so it sits optically centred (quill weight is top-heavy)
lx = (W - logo.width) // 2
ly = (H - logo.height) // 2 - 6
card_rgba = card.convert("RGBA")
card_rgba.alpha_composite(logo, (lx, ly))

# --- thin copper keyline frame (subtle, inset) ------------------------------
draw = ImageDraw.Draw(card_rgba)
m = 28
draw.rectangle([m, m, W - m - 1, H - m - 1], outline=(*COPPER, 90), width=2)

card_rgba.convert("RGB").save(OUT, "PNG", optimize=True)
print(f"wrote {OUT}  ({OUT.stat().st_size // 1024} KB, {W}x{H})")
