# -*- coding: utf-8 -*-
"""The info bands drawn over the photo on the wall (the Android app's OverlayStyle).

top and bottom are the share of the screen height each band covers, in percent: the top
band goes up to MAX_TOP, and the two together never cover more than 100. color is the band
colour ("#rrggbb") and opacity its opacity in percent. With fade on, each band keeps that
opacity over its outer part (where the clock, the weather and the controls sit) and then
fades out towards the middle of the screen.

This file is shared, byte for byte, by the Raspberry Pi app (pi/overlay.py in
jpch/Lumen-wallframe) and the Home Assistant integration (custom_components/lume/overlay.py
in jpch/lumen-wallframe-ha); wall.html mirrors content_color() in JavaScript.
Keep the copies identical. Python 3.6 compatible.
"""

MAX_TOP = 60
DEFAULT = {"top": 0, "bottom": 42, "color": "#000000", "opacity": 35, "fade": False}

# Band colours offered in the Customize dialog, with their i18n keys.
SWATCHES = (
    ("#000000", "color_black"),
    ("#ffffff", "color_white"),
    ("#0b1e3a", "color_blue"),
    ("#0f2a1c", "color_green"),
    ("#2e1f14", "color_brown"),
    ("#6b6b6b", "color_grey"),
)

WALL_LIGHT = "#f4f0e8"
WALL_DARK = "#141210"


def _clamp(value, low, high, default):
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _hex(value, default):
    text = str(value or "").strip().lower()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 8:
        text = text[2:]
    if len(text) != 6:
        return default
    try:
        int(text, 16)
    except ValueError:
        return default
    return "#" + text


def normalize(raw):
    """A complete, valid style from whatever was stored (missing keys take the defaults)."""
    raw = raw if isinstance(raw, dict) else {}
    top = _clamp(raw.get("top"), 0, MAX_TOP, DEFAULT["top"])
    bottom = _clamp(raw.get("bottom"), 0, 100 - top, min(DEFAULT["bottom"], 100 - top))
    fade = raw.get("fade", DEFAULT["fade"])
    if isinstance(fade, str):
        fade = fade.strip().lower() in ("1", "true", "yes", "on")
    return {
        "top": top,
        "bottom": bottom,
        "color": _hex(raw.get("color"), DEFAULT["color"]),
        "opacity": _clamp(raw.get("opacity"), 0, 100, DEFAULT["opacity"]),
        "fade": bool(fade),
    }


def with_top(style, top):
    """Changes the top band; the bottom band shrinks if the two would pass 100 %."""
    out = dict(normalize(style))
    out["top"] = _clamp(top, 0, MAX_TOP, out["top"])
    out["bottom"] = min(out["bottom"], 100 - out["top"])
    return out


def with_bottom(style, bottom):
    """Changes the bottom band; the top band shrinks if the two would pass 100 %."""
    out = dict(normalize(style))
    out["bottom"] = _clamp(bottom, 0, 100, out["bottom"])
    out["top"] = min(out["top"], 100 - out["bottom"])
    return out


def rgb(color):
    text = _hex(color, "#000000")[1:]
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def luminance(color):
    """Relative luminance (0-1) of an sRGB colour, as Compose's Color.luminance()."""

    def channel(value):
        c = value / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb(color)
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def content_color(style):
    """Text colour for the wall: dark on a strong light band, cream otherwise."""
    style = normalize(style)
    if luminance(style["color"]) > 0.5 and style["opacity"] >= 50:
        return WALL_DARK
    return WALL_LIGHT


def shadow_rgba(style):
    """The soft halo behind the wall text: light behind dark text, dark behind light text."""
    if content_color(style) == WALL_DARK:
        return (255, 255, 255, 153)
    return (0, 0, 0, 153)


def band_alpha(style, band, t):
    """Opacity (0-255) of a band at t (0 = top edge of the band, 1 = bottom edge).

    band is "top" or "bottom". Without fade the band is flat. With fade, the top band is
    solid over its upper 40 % and fades out downwards; the bottom band fades in over its
    upper 60 % and is solid below.
    """
    style = normalize(style)
    alpha = 255.0 * style["opacity"] / 100.0
    if not style["fade"]:
        return int(round(alpha))
    t = max(0.0, min(1.0, float(t)))
    if band == "top":
        factor = 1.0 if t <= 0.4 else 1.0 - (t - 0.4) / 0.6
    else:
        factor = t / 0.6 if t < 0.6 else 1.0
    return int(round(alpha * factor))
