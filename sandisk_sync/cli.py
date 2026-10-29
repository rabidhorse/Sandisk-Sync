"""Command line entry point: python -m sandisk_sync [--dry-run]"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .common import Report, State, default_state_path, format_size
from .config import load_config
from .device import find_player
from .music import sync_music
from .podcasts import sync_podcasts

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.toml"
DONE = {"copy": "Copied", "download": "Downloaded", "remove": "Removed"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sandisk_sync",
        description="Sync podcasts and music to a SanDisk Clip Sport Plus.",
    )
    parser.add_argument(
        "--dry-run", "--preview", action="store_true",
        help="show what would be removed, downloaded and copied without changing the player",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="settings file to use")
    parser.add_argument("--drive", help="the player's drive (for example E:), instead of searching by name")
    parser.add_argument("--skip-podcasts", action="store_true", help="only sync music")
    parser.add_argument("--skip-music", action="store_true", help="only sync podcasts")
    parser.add_argument("--state", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    # Episode titles can contain characters the Windows console can't show; don't crash on them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    config = load_config(args.config)
    root = find_player(config.player_label, args.drive or config.player_drive)
    if root is None:
        print(f"Couldn't find the player (a drive named '{config.player_label}'). Is it plugged in?")
        return 1

    report = Report(dry_run=args.dry_run)
    print(f"Found the player at {root}")
    if args.dry_run:
        print("Preview only: nothing on the player will be changed.")

    state = State(args.state or default_state_path())
    try:
        if not args.skip_podcasts:
            sync_podcasts(config, root, state, report)
        if not args.skip_music:
            sync_music(config, root, state, report)
    except KeyboardInterrupt:
        print("\nStopped before finishing. Run it again to pick up where it left off.")
        return 130
    finally:
        if not args.dry_run:
            state.save()

    _print_summary(report, root)
    return 1 if report.errors else 0


def _print_summary(report: Report, root: Path) -> None:
    print("\n== Summary ==")
    if report.counts:
        for kind, count in sorted(report.counts.items()):
            label = f"Would {kind}" if report.dry_run else DONE.get(kind, kind)
            print(f"  {label}: {count} file{'s' if count != 1 else ''}")
    else:
        print("  Everything was already up to date.")
    print(f"  Free space on the player: {format_size(shutil.disk_usage(root).free)}")
    if report.errors:
        print(f"  {len(report.errors)} problem{'s' if len(report.errors) != 1 else ''}; see ERROR lines above.")
