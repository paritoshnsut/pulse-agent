"""
cards.py — the Pillow image card generator (CLAUDE.md: dark background,
headline text, account branding, always an AI label, no scraped images).

A 1200x675 (16:9, X-native) branded card for a post: accent bar, the post text
large, the handle, and a footer with the date and the AI label (rule #10 — the
label is baked into the pixels, so it survives even if the caption is edited).

The card is generated at APPROVAL time and attached to the Telegram package;
in the manual posting flow you download it and attach it in X's compose window
yourself, like everything else.

All drawing is deterministic; there is no model anywhere near this module.
Emoji are stripped before rendering (system TTFs can't draw them and Pillow
would emit tofu boxes). Fonts: tries common macOS/Linux TTFs, falls back to
Pillow's built-in bitmap font so the module never hard-fails over typography.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import settings

logger = logging.getLogger("cards")

W, H = 1200, 675
MARGIN = 90
ACCENT = (77, 163, 255)        # the brand blue bar + handle
BG = (17, 20, 24)              # near-black
FG = (240, 242, 245)           # post text
MUTED = (140, 148, 158)        # footer

EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF]"
)

FONT_PATHS = (
    "/System/Library/Fonts/Helvetica.ttc",            # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",   # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",         # Fedora
)


def _load_font(size: int):
    from PIL import ImageFont

    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def body_font_size(text: str) -> int:
    """Longer posts get smaller type so they still fit the canvas."""
    n = len(text)
    if n <= 120:
        return 56
    if n <= 220:
        return 46
    return 38


def wrap_to_width(draw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap measured in pixels (not characters), so it holds for
    any font. Overlong single words are hard-broken rather than overflowing."""
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            cand = f"{cur} {word}".strip()
            if draw.textlength(cand, font=font) <= max_width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            while draw.textlength(word, font=font) > max_width and len(word) > 1:
                cut = max(1, int(len(word) * max_width / draw.textlength(word, font=font)))
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        lines.append(cur)
    return lines


def render_card(text: str, handle: str = "", out_path: Optional[str] = None) -> str:
    """Render the card PNG and return its path.

    text: the post body (the card strips emoji and trims very long content).
    handle: account handle shown as branding (e.g. "@markets_take").
    """
    from PIL import Image, ImageDraw

    text = EMOJI.sub("", text).strip()
    if len(text) > 420:  # threads / long bodies: card carries the hook, not all of it
        text = text[:419].rsplit(" ", 1)[0] + "…"

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 14, H], fill=ACCENT)  # accent bar

    font_body = _load_font(body_font_size(text))
    font_handle = _load_font(30)
    font_footer = _load_font(24)

    max_text_width = W - 2 * MARGIN
    lines = wrap_to_width(draw, text, font_body, max_text_width)
    line_h = int(font_body.size * 1.35) if hasattr(font_body, "size") else 20
    block_h = line_h * len(lines)

    y = max(MARGIN + 50, (H - block_h) // 2 - 20)
    for line in lines:
        draw.text((MARGIN, y), line, font=font_body, fill=FG)
        y += line_h

    if handle:
        h = handle if handle.startswith("@") else f"@{handle}"
        draw.text((MARGIN, 52), h, font=font_handle, fill=ACCENT)

    footer = datetime.now(timezone.utc).strftime("%d %b %Y")
    label = EMOJI.sub("", settings.ai_label).strip()
    if label:
        footer += f"  ·  {label}"
    draw.text((MARGIN, H - 64), footer, font=font_footer, fill=MUTED)

    out_dir = Path(settings.cards_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = Path(out_path) if out_path else out_dir / f"card-{stamp}.png"
    img.save(path, "PNG")
    logger.info("Card rendered: %s", path)
    return str(path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    p = render_card(
        "RBI holds rates again. 'Inflation under control' — tell that to your "
        "grocery bill. let that sink in",
        handle="markets_take",
    )
    print(p)
