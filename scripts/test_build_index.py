import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_index
from build_index import category, normalize_key, normalize_title
from genres import genre

REEL = 'X:1\nT:The Morning Dew\nR:reel\nM:4/4\nL:1/8\nK:Edor\n|:"Em"EB B2 ~e2 dB|AD FD AD FA:|\n'
# Same notes as REEL, retyped with different chords, spacing, bars and header order.
REEL_COPY = 'X:7\nT:Morning Dew, The\nM:C|\nL:1/8\nR:Reel\nK:E Dorian\n|: EBB2 e2dB | ADFD ADFA :|\n'
JIG = 'X:2\nT:Untitled\nM:6/8\nK:G\nGAB cde|dBG A2B|\n'


class IndexTests(unittest.TestCase):
    def build(self, files):
        with tempfile.TemporaryDirectory() as root:
            for path, text in files.items():
                target = Path(root) / 'sources' / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text if isinstance(text, bytes) else text.encode())
            for source in {path.split('/')[0] for path in files}:
                (Path(root) / 'sources' / source / 'source.json').write_text(
                    json.dumps({'name': source, 'license': 'test'}))
            catalog = build_index.build('https://example.test/', Path(root) / 'sources')
            catalog['tunes'] = [tune for tunes in catalog['genres'].values() for tune in tunes]
            return catalog

    def test_removes_duplicate_settings_across_sources(self):
        catalog = self.build({'a/one.abc': REEL, 'b/two.abc': REEL_COPY + '\n' + JIG})
        self.assertEqual(1, catalog['duplicates_removed'])
        reel = next(t for t in catalog['tunes'] if t['category'] == 'reel')
        self.assertEqual('https://example.test/sources/a/one.abc', reel['url'])
        self.assertEqual([{'url': 'https://example.test/sources/b/two.abc', 'x': '7', 'ordinal': 0}],
                         reel['duplicates'])
        self.assertEqual(['The Morning Dew', 'Morning Dew, The'], reel['titles'])
        self.assertEqual(['jig', 'reel'], sorted(tune['category'] for tune in catalog['tunes']))

    def test_skips_tunes_without_notes(self):
        placeholders = 'X:4\nT:Empty (vide)\nK:G\n\nX:5\nT:Missing (not available here)\nK:G\n'
        catalog = self.build({'a/one.abc': placeholders + '\n' + JIG})
        self.assertEqual(['Untitled'], [tune['titles'][0] for tune in catalog['tunes']])
        self.assertEqual(0, catalog['duplicates_removed'])

    def test_groups_variant_settings_by_title_and_category(self):
        variant = REEL.replace('X:1', 'X:3').replace('AD FA', 'AF dF')
        catalog = self.build({'a/one.abc': REEL + '\n' + variant})
        self.assertEqual(0, catalog['duplicates_removed'])
        self.assertEqual(1, len({tune['tune'] for tune in catalog['tunes']}))

    def test_windows_1252_files_keep_an_encoding_the_app_accepts(self):
        catalog = self.build({'a/one.abc': JIG.replace('Untitled', 'Caf\u00e9').encode('windows-1252') + b'% \x9d\n'})
        self.assertEqual('windows-1252', catalog['tunes'][0]['encoding'])

    def test_unclassified_tune_takes_genre_other_sources_agree_on(self):
        irish = REEL.replace('X:1', 'X:8').replace('AD FA', 'AF dF')
        other = REEL.replace('X:1', 'X:9').replace('AD FA', 'AB cB')
        catalog = self.build({'ceolas/a.abc': REEL + '\n' + irish, 'unknown/b.abc': other})
        unknown = next(tune for tune in catalog['tunes'] if tune['source'] == 'unknown')
        self.assertEqual(('irish', True), (unknown['genre'], unknown['genre_inferred']))

    def test_books_keep_single_genre_tunebooks_and_combine_the_rest(self):
        def tune(x, title, origin, length):
            # A distinct number of notes per tune, so none are merged as duplicates.
            return f'X:{x}\nT:{title}\nO:{origin}\nM:4/4\nK:D\nABcd efga|{"B" * length}|\n'
        book = '\n'.join(tune(i, f'Irish {i}', 'Ireland', i) for i in range(1, 11))
        mixed = tune(1, 'Mixed Irish', 'Ireland', 11) + '\n' + tune(1, 'Mixed English', 'England', 12)
        with tempfile.TemporaryDirectory() as root:
            for path, text in {'site/book.abc': book, 'site/mixed.abc': mixed, 'tiny/one.abc': tune(5, 'Tiny', 'Ireland', 13)}.items():
                target = Path(root) / 'sources' / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            for source in ('site', 'tiny'):
                (Path(root) / 'sources' / source / 'source.json').write_text(json.dumps({'name': source.title(), 'license': 'test'}))
            with patch('build_index.ROOT', Path(root)), patch('build_index.BOOKS', Path(root) / 'books'):
                catalog = build_index.build('https://example.test/', Path(root) / 'sources')
                irish = next(g for g in build_index.books(catalog, 'https://example.test/')['genres'] if g['genre'] == 'irish')
                self.assertEqual(['Site', 'Various collections'], [source['name'] for source in irish['sources']])
                site, various = irish['sources']
                self.assertEqual([('book', 'sources/site/book.abc', 10), ('More tunes', 'books/irish/site.abc', 1)],
                                 [(b['label'], b['path'], b['tunes']) for b in site['books']])
                self.assertEqual([('All tunes', 'books/irish/various.abc', 1)],
                                 [(b['label'], b['path'], b['tunes']) for b in various['books']])
                combined = (Path(root) / 'books/irish/site.abc').read_text()
                self.assertIn('X:1\nT:Mixed Irish', combined)
                self.assertNotIn('Mixed English', combined)
                self.assertIn('% Source: sources/site/mixed.abc', combined)

    def test_genres(self):
        self.assertEqual('nordic', genre(['Dalarna, Sweden'], 'reel', 'irish-site/a.abc'))
        self.assertEqual('american', genre(['New England'], '', 'x/a.abc'))
        self.assertEqual('nordic', genre([], 'Slängpolska', 'norbeck/i/hnr0.abc'))
        self.assertEqual('irish', genre([], 'reel', 'norbeck/i/hnr0.abc'))
        self.assertEqual('scottish', genre([], 'minuet', 'jc/Gow/x.abc'))
        self.assertEqual('early', genre([], 'Pavane', 'unknown/x.abc'))
        self.assertEqual('other', genre([], 'reel', 'unknown/x.abc'))

    def test_categories(self):
        self.assertEqual(('slip jig', False), category('Slip Jig', '9/8'))
        self.assertEqual(('jig', False), category('double jig', '6/8'))
        self.assertEqual(('slip jig', True), category('', '9/8'))
        self.assertEqual(('other', False), category('', '5/4'))
        self.assertEqual(('other', False), category('', '2/4'))

    def test_normalization(self):
        self.assertEqual('Edor', normalize_key('E Dorian'))
        self.assertEqual('F#min', normalize_key('F#m'))
        self.assertEqual('Gmaj', normalize_key('G'))
        self.assertEqual('morning dew', normalize_title('Morning Dew, The'))
        self.assertEqual('morning dew', normalize_title('The Morning Dew (reel)'))


if __name__ == '__main__':
    unittest.main()
