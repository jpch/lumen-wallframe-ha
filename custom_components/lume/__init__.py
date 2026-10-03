# -*- coding: utf-8 -*-
import logging
import os

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN
from .runtime import Runtime

_LOGGER = logging.getLogger(__name__)
PANEL_PATH = "lume-parede"


def _runtime(request):
    hass = request.app["hass"]
    bucket = hass.data.get(DOMAIN) or {}
    runtime = bucket.get("runtime")
    if runtime is None:
        raise RuntimeError("Lumen-wallframe não está carregado.")
    return runtime


async def _persist(runtime):
    if not runtime.mem:
        return
    data = dict(runtime.entry.data)
    data.update(runtime.mem)
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


async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("views"):
        hass.http.register_view(LumeAppView())
        hass.http.register_view(LumeStateView())
        hass.http.register_view(LumeActionView())
        hass.http.register_view(LumeMediaView())
        hass.data[DOMAIN]["views"] = True
    return True


async def async_setup_entry(hass, entry):
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["runtime"] = Runtime(hass, entry)
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
        _LOGGER.warning("Painel Lumen-wallframe não registado: %s", err)
    return True


async def async_unload_entry(hass, entry):
    bucket = hass.data.get(DOMAIN) or {}
    bucket.pop("runtime", None)
    try:
        from homeassistant.components.frontend import async_remove_panel

        async_remove_panel(hass, PANEL_PATH)
    except Exception as err:
        _LOGGER.debug("painel: %s", err)
    return True


class LumeAppView(HomeAssistantView):
    url = "/api/lume/app"
    name = "api:lume:app"
    requires_auth = False

    async def get(self, request):
        path = os.path.join(os.path.dirname(__file__), "wall.html")
        with open(path, encoding="utf-8") as handle:
            html = handle.read()
        return web.Response(text=html, content_type="text/html", charset="utf-8")


class LumeStateView(HomeAssistantView):
    url = "/api/lume/state"
    name = "api:lume:state"
    requires_auth = False

    async def get(self, request):
        runtime = _runtime(request)
        indoor = _indoor(runtime)

        def work():
            return runtime.public_state(indoor)

        try:
            payload = await runtime.hass.async_add_executor_job(work)
        except Exception as err:
            return self.json({"error": str(err)}, status_code=500)
        await _persist(runtime)
        return self.json(payload)


class LumeActionView(HomeAssistantView):
    url = "/api/lume/action"
    name = "api:lume:action"
    requires_auth = False

    async def post(self, request):
        runtime = _runtime(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = body.get("action")
        try:
            if action == "device_start":
                result = await runtime.hass.async_add_executor_job(runtime.device_start)
            elif action == "device_poll":
                result = await runtime.hass.async_add_executor_job(runtime.device_poll)
            elif action == "picker_start":
                result = await runtime.hass.async_add_executor_job(runtime.picker_start)
                uri = (result or {}).get("picker_uri")
                if uri:
                    await runtime.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {"title": "Lumen-wallframe", "message": uri, "notification_id": "lume"},
                        blocking=False,
                    )
            elif action == "picker_poll":
                result = await runtime.hass.async_add_executor_job(runtime.picker_poll)
            elif action == "interval":
                runtime.set_interval(int(body.get("seconds") or 60))
                result = {"ok": True}
            elif action == "entity":
                runtime.set_entity(body.get("entity") or "")
                result = {"ok": True}
            elif action == "lang":
                runtime.set_lang(body.get("lang") or "pt")
                result = {"ok": True}
            elif action == "album_prepare":
                target = body.get("url") or ""
                result = await runtime.hass.async_add_executor_job(lambda: runtime.album_prepare(target))
            elif action == "album_step":
                result = await runtime.hass.async_add_executor_job(runtime.album_step)
            else:
                return self.json({"error": "acção desconhecida"}, status_code=400)
        except Exception as err:
            _LOGGER.exception("lume %s", action)
            return self.json({"error": str(err)}, status_code=400)
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
        if not os.path.isfile(path):
            return web.Response(status=404)
        return web.FileResponse(path)
