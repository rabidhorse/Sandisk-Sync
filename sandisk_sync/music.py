"""Music sync: makes the player's Music folder a mirror of the music folder on the PC."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .common import Report, State, format_size, free_bytes, remove_empty_dirs
from .config import Config


def sync_music(config: Config, player_root: Path, state: State, report: Report) -> None:
    report.section("Music")
    source = Path(config.music_source)
    dest = player_root / config.music_folder
    skipped = "so music was skipped and nothing on the player was removed"

    # Never mirror from a source we can't fully see, or every song on the player would be deleted.
    if not source.is_dir():
        report.error(f"can't reach {source}, {skipped}")
        return
    try:
        source_files = _scan(source, config.music_extensions, strict=True)
    except OSError as exc:
        report.error(f"couldn't read all of {source} ({exc}), {skipped}")
        return
    if not source_files:
        report.error(f"found no music files in {source}, {skipped}")
        return

    if not report.dry_run and dest.is_dir():
        for part in dest.rglob("*.part"):
            part.unlink(missing_ok=True)  # Left over from a copy that was interrupted.
    player_files = _scan(dest, config.music_extensions, strict=False) if dest.is_dir() else {}

    # What was copied last time, by path: [size, modified time] of the PC's file at that point.
    copied: dict[str, list[int]] = state.section("music_copied")
    for key in [k for k in copied if k not in source_files]:
        del copied[key]

    freed = 0
    for key in sorted(k for k in player_files if k not in source_files):
        path = player_files[key]
        report.action("remove", str(path.relative_to(dest)))
        freed += path.stat().st_size
        if not report.dry_run:
            try:
                path.unlink()
            except OSError as exc:
                report.error(f"couldn't remove {path}: {exc}")
    if not report.dry_run:
        remove_empty_dirs(dest)

    to_copy = []
    for key, src in sorted(source_files.items()):
        stat = src.stat()
        signature = [stat.st_size, stat.st_mtime_ns]
        on_player = player_files.get(key)
        if on_player is not None:
            if copied.get(key) == signature:
                continue
            if key not in copied and on_player.stat().st_size == stat.st_size:
                # Already on the player from before this program was used.
                copied[key] = signature
                continue
        to_copy.append((key, src, signature))

    if not to_copy:
        report.info("up to date")
        return

    needed = sum(signature[0] for _, _, signature in to_copy)
    available = free_bytes(player_root) + (freed if report.dry_run else 0)
    if needed > available:
        report.info(
            f"{format_size(needed)} of music to copy but only {format_size(available)} free, "
            "so some files won't fit"
        )

    for index, (key, src, signature) in enumerate(to_copy):
        relative = src.relative_to(source)
        report.action("copy", str(relative))
        if report.dry_run:
            continue
        target = dest / relative
        replacing = target.stat().st_size if target.exists() else 0
        if signature[0] > free_bytes(player_root) + replacing:
            left = to_copy[index:]
            report.error(
                f"the player is full: {len(left)} files ({format_size(sum(s[0] for _, _, s in left))}) "
                "were not copied"
            )
            break
        try:
            _copy(src, target)
        except OSError as exc:
            report.error(f"couldn't copy {relative}: {exc}")
            continue
        copied[key] = signature


def _scan(top: Path, extensions: tuple[str, ...], strict: bool) -> dict[str, Path]:
    """Map each audio file's path relative to `top` (lowercased, for Windows) to its full path."""

    def fail(error: OSError) -> None:
        raise error

    files = {}
    for dirpath, dirnames, filenames in os.walk(top, onerror=fail if strict else None):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            # Skip the "._song.mp3" metadata files macOS leaves behind; they aren't playable.
            if name.startswith("._") or os.path.splitext(name)[1].lower() not in extensions:
                continue
            path = Path(dirpath, name)
            files[path.relative_to(top).as_posix().casefold()] = path
    return files


def _copy(src: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    try:
        shutil.copyfile(src, part)
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
