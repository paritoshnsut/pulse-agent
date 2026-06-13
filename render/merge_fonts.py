"""
merge_fonts.py — build single-file fonts for the Satori render service.

WHY THIS EXISTS: fontsource ships fonts split into unicode-range subsets
(latin, latin-ext, …) meant for browsers, which assemble them via CSS
unicode-range. Satori does NOT do per-glyph fallback across multiple files
registered under the same family — only the first (family, weight) file wins,
so glyphs living in the -ext subset (₹ above all) rendered as tofu.

Fix: merge latin + latin-ext into ONE ttf per (family, weight) so each
family's full coverage is actually available, and additionally produce a
merged Noto Sans used as the end of every font stack (Lora and JetBrains Mono
simply don't contain ₹ at any subset — Noto carries it).

Run once after `npm install` when bumping font versions:
    python3 merge_fonts.py
The merged ttfs in fonts/ are committed, so the Docker build needs nothing.
"""

import tempfile
from pathlib import Path

from fontTools.merge import Merger
from fontTools.ttLib import TTFont

HERE = Path(__file__).parent
OUT = HERE / "fonts"

FAMILIES = {
    "inter": "Inter",
    "lora": "Lora",
    "jetbrains-mono": "JetBrainsMono",
    "noto-sans": "NotoSans",
    "playfair-display": "PlayfairDisplay",  # editorial display headline face
}


def woff_to_ttf(woff_path: Path, tmpdir: Path) -> Path:
    font = TTFont(woff_path)
    font.flavor = None
    out = tmpdir / (woff_path.stem + ".ttf")
    font.save(out)
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        for pkg, out_name in FAMILIES.items():
            files_dir = HERE / "node_modules" / "@fontsource" / pkg / "files"
            for weight in (400, 700):
                parts = [
                    woff_to_ttf(files_dir / f"{pkg}-latin-{weight}-normal.woff", tmpdir),
                    woff_to_ttf(files_dir / f"{pkg}-latin-ext-{weight}-normal.woff", tmpdir),
                ]
                merged = Merger().merge([str(p) for p in parts])
                dest = OUT / f"{out_name}-{weight}.ttf"
                merged.save(dest)
                cmap = merged.getBestCmap()
                print(f"{dest.name}: {len(cmap)} glyph mappings, "
                      f"rupee={'yes' if 0x20B9 in cmap else 'NO'}")


if __name__ == "__main__":
    main()
