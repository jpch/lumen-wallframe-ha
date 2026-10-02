# -*- coding: utf-8 -*-
"""Google Photos Picker API + OAuth (device code and loopback).

Since 31/03/2025 the Library API no longer lists existing albums.
The choice is a session: the photos stay in the cache and there is no automatic
album sync.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
DEVICE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
PICKER = "https://photospicker.googleapis.com/v1"
UA = "Lume/1.0 (Raspberry Pi photo frame)"


class ApiError(Exception):
    def __init__(self, status, body):
        self.status = status
        self.body = body or ""
        self.error = ""
        self.payload = {}
        try:
            self.payload = json.loads(self.body)
            self.error = self.payload.get("error") or ""
        except (ValueError, TypeError):
            pass
        Exception.__init__(self, "HTTP %s: %s" % (status, self.body[:400]))


def _request(url, method="GET", form=None, payload=None, headers=None, timeout=60):
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode("utf-8")
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif payload is not None:
        body = json.dumps(payload).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs)
    if method and method != "GET":
        req.get_method = lambda: method
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        raise ApiError(err.code, detail)
    try:
        raw = resp.read()
    finally:
        resp.close()
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _secret_form(client_id, client_secret, extra):
    form = {"client_id": client_id}
    if client_secret:
        form["client_secret"] = client_secret
    form.update(extra)
    return form


def start_device_flow(client_id, client_secret):
    return _request(
        DEVICE_URL,
        method="POST",
        form=_secret_form(client_id, client_secret, {"scope": SCOPE}),
    )


def poll_device_token(client_id, client_secret, device_code):
    return _request(
        TOKEN_URL,
        method="POST",
        form=_secret_form(
            client_id,
            client_secret,
            {
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        ),
    )


def exchange_code(client_id, client_secret, code, redirect_uri):
    return _request(
        TOKEN_URL,
        method="POST",
        form=_secret_form(
            client_id,
            client_secret,
            {
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        ),
    )


def refresh_access_token(client_id, client_secret, refresh_token):
    return _request(
        TOKEN_URL,
        method="POST",
        form=_secret_form(
            client_id,
            client_secret,
            {"refresh_token": refresh_token, "grant_type": "refresh_token"},
        ),
    )


def auth_url(client_id, redirect_uri):
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return AUTH_URL + "?" + query


def create_session(access_token):
    return _request(
        PICKER + "/sessions",
        method="POST",
        payload={"pickingConfig": {"maxItemCount": "2000"}},
        headers={"Authorization": "Bearer " + access_token},
    )


def get_session(access_token, session_id):
    return _request(
        PICKER + "/sessions/" + urllib.parse.quote(session_id),
        headers={"Authorization": "Bearer " + access_token},
    )


def list_media(access_token, session_id):
    items = []
    page = None
    while True:
        query = {"sessionId": session_id, "pageSize": "100"}
        if page:
            query["pageToken"] = page
        data = _request(
            PICKER + "/mediaItems?" + urllib.parse.urlencode(query),
            headers={"Authorization": "Bearer " + access_token},
        )
        batch = data.get("mediaItems") or []
        items.extend(batch)
        page = data.get("nextPageToken")
        if not page:
            break
    return items


def is_video(item):
    """A Picker item that is a video: type VIDEO, a video/... MIME type or video metadata."""
    media = item.get("mediaFile") or {}
    mime = (media.get("mimeType") or "").lower()
    meta = media.get("mediaFileMetadata") or {}
    return item.get("type") == "VIDEO" or mime.startswith("video") or "videoMetadata" in meta


def download_photo(access_token, item, dest_path):
    media = item.get("mediaFile") or {}
    if is_video(item):
        return False
    base = media.get("baseUrl")
    if not base:
        return False
    url = base + "=w1280-h1280"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Authorization": "Bearer " + access_token})
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        resp = urllib.request.urlopen(req, timeout=120)
    tmp = dest_path + ".part"
    try:
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
    finally:
        resp.close()
    os.rename(tmp, dest_path)
    return True
