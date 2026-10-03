#!/usr/bin/env python3
"""Recover JC's ABC archive (trillian.mit.edu/~jc/music/book/) from the Wayback Machine.

Downloads the latest archived copy of every .abc file into sources/jc/, keeping JC's
directory layout. Resumable: files already on disk are skipped. Slow by design
(one request every 1.5 s, backing off when archive.org throttles).
"""
import datetime
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'sources/jc'
PREFIX = 'trillian.mit.edu/~jc/music/book/'
USER_AGENT = 'JamBuddyAbc/1.0 (+https://jambuddy.live)'
DELAY = 1.5


def fetch(url, attempts=6):
    for attempt in range(attempts):
        time.sleep(DELAY)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(30 * 2 ** attempt)


def snapshots():
    """Latest successful capture of each archived .abc URL: {path: (timestamp, original)}."""
    query = urllib.parse.urlencode([('url', PREFIX), ('matchType', 'prefix'), ('filter', 'statuscode:200'),
                                    ('filter', r'original:.*\.abc$'), ('fl', 'original,timestamp')])
    latest = {}
    for line in fetch('https://web.archive.org/cdx/search/cdx?' + query).decode().splitlines():
        original, timestamp = line.split()
        path = urllib.parse.unquote(urllib.parse.urlsplit(original).path)
        # CDX matches case-insensitively; keep only JC's canonical tree.
        if not path.startswith('/~jc/music/book/') or '..' in path:
            continue
        if path not in latest or timestamp > latest[path][0]:
            latest[path] = (timestamp, original)
    return latest


def main():
    latest = snapshots()
    print(f'{len(latest)} archived ABC files', flush=True)
    failures, saved = [], 0
    for count, (path, (timestamp, original)) in enumerate(sorted(latest.items()), 1):
        relative = path.split('/~jc/music/book/', 1)[1]
        target = OUTPUT / relative
        if target.exists():
            continue
        try:
            data = fetch(f'https://web.archive.org/web/{timestamp}id_/{original}')
            if re.search(rb'(?i)<(?:!doctype|html|body)\b', data[:2000]) or not re.search(rb'(?m)^X:', data):
                raise ValueError('not an ABC file')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            saved += 1
        except Exception as error:
            failures.append(f'{path}: {error}')
        if count % 250 == 0:
            print(f'{count}/{len(latest)} checked, {saved} saved, {len(failures)} failed', flush=True)
    meta = {'name': "John Chambers' ABC archive (recovered from the Wayback Machine)",
            'license': 'Not stated; tunes believed traditional',
            'origin': 'https://' + PREFIX, 'via': 'https://web.archive.org/',
            'downloaded': datetime.date.today().isoformat(),
            'files': sum(1 for _ in OUTPUT.rglob('*.abc')), 'failures': failures}
    (OUTPUT / 'source.json').write_text(json.dumps(meta, indent=2) + '\n')
    print(f"Done: {meta['files']} files on disk, {len(failures)} failures", flush=True)


if __name__ == '__main__':
    main()
