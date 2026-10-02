# Lumen-wallframe for Home Assistant

A photo wall inside Home Assistant: Lisbon time, Coimbra weather, and photos from a shared Google Photos album, with two portrait photos side by side.

This is the Home Assistant integration of Lumen-wallframe. The Android tablet app and the Raspberry Pi frame are separate.

## Install with HACS

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jpch&repository=lumen-wallframe-ha&category=integration)

1. Click the button above (HACS must be installed). It opens HACS on your Home Assistant with this repository.
2. Press **Download**, then restart Home Assistant.
3. Add the integration:

   [![Open your Home Assistant instance and start setting up Lumen-wallframe.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=lume)

4. Open **Lumen-wallframe** in the sidebar, or go to `/lume-parede` on your Home Assistant (the bare wall is at `/api/lume/app`).

## Manual install

Copy `custom_components/lume` into your Home Assistant configuration folder, so that you end up with `/config/custom_components/lume/manifest.json`, restart Home Assistant, then go to Settings → Devices & services → Add integration → Lumen-wallframe.

## Google Photos

The way to keep a wall up to date is a shared album link:

1. In Google Photos: album → Share → create a link ("anyone with the link").
2. In the Lumen-wallframe panel, paste the `https://photos.app.goo.gl/…` link and press "Fetch album" ("Obter álbum").
3. Photos are stored in `/config/lume/cache` before they go on the wall. Videos are left out.
4. Every 20 minutes the panel reads the album again without covering the photos already on screen.

Linking a Google account (a code on the phone) is only for picking photos by hand, and does not follow the album. If you want that:

1. At console.cloud.google.com enable the "Photos Picker API".
2. Set up the OAuth consent screen (external) with your Gmail as a test user.
3. Create an OAuth client of type "TVs and Limited Input devices".
4. Paste the Client ID when you add the integration.
5. In the panel use "Link with the phone" ("Ligar com o telemóvel"), then "Choose photos" ("Escolher fotos"). The picking address is also left in a persistent Home Assistant notification.

## Indoor temperature

Optional. In the panel, enter a temperature sensor entity (for example `sensor.temperatura_sala`) to show it on the wall. The Coimbra weather does not use it.
