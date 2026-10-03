# JamBuddy ABC collection

ABC tune files gathered from the collections linked from abcnotation.com and others, plus a
categorized, de-duplicated index, split by genre (`index/`), that the JamBuddy app can search.
Files are served from `raw.githubusercontent.com`, which the Android app already
allows, so new tunes reach users without an app release.

The tunes are mostly traditional and believed to be public domain. Each source keeps
its origin and attribution; remove a source promptly if its owner asks.

## Sources

Each `sources/<id>/` folder holds the ABC files and a `source.json` (name, license,
origin, download date, failures).

| Source | How it gets here |
| --- | --- |
| `nottingham` (GPL-3.0) | Copied from jukedeck/nottingham-dataset `ABC_original` |
| `norbeck`, `hardy`, `ceolas` | `python3 scripts/mirror.py [id ...]`, configured in `scripts/mirror.json` |
| `jc` | `python3 scripts/mirror_wayback.py`: JC's archive recovered from the Wayback Machine (resumable, takes hours) |
| one folder per site linked from abcnotation.com/tunes | `python3 scripts/crawl_sites.py [--ignore-robots] [site-id ...]`, sites listed in `scripts/sites.json` |

`crawl_sites.py` saves linked `.abc` files, `.abc` files inside zips, and ABC typed
into web pages (saved under `pages/`). It fetches each site at most once every 1.5
seconds, caches pages in `.cache/` and skips files it already has, so it can be rerun.
Each site gets at most 3,000 pages and 2 hours. Don't run two crawls at once.
The Session isn't included; JamBuddy uses its API directly.

## Index

`python3 scripts/build_index.py` scans every source and writes one index file per
genre to `index/` (`irish.json`, `scottish.json`, `nordic.json`, ...), plus
`index/genres.json` listing each file with its tune count, size and tune types.
Each file uses the jambuddy.live tune-index schema (version 1), with these extra fields:

- `genre`: musical tradition, decided by [genres.py](scripts/genres.py) from the
  tune's `O:` origin, then tradition-specific tune types (polska, strathspey,
  bourrée, hora, ...), then the site or folder it came from. Tunes still unclassified
  take the genre other sources agree on for the same title (`genre_inferred`).
- `category`: tune type (reel, jig, slip jig, hornpipe, polka, waltz, ...) from `R:`.
  When `R:` is missing, 6/8, 9/8 and 12/8 are guessed as jig, slip jig and slide
  (`category_inferred`); anything else is `other`. `meter` holds the `M:` field.
- `tune`: group id shared by settings with the same normalized title and category,
  so variant settings of one tune can be shown together.
- `duplicates`: up to 3 other copies of an identical setting. Settings count as
  identical when their notes, key and unit length match after ignoring chords,
  decorations, grace notes, spacing and bar-line style. Only one copy is indexed.
  Tunes with fewer than 8 notes (empty placeholders) are skipped.

To fix a misclassified site, add or change its folder in `FOLDERS` in `genres.py`.

Pass `--base-url` if the repository is published somewhere other than
`stewing-co/jambuddy-abc`.

Tests: `python3 -m unittest discover -s scripts -p 'test_*.py'`.
