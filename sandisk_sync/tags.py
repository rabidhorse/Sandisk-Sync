"""Reads and sets the album name in an MP3's ID3 tag, using only the standard library.

The player's Podcasts menu groups episodes by album, so every episode needs its show's name
there. Some feeds (NPR's, for example) leave it out, and the player then lists them as
"Unknown Album".
"""

from __future__ import annotations

import os
import shutil
import struct
from pathlib import Path

ALBUM_FRAMES = {b"TALB", b"TAL"}
PADDING = 1024
_FRAME_ID_CHARS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


class TagError(Exception):
    pass


def _syncsafe(data: bytes) -> int:
    return (data[0] << 21) | (data[1] << 14) | (data[2] << 7) | data[3]


def _to_syncsafe(value: int) -> bytes:
    return bytes([(value >> 21) & 0x7F, (value >> 14) & 0x7F, (value >> 7) & 0x7F, value & 0x7F])


class _Tag:
    """The ID3v2 tag at the start of a file, split into frames."""

    def __init__(self, version: int, frames: list[tuple[bytes, bytes, bytes]], region: int) -> None:
        self.version = version  # 2, 3 or 4 (ID3v2.x)
        self.frames = frames  # (frame id, flags, data); flags is b"" for v2.2
        self.region = region  # bytes the tag takes up at the start of the file, padding included

    @property
    def id_length(self) -> int:
        return 3 if self.version == 2 else 4


def _read_tag(path: Path) -> _Tag | None:
    with open(path, "rb") as f:
        header = f.read(10)
        if len(header) < 10 or header[:3] != b"ID3":
            return None
        version, flags = header[3], header[5]
        if version not in (2, 3, 4):
            raise TagError(f"unsupported ID3v2.{version} tag")
        size = _syncsafe(header[6:10])
        body = f.read(size)
    if len(body) < size:
        raise TagError("the ID3 tag is cut short")

    region = 10 + size + (10 if version == 4 and flags & 0x10 else 0)
    if version == 2 and flags & 0x40:
        raise TagError("compressed ID3v2.2 tag")
    if version == 3 and flags & 0x80:
        # Whole-tag unsynchronisation: undo it so the frames can be read; the new tag won't use it.
        body = body.replace(b"\xff\x00", b"\xff")
    if version in (3, 4) and flags & 0x40:
        ext = struct.unpack(">I", body[:4])[0] if version == 3 else _syncsafe(body[:4])
        body = body[(ext + 4 if version == 3 else ext):]

    id_len, head_len = (3, 6) if version == 2 else (4, 10)
    frames, pos = [], 0
    while pos + head_len <= len(body):
        frame_id = body[pos : pos + id_len]
        if not all(c in _FRAME_ID_CHARS for c in frame_id):
            break  # padding, or garbage after the last frame
        raw_size = body[pos + id_len : pos + id_len + (3 if version == 2 else 4)]
        if version == 2:
            frame_size = int.from_bytes(raw_size, "big")
        elif version == 3:
            frame_size = struct.unpack(">I", raw_size)[0]
        else:
            frame_size = _syncsafe(raw_size)
        frame_flags = b"" if version == 2 else body[pos + 8 : pos + 10]
        data = body[pos + head_len : pos + head_len + frame_size]
        if len(data) < frame_size:
            break
        frames.append((frame_id, frame_flags, data))
        pos += head_len + frame_size
    return _Tag(version, frames, region)


def _decode_text(data: bytes) -> str:
    if not data:
        return ""
    encoding, text = data[0], data[1:]
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(encoding, "latin-1")
    return text.decode(codec, errors="replace").split("\x00")[0].strip()


def _encode_text(text: str) -> bytes:
    try:
        return b"\x00" + text.encode("latin-1")
    except UnicodeEncodeError:
        return b"\x01" + text.encode("utf-16")  # with a byte-order mark; valid in every ID3v2 version


def read_album(path: Path) -> str:
    """The album name in the file's ID3v2 tag, or '' when there isn't one."""
    tag = _read_tag(path)
    if tag is None:
        return ""
    for frame_id, flags, data in tag.frames:
        # Skip frames stored in a way we don't decode (compressed, encrypted, or in v2.4
        # unsynchronised / length-prefixed); treating them as blank just means they get rewritten.
        if frame_id in ALBUM_FRAMES and not (flags and flags[1] & 0xCF):
            return _decode_text(data)
    return ""


def set_album(path: Path, album: str) -> None:
    """Write `album` into the file's ID3v2 tag, keeping every other frame as it was."""
    tag = _read_tag(path) or _Tag(3, [], 0)
    album_id = b"TAL" if tag.version == 2 else b"TALB"
    text = _encode_text(album)
    frames = [f for f in tag.frames if f[0] not in ALBUM_FRAMES]
    frames.insert(0, (album_id, b"" if tag.version == 2 else b"\x00\x00", text))

    body = bytearray()
    for frame_id, flags, data in frames:
        if tag.version == 2:
            body += frame_id + len(data).to_bytes(3, "big") + data
        elif tag.version == 3:
            body += frame_id + struct.pack(">I", len(data)) + flags + data
        else:
            body += frame_id + _to_syncsafe(len(data)) + flags + data

    if 10 + len(body) <= tag.region:
        # Fits in the space the old tag used: overwrite it in place, no need to copy the audio.
        body += b"\x00" * (tag.region - 10 - len(body))
        with open(path, "r+b") as f:
            f.write(b"ID3" + bytes([tag.version, 0, 0]) + _to_syncsafe(len(body)) + body)
        return

    body += b"\x00" * PADDING
    new_header = b"ID3" + bytes([tag.version, 0, 0]) + _to_syncsafe(len(body))
    tmp = path.with_name(path.name + ".part")
    try:
        with open(path, "rb") as src, open(tmp, "wb") as out:
            out.write(new_header + body)
            src.seek(tag.region)
            shutil.copyfileobj(src, out, 1024 * 1024)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
