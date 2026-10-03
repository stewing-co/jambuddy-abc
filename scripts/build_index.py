#!/usr/bin/env python3
"""Index, categorize and de-duplicate the ABC files under sources/.

Writes index/<genre>.json files in the jambuddy.live tune-index schema (version 1), and
index/genres.json listing them. Besides the fields the app reads, each tune has:
  category   normalized tune type (reel, jig, ...); from R:, or from a compound M: when R: is absent
  meter      the tune's M: field
  genre      musical tradition (irish, scottish, nordic, ...); see genres.py
  tune       group id shared by settings with the same normalized title and category
  duplicates other copies of an identical setting, which are omitted from `tunes`
"""
import argparse
import hashlib
import json
import re
import shutil
import unicodedata
from pathlib import Path

from genres import GENRES, genre

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / 'sources'
OUTPUT = ROOT / 'index'
MIN_NOTES = 8
MAX_DUPLICATES = 3  # Fallback copies listed per tune; some sites repeat a tune dozens of times.
DEFAULT_BASE = 'https://raw.githubusercontent.com/stewing-co/jambuddy-abc/main/'

# Most specific names first: "slip jig" must not match "jig".
CATEGORIES = [
    ('slip jig', r'slip ?jig'), ('hop jig', r'hop ?jig'), ('single jig', r'single ?jig'),
    ('jig', r'jig|jigg'), ('reel', r'reel'), ('hornpipe', r'hornpipe'), ('polka', r'polka'),
    ('slide', r'slide'), ('strathspey', r'strathspey'), ('waltz', r'waltz|vals'),
    ('mazurka', r'mazurka'), ('barndance', r'barn ?dance|fling|highland'),
    ('three-two', r'three[- ]?two|3/2'), ('march', r'march'), ('schottische', r'schottis'),
    ('polska', r'polska'), ('set dance', r'set ?dance'), ('air', r'air|lament|song|ballad'),
    ('morris', r'morris'), ('carol', r'carol'),
]
# Used only when a tune has no recognizable R: field. Simple meters (2/4, 3/4, 4/4) are
# shared by songs, marches, polkas, waltzes and reels alike, so they aren't guessed.
METER_CATEGORIES = {'6/8': 'jig', '9/8': 'slip jig', '12/8': 'slide'}
MODES = {'': 'maj', 'maj': 'maj', 'major': 'maj', 'ion': 'maj', 'ionian': 'maj',
         'm': 'min', 'min': 'min', 'minor': 'min', 'aeo': 'min', 'aeolian': 'min',
         'dor': 'dor', 'dorian': 'dor', 'mix': 'mix', 'mixolydian': 'mix',
         'phr': 'phr', 'phrygian': 'phr', 'lyd': 'lyd', 'lydian': 'lyd', 'loc': 'loc', 'locrian': 'loc'}


def fields(text, key):
    return [value.strip() for value in re.findall(r'^' + key + r':\s*([^\r\n]+)', text, re.M)]


def category(rhythm, meter):
    lower = rhythm.lower()
    for name, pattern in CATEGORIES:
        if re.search(pattern, lower):
            return name, False
    inferred = METER_CATEGORIES.get(meter.replace(' ', ''))
    return (inferred, True) if inferred else ('other', False)


def normalize_key(key):
    match = re.match(r'\s*([A-Ga-g])([#b]?)\s*([A-Za-z]*)', key)
    if not match:
        return key.strip()
    tonic, accidental, mode = match.groups()
    return tonic.upper() + accidental + MODES.get(mode.lower(), mode.lower()[:3])


def normalize_title(title):
    title = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode().lower()
    title = re.sub(r'\(.*?\)|\[.*?\]', ' ', title)
    title = re.sub(r'^(the|an|a)\s+|,\s*(the|an|a)$', '', title.strip())
    return re.sub(r'[^a-z0-9]+', ' ', title).strip()


def notes(part):
    """The melody alone: no headers, chords, decorations, grace notes, spacing or bar styles."""
    header = ' '.join(normalize_key(k) for k in fields(part, 'K')[:1]) + '|' + ''.join(fields(part, 'L')[:1])
    body = '\n'.join(line for line in part.splitlines() if not re.match(r'^(?:[A-Za-z]:|%)', line))
    body = re.sub(r'"[^"]*"|![^!\n]*!|\+[^+\n]*\+|\{[^}]*\}|[~.HLMOPSTuv]', '', body)
    return header, re.sub(r'[\s\\]|\[?\|+\]?|:', '', body)


def fingerprint(part):
    """Hash of the notes alone, so re-typed copies of one transcription collide."""
    return hashlib.sha256(''.join(notes(part)).encode()).hexdigest()[:24]


def parse_file(path, source, base, sources=SOURCES):
    data = path.read_bytes()
    try:
        text, encoding = data.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        # The app accepts only utf-8 and windows-1252; both decoders replace undefined bytes.
        text, encoding = data.decode('windows-1252', errors='replace'), 'windows-1252'
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    relative = path.relative_to(sources).as_posix()
    url = base + 'sources/' + relative
    tunes = []
    for ordinal, part in enumerate(re.split(r'(?m)(?=^X:\s*\S)', text)[1:]):
        titles = list(dict.fromkeys(fields(part, 'T')))
        keys = fields(part, 'K')
        # Skip header-only placeholders ("(vide)", "not available here").
        if not titles or not keys or len(re.findall(r'[A-Ga-g]', notes(part)[1])) < MIN_NOTES:
            continue
        x = fields(part, 'X')[0]
        rhythm = next(iter(fields(part, 'R')), '')
        meter = next(iter(fields(part, 'M')), '')
        kind, inferred = category(rhythm, meter)
        music = '\n'.join(line.strip() for line in part.splitlines()
                          if line.strip() and not re.match(r'^(?:[XTNSZH]:|%)', line))
        tune = {'id': hashlib.sha256(f'{url}#{ordinal}:{x}'.encode()).hexdigest()[:24],
                'titles': titles, 'key': normalize_key(keys[0]), 'meter': meter, 'category': kind,
                'genre': genre(fields(part, 'O'), rhythm, relative), 'url': url, 'x': x,
                'ordinal': ordinal, 'source': source,
                'setting': hashlib.sha256(music.encode()).hexdigest()[:24], 'fingerprint': fingerprint(part)}
        if inferred:
            tune['category_inferred'] = True
        if encoding != 'utf-8':  # The app defaults to utf-8.
            tune['encoding'] = encoding
        tunes.append(tune)
    return tunes


def build(base=DEFAULT_BASE, sources=SOURCES):
    settings, reports = [], []
    # Folders without source.json are still downloading (or found nothing).
    for directory in sorted(path for path in sources.iterdir() if (path / 'source.json').exists()):
        meta = json.loads((directory / 'source.json').read_text())
        files = sorted(path for path in directory.rglob('*') if path.suffix.lower() == '.abc')
        if not files:
            continue
        found = []
        for path in files:
            try:
                found.extend(parse_file(path, directory.name, base, sources))
            except Exception as error:
                print(f'Skipping {path.relative_to(sources)}: {error}')
        settings.extend(found)
        reports.append({'id': directory.name, 'name': meta['name'], 'license': meta['license'],
                        'files': len(files), 'settings': len(found), 'stale': False, 'failures': []})
    # Keep the first copy of each identical setting (sources sort alphabetically, then
    # by path) and list the others so clients can fall back to them.
    kept, by_print = [], {}
    for tune in sorted(settings, key=lambda t: (t['source'], t['url'], t['ordinal'])):
        first = by_print.get(tune['fingerprint'])
        if first:
            if len(first.setdefault('duplicates', [])) < MAX_DUPLICATES:
                first['duplicates'].append({'url': tune['url'], 'x': tune['x'], 'ordinal': tune['ordinal']})
            first['titles'] = list(dict.fromkeys(first['titles'] + tune['titles']))
            if first['genre'] == 'other':
                first['genre'] = tune['genre']
            continue
        by_print[tune['fingerprint']] = tune
        kept.append(tune)
    for tune in kept:
        group = normalize_title(tune['titles'][0]) + '|' + tune['category']
        tune['tune'] = hashlib.sha256(group.encode()).hexdigest()[:16]
        del tune['fingerprint']
    # Unclassified tunes take the genre other sources clearly agree on for the same title.
    votes = {}
    for tune in kept:
        if tune['genre'] != 'other':
            tally = votes.setdefault(normalize_title(tune['titles'][0]), {})
            tally[tune['genre']] = tally.get(tune['genre'], 0) + 1
    for tune in kept:
        tally = votes.get(normalize_title(tune['titles'][0])) if tune['genre'] == 'other' else None
        if tally:
            best = max(tally, key=tally.get)
            if tally[best] >= 2 and tally[best] >= 0.75 * sum(tally.values()):
                tune['genre'] = best
                tune['genre_inferred'] = True
    by_genre = {name: [] for name in GENRES}
    for tune in sorted(kept, key=lambda tune: tune['id']):
        by_genre[tune['genre']].append(tune)
    return {'sources': reports, 'duplicates_removed': len(settings) - len(kept), 'genres': by_genre}


def count(tunes, field):
    totals = {}
    for tune in tunes:
        totals[tune[field]] = totals.get(tune[field], 0) + 1
    return dict(sorted(totals.items(), key=lambda item: -item[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--base-url', default=DEFAULT_BASE, help='public URL prefix for repo files')
    args = parser.parse_args()
    catalog = build(args.base_url)
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir()
    manifest = []
    for name, tunes in catalog['genres'].items():
        if not tunes:
            continue
        used = {tune['source'] for tune in tunes}
        payload = {'version': 1, 'genre': name, 'name': GENRES[name],
                   'sources': [source for source in catalog['sources'] if source['id'] in used], 'tunes': tunes}
        path = OUTPUT / f'{name}.json'
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
        manifest.append({'genre': name, 'name': GENRES[name], 'file': f'{name}.json', 'tunes': len(tunes),
                         'bytes': path.stat().st_size, 'categories': count(tunes, 'category')})
    (OUTPUT / 'genres.json').write_text(json.dumps(
        {'version': 1, 'base_url': args.base_url + 'index/', 'genres': manifest}, indent=1) + '\n')
    total = sum(entry['tunes'] for entry in manifest)
    print(f"Indexed {total} settings ({catalog['duplicates_removed']} duplicates removed)")
    for entry in manifest:
        print(f"  {entry['genre']}: {entry['tunes']} tunes, {entry['bytes'] / 1e6:.1f} MB")


if __name__ == '__main__':
    main()
