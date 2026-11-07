import struct
import tempfile
import unittest
from pathlib import Path

from sandisk_sync.tags import read_album, set_album

AUDIO = b"\xff\xfb\x90\x00" + bytes(range(256)) * 4


def syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def frame(version, frame_id, text):
    data = b"\x00" + text.encode("latin-1")
    size = struct.pack(">I", len(data)) if version == 3 else syncsafe(len(data))
    return frame_id + size + b"\x00\x00" + data


def tag(version, frames, padding=0):
    body = b"".join(frames) + b"\x00" * padding
    return b"ID3" + bytes([version, 0, 0]) + syncsafe(len(body)) + body


class TagTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name, "episode.mp3")

    def tearDown(self):
        self.tmp.cleanup()

    def frames_after(self):
        data = self.path.read_bytes()
        return data, data[10 : 10 + int.from_bytes(data[6:10], "big")]

    def test_adds_a_tag_to_a_file_without_one(self):
        self.path.write_bytes(AUDIO)
        self.assertEqual(read_album(self.path), "")

        set_album(self.path, "The Best of Car Talk")

        self.assertEqual(read_album(self.path), "The Best of Car Talk")
        self.assertTrue(self.path.read_bytes().endswith(AUDIO))

    def test_replaces_the_album_and_keeps_other_frames(self):
        for version in (3, 4):
            with self.subTest(version=version):
                original = tag(version, [frame(version, b"TIT2", "Episode 1"), frame(version, b"TALB", "NPR")])
                self.path.write_bytes(original + AUDIO)

                set_album(self.path, "The Best of Car Talk")

                data = self.path.read_bytes()
                self.assertEqual(read_album(self.path), "The Best of Car Talk")
                self.assertEqual(data[3], version)
                self.assertIn(b"Episode 1", data)
                self.assertNotIn(b"NPR", data)
                self.assertTrue(data.endswith(AUDIO))

    def test_reuses_padding_instead_of_rewriting_the_file(self):
        original = tag(3, [frame(3, b"TIT2", "Episode 1")], padding=200)
        self.path.write_bytes(original + AUDIO)

        set_album(self.path, "The Best of Car Talk")

        data = self.path.read_bytes()
        self.assertEqual(len(data), len(original) + len(AUDIO))
        self.assertEqual(read_album(self.path), "The Best of Car Talk")
        self.assertTrue(data.endswith(AUDIO))

    def test_names_outside_latin1_survive(self):
        self.path.write_bytes(AUDIO)
        set_album(self.path, "Café Ñ — 東京")
        self.assertEqual(read_album(self.path), "Café Ñ — 東京")

    def test_no_leftover_temp_file(self):
        self.path.write_bytes(AUDIO)
        set_album(self.path, "Show")
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["episode.mp3"])


if __name__ == "__main__":
    unittest.main()
