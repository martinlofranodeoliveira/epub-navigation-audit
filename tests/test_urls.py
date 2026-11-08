import unittest

from epub_navigation_audit.urls import resolve_reference


class UrlTests(unittest.TestCase):
    def local(self, base, href, path, fragment=None):
        self.assertEqual(resolve_reference(base, href), {
            'kind': 'local', 'path': path, 'fragment': fragment, 'reason': None})

    def test_local_paths_and_fragments(self):
        for href, expected in [('chapter.xhtml', 'EPUB/chapter.xhtml'),
                               ('./chapter.xhtml', 'EPUB/chapter.xhtml'),
                               ('Text/../chapter.xhtml', 'EPUB/chapter.xhtml'),
                               ('Text/%2E%2e/chapter.xhtml', 'EPUB/chapter.xhtml'),
                               ('Text/.%2e/chapter.xhtml', 'EPUB/chapter.xhtml'),
                               ('Text/%2e./chapter.xhtml', 'EPUB/chapter.xhtml'),
                               ('Text/%2E/chapter.xhtml', 'EPUB/Text/chapter.xhtml'),
                               ('../chapter.xhtml', 'chapter.xhtml'),
                               ('%252e.xhtml', 'EPUB/%2e.xhtml'),
                               ('café com%20leite.xhtml', 'EPUB/café com leite.xhtml'),
                               ('caf%C3%A9.xhtml', 'EPUB/café.xhtml')]:
            with self.subTest(href=href):
                self.local('EPUB/nav.xhtml', href, expected)
        self.local('EPUB/nav.xhtml', '', 'EPUB/nav.xhtml')
        self.local('EPUB/nav.xhtml', '#', 'EPUB/nav.xhtml', '')
        self.local('EPUB/nav.xhtml', '#caf%C3%A9', 'EPUB/nav.xhtml', 'café')
        self.local('EPUB/nav.xhtml', '#a%2Fb', 'EPUB/nav.xhtml', 'a/b')
        self.local('', 'EPUB/Book.opf', 'EPUB/Book.opf')

    def test_final_dot_is_directory(self):
        for href, expected in [('.', 'EPUB/'), ('Text/..', 'EPUB/'),
                               ('Text/%2e%2e', 'EPUB/'), ('../', ''),
                               ('Text/', 'EPUB/Text/'), ('Text/.', 'EPUB/Text/')]:
            with self.subTest(href=href):
                self.local('EPUB/nav.xhtml', href, expected)

    def test_preserves_case_and_unicode_normalization(self):
        self.local('EPUB/nav.xhtml', 'Cafe\u0301.xhtml', 'EPUB/Cafe\u0301.xhtml')
        self.local('EPUB/nav.xhtml', 'CHAPTER.xhtml#Intro', 'EPUB/CHAPTER.xhtml', 'Intro')

    def test_remote_classification_never_returns_secrets(self):
        for href in ['https://u:secret@example.org/a?token=secret#frag',
                     '//example.org/a?token=secret', 'urn:example:remote',
                     'https://example.org/a?']:
            with self.subTest(href=href):
                self.assertEqual(resolve_reference('EPUB/nav.xhtml', href), {
                    'kind': 'remote', 'path': None, 'fragment': None, 'reason': None})

    def test_unsupported_is_not_a_fabricated_member(self):
        for href in ['../../a.xhtml', '/a.xhtml', 'a//b.xhtml', 'a\\b.xhtml',
                     'a%2fb.xhtml', 'a%5Cb.xhtml', 'a%00.xhtml',
                     '%ff.xhtml', '%C3.xhtml', 'a%.xhtml', 'a%0.xhtml',
                     'a%GG.xhtml', ' a.xhtml', 'a.xhtml ', 'a\t.xhtml',
                     'a.xhtml?', 'a.xhtml?x=1', 'a.xhtml#epubcfi(/6/2)',
                     'a.xhtml#xpointer(id(x))', 'a.xhtml#svgView(viewBox(1,2,3,4))',
                     'a.xhtml#element(x)', 'a.xhtml#x:~:text=secret',
                     'a.xhtml#foo=bar', 'a.xhtml#%ff', 'a.xhtml#x%00',
                     'file:///tmp/secret', 'data:text/plain,secret',
                     'javascript:alert(1)', 'js:x', 'local:x']:
            with self.subTest(href=href):
                result = resolve_reference('EPUB/nav.xhtml', href)
                self.assertEqual(result['kind'], 'unsupported')
                self.assertIsNone(result['path'])
                self.assertIsNone(result['fragment'])
                self.assertNotIn(href, result.values())

    def test_bad_api_types_and_noncanonical_bases(self):
        for base, href in [(None, ''), ('', None), ('/absolute', ''),
                           ('a/../b', ''), ('a//b', ''), ('a\\b', '')]:
            with self.subTest(base=base, href=href), self.assertRaises(ValueError):
                resolve_reference(base, href)
