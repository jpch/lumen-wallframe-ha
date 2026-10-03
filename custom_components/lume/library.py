# -*- coding: utf-8 -*-
"""The album as the wall sees it (a Python port of the Android app's Library.kt).

- the list of photos in the shared album, re-read every hour without downloading them;
- the photos already downloaded, kept in a local cache folder;
- the shuffled Rotation.

Photos are downloaded one at a time, just before they are needed: prefetch() downloads
the next planned slides, so a slide is on disk before it is shown. Every download is kept,
so the cache grows as the wall runs and keeps working offline. Photos that leave the album
are deleted from the cache when the list is replaced.

A photo is a dict: {"id", "name", "w", "h", "remote"}, plus an optional absolute "file"
for photos that live outside the cache folder (old picker downloads on the Pi). "remote"
is the Google URL; it is empty for photos that cannot be downloaded again.

This file is shared, byte for byte, by the Raspberry Pi app (pi/library.py in
jpch/Lumen-wallframe) and the Home Assistant integration (custom_components/lume/library.py
in jpch/lumen-wallframe-ha). Keep the two copies identical. Python 3.6 compatible.
Thread-safe: every method can be called from any thread; it does blocking disk and network
IO, so on Home Assistant call it from the executor.
"""
import json
import os
import threading
import time

try:
    from .rotation import Rotation
except (ImportError, SystemError, ValueError):
    from rotation import Rotation

LIST_NAME = "album.json"
MIN_BYTES = 800


def safe_name(uid):
    keep = "".join(ch for ch in (uid or "") if ch.isalnum())
    return (keep or "foto")[:80] + ".jpg"


def _int(value, default=1):
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


class Library(object):
    def __init__(self, data_dir, cache_dir, download, rng=None, log=None):
        """download(remote_url, dest_path) saves one photo or raises."""
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.list_path = os.path.join(data_dir, LIST_NAME)
        self._download = download
        self._log = log or (lambda msg: None)
        self._lock = threading.RLock()
        self._io = threading.Lock()
        self._rotation = Rotation(rng)
        self.photos = []
        self._by_id = {}
        self.source = ""
        self.checked = 0.0
        self.url = ""
        self._read()

    # -- list ------------------------------------------------------------------------

    def has_list(self):
        return os.path.isfile(self.list_path)

    def _read(self):
        if not os.path.isfile(self.list_path):
            return
        try:
            with open(self.list_path, "r") as fh:
                data = json.load(fh)
        except (OSError, IOError, ValueError) as exc:
            self._log("album list: %s" % exc)
            return
        self.source = data.get("source") or ""
        self.url = data.get("url") or ""
        try:
            self.checked = float(data.get("checked") or 0)
        except (TypeError, ValueError):
            self.checked = 0.0
        self._apply(data.get("items") or [])

    def _apply(self, items):
        photos = []
        seen = set()
        for item in items:
            uid = item.get("id")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            photo = {
                "id": uid,
                "name": item.get("name") or safe_name(uid),
                "w": _int(item.get("w")),
                "h": _int(item.get("h")),
                "remote": item.get("remote") or "",
            }
            if item.get("file"):
                photo["file"] = item["file"]
            photos.append(photo)
        with self._lock:
            self.photos = photos
            self._by_id = dict((p["id"], p) for p in photos)
            self._rotation.update([p["id"] for p in photos], [p["id"] for p in photos if p["h"] > p["w"]])

    def set_photos(self, items, source, url="", prune=True, checked=None):
        """Replaces the album list and saves it.

        items: dicts with id, w, h and remote (as album.list_album returns them), or name/file
        for photos that are already on disk. With prune, cached files of photos that are no
        longer in the list are deleted. checked is when the list was read from the album
        (now by default; 0 for a list that did not come from the album just now).
        """
        self._apply(items)
        with self._lock:
            self.source = source
            self.url = url or ""
            self.checked = time.time() if checked is None else float(checked)
            photos = [dict(p) for p in self.photos]
        self._write(photos)
        if prune:
            self._prune(photos)
        return len(photos)

    def clear(self):
        self._apply([])
        with self._lock:
            self.source = ""
            self.url = ""
            self.checked = 0.0
        try:
            os.remove(self.list_path)
        except OSError:
            pass

    def _write(self, photos):
        if not os.path.isdir(self.data_dir):
            os.makedirs(self.data_dir)
        tmp = self.list_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"source": self.source, "url": self.url, "checked": self.checked, "items": photos}, fh)
        os.rename(tmp, self.list_path)

    def _prune(self, photos):
        if not os.path.isdir(self.cache_dir):
            return
        keep = set()
        for photo in photos:
            keep.add(photo["name"])
            keep.add(photo["name"] + ".part")
        for name in os.listdir(self.cache_dir):
            if name in keep or not name.endswith((".jpg", ".part")):
                continue
            try:
                os.remove(os.path.join(self.cache_dir, name))
                self._log("pruned %s (no longer in the album)" % name)
            except OSError:
                pass

    def age(self):
        """Seconds since the list was last read from the album (large when never)."""
        return time.time() - (self.checked or 0)

    # -- cache -----------------------------------------------------------------------

    def path(self, photo):
        return photo.get("file") or os.path.join(self.cache_dir, photo["name"])

    def is_cached(self, photo):
        path = self.path(photo)
        try:
            return os.path.isfile(path) and os.path.getsize(path) >= MIN_BYTES
        except OSError:
            return False

    def counts(self):
        """(photos in the album, photos saved locally)."""
        with self._lock:
            photos = list(self.photos)
        return len(photos), sum(1 for p in photos if self.is_cached(p))

    def cached_photos(self):
        with self._lock:
            photos = list(self.photos)
        return [self._out(p) for p in photos if self.is_cached(p)]

    def first_cached(self):
        with self._lock:
            photos = list(self.photos)
        for photo in photos:
            if self.is_cached(photo):
                return self._out(photo)
        return None

    def _out(self, photo):
        out = dict(photo)
        out["file"] = self.path(photo)
        return out

    def _ensure(self, photo):
        if self.is_cached(photo):
            return False
        if not photo.get("remote"):
            return False
        with self._io:
            if self.is_cached(photo):
                return False
            if not os.path.isdir(self.cache_dir):
                os.makedirs(self.cache_dir)
            try:
                self._download(photo["remote"], self.path(photo))
            except Exception as exc:
                self._log("download %s failed: %s" % (photo["id"][:14], exc))
                return False
        self._log("downloaded %s" % photo["id"][:14])
        return True

    # -- rotation --------------------------------------------------------------------

    def prefetch(self, count=2):
        """Downloads the next `count` planned slides. Returns how many photos it downloaded."""
        with self._lock:
            ahead = [[self._by_id[uid] for uid in slide if uid in self._by_id] for slide in self._rotation.peek(count)]
        done = 0
        for slide in ahead:
            for photo in slide:
                if self._ensure(photo):
                    done += 1
        return done

    def upcoming(self, count=1):
        """The next planned slides, cached photos only (for preloading)."""
        with self._lock:
            ahead = [[self._by_id[uid] for uid in slide if uid in self._by_id] for slide in self._rotation.peek(count)]
        out = []
        for slide in ahead:
            ready = [self._out(p) for p in slide if self.is_cached(p)]
            if ready:
                out.append(ready)
        return out

    def next(self):
        """The next slide to show (photo dicts with "file"), or None if no photo is cached.

        Slides whose photos are not on disk yet (download failed, offline) are skipped, so the
        wall falls back to cached photos. A pair with one photo missing shows the other alone.
        """
        with self._lock:
            if not any(self.is_cached(p) for p in self.photos):
                return None
            # Two full cycles at most: every cycle holds every photo, so a cached one turns up.
            for _ in range(2 * len(self.photos) + 1):
                planned = self._rotation.next()
                if planned is None:
                    return None
                slide = [self._by_id[uid] for uid in planned if uid in self._by_id]
                ready = [self._out(p) for p in slide if self.is_cached(p)]
                if len(ready) < len(slide):
                    self._log("skip %s: not saved yet" % ", ".join(p["id"][:14] for p in slide if not self.is_cached(p)))
                if ready:
                    return ready
        return None
