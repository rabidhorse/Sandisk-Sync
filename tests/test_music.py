import io
import os
import tempfile
import unittest
from pathlib import Path

from sandisk_sync.common import Report, State
from sandisk_sync.config import Config
from sandisk_sync.music import sync_music


class SyncMusicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.source = base / "Music on PC"
        self.root = base / "player"
        self.dest = self.root / "Music"
        self.source.mkdir()
        self.root.mkdir()
        self.state = State(base / "state.json")
        self.config = Config(music_source=str(self.source))

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, top: Path, relative: str, data: bytes = b"song") -> Path:
        path = top / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def player_files(self) -> list[str]:
        if not self.dest.exists():
            return []
        return sorted(p.relative_to(self.dest).as_posix() for p in self.dest.rglob("*") if p.is_file())

    def run_sync(self, dry_run=False) -> Report:
        report = Report(dry_run=dry_run, out=io.StringIO())
        sync_music(self.config, self.root, self.state, report)
        return report

    def test_copies_audio_from_all_subfolders(self):
        self.add(self.source, "Artist/Album/01 Song.mp3")
        self.add(self.source, "Artist/Album/02 Song.flac")
        self.add(self.source, "Loose Song.m4a")
        self.add(self.source, "Artist/Album/cover.jpg")
        self.add(self.source, "Artist/Album/._01 Song.mp3")

        self.run_sync()

        self.assertEqual(
            self.player_files(),
            ["Artist/Album/01 Song.mp3", "Artist/Album/02 Song.flac", "Loose Song.m4a"],
        )

    def test_second_run_copies_nothing(self):
        self.add(self.source, "Artist/Song.mp3")
        self.run_sync()

        report = self.run_sync()

        self.assertEqual(report.counts, {})

    def test_removes_songs_deleted_from_the_pc(self):
        self.add(self.source, "Keep/Song.mp3")
        gone = self.add(self.source, "Gone/Song.mp3")
        self.run_sync()
        gone.unlink()

        report = self.run_sync()

        self.assertEqual(report.counts, {"remove": 1})
        self.assertEqual(self.player_files(), ["Keep/Song.mp3"])
        self.assertFalse((self.dest / "Gone").exists())

    def test_recopies_songs_that_changed(self):
        song = self.add(self.source, "Song.mp3", b"old")
        self.run_sync()
        song.write_bytes(b"new and longer")
        os.utime(song, (song.stat().st_atime, song.stat().st_mtime + 10))

        report = self.run_sync()

        self.assertEqual(report.counts, {"copy": 1})
        self.assertEqual((self.dest / "Song.mp3").read_bytes(), b"new and longer")

    def test_keeps_matching_songs_already_on_the_player(self):
        self.add(self.source, "Song.mp3", b"same")
        self.add(self.dest, "Song.mp3", b"same")

        report = self.run_sync()

        self.assertEqual(report.counts, {})

    def test_leaves_other_player_folders_alone(self):
        self.add(self.source, "Song.mp3")
        book = self.add(self.root, "Audible/Book.aax")
        episode = self.add(self.root, "Podcasts/Show/2026-10-28 Episode.mp3")

        self.run_sync()

        self.assertTrue(book.exists())
        self.assertTrue(episode.exists())

    def test_does_nothing_when_the_music_folder_is_unreachable(self):
        self.add(self.dest, "Song.mp3")
        self.config.music_source = str(Path(self.tmp.name, "Y drive not connected"))

        report = self.run_sync()

        self.assertEqual(self.player_files(), ["Song.mp3"])
        self.assertEqual(len(report.errors), 1)

    def test_does_nothing_when_the_music_folder_is_empty(self):
        self.add(self.dest, "Song.mp3")

        report = self.run_sync()

        self.assertEqual(self.player_files(), ["Song.mp3"])
        self.assertEqual(len(report.errors), 1)

    def test_preview_changes_nothing(self):
        self.add(self.source, "New.mp3")
        self.add(self.dest, "Old.mp3")

        report = self.run_sync(dry_run=True)

        self.assertEqual(self.player_files(), ["Old.mp3"])
        self.assertEqual(report.counts, {"copy": 1, "remove": 1})


if __name__ == "__main__":
    unittest.main()
