"""Integration test with a real Home Assistant core (pytest-homeassistant-custom-component).

Run from the repository root:
    pip install pytest-homeassistant-custom-component
    PYTHONPATH=. pytest -o asyncio_mode=auto tests_ha
"""
import asyncio
import os
from unittest.mock import patch

import custom_components

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

# The test plugin ships its own custom_components package; add this repository's to it.
_HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "custom_components")
if os.path.abspath(_HERE) not in [os.path.abspath(p) for p in custom_components.__path__]:
    custom_components.__path__.insert(0, os.path.abspath(_HERE))

JPEG = b"\xff\xd8\xff" + b"\0" * 2000
ALBUM = [
    {"id": "AF1Qip%d" % i, "remote": "https://lh3.googleusercontent.com/pw/p%d" % i, "w": 300 if i % 2 else 400, "h": 400 if i % 2 else 300}
    for i in range(8)
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def own_config_dir(hass, tmp_path):
    # /config/lume (album list and photo cache) goes to a fresh folder for every test.
    hass.config.config_dir = str(tmp_path)
    yield


@pytest.fixture
def fake_google():
    from custom_components.lume import album

    downloads = []

    def list_album(url):
        album.validate_share_url(url)
        return list(ALBUM)

    def download_image(remote, dest, edge=1280):
        downloads.append(remote)
        with open(dest, "wb") as fh:
            fh.write(JPEG)

    with patch.object(album, "list_album", list_album), patch.object(album, "download_image", download_image):
        yield downloads


async def _setup(hass, data):
    hass.config.components.add("frontend")  # the panel needs the real frontend; not under test
    entry = MockConfigEntry(domain="lume", data=data, unique_id="lume", title="Lumen-wallframe")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_old_entry_loads_and_serves_the_wall(hass, hass_client, fake_google):
    entry = await _setup(hass, {"interval_s": 60, "client_id": "", "client_secret": "", "temp_entity": ""})
    assert entry.state.value == "loaded"
    client = await hass_client()
    page = await client.get("/api/lume/app")
    assert page.status == 200
    assert "Lumen-wallframe" in await page.text()
    state = await (await client.get("/api/lume/state")).json()
    assert state["version"] == "1.2.0"
    assert state["overlay"] == {"top": 0, "bottom": 42, "color": "#000000", "opacity": 35, "fade": False}
    assert state["total"] == 0
    slide = await (await client.get("/api/lume/slide")).json()
    assert slide["slide"] == []


async def test_album_settings_and_slides(hass, hass_client, fake_google):
    entry = await _setup(hass, {"interval_s": 60})
    client = await hass_client()
    bad = await client.post("/api/lume/action", json={"action": "album_refresh", "url": "https://example.com/x"})
    assert bad.status == 400
    assert (await bad.json())["error_key"] == "bad_link"
    res = await client.post("/api/lume/action", json={"action": "album_refresh", "url": "https://photos.app.goo.gl/abc"})
    body = await res.json()
    assert res.status == 200, body
    assert body["total"] == 8
    assert 1 <= body["cached"] <= 4  # only the next slides, not the whole album
    assert entry.data["album_url"] == "https://photos.app.goo.gl/abc"

    slide = await (await client.get("/api/lume/slide")).json()
    assert slide["slide"], slide
    media = await client.get(slide["slide"][0]["url"])
    assert media.status == 200

    for action in (
        {"action": "overlay", "overlay": {"top": 10, "bottom": 95, "color": "#ffffff", "opacity": 80, "fade": True}},
        {"action": "lang", "lang": "en"},
        {"action": "interval", "seconds": 15},
    ):
        assert (await client.post("/api/lume/action", json=action)).status == 200
    assert entry.data["overlay"] == {"top": 10, "bottom": 90, "color": "#ffffff", "opacity": 80, "fade": True}
    assert entry.data["lang"] == "en"
    assert entry.data["interval_s"] == 15
    state = await (await client.get("/api/lume/state")).json()
    assert state["lang"] == "en" and state["interval_s"] == 15

    # The old 1.1.x page keeps working until it reloads.
    old = await client.post("/api/lume/action", json={"action": "album_step"})
    assert (await old.json())["done"] is True

    # Reload the entry: the settings and the album list survive.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = await (await client.get("/api/lume/state")).json()
    assert state["total"] == 8 and state["overlay"]["color"] == "#ffffff" and state["lang"] == "en"
    await asyncio.sleep(0)
