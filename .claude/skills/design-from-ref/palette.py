"""Exact dominant colors from a reference image, ranked by area.

Usage: python3 palette.py <image> [count]
Needs Pillow (pip install pillow).
"""
import sys
from collections import Counter

from PIL import Image


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 palette.py <image> [count]")
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    img = Image.open(sys.argv[1]).convert("RGB")
    width, height = img.size
    img.thumbnail((400, 400))
    quantized = img.quantize(colors=count * 2, method=Image.Quantize.MEDIANCUT)
    palette = quantized.getpalette()
    counts = sorted(quantized.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)

    print(f"image {width}x{height}px")
    print("share   hex      saturation  note")
    shown = 0
    for n, idx in counts:
        r, g, b = palette[idx * 3: idx * 3 + 3]
        hi, lo = max(r, g, b), min(r, g, b)
        sat = 0 if hi == 0 else (hi - lo) / hi
        lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        note = "saturated: accent candidate" if sat > 0.45 and 0.15 < lum < 0.85 else ""
        if shown == 0:
            note = "largest area: background candidate"
        print(f"{n / total:5.1%}   #{r:02X}{g:02X}{b:02X}  {sat:5.2f}       {note}")
        shown += 1
        if shown >= count:
            break

    # Accents are usually small (a button, a link), so the area ranking above
    # blurs them. Count exact saturated pixels instead: solid fills win.
    full = Image.open(sys.argv[1]).convert("RGB")
    full.thumbnail((1200, 1200))
    exact = Counter()
    pixels = getattr(full, "get_flattened_data", full.getdata)()
    for r, g, b in pixels:
        hi, lo = max(r, g, b), min(r, g, b)
        lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
        if hi and (hi - lo) / hi > 0.4 and 0.12 < lum < 0.9:
            exact[(r, g, b)] += 1
    if exact:
        print("\nexact saturated colors (accent candidates):")
        for (r, g, b), n in exact.most_common(5):
            print(f"  #{r:02X}{g:02X}{b:02X}  {n} px")


if __name__ == "__main__":
    main()
