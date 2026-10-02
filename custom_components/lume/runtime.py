# -*- coding: utf-8 -*-
"""Lumen-wallframe state inside Home Assistant. Blocking network calls run in an executor."""
import json
import os
import time

from . import album
from . import google_photos
from . import weather
from .slides import build_slides


class Runtime(object):
    def __init__(self, hass, entry):
        self.hass = hass
        self.entry = entry
        self.root = hass.config.path("lume")
        self.cache = os.path.join(self.root, "cache")
        self.manifest_path = os.path.join(self.root, "manifest.json")
        self.flow_path = os.path.join(self.root, "flow.json")
        self.mem = {}
        self.weather_cache = {"at": 0, "temp": None, "label": "…"}

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
            raise RuntimeError("Liga primeiro a conta Google.")
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

    def read_items(self):
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
            path = os.path.join(self.cache, name) if name else ""
            if name and os.path.isfile(path):
                items.append(
                    {
                        "id": item.get("id") or name,
                        "name": name,
                        "w": int(item.get("w") or 1),
                        "h": int(item.get("h") or 1),
                    }
                )
        return items

    def write_items(self, items):
        self.ensure_dirs()
        tmp = self.manifest_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"items": items}, fh)
        os.rename(tmp, self.manifest_path)

    def device_start(self):
        data = self._data()
        if not data.get("client_id"):
            raise RuntimeError("Falta o Client ID na integração.")
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
            return {"pending": False, "connected": bool(self._data().get("refresh_token")), "error": "Ainda não há código."}
        if time.time() > float(flow.get("device_deadline") or 0):
            return {"pending": False, "connected": False, "error": "O código expirou."}
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
            raise RuntimeError("O Google não abriu a sessão de escolha.")
        self.write_flow(flow)
        return {"picker_uri": flow["picker_uri"]}

    def picker_poll(self):
        flow = self.read_flow()
        sid = flow.get("session_id")
        if not sid:
            return {"done": False, "error": "Ainda não há uma escolha a decorrer.", "have": 0, "total": 0}
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
            safe = "".join(ch for ch in (item.get("id") or "") if ch.isalnum())[:48] or "foto"
            name = safe + ".jpg"
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
            self.write_items(saved)
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

    def set_interval(self, seconds):
        self.mem["interval_s"] = int(seconds)

    def set_entity(self, entity_id):
        self.mem["temp_entity"] = (entity_id or "").strip()

    def album_prepare(self, url):
        remote = album.list_album(url)
        flow = self.read_flow()
        flow["album_url"] = url
        flow["album_queue"] = remote
        flow["album_saved"] = []
        flow["phase"] = "album"
        flow["error"] = ""
        self.write_flow(flow)
        self.mem["album_url"] = url
        return {"total": len(remote), "have": 0, "done": False}

    def album_step(self):
        flow = self.read_flow()
        queue = list(flow.get("album_queue") or [])
        saved = list(flow.get("album_saved") or [])
        if not queue:
            if saved:
                self.write_items(saved)
                flow["phase"] = "album-ready"
            self.write_flow(flow)
            return {"done": True, "have": len(saved), "total": len(saved), "error": flow.get("error") or ""}
        batch = queue[:3]
        rest = queue[3:]
        self.ensure_dirs()
        for item in batch:
            name = album.safe_name(item.get("id") or "") + ".jpg"
            dest = os.path.join(self.cache, name)
            try:
                if not os.path.isfile(dest) or os.path.getsize(dest) < 800:
                    album.download_image(item.get("remote") or "", dest)
            except Exception:
                continue
            saved.append(
                {
                    "id": item.get("id") or name,
                    "name": name,
                    "w": int(item.get("w") or 1),
                    "h": int(item.get("h") or 1),
                }
            )
        flow["album_queue"] = rest
        flow["album_saved"] = saved
        done = not rest
        if done and saved:
            self.write_items(saved)
            flow["phase"] = "album-ready"
            flow["error"] = ""
        elif done:
            flow["phase"] = "album-ready"
            flow["error"] = "Nenhuma foto foi guardada."
        self.write_flow(flow)
        return {
            "done": done,
            "have": len(saved),
            "total": len(saved) + len(rest),
            "error": flow.get("error") or "",
        }

    def set_lang(self, lang):
        code = lang if lang in ("pt", "en", "es", "fr") else "pt"
        self.mem["lang"] = code

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
        items = self.read_items()
        flow = self.read_flow()
        meteo = self.weather()
        data = self._data()
        public = []
        for item in items:
            public.append(
                {
                    "id": item["id"],
                    "w": item["w"],
                    "h": item["h"],
                    "url": "/api/lume/media/" + item["name"],
                }
            )
        return {
            "connected": bool(data.get("refresh_token") or data.get("access_token")),
            "interval_s": int(data.get("interval_s") or 60),
            "temp_entity": data.get("temp_entity") or "",
            "album_url": data.get("album_url") or flow.get("album_url") or "",
            "lang": data.get("lang") or "pt",
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
                "album_have": len(flow.get("album_saved") or []),
                "album_total": len(flow.get("album_saved") or []) + len(flow.get("album_queue") or []),
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
