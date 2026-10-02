# -*- coding: utf-8 -*-
"""Groups photos: two side by side only when both are portrait."""


def is_portrait(item):
    return int(item["h"]) > int(item["w"])


def build_slides(items):
    slides = []
    pending = None
    for item in items:
        if is_portrait(item):
            if pending is not None:
                slides.append([pending, item])
                pending = None
            else:
                pending = item
        else:
            if pending is not None:
                slides.append([pending])
                pending = None
            slides.append([item])
    if pending is not None:
        slides.append([pending])
    return slides
