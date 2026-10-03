# -*- coding: utf-8 -*-
"""Shared Google Photos album, without OAuth.

The link (photos.app.goo.gl or photos.google.com/share) belongs to the album owner.
list_album() only reads the album page (the list of photos, videos left out); each photo is
downloaded on its own with download_image(), just before the wall needs it (see library.py).

This file is shared by the Raspberry Pi app (pi/album.py in jpch/Lumen-wallframe) and the
Home Assistant integration (custom_components/lume/album.py in jpch/lumen-wallframe-ha).
Keep the two copies identical. Python 3.6 compatible.
"""
import os
import re
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/72.0.3626.121 Safari/537.36"
)
ALLOWED_HOSTS = ("photos.app.goo.gl", "photos.google.com")
PHOTO_RE = re.compile(
    r'\["(AF1Qip[^"\\]+)",\["(https://lh3\.googleusercontent\.com/[^"\\]+)",(\d+),(\d+)'
)
# Video signals inside a page item. The item's URL is the video's poster image,
# so the whole item is read and dropped if it has:
# - the "76647426" entry (duration, size and video URL), which Google Photos only adds to videos;
# - a "=dv" URL (video download);
# - a video/... MIME type.
VIDEO_SIGNALS = (
    re.compile(r'"76647426"\s*:'),
    re.compile(r'=dv(?:[-"\\&]|$)'),
    re.compile(r'"video/[A-Za-z0-9.+-]+"'),
)


class AlbumError(Exception):
    """An album problem to show to the user. key picks the translated text ("err_" + key)."""

    def __init__(self, key, message):
        Exception.__init__(self, message)
        self.key = key


def validate_share_url(url):
    raw = (url or "").strip()
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in ALLOWED_HOSTS:
        raise AlbumError(
            "bad_link", "O link tem de ser de um álbum partilhado: photos.app.goo.gl ou photos.google.com/share."
        )
    if host == "photos.google.com" and not parsed.path.startswith("/share/"):
        raise AlbumError("not_shared", "Abre o álbum, escolhe Partilhar e copia o link, não o endereço da tua biblioteca.")
    return raw


def _read(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt,en;q=0.8"})
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        raw = resp.read()
    finally:
        resp.close()
    return raw.decode("utf-8", "replace")


def item_text(page, start, limit=64000):
    """Text of the JSON array that opens at start (respects strings and escapes)."""
    depth = 0
    in_string = False
    escaped = False
    end = min(len(page), start + limit)
    for i in range(start, end):
        ch = page[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return page[start:i + 1]
    return page[start:end]


def is_video(item_json):
    return any(rx.search(item_json) for rx in VIDEO_SIGNALS)


def parse_album_page(page):
    """Photos only: an id that shows up as a video anywhere on the page is left out."""
    matches = list(PHOTO_RE.finditer(page))
    videos = set(m.group(1) for m in matches if is_video(item_text(page, m.start())))
    found = []
    seen = set()
    for m in matches:
        uid, remote, width, height = m.groups()
        if uid in videos or uid in seen:
            continue
        w = int(width)
        h = int(height)
        if w < 1 or h < 1:
            continue
        seen.add(uid)
        found.append({"id": uid, "remote": remote, "w": w, "h": h})
    return found


def list_album(share_url):
    found = parse_album_page(_read(validate_share_url(share_url)))
    if not found:
        raise AlbumError(
            "empty", "Não encontrei fotos. Confirma que o álbum está partilhado com «qualquer pessoa com o link»."
        )
    return found


def sized_url(remote, edge=1280):
    """Google's size suffix: the photo comes back with its longest side at most `edge` px."""
    edge = int(edge)
    return remote.split("=")[0] + "=w%d-h%d" % (edge, edge)


def safe_name(uid):
    keep = "".join(ch for ch in uid if ch.isalnum())
    return (keep or "foto")[:80]


def download_image(remote, dest_path, edge=1280):
    host = (urllib.parse.urlparse(remote).hostname or "").lower()
    if not host.endswith("googleusercontent.com"):
        raise AlbumError("bad_photo_url", "Endereço de foto inesperado.")
    req = urllib.request.Request(sized_url(remote, edge), headers={"User-Agent": UA})
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
    try:
        with open(tmp, "rb") as fh:
            magic = fh.read(3)
    except OSError:
        magic = b""
    if magic[:2] != b"\xff\xd8" and magic != b"\x89PN":
        os.remove(tmp)
        raise AlbumError("not_image", "O Google não devolveu uma imagem.")
    os.rename(tmp, dest_path)

