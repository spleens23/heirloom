"""Offline downloads, run in the background with yt-dlp."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from gi.repository import GLib

from .models import Video
from .paths import DOWNLOAD_DIR

# Up to 1080p. VP9/AV1 + Opus is preferred because Fedora can play those with
# its default codecs. Everything is merged into one .mkv file (needs ffmpeg).
FORMAT = "bv*[height<=1080][vcodec!^=avc1]+ba[acodec=opus]/bv*[height<=1080]+ba/b[height<=1080]/b"


@dataclass
class Job:
    video: Video
    progress: float = 0.0  # 0..1
    status: str = "Waiting…"
    done: bool = False
    failed: bool = False
    cancelled: bool = False


class Cancelled(Exception):
    pass


class DownloadManager:
    def __init__(self, library):
        self.library = library
        self.jobs: dict[str, Job] = {}
        self._listeners = []
        self._sem = threading.Semaphore(2)  # two at a time keeps Wi-Fi responsive

    def connect(self, fn) -> None:
        self._listeners.append(fn)

    def _notify(self, job: Job) -> None:
        def emit():
            for fn in list(self._listeners):
                fn(job)
            return False
        GLib.idle_add(emit)

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if not j.done]

    def start(self, video: Video) -> Job | None:
        if self.library.downloaded(video.id):
            return None
        existing = self.jobs.get(video.id)
        if existing and not existing.done:
            return existing
        job = Job(Video.from_dict(video.to_dict()))
        self.jobs[video.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        self._notify(job)
        return job

    def cancel(self, video_id: str) -> None:
        job = self.jobs.get(video_id)
        if job and not job.done:
            job.cancelled = True

    def _run(self, job: Job) -> None:
        import yt_dlp

        def hook(d):
            if job.cancelled:
                raise Cancelled()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                got = d.get("downloaded_bytes") or 0
                part = (got / total) if total else 0
                # Video and audio download separately: weight video as 85%.
                is_audio = (d.get("info_dict") or {}).get("vcodec") == "none"
                job.progress = 0.85 + 0.15 * part if is_audio else 0.85 * part
                speed = d.get("speed")
                job.status = f"{job.progress * 100:.0f}%" + (f" · {speed / 1e6:.1f} MB/s" if speed else "")
                self._notify(job)
            elif d.get("status") == "finished":
                job.status = "Finishing…"
                self._notify(job)

        with self._sem:
            if job.cancelled:
                return self._finish(job, cancelled=True)
            job.status = "Starting…"
            self._notify(job)
            opts = {
                "quiet": True,
                "no_warnings": True,
                "format": FORMAT,
                "merge_output_format": "mkv",
                "outtmpl": str(DOWNLOAD_DIR / "%(title).120B [%(id)s].%(ext)s"),
                "progress_hooks": [hook],
                "writethumbnail": False,
                "noplaylist": True,
            }
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(job.video.url, download=True)
                    path = None
                    if info.get("requested_downloads"):
                        path = info["requested_downloads"][0].get("filepath")
                    path = path or ydl.prepare_filename(info)
                job.video.local_path = path
                job.video.duration = job.video.duration or info.get("duration")
                job.video.channel = job.video.channel or info.get("channel", "")
                job.video.channel_id = job.video.channel_id or info.get("channel_id", "")
                self._finish(job)
            except Cancelled:
                self._finish(job, cancelled=True)
            except Exception as e:  # network trouble, removed video, missing ffmpeg…
                job.status = _friendly(str(e))
                self._finish(job, failed=True)

    def _finish(self, job: Job, failed=False, cancelled=False) -> None:
        job.done = True
        job.failed = failed
        job.cancelled = cancelled
        if not failed and not cancelled:
            job.progress = 1.0
            job.status = "Downloaded"
            GLib.idle_add(lambda: (self.library.add_download(job.video), False)[1])
        elif cancelled:
            job.status = "Cancelled"
            self.jobs.pop(job.video.id, None)
        self._notify(job)


def _friendly(msg: str) -> str:
    low = msg.lower()
    if "ffmpeg" in low:
        return "Needs ffmpeg — run the installer again"
    if "private" in low or "unavailable" in low:
        return "This video isn't available"
    if "network" in low or "timed out" in low or "resolve" in low:
        return "No connection — try again"
    return "Download failed — try updating yt-dlp"
