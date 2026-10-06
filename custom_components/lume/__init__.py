# -*- coding: utf-8 -*-
"""Lumen-wallframe for Home Assistant: a photo wall served as a sidebar panel.

The wall page (wall.html) talks to the views below. Blocking work (disk, Google, weather)
always runs in the executor. The album list is re-read 30 s after start-up, then every
hour; photos are downloaded one by one as the wall needs them (see runtime.py).
"""
import asyncio
import logging
import os
from datetime import timedelta

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import DOMAIN
from .runtime import ALBUM_CHECK_S, Runtime

_LOGGER = logging.getLogger(__name__)
PANEL_PATH = "lume-parede"
FIRST_CHECK_S = 30


def _runtime(request):
    hass = request.app["hass"]
    bucket = hass.data.get(DOMAIN) or {}
    runtime = bucket.get("runtime")
    if runtime is None:
        raise web.HTTPServiceUnavailable(text="Lumen-wallframe is not loaded.")
    return runtime


async def _persist(runtime):
    """Keeps settings (language, pace, overlay, album link, tokens) in the config entry."""
    if not runtime.mem:
        return
    data = dict(runtime.entry.data)
    data.update(runtime.mem)
    if data != dict(runtime.entry.data):
        runtime.hass.config_entries.async_update_entry(runtime.entry, data=data)


def _indoor(runtime):
    entity = (runtime._data().get("temp_entity") or "").strip()
    if not entity:
        return None
    state = runtime.hass.states.get(entity)
    if state is None:
        return None
    try:
        return round(float(state.state), 1)
    except (TypeError, ValueError):
        return None


def _error(err):
    body = {"error": str(err)}
    key = getattr(err, "key", None)
    if key:
        body["error_key"] = key
    return body


def _kick_prefetch(runtime):
    """Starts a background prefetch in the executor and returns its future."""
    return runtime.hass.async_add_executor_job(runtime.prefetch)


async def _check_album(runtime, hourly=True):
    try:
        result = await runtime.hass.async_add_executor_job(lambda: runtime.refresh_album(None, hourly))
    except Exception as err:
        _LOGGER.warning("Lumen-wallframe album check failed: %s", err)
        return
    if result is not None:
        await _persist(runtime)
        _kick_prefetch(runtime)


async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("views"):
        hass.http.register_view(LumeAppView())
        hass.http.register_view(LumeStateView())
        hass.http.register_view(LumeSlideView())
        hass.http.register_view(LumeActionView())
        hass.http.register_view(LumeMediaView())
        hass.data[DOMAIN]["views"] = True
    return True


async def async_setup_entry(hass, entry):
    hass.data.setdefault(DOMAIN, {})
    runtime = Runtime(hass, entry, log=_LOGGER.debug)
    await hass.async_add_executor_job(runtime.load)
    hass.data[DOMAIN]["runtime"] = runtime

    async def hourly(_now=None):
        await _check_album(runtime, hourly=True)

    first = FIRST_CHECK_S if runtime.library.age() > 120 else max(FIRST_CHECK_S, ALBUM_CHECK_S - runtime.library.age())
    entry.async_on_unload(async_call_later(hass, first, hourly))
    entry.async_on_unload(async_track_time_interval(hass, hourly, timedelta(seconds=ALBUM_CHECK_S)))
    try:
        from homeassistant.components.frontend import async_register_built_in_panel

        # Keyword arguments only: newer Home Assistant versions added positional
        # parameters (sidebar_default_visible) before frontend_url_path.
        panel = dict(
            sidebar_title="Lumen-wallframe",
            sidebar_icon="mdi:image-frame",
            frontend_url_path=PANEL_PATH,
            config={"url": "/api/lume/app"},
            require_admin=False,
        )
        try:
            async_register_built_in_panel(hass, "iframe", update=True, **panel)
        except TypeError:
            async_register_built_in_panel(hass, "iframe", **panel)
    except Exception as err:
        _LOGGER.warning("Lumen-wallframe panel not registered: %s", err)
    return True


async def async_unload_entry(hass, entry):
    bucket = hass.data.get(DOMAIN) or {}
    bucket.pop("runtime", None)
    try:
        from homeassistant.components.frontend import async_remove_panel

        async_remove_panel(hass, PANEL_PATH)
    except Exception as err:
        _LOGGER.debug("panel: %s", err)
    return True


class LumeAppView(HomeAssistantView):
    url = "/api/lume/app"
    name = "api:lume:app"
    requires_auth = False

    async def get(self, request):
        hass = request.app["hass"]
        path = os.path.join(os.path.dirname(__file__), "wall.html")

        def read():
            with open(path, encoding="utf-8") as handle:
                return handle.read()

        html = await hass.async_add_executor_job(read)
        return web.Response(text=html, content_type="text/html", charset="utf-8", headers={"Cache-Control": "no-cache"})


class LumeStateView(HomeAssistantView):
    url = "/api/lume/state"
    name = "api:lume:state"
    requires_auth = False

    async def get(self, request):
        runtime = _runtime(request)
        indoor = _indoor(runtime)
        try:
            payload = await runtime.hass.async_add_executor_job(lambda: runtime.public_state(indoor))
        except Exception as err:
            return self.json(_error(err), status_code=500)
        await _persist(runtime)
        return self.json(payload)


class LumeSlideView(HomeAssistantView):
    """The slide every wall shows now, the next one to preload, and when to ask again."""

    url = "/api/lume/slide"
    name = "api:lume:slide"
    requires_auth = False

    async def get(self, request):
        runtime = _runtime(request)
        hass = runtime.hass
        try:
            payload = await hass.async_add_executor_job(runtime.slide_state)
            if not payload["slide"] and payload["total"]:
                # Nothing downloaded yet: give the first downloads up to 8 s.
                try:
                    await asyncio.wait_for(asyncio.shield(_kick_prefetch(runtime)), 8)
                except asyncio.TimeoutError:
                    pass
                payload = await hass.async_add_executor_job(runtime.slide_state)
        except Exception as err:
            return self.json(_error(err), status_code=500)
        if payload["total"] > payload["cached"]:
            _kick_prefetch(runtime)
        return self.json(payload)


class LumeActionView(HomeAssistantView):
    url = "/api/lume/action"
    name = "api:lume:action"
    requires_auth = False

    async def post(self, request):
        runtime = _runtime(request)
        hass = runtime.hass
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = body.get("action")
        try:
            if action == "device_start":
                result = await hass.async_add_executor_job(runtime.device_start)
            elif action == "device_poll":
                result = await hass.async_add_executor_job(runtime.device_poll)
            elif action == "picker_start":
                result = await hass.async_add_executor_job(runtime.picker_start)
                uri = (result or {}).get("picker_uri")
                if uri:
                    await hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {"title": "Lumen-wallframe", "message": uri, "notification_id": "lume"},
                        blocking=False,
                    )
            elif action == "picker_poll":
                result = await hass.async_add_executor_job(runtime.picker_poll)
            elif action == "interval":
                runtime.set_interval(int(body.get("seconds") or 60))
                result = {"ok": True}
            elif action == "entity":
                runtime.set_entity(body.get("entity") or "")
                result = {"ok": True}
            elif action == "lang":
                runtime.set_lang(body.get("lang") or "pt")
                result = {"ok": True, "lang": runtime._data().get("lang")}
            elif action == "overlay":
                result = {"ok": True, "overlay": runtime.set_overlay(body.get("overlay") or {})}
            elif action == "wall_info":
                result = {"ok": True, "wall_info": runtime.set_wall_info(body)}
            elif action == "geocode":
                query = body.get("query") or ""
                lang = body.get("lang") or runtime._data().get("lang") or "pt"

                def lookup():
                    from . import weather as weather_mod

                    return weather_mod.geocode(query, lang)

                place = await hass.async_add_executor_job(lookup)
                result = {"ok": True, "place": place}
            elif action in ("album_refresh", "album_prepare"):
                # album_prepare is what 1.1.x wall pages send; it now only reads the list.
                target = body.get("url") or ""
                counts = await hass.async_add_executor_job(lambda: runtime.refresh_album(target))
                await _persist(runtime)
                await asyncio.wait_for(asyncio.shield(_kick_prefetch(runtime)), 15)
                total, cached = await hass.async_add_executor_job(runtime.library.counts)
                result = {"ok": True, "total": total, "cached": cached, "have": cached, "done": action == "album_refresh"}
                if counts is None:
                    result["busy"] = True
            elif action == "album_step":
                total, cached = await hass.async_add_executor_job(runtime.library.counts)
                result = {"done": True, "have": cached, "total": total, "error": ""}
            else:
                return self.json({"error": "unknown action", "error_key": "unknown"}, status_code=400)
        except asyncio.TimeoutError:
            total, cached = await hass.async_add_executor_job(runtime.library.counts)
            result = {"ok": True, "total": total, "cached": cached, "done": True}
        except Exception as err:
            _LOGGER.warning("Lumen-wallframe %s: %s", action, err)
            return self.json(_error(err), status_code=400)
        await _persist(runtime)
        return self.json(result)


class LumeMediaView(HomeAssistantView):
    url = "/api/lume/media/{name}"
    name = "api:lume:media"
    requires_auth = False

    async def get(self, request, name):
        runtime = _runtime(request)
        if not name or "/" in name or ".." in name or not name.endswith(".jpg"):
            return web.Response(status=404)
        path = os.path.join(runtime.cache, name)
        exists = await runtime.hass.async_add_executor_job(os.path.isfile, path)
        if not exists:
            return web.Response(status=404)
        return web.FileResponse(path, headers={"Cache-Control": "max-age=86400"})
