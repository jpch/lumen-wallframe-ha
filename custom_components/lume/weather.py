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
UA = "Lume/1.0 (photo frame)"


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


def lisbon_parts(lang="pt"):
    os.environ["TZ"] = "Europe/Lisbon"
    try:
        time.tzset()
    except AttributeError:
        pass
    now = time.localtime()
    clock = time.strftime("%H:%M", now)
    return clock, i18n.date_line(lang, now.tm_wday, now.tm_mday, now.tm_mon)


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


def _met_no():
    url = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=%s&lon=%s" % COIMBRA
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


def fetch_coimbra():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=%s&longitude=%s&current_weather=true&timezone=Europe%%2FLisbon"
        % COIMBRA
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
        return _met_no()


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
