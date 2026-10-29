"""Podcast sync: removes old episodes from the player and downloads the newest ones."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlparse

from .common import Report, State, free_bytes, format_size, remove_empty_dirs, sanitize_filename
from .config import Config

USER_AGENT = "SandiskSync/1.0 (+https://github.com/rabidhorse/Sandisk-Sync)"
PODCAST_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wma", ".wav", ".flac"}
MIME_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/x-ms-wma": ".wma",
}
DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


@dataclass
class Episode:
    title: str
    guid: str
    url: str
    published: datetime
    mime: str = ""

    @property
    def day(self) -> date:
        return self.published.astimezone().date()

    def filename(self) -> str:
        # The date prefix is how later syncs tell how old a file on the player is.
        title = sanitize_filename(self.title) or hashlib.sha1(self.guid.encode()).hexdigest()[:10]
        return f"{self.day:%Y-%m-%d} {title}{self.extension()}"

    def extension(self) -> str:
        suffix = PurePosixPath(urlparse(self.url).path).suffix.lower()
        if suffix in PODCAST_EXTENSIONS:
            return suffix
        return MIME_EXTENSIONS.get(self.mime.lower(), ".mp3")


def parse_feed(xml: bytes) -> list[Episode]:
    """Return the feed's episodes, newest first."""
    channel = ET.fromstring(xml).find("channel")
    if channel is None:
        raise ValueError("this doesn't look like a podcast RSS feed")

    episodes = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        url = (enclosure.get("url") or "").strip() if enclosure is not None else ""
        if not url:
            continue
        try:
            published = parsedate_to_datetime((item.findtext("pubDate") or "").strip())
        except (TypeError, ValueError):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        title = (item.findtext("title") or "").strip() or "Untitled episode"
        guid = (item.findtext("guid") or "").strip() or url
        episodes.append(Episode(title, guid, url, published, enclosure.get("type") or ""))

    episodes.sort(key=lambda e: e.published, reverse=True)
    return episodes


def fetch_url(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=60)


def file_date(path: Path) -> date:
    """The episode date from a file name like '2026-10-28 Title.mp3', or the file's modified date."""
    match = DATE_PREFIX.match(path.name)
    if match:
        try:
            return date(int(match[1]), int(match[2]), int(match[3]))
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def sync_podcasts(
    config: Config,
    player_root: Path,
    state: State,
    report: Report,
    today: date | None = None,
    fetch: Callable = fetch_url,
) -> None:
    report.section("Podcasts")
    podcast_dir = player_root / config.podcast_folder
    today = today or date.today()
    cutoff = today - timedelta(days=config.max_age_days)

    _remove_old_episodes(podcast_dir, cutoff, today, report)

    history: dict[str, str] = state.section("podcast_downloads")
    for guid in [g for g, day in history.items() if date.fromisoformat(day) <= cutoff]:
        del history[guid]

    for show in config.shows:
        try:
            with fetch(show.feed) as response:
                episodes = parse_feed(response.read())
        except Exception as exc:
            report.error(f"couldn't read the feed for {show.name}: {exc}")
            continue

        show_dir = podcast_dir / sanitize_filename(show.name)
        on_player = {p.name.casefold() for p in show_dir.iterdir()} if show_dir.is_dir() else set()
        newest = [e for e in episodes if e.day > cutoff][: config.episodes_per_show]

        wanted = []
        for episode in newest:
            if episode.guid in history:
                continue  # Downloaded on an earlier sync; if it's gone, it was removed on purpose.
            if episode.filename().casefold() in on_player:
                history[episode.guid] = episode.day.isoformat()
                continue
            wanted.append(episode)

        if not wanted:
            report.info(f"{show.name}: up to date")
            continue

        for episode in wanted:
            report.action("download", f"{show.name} / {episode.filename()}")
            if report.dry_run:
                continue
            try:
                _download(episode.url, show_dir / episode.filename(), player_root, fetch)
            except Exception as exc:
                report.error(f"download failed for '{episode.title}': {exc}")
                continue
            history[episode.guid] = episode.day.isoformat()
            state.save()


def _remove_old_episodes(podcast_dir: Path, cutoff: date, today: date, report: Report) -> None:
    if not podcast_dir.is_dir():
        return
    for path in sorted(podcast_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name.endswith(".part"):
            # Left over from a download that was interrupted.
            if not report.dry_run:
                path.unlink(missing_ok=True)
            continue
        if path.suffix.lower() not in PODCAST_EXTENSIONS:
            continue
        day = file_date(path)
        if day <= cutoff:
            report.action("remove", f"{path.relative_to(podcast_dir)} ({(today - day).days} days old)")
            if not report.dry_run:
                path.unlink()
    if not report.dry_run:
        remove_empty_dirs(podcast_dir)


def _download(url: str, dest: Path, player_root: Path, fetch: Callable) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with fetch(url) as response, open(part, "wb") as out:
            length = response.headers.get("Content-Length")
            if length and int(length) > free_bytes(player_root):
                raise OSError(f"not enough space on the player ({format_size(int(length))} needed)")
            shutil.copyfileobj(response, out, 1024 * 1024)
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
