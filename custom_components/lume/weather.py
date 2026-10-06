# -*- coding: utf-8 -*-
try:
    import i18n
except ImportError:
    from . import i18n
import json
import os
import time
import urllib.parse
import urllib.request

COIMBRA = (40.2033, -8.4103)
COIMBRA_PLACE = {"name": "Coimbra", "region": "", "lat": 40.2033, "lon": -8.4103}
UA = "Lumen-wallframe/1.0 (photo frame)"


def weather_key(code):
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "unavailable"
    if code < 0:
        return "unavailable"
    if code == 0:
        return "clear"
    if code == 1:
        return "mostly"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "drizzle"
    if code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "thunder"
    return "unstable"


def symbol_key(code):
    base = (code or "").split("_")[0]
    if base == "clearsky":
        return "clear"
    if base == "fair":
        return "mostly"
    if base == "partlycloudy":
        return "partly"
    if base == "cloudy":
        return "cloudy"
    if base == "fog":
        return "fog"
    if "snow" in base:
        return "snow"
    if "thunder" in base:
        return "thunder"
    if "rain" in base or "sleet" in base:
        return "rain"
    if not base:
        return "unavailable"
    return "unstable"


def describe_weather(code, lang="pt"):
    """Translated label for an Open-Meteo weather code."""
    return i18n.tr(lang, "w_" + weather_key(code))


def describe_symbol(code, lang="pt"):
    """Translated label for a MET Norway symbol code (e.g. "clearsky_night")."""
    return i18n.tr(lang, "w_" + symbol_key(code))


def lisbon_parts(lang="pt"):
    os.environ["TZ"] = "Europe/Lisbon"
    try:
        time.tzset()
    except AttributeError:
        pass
    now = time.localtime()
    clock = time.strftime("%H:%M", now)
    return clock, i18n.date_line(lang, now.tm_wday, now.tm_mday, now.tm_mon)


def coord(value):
    """Four decimals with a dot (MET Norway's limit), never a decimal comma or an exponent."""
    return "%.4f" % float(value)


def default_place():
    return dict(COIMBRA_PLACE)


def normalize_place(raw):
    """A weather place dict. Missing or invalid fields fall back to Coimbra."""
    raw = raw or {}
    try:
        lat = float(raw.get("lat"))
        lon = float(raw.get("lon"))
    except (TypeError, ValueError):
        return default_place()
    name = (raw.get("name") or "").strip()
    if not name:
        return default_place()
    return {
        "name": name,
        "region": (raw.get("region") or "").strip(),
        "lat": lat,
        "lon": lon,
    }


def place_label(place):
    """'Lisboa (Distrito de Lisboa, Portugal)', or just the name when there is no region."""
    place = normalize_place(place)
    if place["region"]:
        return "%s (%s)" % (place["name"], place["region"])
    return place["name"]


def _get_json(url, headers=None, timeout=20):
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        raw = resp.read()
    finally:
        resp.close()
    return json.loads(raw.decode("utf-8"))


def geocode(query, language="en"):
    """Looks a typed place up with the Open-Meteo geocoding API (no key).

    "Coimbra" takes the best match; "Coimbra, Brasil" or "Porto, PT" keeps only matches whose
    country, country code or region contains the part after the comma. Returns None when
    nothing matches. Raises when the lookup itself fails (no network, bad answer).
    """
    text = (query or "").strip()
    if not text:
        return None
    if "," in text:
        name, hint = text.split(",", 1)
        name, hint = name.strip(), hint.strip()
    else:
        name, hint = text, ""
    if not name:
        return None
    lang = (language or "en").strip() or "en"
    count = 1 if not hint else 20
    url = (
        "https://geocoding-api.open-meteo.com/v1/search?name=%s&count=%d&language=%s&format=json"
        % (urllib.parse.quote(name), count, urllib.parse.quote(lang))
    )
    data = _get_json(url)
    results = data.get("results") or []
    hint_l = hint.lower()
    for item in results:
        if "latitude" not in item or "longitude" not in item:
            continue
        country = item.get("country") or ""
        admin = item.get("admin1") or ""
        code = item.get("country_code") or ""
        if hint_l and hint_l not in country.lower() and hint_l not in admin.lower() and hint_l not in code.lower():
            continue
        found_name = (item.get("name") or "").strip() or name
        region_parts = []
        for part in (admin, country):
            if part and part.lower() != found_name.lower():
                region_parts.append(part)
        return {
            "name": found_name,
            "region": ", ".join(region_parts),
            "lat": float(item["latitude"]),
            "lon": float(item["longitude"]),
        }
    return None


def _met_no(lat, lon):
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=%s&lon=%s" % (
        coord(lat),
        coord(lon),
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=20)
    try:
        data = json.loads(resp.read().decode("utf-8"))
    finally:
        resp.close()
    point = (((data.get("properties") or {}).get("timeseries") or [{}])[0].get("data") or {})
    details = ((point.get("instant") or {}).get("details") or {})
    summary = ((point.get("next_1_hours") or {}).get("summary") or {})
    temp = details.get("air_temperature")
    return {"temp": temp, "key": symbol_key(summary.get("symbol_code"))}


def fetch(lat=None, lon=None):
    """Current weather at lat/lon (defaults to Coimbra): Open-Meteo first, MET Norway if that fails."""
    if lat is None or lon is None:
        lat, lon = COIMBRA
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=%s&longitude=%s&current_weather=true&timezone=auto"
        % (coord(lat), coord(lon))
    )
    try:
        data = _get_json(url)
        if data.get("error"):
            raise RuntimeError("limite")
        current = data.get("current_weather") or {}
        temp = current.get("temperature")
        if temp is None:
            raise RuntimeError("sem temperatura")
        code = current.get("weathercode")
        return {"temp": temp, "key": weather_key(code)}
    except Exception:
        return _met_no(lat, lon)


def fetch_coimbra():
    """Backwards-compatible alias for fetch at Coimbra."""
    return fetch(*COIMBRA)


def fetch_indoor(base_url, token, entity_id):
    if not base_url or not token or not entity_id:
        return None
    url = base_url.rstrip("/") + "/api/states/" + urllib.parse.quote(entity_id)
    data = _get_json(url, headers={"Authorization": "Bearer " + token})
    state = data.get("state")
    try:
        return round(float(state), 1)
    except (TypeError, ValueError):
        return None
