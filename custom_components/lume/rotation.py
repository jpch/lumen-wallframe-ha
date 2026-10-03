# -*- coding: utf-8 -*-
"""Shuffled-cycle order for the wall (a Python port of the Android app's Rotation.kt).

Every photo is shown once, in random order, before any photo repeats. A new cycle never
starts with a photo from the slide that ended the previous one. Two portraits share a
slide: when a portrait comes up, the next portrait still left in the cycle is pulled
forward to sit beside it.

Slides are planned ahead (peek) so the caller can download them before they are shown;
next() hands out the planned slides in order.

This file is shared, byte for byte, by the Raspberry Pi app (pi/rotation.py in
jpch/Lumen-wallframe) and the Home Assistant integration (custom_components/lume/rotation.py
in jpch/lumen-wallframe-ha). Keep the two copies identical. Python 3.6 compatible, no
dependencies, not thread-safe on its own (Library guards it with a lock).
"""
import random


class Rotation(object):
    def __init__(self, rng=None):
        self._random = rng if rng is not None else random.Random()
        self._ids = []
        self._portraits = set()
        self._queue = []
        self._planned = []
        self._last_built = []

    @property
    def size(self):
        return len(self._ids)

    def update(self, all_ids, portrait_ids):
        """Sets the album contents.

        Photos that left the album also leave the cycle and the plan. New photos join the
        current cycle at random places.
        """
        ordered = []
        seen = set()
        for uid in all_ids:
            if uid not in seen:
                seen.add(uid)
                ordered.append(uid)
        keep = seen
        old = set(self._ids)
        self._ids = ordered
        self._portraits = set(portrait_ids)
        if any(uid not in keep for slide in self._planned for uid in slide):
            back = [uid for slide in self._planned for uid in slide if uid in keep]
            self._planned = []
            self._queue = back + self._queue
        self._queue = [uid for uid in self._queue if uid in keep]
        for uid in ordered:
            if uid not in old:
                self._queue.insert(self._random.randrange(len(self._queue) + 1), uid)

    def peek(self, count):
        """The next `count` slides (lists of ids), without consuming them."""
        while len(self._planned) < count and self._ids:
            self._planned.append(self._build())
        return [list(slide) for slide in self._planned[:count]]

    def next(self):
        """The next slide (a list of one or two ids), or None when the album is empty."""
        if not self._planned:
            self.peek(1)
        if not self._planned:
            return None
        return list(self._planned.pop(0))

    def _build(self):
        if not self._queue:
            self._refill()
        first = self._queue.pop(0)
        slide = [first]
        if first in self._portraits:
            at = -1
            for i, uid in enumerate(self._queue):
                if uid in self._portraits and uid not in self._last_built:
                    at = i
                    break
            if at < 0:
                for i, uid in enumerate(self._queue):
                    if uid in self._portraits:
                        at = i
                        break
            if at >= 0:
                slide = [first, self._queue.pop(at)]
        self._last_built = slide
        return slide

    def _refill(self):
        avoid = set(self._last_built)
        cycle = [uid for uid in self._ids if uid not in avoid]
        self._random.shuffle(cycle)
        late = [uid for uid in self._ids if uid in avoid]
        self._random.shuffle(late)
        # Photos from the slide that closed the last cycle go somewhere after the first two.
        for uid in late:
            start = min(2, len(cycle))
            cycle.insert(start + self._random.randrange(len(cycle) - start + 1), uid)
        self._queue.extend(cycle)
