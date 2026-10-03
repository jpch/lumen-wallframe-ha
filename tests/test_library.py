# -*- coding: utf-8 -*-
"""Tests for library.py and overlay.py. Shared by the Pi app and the Home Assistant integration."""
import json
import os
import random
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for _dir in (HERE, os.path.join(HERE, "..", "custom_components", "lume")):
    if os.path.isfile(os.path.join(_dir, "library.py")) and _dir not in sys.path:
        sys.path.insert(0, _dir)

import overlay  # noqa: E402
from library import Library, safe_name  # noqa: E402

JPEG = b"\xff\xd8\xff" + b"\0" * 2000


def remote(uid, w=400, h=300):
    return {"id": uid, "remote": "https://lh3.googleusercontent.com/pw/" + uid, "w": w, "h": h}


class FakeNet(object):
    def __init__(self):
        self.calls = []
        self.offline = False

    def __call__(self, url, dest):
        self.calls.append(url.rsplit("/", 1)[-1])
        if self.offline:
            raise IOError("offline")
        with open(dest, "wb") as fh:
            fh.write(JPEG)


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.cache = os.path.join(self.root, "cache")
        self.net = FakeNet()

    def tearDown(self):
        shutil.rmtree(self.root)

    def make(self, seed=1):
        return Library(self.root, self.cache, self.net, rng=random.Random(seed))

    def test_reading_the_list_downloads_nothing(self):
        lib = self.make()
        lib.set_photos([remote("AF1a"), remote("AF1b"), remote("AF1c")], "album", "https://photos.app.goo.gl/x")
        self.assertEqual([], self.net.calls)
        self.assertEqual((3, 0), lib.counts())
        self.assertIsNone(lib.next())

    def test_prefetch_downloads_only_the_next_slides(self):
        lib = self.make()
        lib.set_photos([remote("AF1%d" % i) for i in range(10)], "album")
        planned = lib._rotation.peek(2)
        self.assertEqual(2, lib.prefetch(2))
        self.assertEqual(sorted(s[0] for s in planned), sorted(self.net.calls))
        self.assertEqual((10, 2), lib.counts())
        shown = lib.next()
        self.assertEqual(planned[0], [p["id"] for p in shown])
        self.assertTrue(os.path.isfile(shown[0]["file"]))
        self.assertEqual([planned[1]], [[p["id"] for p in s] for s in lib.upcoming(1)])

    def test_cache_grows_and_a_full_cycle_shows_everything(self):
        lib = self.make(4)
        ids = ["AF1%d" % i for i in range(7)]
        lib.set_photos([remote(i) for i in ids], "album")
        shown = []
        for _ in range(7):
            lib.prefetch(2)
            shown.append(lib.next()[0]["id"])
        self.assertEqual(sorted(ids), sorted(shown))
        self.assertEqual((7, 7), lib.counts())
        self.assertEqual(len(set(self.net.calls)), len(self.net.calls))

    def test_offline_falls_back_to_cached_photos(self):
        lib = self.make(2)
        ids = ["AF1%d" % i for i in range(6)]
        lib.set_photos([remote(i) for i in ids], "album")
        lib.prefetch(2)
        cached = set(p["id"] for p in lib.cached_photos())
        self.net.offline = True
        for _ in range(12):
            lib.prefetch(2)
            slide = lib.next()
            self.assertIsNotNone(slide)
            self.assertIn(slide[0]["id"], cached)

    def test_pair_with_one_photo_missing_shows_the_other(self):
        lib = self.make(3)
        lib.set_photos([remote("AF1p", 300, 400), remote("AF1q", 300, 400)], "album")
        planned = lib._rotation.peek(1)[0]
        self.assertEqual(2, len(planned))
        os.makedirs(self.cache)
        with open(os.path.join(self.cache, safe_name(planned[0])), "wb") as fh:
            fh.write(JPEG)
        slide = lib.next()
        self.assertEqual([planned[0]], [p["id"] for p in slide])

    def test_list_survives_a_restart(self):
        lib = self.make()
        lib.set_photos([remote("AF1a", 300, 400), remote("AF1b")], "album", "https://photos.app.goo.gl/x")
        again = self.make()
        self.assertEqual(["AF1a", "AF1b"], [p["id"] for p in again.photos])
        self.assertEqual("album", again.source)
        self.assertEqual("https://photos.app.goo.gl/x", again.url)
        self.assertLess(again.age(), 60)
        with open(again.list_path) as fh:
            self.assertEqual(2, len(json.load(fh)["items"]))

    def test_prune_removes_photos_that_left_the_album(self):
        lib = self.make()
        lib.set_photos([remote("AF1a"), remote("AF1b")], "album")
        lib.prefetch(2)
        self.assertEqual((2, 2), lib.counts())
        with open(os.path.join(self.cache, "notes.txt"), "w") as fh:
            fh.write("keep me")
        lib.set_photos([remote("AF1b")], "album")
        self.assertEqual(sorted(["AF1b.jpg", "notes.txt"]), sorted(os.listdir(self.cache)))
        self.assertEqual((1, 1), lib.counts())

    def test_photos_without_remote_and_external_files(self):
        outside = os.path.join(self.root, "old.jpg")
        with open(outside, "wb") as fh:
            fh.write(JPEG)
        lib = self.make()
        lib.set_photos([{"id": "old", "file": outside, "w": 4, "h": 3}, {"id": "gone", "w": 4, "h": 3}], "google", prune=False)
        self.assertEqual((2, 1), lib.counts())
        self.assertEqual(0, lib.prefetch(2))
        for _ in range(4):
            self.assertEqual(outside, lib.next()[0]["file"])
        self.assertEqual([], self.net.calls)

    def test_clear(self):
        lib = self.make()
        lib.set_photos([remote("AF1a")], "album")
        lib.clear()
        self.assertFalse(lib.has_list())
        self.assertEqual((0, 0), lib.counts())
        self.assertIsNone(lib.next())

    def test_safe_name_matches_the_old_cache_names(self):
        self.assertEqual("AF1QipAbC.jpg", safe_name("AF1Qip-Ab_C"))
        self.assertEqual("foto.jpg", safe_name(""))
        self.assertEqual(84, len(safe_name("a" * 200)))


class OverlayTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual({"top": 0, "bottom": 42, "color": "#000000", "opacity": 35, "fade": False}, overlay.normalize(None))
        self.assertEqual(overlay.DEFAULT, overlay.normalize({}))

    def test_limits(self):
        style = overlay.normalize({"top": 90, "bottom": 80, "opacity": 140, "color": "nope"})
        self.assertEqual(60, style["top"])
        self.assertEqual(40, style["bottom"])
        self.assertEqual(100, style["opacity"])
        self.assertEqual("#000000", style["color"])
        self.assertEqual("#ffffff", overlay.normalize({"color": "#FFFFFFFF"})["color"])
        self.assertEqual(100, overlay.normalize({"top": 0, "bottom": 100})["bottom"])

    def test_bands_never_pass_100(self):
        style = overlay.with_bottom({"top": 50, "bottom": 10}, 80)
        self.assertEqual((20, 80), (style["top"], style["bottom"]))
        style = overlay.with_top({"top": 0, "bottom": 70}, 45)
        self.assertEqual((45, 55), (style["top"], style["bottom"]))

    def test_text_colour(self):
        self.assertEqual(overlay.WALL_DARK, overlay.content_color({"color": "#ffffff", "opacity": 50}))
        self.assertEqual(overlay.WALL_LIGHT, overlay.content_color({"color": "#ffffff", "opacity": 49}))
        self.assertEqual(overlay.WALL_LIGHT, overlay.content_color({"color": "#6b6b6b", "opacity": 100}))
        self.assertEqual(overlay.WALL_LIGHT, overlay.content_color({"color": "#000000", "opacity": 100}))
        self.assertEqual((255, 255, 255, 153), overlay.shadow_rgba({"color": "#ffffff", "opacity": 90}))
        self.assertEqual((0, 0, 0, 153), overlay.shadow_rgba(overlay.DEFAULT))

    def test_fade(self):
        flat = {"opacity": 100, "fade": False}
        self.assertEqual(255, overlay.band_alpha(flat, "top", 0.9))
        faded = {"opacity": 100, "fade": True}
        self.assertEqual(255, overlay.band_alpha(faded, "top", 0.2))
        self.assertEqual(0, overlay.band_alpha(faded, "top", 1.0))
        self.assertEqual(0, overlay.band_alpha(faded, "bottom", 0.0))
        self.assertEqual(255, overlay.band_alpha(faded, "bottom", 0.8))
        self.assertEqual(6, len(overlay.SWATCHES))


if __name__ == "__main__":
    unittest.main()
