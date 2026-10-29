# Sandisk Sync

Keeps a SanDisk Clip Sport Plus loaded with fresh podcast episodes and a copy of the music library. Plug the player in, double-click `sync.bat`, and it:

1. Removes podcast episodes that are two months old or older.
2. Downloads the newest episodes of Stuff You Should Know and The 404 Media Podcast.
3. Mirrors `Y:\Media\Music` (every subfolder) to the player's Music folder: new and changed songs are copied, and songs you've deleted from the PC are removed from the player.

The Audible, Audiobooks and Playlists folders on the player are never touched.

## Setup

1. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/). Nothing else is needed; the program only uses Python's standard library.
2. Download this repository (Code → Download ZIP, or `git clone`) to a folder on your PC.

## Using it

1. Plug in the player. It should show up in File Explorer as **SPORT PLUS**.
2. The first time, double-click **`preview.bat`**. It lists everything a sync would remove, download and copy, without changing anything on the player.
3. If the list looks right, double-click **`sync.bat`** to do it for real.

The window stays open at the end with a summary, including free space left on the player. Any problems are shown as `ERROR` lines, and the rest of the sync carries on.

From a command prompt you can also run `py -m sandisk_sync` with these options:

| Option | What it does |
| --- | --- |
| `--dry-run` | Preview only (same as `preview.bat`) |
| `--drive E:` | Use this drive instead of looking for one named SPORT PLUS |
| `--skip-music` | Only sync podcasts |
| `--skip-podcasts` | Only sync music |

## Settings

Everything is in [`config.toml`](config.toml): the music folder, which shows to download, how old an episode can get (`max_age_days`, 60 by default) and how many of each show's newest episodes to fetch (`episodes_per_show`, 5 by default). To add a show, copy one of the `[[podcasts.shows]]` blocks and put in its name and RSS feed address.

## How it decides what to do

**Podcasts.** Each show gets its own folder inside `Podcasts`, and every episode's file name starts with its release date, for example `2026-10-28 How Lighthouses Work.mp3`. That date is how the program tells an episode's age on later syncs (files without a date in the name use the file's modified date). Every audio file in `Podcasts` that is `max_age_days` old or older is removed. The program remembers which episodes it has downloaded, so an episode you delete from the player yourself won't come back.

**Music.** Files are matched by their path under `Y:\Media\Music`. A song is copied when it's missing from the player or has changed on the PC since it was last copied. Songs already on the player before you started using this program are kept as long as the file size matches. If `Y:\Media\Music` can't be reached or is empty, music is skipped completely so a disconnected drive can never wipe the player. When the player runs out of space, copying stops and the summary says how much didn't fit.

The program's memory of what it has synced is kept on the PC in `%LOCALAPPDATA%\SandiskSync\state.json`, so nothing extra is written to the player. Deleting that file is safe; the next sync just rebuilds it.

## Development

Run the tests with `py -m unittest` from the repository folder. GitHub Actions runs them on Windows for every pull request.
