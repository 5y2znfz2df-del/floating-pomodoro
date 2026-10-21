"""Generate assets/icon.ico for the packaged app.

    python tools/make_icon.py

Draws a simple tomato-with-clock-face mark at several sizes and packs them
into a multi-resolution .ico (16 / 32 / 48 / 64 / 128 / 256).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "icon.ico"

BG = (28, 28, 30, 255)
BODY = (255, 90, 78, 255)
BODY_DARK = (214, 62, 54, 255)
LEAF = (48, 209, 88, 255)
FACE = (255, 255, 255, 255)


def draw(size: int) -> Image.Image:
    # 4x supersampling keeps the curves smooth when downscaled
    s = size * 4
    image = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)

    # 圆角底板
    radius = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=BG)

    # 番茄身体
    pad = int(s * 0.17)
    body = [pad, pad + int(s * 0.06), s - pad, s - pad - int(s * 0.02)]
    d.ellipse(body, fill=BODY)
    # 底部一点暗色，做出体积感
    d.arc(
        [body[0] + int(s * 0.05), body[1] + int(s * 0.10), body[2] - int(s * 0.05), body[3]],
        start=20, end=160, fill=BODY_DARK, width=max(2, int(s * 0.03)),
    )

    # 叶子
    cx = s // 2
    top = body[1] + int(s * 0.01)
    d.polygon(
        [
            (cx, top - int(s * 0.09)),
            (cx + int(s * 0.07), top + int(s * 0.01)),
            (cx, top + int(s * 0.03)),
            (cx - int(s * 0.07), top + int(s * 0.01)),
        ],
        fill=LEAF,
    )

    # 表盘刻度环
    ring = [body[0] + int(s * 0.16), body[1] + int(s * 0.16),
            body[2] - int(s * 0.16), body[3] - int(s * 0.16)]
    d.ellipse(ring, outline=FACE, width=max(2, int(s * 0.022)))

    # 指针（指向 10 点方向多一点，像倒计时）
    ccx = (ring[0] + ring[2]) // 2
    ccy = (ring[1] + ring[3]) // 2
    hand = int(s * 0.16)
    d.line([ccx, ccy, ccx, ccy - hand], fill=FACE, width=max(2, int(s * 0.03)))
    d.line([ccx, ccy, ccx + int(hand * 0.7), ccy + int(hand * 0.35)],
           fill=FACE, width=max(2, int(s * 0.026)))
    r = max(2, int(s * 0.025))
    d.ellipse([ccx - r, ccy - r, ccx + r, ccy + r], fill=FACE)

    return image.resize((size, size), Image.LANCZOS)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    frames = [draw(sz) for sz in sizes]
    frames[-1].save(OUT, format="ICO", sizes=[(sz, sz) for sz in sizes])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, sizes={sizes})")

    preview = ROOT / "assets" / "icon-preview.png"
    frames[-1].save(preview, format="PNG")
    print(f"wrote {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
