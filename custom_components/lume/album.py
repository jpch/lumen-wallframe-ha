# -*- coding: utf-8 -*-
"""Shared Google Photos album, without OAuth.

The link (photos.app.goo.gl or photos.google.com/share) belongs to the album owner.
The photos are downloaded to disk before the wall shows them.
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
    pass


def validate_share_url(url):
    raw = (url or "").strip()
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in ALLOWED_HOSTS:
        raise AlbumError(
            "O link tem de ser de um álbum partilhado: photos.app.goo.gl ou photos.google.com/share."
        )
    if host == "photos.google.com" and not parsed.path.startswith("/share/"):
        raise AlbumError("Abre o álbum, escolhe Partilhar e copia o link, não o endereço da tua biblioteca.")
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
            "Não encontrei fotos. Confirma que o álbum está partilhado com «qualquer pessoa com o link»."
        )
    return found


def sized_url(remote):
    return remote.split("=")[0] + "=w1280-h1280"


def safe_name(uid):
    keep = "".join(ch for ch in uid if ch.isalnum())
    return (keep or "foto")[:80]


def download_image(remote, dest_path):
    host = (urllib.parse.urlparse(remote).hostname or "").lower()
    if not host.endswith("googleusercontent.com"):
        raise AlbumError("Endereço de foto inesperado.")
    req = urllib.request.Request(sized_url(remote), headers={"User-Agent": UA})
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
        raise AlbumError("O Google não devolveu uma imagem.")
    os.rename(tmp, dest_path)


def sync_album(share_url, cache_dir, progress=None):
    """Downloads everything and only then returns the list. The caller writes the manifest at the end."""
    remote = list_album(share_url)
    if not os.path.isdir(cache_dir):
        os.makedirs(cache_dir)
    saved = []
    total = len(remote)
    for index, item in enumerate(remote):
        if progress:
            progress(index, total)
        dest = os.path.join(cache_dir, safe_name(item["id"]) + ".jpg")
        if not os.path.isfile(dest) or os.path.getsize(dest) < 800:
            download_image(item["remote"], dest)
        saved.append({"id": item["id"], "file": dest, "w": item["w"], "h": item["h"], "name": os.path.basename(dest)})
    keep = set(os.path.basename(item["file"]) for item in saved)
    for name in os.listdir(cache_dir):
        if name.endswith(".jpg") and name not in keep:
            try:
                os.remove(os.path.join(cache_dir, name))
            except OSError:
                pass
    return saved
