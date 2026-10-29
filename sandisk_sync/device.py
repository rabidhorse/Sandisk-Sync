"""Finds the player's drive."""

from __future__ import annotations

import os
import string
from pathlib import Path

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
SEM_FAILCRITICALERRORS = 0x0001


def find_player(label: str, drive: str = "") -> Path | None:
    """Return the root of the player, using `drive` if given, otherwise searching by volume label."""
    if drive:
        if len(drive) == 1 and drive.isalpha():
            drive += ":"
        root = Path(drive + "\\" if drive.endswith(":") else drive)
        return root if root.is_dir() else None
    if os.name != "nt":
        return None
    return _find_windows_drive_by_label(label)


def _find_windows_drive_by_label(label: str) -> Path | None:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    # Stop Windows from popping up "insert a disk" dialogs for empty card readers.
    old_mode = kernel32.SetErrorMode(SEM_FAILCRITICALERRORS)
    try:
        drives = kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if not drives & (1 << i):
                continue
            root = f"{letter}:\\"
            # Skip network, CD and RAM drives so a slow network share doesn't hold things up.
            if kernel32.GetDriveTypeW(root) not in (DRIVE_REMOVABLE, DRIVE_FIXED):
                continue
            name = ctypes.create_unicode_buffer(261)
            if kernel32.GetVolumeInformationW(root, name, len(name), None, None, None, None, 0):
                if name.value.strip().casefold() == label.strip().casefold():
                    return Path(root)
    finally:
        kernel32.SetErrorMode(old_mode)
    return None
