import io
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from sandisk_sync.common import Report, State, sanitize_filename
from sandisk_sync.config import Config, Show
from sandisk_sync.podcasts import file_date, parse_feed, sync_podcasts

FEED_URL = "https://feeds.example.com/show.rss"
FEED = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()
TODAY = date(2026, 10, 29)


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class FakeWeb:
    """Serves the sample feed and a few bytes of 'audio' for every other URL."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def __call__(self, url: str) -> FakeResponse:
        self.requested.append(url)
        return FakeResponse(FEED if url == FEED_URL else b"audio for " + url.encode())


def make_config(**overrides) -> Config:
    config = Config(shows=[Show("Sample Show", FEED_URL)], episodes_per_show=2)
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


class ParseFeedTests(unittest.TestCase):
    def test_returns_episodes_with_audio_newest_first(self):
        episodes = parse_feed(FEED)
        self.assertEqual([e.guid for e in episodes], ["ep-4", "ep-3", "ep-2", "ep-1", "ep-0"])

    def test_filename_has_date_prefix_and_safe_title(self):
        newest = parse_feed(FEED)[0]
        self.assertEqual(newest.filename(), "2026-10-28 Newest What's up with Daylight Saving.mp3")

    def test_extension_falls_back_to_mime_type(self):
        middle = parse_feed(FEED)[1]
        self.assertEqual(middle.filename(), "2026-10-24 Middle Short Stuff.m4a")

    def test_rejects_non_rss(self):
        with self.assertRaises(ValueError):
            parse_feed(b"<html><body>Not found</body></html>")


class HelperTests(unittest.TestCase):
    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename('a/b\\c: "d"?  e. '), "abc d e")

    def test_file_date_reads_prefix_then_falls_back_to_modified_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            dated = Path(tmp, "2026-08-15 Episode.mp3")
            undated = Path(tmp, "Episode.mp3")
            for path in (dated, undated):
                path.write_bytes(b"x")
            stamp = datetime(2026, 7, 4, 12).timestamp()
            os.utime(undated, (stamp, stamp))
            self.assertEqual(file_date(dated), date(2026, 8, 15))
            self.assertEqual(file_date(undated), date(2026, 7, 4))


class SyncPodcastsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name, "player")
        self.podcasts = self.root / "Podcasts"
        self.show_dir = self.podcasts / "Sample Show"
        self.show_dir.mkdir(parents=True)
        self.state = State(Path(self.tmp.name, "state.json"))
        self.web = FakeWeb()

    def tearDown(self):
        self.tmp.cleanup()

    def show_files(self):
        return sorted(p.name for p in self.show_dir.iterdir()) if self.show_dir.exists() else []

    def run_sync(self, dry_run=False, **config):
        report = Report(dry_run=dry_run, out=io.StringIO())
        sync_podcasts(make_config(**config), self.root, self.state, report, today=TODAY, fetch=self.web)
        return report

    def test_removes_episodes_two_months_old_or_older(self):
        old = self.show_dir / "2026-08-30 Exactly 60 days.mp3"
        recent = self.show_dir / "2026-08-31 59 days.mp3"
        other_show = self.podcasts / "Some Other Show" / "2026-01-01 Ancient.mp3"
        other_show.parent.mkdir()
        for path in (old, recent, other_show):
            path.write_bytes(b"x")

        self.run_sync(episodes_per_show=0)

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertFalse(other_show.parent.exists(), "emptied folders are tidied up")

    def test_downloads_newest_episodes(self):
        report = self.run_sync()

        self.assertEqual(
            self.show_files(),
            ["2026-10-24 Middle Short Stuff.m4a", "2026-10-28 Newest What's up with Daylight Saving.mp3"],
        )
        self.assertEqual(report.counts, {"download": 2})
        self.assertEqual(report.errors, [])

    def test_does_not_download_again_after_you_delete_an_episode(self):
        self.run_sync()
        for path in self.show_dir.iterdir():
            path.unlink()

        report = self.run_sync()

        self.assertEqual(report.counts, {})
        self.assertEqual(self.show_files(), [])

    def test_skips_episodes_already_on_the_player(self):
        (self.show_dir / "2026-10-28 Newest What's up with Daylight Saving.mp3").write_bytes(b"x")

        report = self.run_sync()

        self.assertEqual(report.counts, {"download": 1})

    def test_never_downloads_episodes_past_the_age_limit(self):
        self.run_sync(episodes_per_show=10)

        days = [name[:10] for name in self.show_files()]
        self.assertEqual(days, ["2026-09-01", "2026-10-20", "2026-10-24", "2026-10-28"])

    def test_preview_changes_nothing(self):
        old = self.show_dir / "2026-01-01 Old.mp3"
        old.write_bytes(b"x")

        report = self.run_sync(dry_run=True)

        self.assertTrue(old.exists())
        self.assertEqual(self.show_files(), [old.name])
        self.assertEqual(report.counts, {"remove": 1, "download": 2})
        self.assertFalse(self.state.path.exists())

    def test_a_broken_feed_is_reported_and_other_shows_still_sync(self):
        config = make_config()
        config.shows.insert(0, Show("Broken", "https://feeds.example.com/broken.rss"))

        def fetch(url):
            if "broken" in url:
                raise OSError("connection refused")
            return self.web(url)

        report = Report(dry_run=False, out=io.StringIO())
        sync_podcasts(config, self.root, self.state, report, today=TODAY, fetch=fetch)

        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.counts, {"download": 2})

    def test_failed_download_leaves_no_partial_file(self):
        def fetch(url):
            if url == FEED_URL:
                return self.web(url)
            raise OSError("connection reset")

        report = Report(dry_run=False, out=io.StringIO())
        sync_podcasts(make_config(), self.root, self.state, report, today=TODAY, fetch=fetch)

        self.assertEqual(len(report.errors), 2)
        self.assertEqual(self.show_files(), [])


if __name__ == "__main__":
    unittest.main()
