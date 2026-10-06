# -*- coding: utf-8 -*-
"""Tests for runtime.py (the integration's state), without Home Assistant installed."""
import json
import os
import random
import shutil
import sys
import tempfile
import types
import unittest
import importlib

PKG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "custom_components", "lume")
# Load the integration's modules as a package without running its __init__.py (which needs
# Home Assistant).
_pkg = types.ModuleType("lume_under_test")
_pkg.__path__ = [PKG_DIR]
sys.modules.setdefault("lume_under_test", _pkg)
runtime_mod = importlib.import_module("lume_under_test.runtime")
album_mod = importlib.import_module("lume_under_test.album")

JPEG = b"\xff\xd8\xff" + b"\0" * 2000


class Config(object):
    def __init__(self, root):
        self.root = root

    def path(self, *parts):
        return os.path.join(self.root, *parts)


class Hass(object):
    def __init__(self, root):
        self.config = Config(root)


class Entry(object):
    def __init__(self, data):
        self.data = data


def remote(uid, w=400, h=300):
    return {"id": uid, "remote": "https://lh3.googleusercontent.com/pw/" + uid, "w": w, "h": h}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.downloads = []
        self.album = [remote("AF1%d" % i) for i in range(6)]
        self._list = album_mod.list_album
        self._download = runtime_mod._download

        def fake_list(url):
            album_mod.validate_share_url(url)
            return list(self.album)

        def fake_download(url, dest):
            self.downloads.append(url.rsplit("/", 1)[-1])
            with open(dest, "wb") as fh:
                fh.write(JPEG)

        album_mod.list_album = fake_list
        runtime_mod._download = fake_download

    def tearDown(self):
        album_mod.list_album = self._list
        runtime_mod._download = self._download
        shutil.rmtree(self.root)

    def make(self, data=None):
        rt = runtime_mod.Runtime(Hass(self.root), Entry(data or {"interval_s": 60}))
        rt.load()
        rt.library._rotation._random = random.Random(1)
        # The library was built with the real downloader; point it at the fake one.
        rt.library._download = runtime_mod._download
        return rt

    def test_old_entry_data_still_works(self):
        rt = self.make({"interval_s": 30, "client_id": "", "client_secret": "", "temp_entity": ""})
        state = rt.public_state(None)
        self.assertEqual(30, state["interval_s"])
        self.assertEqual("pt", state["lang"])
        self.assertEqual({"top": 0, "bottom": 42, "color": "#000000", "opacity": 35, "fade": False}, state["overlay"])
        self.assertEqual(0, state["total"])
        self.assertEqual([], rt.slide_state()["slide"])

    def test_album_refresh_reads_the_list_only(self):
        rt = self.make()
        counts = rt.refresh_album("https://photos.app.goo.gl/abc")
        self.assertEqual({"total": 6, "cached": 0}, counts)
        self.assertEqual([], self.downloads)
        self.assertEqual("https://photos.app.goo.gl/abc", rt.mem["album_url"])
        rt.prefetch()
        self.assertEqual(2, len(self.downloads))

    def test_hourly_check_without_link_or_with_picked_photos(self):
        rt = self.make()
        self.assertIsNone(rt.refresh_album(None, hourly=True))
        rt.library.set_photos([{"id": "picked", "w": 3, "h": 2}], "google")
        rt.mem["album_url"] = "https://photos.app.goo.gl/abc"
        self.assertIsNone(rt.refresh_album(None, hourly=True))
        with self.assertRaises(album_mod.AlbumError) as caught:
            rt.refresh_album("https://photos.google.com/u/0/photos")
        self.assertEqual("not_shared", caught.exception.key)

    def test_slide_moves_on_with_the_pace_and_is_shared(self):
        rt = self.make({"interval_s": 15})
        rt.refresh_album("https://photos.app.goo.gl/abc")
        self.assertEqual([], rt.slide_state(1000.0)["slide"])
        rt.prefetch()
        first = rt.slide_state(1000.0)
        self.assertEqual(1, len(first["slide"]))
        self.assertTrue(first["slide"][0]["url"].startswith("/api/lume/media/AF1"))
        self.assertEqual(15000, first["remaining_ms"])
        again = rt.slide_state(1010.0)
        self.assertEqual(first["seq"], again["seq"])
        self.assertEqual(first["slide"], again["slide"])
        rt.prefetch()
        later = rt.slide_state(1016.0)
        self.assertEqual(first["seq"] + 1, later["seq"])
        self.assertNotEqual(first["slide"], later["slide"])

    def test_full_cycle_without_repeats(self):
        rt = self.make({"interval_s": 15})
        rt.refresh_album("https://photos.app.goo.gl/abc")
        seen = []
        now = 1000.0
        for _ in range(6):
            rt.prefetch()
            seen.append(rt.slide_state(now)["slide"][0]["id"])
            now += 16
        self.assertEqual(sorted(p["id"] for p in self.album), sorted(seen))

    def test_offline_keeps_the_current_slide(self):
        rt = self.make({"interval_s": 15})
        rt.refresh_album("https://photos.app.goo.gl/abc")
        rt.prefetch()
        first = rt.slide_state(1000.0)

        def offline(url, dest):
            raise IOError("offline")

        rt.library._download = offline
        rt.prefetch()
        cached = set(p["id"] for p in rt.library.cached_photos())
        state = rt.slide_state(1020.0)
        self.assertTrue(set(p["id"] for p in state["slide"]) <= cached)
        self.assertTrue(state["slide"])
        self.assertTrue(first["slide"])

    def test_interval_change_shortens_the_current_slide(self):
        rt = self.make({"interval_s": 3600})
        rt.refresh_album("https://photos.app.goo.gl/abc")
        rt.prefetch()
        rt.slide_state()
        rt.set_interval(15)
        self.assertLessEqual(rt.slide_state()["remaining_ms"], 15000)
        self.assertEqual(15, rt.public_state(None)["interval_s"])

    def test_settings_are_normalised_and_bump_the_revision(self):
        rt = self.make()
        rev = rt.rev
        style = rt.set_overlay({"top": 80, "bottom": 70, "color": "#FFFFFF", "opacity": 75, "fade": True})
        self.assertEqual({"top": 60, "bottom": 40, "color": "#ffffff", "opacity": 75, "fade": True}, style)
        rt.set_lang("en")
        rt.set_lang("xx")
        self.assertEqual("pt", rt.public_state(None)["lang"])
        self.assertGreater(rt.rev, rev)
        json.dumps(rt.mem)

    def test_wall_info_defaults_and_place(self):
        rt = self.make()
        info = rt.wall_info()
        self.assertTrue(info["show_clock"])
        self.assertTrue(info["show_weather"])
        self.assertEqual("Coimbra", info["place"]["name"])
        rev = rt.rev
        out = rt.set_wall_info(
            {
                "show_clock": False,
                "show_weather": True,
                "place": {"name": "Lisboa", "region": "Portugal", "lat": 38.7223, "lon": -9.1393},
            }
        )
        self.assertFalse(out["show_clock"])
        self.assertEqual("Lisboa", out["place"]["name"])
        self.assertIn("Portugal", out["place_label"])
        state = rt.public_state(21.5)
        self.assertFalse(state["show_clock"])
        self.assertEqual("Lisboa", state["place"]["name"])
        self.assertEqual("Lisboa", state["weather"]["place"])
        self.assertGreater(rt.rev, rev)
        # Old entries without the keys keep the previous behaviour.
        rt2 = self.make({"interval_s": 60})
        self.assertTrue(rt2.public_state(None)["show_clock"])

    def test_old_manifest_is_taken_over(self):
        cache = os.path.join(self.root, "lume", "cache")
        os.makedirs(cache)
        with open(os.path.join(cache, "AF1old.jpg"), "wb") as fh:
            fh.write(JPEG)
        with open(os.path.join(self.root, "lume", "manifest.json"), "w") as fh:
            json.dump({"items": [{"id": "AF1old", "name": "AF1old.jpg", "w": 4, "h": 3}, {"id": "gone", "name": "gone.jpg"}]}, fh)
        rt = self.make({"album_url": "https://photos.app.goo.gl/abc"})
        self.assertEqual((1, 1), rt.library.counts())
        self.assertEqual("album", rt.library.source)
        self.assertGreater(rt.library.age(), 3600)
        self.assertEqual("AF1old", rt.slide_state()["slide"][0]["id"])
        # The next album check keeps the cached file when the photo is still in the album.
        self.album = [remote("AF1old", 4, 3)] + self.album
        rt.refresh_album(None, hourly=True)
        self.assertEqual((7, 1), rt.library.counts())


if __name__ == "__main__":
    unittest.main()
