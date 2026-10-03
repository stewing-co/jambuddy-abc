#!/usr/bin/env python3
"""Collect ABC tunes from the sites in sites.json (the collections abcnotation.com links to).

For each site, crawls pages inside its listed scopes and saves:
  - linked .abc files, and ABC found in linked .txt files
  - .abc files inside linked .zip archives
  - ABC written directly into web pages (wikis, blogs), as pages/<page>.abc
GitHub/GitLab repositories are listed through their APIs, and Dropbox shared folders
are downloaded as zips. robots.txt is honored and each site is fetched sequentially,
at most one request every DELAY seconds; several sites run in parallel.

Resumable: fetched pages are cached in .cache/ and saved files are not re-downloaded.
Usage: crawl_sites.py [--ignore-robots] [site-id ...]
"""
import concurrent.futures
import datetime
import hashlib
import html
import io
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zipfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / 'scripts/sites.json'
CACHE = ROOT / '.cache/pages'
USER_AGENT = 'JamBuddyAbc/1.0 (+https://jambuddy.live)'
DELAY = 1.5
MAX_PAGES = 3000
MAX_SECONDS = 2 * 3600  # Per site, so one slow site can't stall the run.
MAX_BYTES = 8_000_000
MAX_ZIP_BYTES = 60_000_000
PAGE_EXTENSIONS = ('', '.html', '.htm', '.php', '.asp', '.aspx', '.shtml', '.cfm', '.jsp')
SKIP_QUERY = re.compile(r'(?i)action=|oldid=|diff=|printable=|redlink=|replytocom=|share=|special:|/feed')
ABC = re.compile(rb'(?m)^X:\s*\d')
KEY = re.compile(rb'(?m)^K:')
PRINT_LOCK = threading.Lock()
IGNORE_ROBOTS = False


def log(*parts):
    with PRINT_LOCK:
        print(*parts, flush=True)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ('a', 'frame', 'iframe', 'area'):
            self.links.extend(value for key, value in attrs if key in ('href', 'src') and value)


def is_abc(data):
    return bool(ABC.search(data) and KEY.search(data)) and not re.search(rb'(?i)<(?:!doctype|html|body)\b', data[:2000])


def page_abc(markup):
    """ABC tunes written into an HTML page, as plain text."""
    text = re.sub(r'(?is)<(script|style)\b.*?</\1>', '', markup)
    text = re.sub(r'(?i)<br\s*/?>|</(?:p|div|li|tr|pre|h\d)>', '\n', text)
    text = html.unescape(re.sub(r'<[^>]+>', '', text)).replace('\r\n', '\n').replace('\xa0', ' ')
    tunes = []
    for match in re.finditer(r'(?m)^[ \t]*X:[ \t]*\d+[^\n]*\n(?:[ \t]*\S[^\n]*\n?)+', text):
        tune = '\n'.join(line.strip() for line in match.group(0).splitlines())
        if re.search(r'(?m)^T:', tune) and re.search(r'(?m)^K:', tune):
            tunes.append(tune.strip() + '\n')
    return '\n'.join(tunes)


class Site:
    def __init__(self, site):
        self.site = site
        self.out = ROOT / 'sources' / site['id']
        self.last = 0.0
        self.failures = []
        self.saved = 0
        self.robots = {}

    # -- fetching ---------------------------------------------------------------

    def allowed(self, url):
        if IGNORE_ROBOTS:
            return True
        parts = urllib.parse.urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        if origin not in self.robots:
            robots = urllib.robotparser.RobotFileParser(origin + '/robots.txt')
            try:
                robots.read()
            except Exception:
                robots = None  # Unreachable robots.txt: treat as allowing.
            self.robots[origin] = robots
        robots = self.robots[origin]
        return robots is None or robots.can_fetch(USER_AGENT, url)

    def delay(self, url):
        robots = self.robots.get('{0.scheme}://{0.netloc}'.format(urllib.parse.urlsplit(url)))
        crawl_delay = robots.crawl_delay(USER_AGENT) if robots else None
        return max(DELAY, float(crawl_delay or 0))

    def fetch(self, url, limit=MAX_BYTES, cache=False):
        """(content type, bytes); pages are cached so an interrupted crawl resumes quickly."""
        cached = CACHE / hashlib.sha256(url.encode()).hexdigest()
        if cache and cached.exists():
            blob = cached.read_bytes()
            kind, _, data = blob.partition(b'\n')
            return kind.decode(), data
        time.sleep(max(0.0, self.delay(url) - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        parts = urllib.parse.urlsplit(url)
        quoted = urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path, safe="/%:@!$&'()*+,;=~")))
        request = urllib.request.Request(quoted, headers={'User-Agent': USER_AGENT})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    kind = response.headers.get('Content-Type', '')
                    data = response.read(limit + 1)
                break
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                time.sleep(20 * (attempt + 1))
        if len(data) > limit:
            raise ValueError('exceeds size limit')
        if cache:
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(kind.encode() + b'\n' + data)
        return kind, data

    # -- saving -----------------------------------------------------------------

    def target(self, url, suffix=''):
        parts = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(parts.path).lstrip('/')
        if parts.netloc == 'web.archive.org':
            path = re.sub(r'^web/\d+[a-z_]*/(?:https?:/+)?', '', path)
        if parts.query:
            path += '_' + hashlib.sha256(parts.query.encode()).hexdigest()[:8]
        path = re.sub(r'[^\w./-]+', '_', path).strip('/') or 'index'
        path = '/'.join(segment for segment in path.split('/') if segment not in ('', '.', '..'))
        return self.out / (path + suffix)

    def save(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.saved += 1

    def save_file(self, url):
        name = urllib.parse.urlsplit(url).path.lower()
        target = self.target(url)
        if name.endswith('.zip'):
            done = self.target(url, '.done')
            if done.exists():
                return
            self.save_zip(self.fetch(self.raw(url), MAX_ZIP_BYTES)[1], target)
            done.parent.mkdir(parents=True, exist_ok=True)
            done.write_text('')
            return
        if not name.endswith('.abc'):
            target = target.with_name(target.name + '.abc')
        if target.exists():
            return
        data = self.fetch(self.raw(url))[1]
        if is_abc(data):
            self.save(target, data)

    def save_zip(self, data, folder):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                name = member.filename
                if name.lower().endswith(('.abc', '.txt')) and member.file_size <= MAX_BYTES and '..' not in name:
                    content = archive.read(member)
                    if is_abc(content):
                        path = folder / re.sub(r'[^\w./-]+', '_', name)
                        self.save(path if path.suffix.lower() == '.abc' else path.with_name(path.name + '.abc'), content)

    @staticmethod
    def raw(url):
        """Wayback copies of files are fetched unmodified via the id_ flag."""
        return re.sub(r'(web\.archive\.org/web/\d+)(?:[a-z]{2}_)?/', r'\1id_/', url)

    # -- crawling ---------------------------------------------------------------

    def in_scope(self, url):
        parts = urllib.parse.urlsplit(url)
        same_host = parts.netloc.lower().removeprefix('www.') == self.site['host'].removeprefix('www.')
        if not same_host or parts.scheme not in ('http', 'https'):
            return False
        path = parts.path
        if parts.netloc == 'web.archive.org':
            strip = lambda p: re.sub(r'^/web/\d+[a-z_]*/(?:https?:/+)?', '/', p).lower()
            return any(strip(path).startswith(strip(scope)) for scope in self.site['scopes'])
        return any(path.startswith(scope) for scope in self.site['scopes'])

    def crawl(self):
        seen, queue, pages = set(), list(self.site['seeds']), 0
        limit = self.site.get('max_pages', MAX_PAGES)
        deadline = time.monotonic() + MAX_SECONDS
        while queue and pages < limit and time.monotonic() < deadline:
            url = urllib.parse.urldefrag(queue.pop(0))[0]
            if url in seen or not self.allowed(url):
                continue
            seen.add(url)
            path = urllib.parse.urlsplit(url).path.lower()
            try:
                if path.endswith(('.abc', '.zip', '.txt')):
                    self.save_file(url)
                    continue
                kind, data = self.fetch(url, cache=True)
                pages += 1
                if 'html' not in kind and is_abc(data):
                    target = self.target(url)
                    if not target.exists():
                        self.save(target.with_name(target.name + '.abc') if target.suffix != '.abc' else target, data)
                    continue
                if 'html' not in kind:
                    continue
                markup = data.decode('utf-8', errors='replace')
                embedded = page_abc(markup)
                if embedded:
                    target = self.out / 'pages' / self.target(url, '.abc').relative_to(self.out)
                    if not target.exists():
                        self.save(target, embedded.encode())
                parser = Links()
                parser.feed(markup)
                for href in parser.links:
                    link = urllib.parse.urldefrag(urllib.parse.urljoin(url, href.strip()))[0]
                    lower = urllib.parse.urlsplit(link).path.lower()
                    extension = re.search(r'(\.[a-z0-9]{1,5})$', lower.rsplit('/', 1)[-1])
                    if link in seen or SKIP_QUERY.search(link) or not self.in_scope(link):
                        continue
                    if lower.endswith(('.abc', '.zip', '.txt')):
                        queue.insert(0, link)  # Files before pages: they're what we're here for.
                    elif lower.endswith('/') or not extension or extension.group(1) in PAGE_EXTENSIONS:
                        queue.append(link)
            except Exception as error:
                self.failures.append(f'{url}: {error}')
        return pages, len(queue)

    def repository(self):
        """github.com / gitlab.com repositories: list .abc files through the API."""
        for scope in self.site['scopes']:
            owner_repo = scope.strip('/')
            if self.site['host'] == 'github.com':
                api = f'https://api.github.com/repos/{owner_repo}'
                branch = json.loads(self.fetch(api)[1])['default_branch']
                tree = json.loads(self.fetch(f'{api}/git/trees/{branch}?recursive=1')[1])['tree']
                files = [f'https://raw.githubusercontent.com/{owner_repo}/{branch}/{item["path"]}'
                         for item in tree if item['path'].lower().endswith('.abc')]
            else:
                project = urllib.parse.quote(owner_repo, safe='')
                api = f'https://gitlab.com/api/v4/projects/{project}'
                branch = json.loads(self.fetch(api)[1])['default_branch']
                files, page = [], 1
                while True:
                    items = json.loads(self.fetch(f'{api}/repository/tree?recursive=true&per_page=100&page={page}')[1])
                    files += [f'https://gitlab.com/{owner_repo}/-/raw/{branch}/{item["path"]}'
                              for item in items if item['path'].lower().endswith('.abc')]
                    if len(items) < 100:
                        break
                    page += 1
            for url in files:
                target = self.out / owner_repo / url.split(f'/{branch}/', 1)[1]
                if target.exists():
                    continue
                try:
                    data = self.fetch(url)[1]
                    if is_abc(data):
                        self.save(target, data)
                except Exception as error:
                    self.failures.append(f'{url}: {error}')
        return 0, 0

    def dropbox(self):
        for seed in self.site['seeds']:
            folder = self.out / re.sub(r'[^\w]+', '_', urllib.parse.urlsplit(seed).path).strip('_')
            if folder.exists():
                continue
            parts = urllib.parse.urlsplit(seed)
            query = urllib.parse.urlencode([(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != 'dl'] + [('dl', '1')])
            try:
                self.save_zip(self.fetch(urllib.parse.urlunsplit(parts._replace(query=query)), MAX_ZIP_BYTES)[1], folder)
            except Exception as error:
                self.failures.append(f'{seed}: {error}')
        return 0, 0

    def run(self):
        started = time.monotonic()
        try:
            if self.site['host'] in ('github.com', 'gitlab.com'):
                pages, unvisited = self.repository()
            elif self.site['host'] == 'www.dropbox.com':
                pages, unvisited = self.dropbox()
            else:
                pages, unvisited = self.crawl()
        except Exception as error:
            self.failures.append(f"{self.site['id']}: {error}")
            pages, unvisited = 0, 0
        files = sum(1 for path in self.out.rglob('*') if path.suffix.lower() == '.abc') if self.out.exists() else 0
        if files:
            meta = {'name': self.site['name'], 'license': 'Not stated; tunes believed traditional',
                    'origin': self.site['seeds'], 'found_via': 'https://abcnotation.com/tunes',
                    'downloaded': datetime.date.today().isoformat(), 'files': files,
                    'pages_crawled': pages, 'pages_unvisited': unvisited, 'failures': self.failures[:200]}
            (self.out / 'source.json').write_text(json.dumps(meta, indent=2) + '\n')
        log(f"{self.site['id']}: {files} ABC files ({self.saved} new), {pages} pages, "
            f"{len(self.failures)} failures, {unvisited} unvisited, {time.monotonic() - started:.0f}s")


def main():
    global IGNORE_ROBOTS
    args = sys.argv[1:]
    IGNORE_ROBOTS = '--ignore-robots' in args
    wanted = {arg for arg in args if not arg.startswith('--')}
    sites = json.loads(SITES.read_text())['sites']
    sites = [site for site in sites if not wanted or site['id'] in wanted]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda site: Site(site).run(), sites))


if __name__ == '__main__':
    main()
