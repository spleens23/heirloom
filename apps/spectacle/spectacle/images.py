"""Thumbnail loading with a disk cache, off the main thread."""

from __future__ import annotations

import hashlib
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from gi.repository import Gdk, GLib

from .paths import THUMB_DIR

_pool = ThreadPoolExecutor(max_workers=6)
_memory: dict[str, Gdk.Texture] = {}
_lock = threading.Lock()


def _cache_path(url: str):
    return THUMB_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".img")


def _fetch(url: str) -> str | None:
    path = _cache_path(url)
    if path.exists() and path.stat().st_size > 0:
        return str(path)
    if url.startswith("file://") or url.startswith("/"):
        return url.removeprefix("file://")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        tmp = path.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return str(path)
    except Exception:
        return None


def load(url: str, callback) -> None:
    """Calls callback(texture) on the main thread once the image is ready."""
    if not url:
        return
    with _lock:
        tex = _memory.get(url)
    if tex is not None:
        callback(tex)
        return

    def work():
        path = _fetch(url)
        if not path:
            return
        try:
            tex = Gdk.Texture.new_from_filename(path)
        except GLib.Error:
            return
        with _lock:
            if len(_memory) > 400:
                _memory.clear()
            _memory[url] = tex
        GLib.idle_add(lambda: (callback(tex), False)[1])

    _pool.submit(work)
