# Lumen-wallframe for Home Assistant

A photo wall inside Home Assistant: Lisbon time, Coimbra weather, and photos from a shared Google Photos album, with two portrait photos side by side.

This is the Home Assistant integration of Lumen-wallframe. The Android tablet app and the Raspberry Pi frame are separate.

## Install with HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jpch&repository=lumen-wallframe-ha&category=integration)

1. Click the button above (HACS must be installed). It opens HACS on your Home Assistant with this repository.
2. Press **Download**, then restart Home Assistant. This step is required: until the integration is downloaded and Home Assistant has restarted, the next button shows "This integration does not support configuration via the UI".
3. Add the integration (every field is optional):

   [![Open your Home Assistant instance and start setting up Lumen-wallframe.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=lume)

4. Open **Lumen-wallframe** in the sidebar, or go to `/lume-parede` on your Home Assistant (the bare wall is at `/api/lume/app`).

## Manual install

Copy `custom_components/lume` into your Home Assistant configuration folder, so that you end up with `/config/custom_components/lume/manifest.json`, restart Home Assistant, then go to Settings → Devices & services → Add integration → Lumen-wallframe.

## Google Photos

The way to keep a wall up to date is a shared album link:

1. In Google Photos: album → Share → create a link ("anyone with the link").
2. In the Lumen-wallframe panel, paste the `https://photos.app.goo.gl/…` link and press "Obter álbum" (Fetch album).
3. Only the album's list of photos is read (videos are left out): 30 seconds after Home Assistant starts, every hour, and when you press the button. Nothing is bulk-downloaded.
4. The wall goes through the album in random order, as a shuffled cycle: every photo once before any photo repeats. Each photo is downloaded just before it shows (the next two slides are always fetched ahead) and kept in `/config/lume/cache`, so the cache grows as the wall runs. Photos removed from the album are deleted from the cache at the next check.
5. Every screen showing the wall shows the same slide. Without network the wall keeps going with the photos already saved. The panel shows "Fotos no álbum: N · guardadas: M".

Linking a Google account (a code on the phone) is only for picking photos by hand, and does not follow the album. If you want that:

1. At console.cloud.google.com enable the "Photos Picker API".
2. Set up the OAuth consent screen (external) with your Gmail as a test user.
3. Create an OAuth client of type "TVs and Limited Input devices".
4. Paste the Client ID when you add the integration (or later, by removing and adding it again).
5. In the panel use "Link with the phone" ("Ligar com o telemóvel"), then "Choose photos" ("Escolher fotos"). The picking address is also left in a persistent Home Assistant notification.

## Customize, pace and language

- **Personalizar** (Customize) in the panel sets the info bands over the photo: the top band (0–60 % of the screen height, default 0), the bottom band (0–100 %, default 42; the two together never pass 100 %), the colour (black, white, dark blue, dark green, dark brown, grey), the opacity (0–100 %, default 35) and an optional fade towards the middle. The wall changes as you move the sliders; **Repor** (Reset) goes back to the defaults. On a strong white band the clock and weather turn dark.
- The pace goes from 15 s to 1 h, in the panel or from the menu at the top right of the wall.
- The language menu (Português, English, Español, Français) is at the top right of the wall and of the panel.

The settings are kept in the integration's config entry, so they survive restarts and are shared by every screen.

## Indoor temperature

Optional. In the panel, enter a temperature sensor entity (for example `sensor.temperatura_sala`) to show it on the wall. The Coimbra weather does not use it.

## Development

`rotation.py` (shuffled cycle), `library.py` (album list, lazy cache, prefetch), `overlay.py` (band settings) and `album.py` are identical copies of the files in the Raspberry Pi app (`pi/` in the private jpch/Lumen-wallframe repository); change both together.

- Unit tests, no Home Assistant needed (Python 3.6 or newer): `python3 -m unittest discover -s tests`
- With a real Home Assistant core: `pip install pytest-homeassistant-custom-component`, then `PYTHONPATH=. pytest -o asyncio_mode=auto tests_ha`
