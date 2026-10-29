import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path

from sandisk_sync.cli import DEFAULT_CONFIG, main
from sandisk_sync.config import load_config
from sandisk_sync.device import find_player


class ConfigTests(unittest.TestCase):
    def test_bundled_config_loads(self):
        config = load_config(DEFAULT_CONFIG)
        self.assertEqual(config.player_label, "SPORT PLUS")
        self.assertEqual(config.music_source, r"Y:\Media\Music")
        self.assertEqual(config.max_age_days, 60)
        self.assertEqual(
            [show.name for show in config.shows],
            ["Stuff You Should Know", "The 404 Media Podcast"],
        )


class FindPlayerTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "drive labels are a Windows feature")
    def test_unknown_label_is_not_found(self):
        self.assertIsNone(find_player("NO SUCH PLAYER 1234"))


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.player = self.base / "player"
        self.music = self.base / "music"
        (self.music / "Artist").mkdir(parents=True)
        (self.music / "Artist" / "Song.mp3").write_bytes(b"song")
        self.player.mkdir()
        self.config = self.base / "config.toml"
        self.config.write_text(
            f"[music]\nsource = '{self.music}'\n[podcasts]\nshows = []\n", encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(
                ["--config", str(self.config), "--state", str(self.base / "state.json"), *args]
            )
        return code, out.getvalue()

    def test_syncs_to_the_given_drive(self):
        code, output = self.run_main("--drive", str(self.player))

        self.assertEqual(code, 0, output)
        self.assertTrue((self.player / "Music" / "Artist" / "Song.mp3").exists())
        self.assertIn("Copied: 1 file", output)

    def test_dry_run_changes_nothing(self):
        code, output = self.run_main("--drive", str(self.player), "--dry-run")

        self.assertEqual(code, 0, output)
        self.assertFalse((self.player / "Music").exists())
        self.assertIn("Would copy: 1 file", output)

    def test_reports_a_missing_player(self):
        code, output = self.run_main("--drive", str(self.base / "unplugged"))

        self.assertEqual(code, 1)
        self.assertIn("Couldn't find the player", output)


if __name__ == "__main__":
    unittest.main()
