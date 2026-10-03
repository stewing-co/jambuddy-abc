#!/usr/bin/env python3
"""Download ABC files from the sites listed in mirror.json into sources/<id>/.

Each entry gives a `page` whose same-host .abc links are downloaded (filtered by the
optional `include`/`exclude` regexes), or an explicit `files` list. robots.txt is
honored and requests are paced. Usage: mirror.py [source-id ...]
"""
import datetime
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'scripts/mirror.json'
USER_AGENT = 'JamBuddyAbc/1.0 (+https://jambuddy.live)'
DELAY = 1.5
MAX_BYTES = 8_000_000


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(value for key, value in attrs if key == 'href' and value)


def fetch(url):
    time.sleep(DELAY)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('file exceeds size limit')
    return data


def file_urls(source):
    if 'files' in source:
        return source['files']
    page = source['page']
    parser = Links()
    parser.feed(fetch(page).decode('utf-8', errors='replace'))
    host = urllib.parse.urlsplit(page).hostname
    urls = set()
    for href in parser.links:
        url = urllib.parse.urljoin(page, href)
        path = urllib.parse.urlsplit(url).path
        if (urllib.parse.urlsplit(url).hostname == host and path.lower().endswith('.abc')
                and re.search(source.get('include', ''), path)
                and not (source.get('exclude') and re.search(source['exclude'], path))):
            urls.add(url)
    return sorted(urls)


def local_path(source, url):
    """Keep the path below the source's common directory, e.g. i/hnj0.abc."""
    base = urllib.parse.urlsplit(source.get('page') or source['files'][0]).path.rsplit('/', 1)[0] + '/'
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    relative = path[len(base):] if path.startswith(base) else path.rsplit('/', 1)[-1]
    return ROOT / 'sources' / source['id'] / relative


def mirror(source):
    origin = source.get('page') or source['files'][0]
    robots = urllib.robotparser.RobotFileParser()
    parts = urllib.parse.urlsplit(origin)
    robots.set_url(f'{parts.scheme}://{parts.netloc}/robots.txt')
    robots.read()
    urls = [url for url in file_urls(source) if robots.can_fetch(USER_AGENT, url)]
    if not urls:
        raise RuntimeError(f"{source['id']}: no downloadable ABC files found")
    failures = []
    for url in urls:
        try:
            data = fetch(url)
            if re.search(rb'(?i)<(?:!doctype|html|body)\b', data[:2000]) or not re.search(rb'(?m)^X:', data):
                raise ValueError('not an ABC file')
            target = local_path(source, url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except Exception as error:
            failures.append(f'{url}: {error}')
    meta = {'name': source['name'], 'license': source.get('license', 'Not stated; tunes believed traditional'),
            'origin': origin, 'downloaded': datetime.date.today().isoformat(),
            'files': len(urls) - len(failures), 'failures': failures}
    (ROOT / 'sources' / source['id'] / 'source.json').write_text(json.dumps(meta, indent=2) + '\n')
    print(f"{source['id']}: {meta['files']} files, {len(failures)} failures", flush=True)
    for failure in failures:
        print('  ' + failure)


def main():
    sources = json.loads(CONFIG.read_text())['sources']
    wanted = set(sys.argv[1:])
    for source in sources:
        if not wanted or source['id'] in wanted:
            mirror(source)


if __name__ == '__main__':
    main()
