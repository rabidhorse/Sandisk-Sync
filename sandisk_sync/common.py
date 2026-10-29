"""Helpers shared by the podcast and music syncs."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import TextIO

# Leave this much room on the player so it never fills up completely.
FREE_SPACE_RESERVE = 100 * 1024 * 1024

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Make `name` safe to use as a file or folder name on the player's FAT32 drive."""
    name = _INVALID_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:max_length].rstrip(" .")
    return name


def free_bytes(path: Path) -> int:
    return max(0, shutil.disk_usage(path).free - FREE_SPACE_RESERVE)


def format_size(num_bytes: int) -> str:
    if num_bytes >= 1024**3:
        return f"{num_bytes / 1024**3:.1f} GB"
    if num_bytes >= 1024**2:
        return f"{num_bytes / 1024**2:.0f} MB"
    return f"{num_bytes / 1024:.0f} KB"


def remove_empty_dirs(top: Path) -> None:
    """Remove empty folders below `top`, leaving `top` itself in place."""
    for dirpath, _dirnames, _filenames in os.walk(top, topdown=False):
        path = Path(dirpath)
        if path != top:
            try:
                path.rmdir()
            except OSError:
                pass


class Report:
    """Prints what the sync does and keeps counts for the summary.

    In preview mode nothing on the player is changed; callers check `dry_run` before acting.
    """

    def __init__(self, dry_run: bool, out: TextIO | None = None) -> None:
        self.dry_run = dry_run
        self.out = out
        self.counts: dict[str, int] = {}
        self.errors: list[str] = []

    def section(self, title: str) -> None:
        print(f"\n== {title} ==", file=self.out)

    def action(self, kind: str, message: str) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        prefix = "would " if self.dry_run else ""
        print(f"  {prefix}{kind}: {message}", file=self.out)

    def info(self, message: str) -> None:
        print(f"  {message}", file=self.out)

    def error(self, message: str) -> None:
        self.errors.append(message)
        print(f"  ERROR: {message}", file=self.out)


class State:
    """Remembers what was synced, stored on the PC so the player stays clean."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.data = {}

    def section(self, name: str) -> dict:
        return self.data.setdefault(name, {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


def default_state_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "SandiskSync" / "state.json"
    return Path.home() / ".sandisk-sync" / "state.json"
