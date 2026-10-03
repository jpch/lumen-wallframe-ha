# -*- coding: utf-8 -*-
"""Lumen-wallframe state inside Home Assistant.

Everything here does blocking disk or network IO: call it from the executor
(hass.async_add_executor_job), never from the event loop.

The album: the list of photos in the shared album is re-read at start-up, every hour and
when "Fetch album" is pressed, without downloading the photos (library.py). The wall goes
through it in a shuffled cycle (rotation.py), driven from here so that every screen showing
the wall shows the same slide: slide_state() hands out the current slide, moves on when its
time is up, and the caller then prefetches the next slides in the background. Each photo is
downloaded just before it shows and kept in /config/lume/cache.
"""
import json
import os
import threading
import time

from . import album
from . import google_photos
from . import overlay
from . import weather
from .library import Library, safe_name
from .slides import build_slides

VERSION = "1.2.0"
PHOTO_EDGE = 1920
ALBUM_CHECK_S = 60 * 60
PACES = (15, 30, 60, 300, 900, 3600)


class LumeError(Exception):
    """A problem to show on the wall. key picks the translated text in wall.html ("err_" + key)."""

    def __init__(self, key, message):
        Exception.__init__(self, message)
        self.key = key


def _download(remote, dest):
    album.download_image(remote, dest, PHOTO_EDGE)


class Runtime(object):
    def __init__(self, hass, entry, log=None):
        self.hass = hass
        self.entry = entry
        self.root = hass.config.path("lume")
        self.cache = os.path.join(self.root, "cache")
        self.manifest_path = os.path.join(self.root, "manifest.json")
        self.flow_path = os.path.join(self.root, "flow.json")
        self.mem = {}
        self.weather_cache = {"at": 0, "temp": None, "label": "…"}
        self._log = log or (lambda msg: None)
        self.library = None
        self._lock = threading.Lock()
        self._check_lock = threading.Lock()
        self.slide = []
        self.slide_until = 0.0
        self.seq = 0
        self.rev = 0
        self.prefetching = False

    def load(self):
        """Reads the album list from disk; the first time, takes over the old manifest."""
        self.ensure_dirs()
        self.library = Library(self.root, self.cache, _download, log=self._log)
        if not self.library.has_list():
            old = self._legacy_items()
            if old:
                url = self._data().get("album_url") or ""
                self.library.set_photos(old, "album" if url else "google", url, prune=False, checked=0)
                self._log("moved %d photos from the old manifest" % len(old))
        return self

    def ensure_dirs(self):
        if not os.path.isdir(self.cache):
            os.makedirs(self.cache)

    def _data(self):
        merged = dict(self.entry.data)
        merged.update(self.mem)
        return merged

    def _remember(self, tok):
        if not tok:
            return
        if tok.get("refresh_token"):
            self.mem["refresh_token"] = tok["refresh_token"]
        if tok.get("access_token"):
            self.mem["access_token"] = tok["access_token"]
            self.mem["access_expires"] = time.time() + int(tok.get("expires_in") or 3600)

    def access_token(self):
        data = self._data()
        now = time.time()
        if data.get("access_token") and now < float(data.get("access_expires") or 0) - 30:
            return data["access_token"]
        if not data.get("refresh_token"):
            raise LumeError("link_first", "Liga primeiro a conta Google.")
        tok = google_photos.refresh_access_token(
            data.get("client_id") or "",
            data.get("client_secret") or "",
            data["refresh_token"],
        )
        self._remember(tok)
        return self._data()["access_token"]

    def read_flow(self):
        if not os.path.exists(self.flow_path):
            return {}
        try:
            with open(self.flow_path, "r") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_flow(self, flow):
        self.ensure_dirs()
        tmp = self.flow_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(flow, fh)
        os.rename(tmp, self.flow_path)

    def _legacy_items(self):
        """Photos listed by versions up to 1.1.2 (manifest.json, all already in the cache)."""
        if not os.path.exists(self.manifest_path):
            return []
        try:
            with open(self.manifest_path, "r") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return []
        items = []
        for item in data.get("items") or []:
            name = item.get("name")
            if name and os.path.isfile(os.path.join(self.cache, name)):
                items.append({"id": item.get("id") or name, "name": name, "w": item.get("w"), "h": item.get("h")})
        return items

    def device_start(self):
        data = self._data()
        if not data.get("client_id"):
            raise LumeError("client_id", "Falta o Client ID na integração.")
        started = google_photos.start_device_flow(data.get("client_id"), data.get("client_secret") or "")
        flow = self.read_flow()
        flow["device_code"] = started.get("device_code")
        flow["device_interval"] = int(started.get("interval") or 5)
        flow["device_deadline"] = time.time() + int(started.get("expires_in") or 600)
        flow["user_code"] = started.get("user_code") or ""
        flow["verification_url"] = started.get("verification_url") or "https://www.google.com/device"
        flow["error"] = ""
        flow["phase"] = "device"
        self.write_flow(flow)
        return {
            "user_code": flow["user_code"],
            "verification_url": flow["verification_url"],
        }

    def device_poll(self):
        flow = self.read_flow()
        if not flow.get("device_code"):
            return {"pending": False, "connected": bool(self._data().get("refresh_token")), "error": "Ainda não há código.", "error_key": "no_code"}
        if time.time() > float(flow.get("device_deadline") or 0):
            return {"pending": False, "connected": False, "error": "O código expirou.", "error_key": "expired"}
        data = self._data()
        try:
            tok = google_photos.poll_device_token(
                data.get("client_id") or "",
                data.get("client_secret") or "",
                flow["device_code"],
            )
        except google_photos.ApiError as exc:
            if exc.error in ("authorization_pending", "slow_down"):
                return {"pending": True, "connected": False, "error": ""}
            return {"pending": False, "connected": False, "error": str(exc)}
        self._remember(tok)
        flow["phase"] = "linked"
        flow["error"] = ""
        self.write_flow(flow)
        return {"pending": False, "connected": True, "error": ""}

    def picker_start(self):
        token = self.access_token()
        session = google_photos.create_session(token)
        flow = self.read_flow()
        flow["session_id"] = session.get("id")
        flow["picker_uri"] = session.get("pickerUri") or ""
        flow["phase"] = "picking"
        flow["queue"] = []
        flow["saved"] = []
        flow["error"] = ""
        if not flow["session_id"] or not flow["picker_uri"]:
            raise LumeError("no_session", "O Google não abriu a sessão de escolha.")
        self.write_flow(flow)
        return {"picker_uri": flow["picker_uri"]}

    def picker_poll(self):
        flow = self.read_flow()
        sid = flow.get("session_id")
        if not sid:
            return {"done": False, "error": "Ainda não há uma escolha a decorrer.", "error_key": "no_pick", "have": 0, "total": 0}
        token = self.access_token()
        if not flow.get("queue_ready"):
            info = google_photos.get_session(token, sid)
            if not info.get("mediaItemsSet"):
                return {
                    "done": False,
                    "waiting": True,
                    "have": 0,
                    "total": 0,
                    "picker_uri": flow.get("picker_uri") or "",
                }
            media = google_photos.list_media(token, sid)
            queue = []
            for item in media:
                media_file = item.get("mediaFile") or {}
                if not media_file.get("baseUrl"):
                    continue
                if google_photos.is_video(item):
                    continue
                queue.append(item)
            flow["queue"] = queue
            flow["queue_ready"] = True
            flow["saved"] = []
            self.write_flow(flow)
        queue = flow.get("queue") or []
        saved = flow.get("saved") or []
        batch = queue[:3]
        rest = queue[3:]
        self.ensure_dirs()
        for item in batch:
            name = safe_name(item.get("id") or "")
            safe = name[:-4]
            dest = os.path.join(self.cache, name)
            try:
                ok = google_photos.download_photo(token, item, dest)
            except Exception:
                ok = False
            if not ok:
                continue
            width, height = _jpeg_size(dest)
            saved.append({"id": item.get("id") or safe, "name": name, "w": width, "h": height})
        flow["queue"] = rest
        flow["saved"] = saved
        done = len(rest) == 0
        if done:
            if saved:
                # Picked photos do not follow the album: the hourly check leaves them alone
                # until "Fetch album" is pressed again.
                self.library.set_photos(saved, "google")
                self._bump()
            flow["phase"] = "ready"
            flow["queue_ready"] = False
        self.write_flow(flow)
        total = len(saved) + len(rest)
        return {
            "done": done,
            "waiting": False,
            "have": len(saved),
            "total": total,
            "picker_uri": flow.get("picker_uri") or "",
        }

    # -- settings --------------------------------------------------------------------

    def _bump(self):
        self.rev += 1

    def interval(self):
        try:
            seconds = int(self._data().get("interval_s") or 60)
        except (TypeError, ValueError):
            seconds = 60
        return max(10, seconds)

    def set_interval(self, seconds):
        seconds = max(10, int(seconds))
        self.mem["interval_s"] = seconds
        with self._lock:
            self.slide_until = min(self.slide_until, time.time() + seconds)
        self._bump()

    def set_entity(self, entity_id):
        self.mem["temp_entity"] = (entity_id or "").strip()
        self._bump()

    def set_lang(self, lang):
        code = lang if lang in ("pt", "en", "es", "fr") else "pt"
        self.mem["lang"] = code
        self._bump()

    def overlay_style(self):
        return overlay.normalize(self._data().get("overlay"))

    def set_overlay(self, style):
        self.mem["overlay"] = overlay.normalize(style)
        self._bump()
        return self.mem["overlay"]

    # -- album -----------------------------------------------------------------------

    def album_url(self):
        return (self._data().get("album_url") or "").strip()

    def refresh_album(self, url=None, hourly=False):
        """Re-reads the album list (no photo downloads). url: a new link from the panel.

        The hourly check does nothing without a link, or while the photos were picked by hand.
        Returns the counts, or None when nothing was done.
        """
        target = (url or "").strip() or self.album_url()
        if not target:
            if hourly:
                return None
            raise LumeError("bad_link", "Cola primeiro o link do álbum.")
        if hourly and self.library.source == "google":
            return None
        album.validate_share_url(target)
        if not self._check_lock.acquire(False):
            return None
        try:
            remote = album.list_album(target)
            self.library.set_photos(remote, "album", target)
        finally:
            self._check_lock.release()
        self.mem["album_url"] = target
        self._bump()
        total, cached = self.library.counts()
        self._log("album checked: %d photos, %d saved" % (total, cached))
        return {"total": total, "cached": cached}

    def prefetch(self):
        """Downloads the next two planned slides. One prefetch at a time."""
        with self._lock:
            if self.prefetching:
                return 0
            self.prefetching = True
        try:
            return self.library.prefetch(2)
        except Exception as exc:
            self._log("prefetch: %s" % exc)
            return 0
        finally:
            with self._lock:
                self.prefetching = False

    def _public(self, photo):
        return {"id": photo["id"], "w": photo["w"], "h": photo["h"], "url": "/api/lume/media/" + photo["name"]}

    def slide_state(self, now=None):
        """The slide every wall shows right now, moving on when its time is up.

        If no photo is downloaded yet the slide is empty; the caller prefetches and asks again.
        When the next slide is not ready (offline), the current one stays up a little longer.
        """
        now = time.time() if now is None else now
        interval = self.interval()
        with self._lock:
            if not self.slide or now >= self.slide_until:
                nxt = self.library.next()
                if nxt:
                    self.slide = nxt
                    self.seq += 1
                    self.slide_until = now + interval
                elif self.slide:
                    self.slide_until = now + min(interval, 10)
            slide = list(self.slide)
            remaining = max(0.0, self.slide_until - now) if slide else 2.0
            seq = self.seq
        total, cached = self.library.counts()
        return {
            "seq": seq,
            "slide": [self._public(p) for p in slide],
            "next": [[self._public(p) for p in s] for s in self.library.upcoming(1)],
            "remaining_ms": int(remaining * 1000),
            "rev": self.rev,
            "total": total,
            "cached": cached,
        }

    def weather(self):
        now = time.time()
        if now - float(self.weather_cache.get("at") or 0) < 600 and self.weather_cache.get("temp") is not None:
            return self.weather_cache
        try:
            current = weather.fetch_coimbra()
            self.weather_cache = {
                "at": now,
                "temp": current.get("temp"),
                "key": current.get("key") or "unavailable",
                "label": current.get("key") or "unavailable",
            }
        except Exception as exc:
            self.weather_cache = {
                "at": now,
                "temp": self.weather_cache.get("temp"),
                "key": self.weather_cache.get("key") or "unavailable",
                "label": self.weather_cache.get("key") or "unavailable",
                "error": str(exc),
            }
        return self.weather_cache

    def public_state(self, indoor):
        flow = self.read_flow()
        meteo = self.weather()
        data = self._data()
        total, cached = self.library.counts()
        # "items" (photos already saved) keeps a wall page from 1.1.x working until it reloads.
        public = [self._public(p) for p in self.library.cached_photos()]
        return {
            "version": VERSION,
            "rev": self.rev,
            "connected": bool(data.get("refresh_token") or data.get("access_token")),
            "interval_s": self.interval(),
            "paces": list(PACES),
            "temp_entity": data.get("temp_entity") or "",
            "album_url": data.get("album_url") or flow.get("album_url") or "",
            "lang": data.get("lang") or "pt",
            "overlay": self.overlay_style(),
            "source": self.library.source,
            "total": total,
            "cached": cached,
            "checked": self.library.checked,
            "count": len(public),
            "items": public,
            "slides": len(build_slides(public)),
            "weather": {
                "temp": meteo.get("temp"),
                "key": meteo.get("key") or "unavailable",
                "indoor": indoor,
            },
            "flow": {
                "user_code": flow.get("user_code") or "",
                "verification_url": flow.get("verification_url") or "",
                "picker_uri": flow.get("picker_uri") or "",
                "phase": flow.get("phase") or "",
                "error": flow.get("error") or "",
            },
        }


def _jpeg_size(path):
    """Reads width and height without Pillow, to keep Home Assistant light."""
    with open(path, "rb") as fh:
        data = fh.read(256 * 1024)
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2) and i + 9 < len(data):
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return width, height
        if marker in (0xD8, 0xD9):
            i += 2
            continue
        if i + 4 > len(data):
            break
        seglen = int.from_bytes(data[i + 2 : i + 4], "big")
        i += 2 + seglen
    return 4, 3
