"""Loads config.toml into plain dataclasses."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Show:
    name: str
    feed: str


@dataclass
class Config:
    player_label: str = "SPORT PLUS"
    player_drive: str = ""
    music_source: str = r"Y:\Media\Music"
    music_folder: str = "Music"
    music_extensions: tuple[str, ...] = (".mp3", ".m4a", ".aac", ".wma", ".wav", ".flac")
    podcast_folder: str = "Podcasts"
    max_age_days: int = 60
    episodes_per_show: int = 5
    shows: list[Show] = field(default_factory=list)


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    player = data.get("player", {})
    music = data.get("music", {})
    podcasts = data.get("podcasts", {})
    defaults = Config()

    shows = [Show(name=s["name"], feed=s["feed"]) for s in podcasts.get("shows", [])]
    extensions = music.get("extensions", defaults.music_extensions)

    config = Config(
        player_label=player.get("label", defaults.player_label),
        player_drive=player.get("drive", defaults.player_drive),
        music_source=music.get("source", defaults.music_source),
        music_folder=music.get("folder", defaults.music_folder),
        music_extensions=tuple(e.lower() if e.startswith(".") else "." + e.lower() for e in extensions),
        podcast_folder=podcasts.get("folder", defaults.podcast_folder),
        max_age_days=int(podcasts.get("max_age_days", defaults.max_age_days)),
        episodes_per_show=int(podcasts.get("episodes_per_show", defaults.episodes_per_show)),
        shows=shows,
    )
    if config.max_age_days < 1:
        raise ValueError("podcasts.max_age_days must be at least 1")
    if config.episodes_per_show < 0:
        raise ValueError("podcasts.episodes_per_show can't be negative")
    return config
