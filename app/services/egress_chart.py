"""The digest chart: one bar per daily egress window against the budget, as a PNG.

Pillow is imported inside `render`, so no other route pays the import.
"""

import io
import math

W, H = 800, 300  # twice a 400 x 150 embed image, sharp on high-density screens
LEFT, RIGHT, TOP, BOTTOM = 72, 16, 64, 44
SURFACE, GRID, INK, MUTED = "#1e1f22", "#3a3c42", "#dbdee1", "#9aa0a8"
BAR, OVER = "#7FB0DA", "#DE6E52"
RADIUS = 8  # the rounded data end, 4 px at 1x
MAX_POINTS = 14
TICKS = 4  # about this many gridline steps up to the tallest value


def nice(raw: float) -> float:
    """The smallest 1, 2 or 5 times a power of ten at or above `raw`."""
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 5, 10) if m * power >= raw)


def render(points: list[tuple[str, float]], budget: float) -> bytes:
    """A PNG of the last 14 (label, MB a day) points, oldest first, with a dashed budget line."""
    from PIL import Image, ImageDraw, ImageFont  # lazy: only the digest pays the import

    points = points[-MAX_POINTS:]
    image = Image.new("RGB", (W, H), SURFACE)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    highest = max([v for _, v in points] + [budget, 1.0])
    step_v = nice(highest / TICKS)
    top = math.ceil(highest / step_v) * step_v
    plot = H - TOP - BOTTOM

    def y(v: float) -> float:
        return TOP + plot * (1 - v / top)

    for k in range(round(top / step_v) + 1):
        v = k * step_v
        draw.line([(LEFT, y(v)), (W - RIGHT, y(v))], fill=GRID, width=2)
        draw.text((LEFT - 10, y(v)), f"{v:,.0f}", fill=MUTED, font=font, anchor="rm")
    step = (W - LEFT - RIGHT) / max(len(points), 1)
    bar = step * 0.62
    widest = max(draw.textlength(label, font=font) for label, _ in points)
    # Crowded dates show every n-th one, ending on the last
    every = math.ceil((widest + 8) / step)
    for i, (label, v) in enumerate(points):
        x = LEFT + i * step + (step - bar) / 2
        if y(0) - y(v) >= 1:
            draw.rounded_rectangle(
                [(x, y(v)), (x + bar, y(0))],
                radius=min(RADIUS, (y(0) - y(v)) / 2, bar / 2),
                fill=OVER if v > budget else BAR,
                corners=(True, True, False, False),
            )
        middle = x + bar / 2
        draw.text((middle, y(v) - 6), f"{v:,.0f}", fill=INK, font=font, anchor="md")
        if (len(points) - 1 - i) % every == 0:
            draw.text((middle, H - 12), label, fill=MUTED, font=font, anchor="md")
    line = y(budget)
    for x0 in range(LEFT, W - RIGHT, 14):
        draw.line([(x0, line), (min(x0 + 8, W - RIGHT), line)], fill=INK, width=2)
    # The legend names the dashed line above the plot, clear of the bar labels
    legend = f"budget {budget:,.0f}"
    at = W - RIGHT - draw.textlength(legend, font=font)
    draw.line([(at - 44, 20), (at - 34, 20)], fill=INK, width=2)
    draw.line([(at - 24, 20), (at - 14, 20)], fill=INK, width=2)
    draw.text((W - RIGHT, 20), legend, fill=INK, font=font, anchor="rm")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()
