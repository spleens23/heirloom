"""Your personal library: subscriptions, Watch Later, downloads and history.

Everything is stored locally in one JSON file. No account, no cloud.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from typing import Callable

from .models import Channel, Video
from .paths import LIBRARY_FILE


class Library:
    def __init__(self, path=LIBRARY_FILE):
        self.path = path
        self.subscriptions: list[Channel] = []
        self.watch_later: list[Video] = []
        self.downloads: list[Video] = []
        self.history: list[Video] = []
        self.positions: dict[str, float] = {}  # resume points, seconds
        self._listeners: list[Callable[[str], None]] = []
        self.load()

    # ---- change notifications (the UI refreshes on these) --------------
    def connect(self, fn: Callable[[str], None]) -> None:
        self._listeners.append(fn)

    def _changed(self, what: str) -> None:
        self.save()
        for fn in list(self._listeners):
            fn(what)

    # ---- persistence ----------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            # Keep a copy of a damaged file instead of silently losing it.
            self.path.rename(self.path.with_suffix(".broken.json"))
            return
        self.subscriptions = [Channel.from_dict(c) for c in data.get("subscriptions", [])]
        self.watch_later = [Video.from_dict(v) for v in data.get("watch_later", [])]
        self.downloads = [Video.from_dict(v) for v in data.get("downloads", [])]
        self.history = [Video.from_dict(v) for v in data.get("history", [])]
        self.positions = dict(data.get("positions", {}))
        # Forget downloads whose files were deleted outside the app.
        self.downloads = [v for v in self.downloads if v.local_path and os.path.exists(v.local_path)]

    def save(self) -> None:
        data = {
            "subscriptions": [c.to_dict() for c in self.subscriptions],
            "watch_later": [v.to_dict() for v in self.watch_later],
            "downloads": [v.to_dict() for v in self.downloads],
            "history": [v.to_dict() for v in self.history[:200]],
            "positions": self.positions,
        }
        # Write atomically so a crash never corrupts the library.
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    # ---- subscriptions --------------------------------------------------
    def is_subscribed(self, channel_id: str) -> bool:
        return any(c.id == channel_id for c in self.subscriptions)

    def subscribe(self, channel: Channel) -> None:
        if not self.is_subscribed(channel.id):
            self.subscriptions.append(Channel(channel.id, channel.name, channel.avatar))
            self.subscriptions.sort(key=lambda c: c.name.lower())
            self._changed("subscriptions")

    def unsubscribe(self, channel_id: str) -> None:
        self.subscriptions = [c for c in self.subscriptions if c.id != channel_id]
        self._changed("subscriptions")

    def import_takeout_csv(self, path: str) -> int:
        """Import subscriptions.csv from a Google Takeout export.

        Columns are: Channel Id, Channel Url, Channel Title.
        """
        added = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) < 3 or not row[0].startswith("UC"):
                    continue  # skips the header and blank lines
                cid, _url, title = row[0].strip(), row[1], row[2].strip()
                if not self.is_subscribed(cid):
                    self.subscriptions.append(Channel(cid, title))
                    added += 1
        self.subscriptions.sort(key=lambda c: c.name.lower())
        self._changed("subscriptions")
        return added

    # ---- watch later ----------------------------------------------------
    def in_watch_later(self, video_id: str) -> bool:
        return any(v.id == video_id for v in self.watch_later)

    def toggle_watch_later(self, video: Video) -> bool:
        """Returns True if the video is now saved."""
        if self.in_watch_later(video.id):
            self.watch_later = [v for v in self.watch_later if v.id != video.id]
            saved = False
        else:
            self.watch_later.insert(0, Video.from_dict(video.to_dict()))
            saved = True
        self._changed("watch_later")
        return saved

    # ---- downloads ------------------------------------------------------
    def downloaded(self, video_id: str) -> Video | None:
        return next((v for v in self.downloads if v.id == video_id), None)

    def add_download(self, video: Video) -> None:
        self.downloads = [v for v in self.downloads if v.id != video.id]
        self.downloads.insert(0, video)
        self._changed("downloads")

    def remove_download(self, video_id: str) -> None:
        v = self.downloaded(video_id)
        if v and v.local_path:
            try:
                os.remove(v.local_path)
            except OSError:
                pass
        self.downloads = [d for d in self.downloads if d.id != video_id]
        self._changed("downloads")

    # ---- history & resume points ---------------------------------------
    def record_watch(self, video: Video) -> None:
        self.history = [v for v in self.history if v.id != video.id]
        self.history.insert(0, Video.from_dict(video.to_dict()))
        self._changed("history")

    def set_position(self, video_id: str, seconds: float, duration: float | None) -> None:
        # Forget the spot once you're basically at the end.
        if duration and seconds > duration - 15:
            self.positions.pop(video_id, None)
        elif seconds > 10:
            self.positions[video_id] = round(seconds, 1)
        self.save()
