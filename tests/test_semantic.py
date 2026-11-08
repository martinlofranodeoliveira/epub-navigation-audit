import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from epub_navigation_audit.model import AuditError, AuditLimits, Issues, StopAudit
from epub_navigation_audit.semantic import inspect_publication


CONTAINER = '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="EPUB/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''
OPF = '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata><title xmlns="http://purl.org/dc/elements/1.1/">PRIVATE TITLE</title></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/><item id="two" href="two.svg" media-type="image/svg+xml"/></manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>'''
NAV = '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:e="http://www.idpf.org/2007/ops"><head><title>PRIVATE NAV</title></head><body><nav e:type="toc"><h1>PRIVATE TOC</h1><ol><li><a href="one.xhtml#intro">PRIVATE LABEL</a></li><li><a href="two.svg#picture">SVG</a></li></ol></nav></body></html>'''
ONE = '''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>PRIVATE CHAPTER</title></head><body><h1 id="intro" xml:id="intro">PRIVATE PROSE</h1></body></html>'''
TWO = '''<svg xmlns="http://www.w3.org/2000/svg"><g id="picture"/></svg>'''


def publication():
    return {path: value.encode() for path, value in {
        'META-INF/container.xml': CONTAINER, 'EPUB/book.opf': OPF,
        'EPUB/nav.xhtml': NAV, 'EPUB/one.xhtml': ONE, 'EPUB/two.svg': TWO,
    }.items()}


class Reader:
    def __init__(self, members, failures=(), stop=None):
        self.members, self.failures, self.stop = members, set(failures), stop
        self.entries = {name: SimpleNamespace(directory=name.endswith('/')) for name in members}
        self.reads = []

    def read(self, name, *, max_bytes=None):
        self.reads.append(name)
        if name == self.stop:
            raise StopAudit
        return None if name in self.failures else self.members.get(name)


class SemanticTests(unittest.TestCase):
    def audit(self, members=None, *, limits=None, rootfile=None, include_hrefs=False, reader=None):
        limits = limits or AuditLimits()
        issues = Issues(limits.max_issues)
        reader = reader or Reader(members if members is not None else publication())
        result = inspect_publication(reader, rootfile=rootfile, include_hrefs=include_hrefs, limits=limits, issues=issues)
        return result, issues, reader

    def changed(self, path, old, new):
        members = publication()
        members[path] = members[path].replace(old.encode(), new.encode())
        return members

    def codes(self, issues):
        return {issue.code for issue in issues.items}

    def test_consistent_inventory_ids_and_privacy(self):
        result, issues, reader = self.audit()
        self.assertEqual(issues.items, [])
        self.assertEqual(result['summary'], {'manifest_items': 3, 'spine_items': 2,
                         'nav_links': 2, 'resolved_links': 2, 'xml_documents': 5,
                         'xml_nodes': result['summary']['xml_nodes']})
        self.assertEqual(result['package']['path'], 'EPUB/book.opf')
        self.assertEqual(result['package']['rootfiles'], ['EPUB/book.opf'])
        self.assertEqual([d['path'] for d in result['documents']], ['EPUB/nav.xhtml', 'EPUB/one.xhtml', 'EPUB/two.svg'])
        self.assertTrue(all(d['complete'] for d in result['documents']))
        self.assertEqual(next(d for d in result['documents'] if d['path'] == 'EPUB/one.xhtml')['ids'], 1)
        serialized = json.dumps(result)
        self.assertNotIn('PRIVATE', serialized)
        self.assertNotIn('href"', serialized)
        self.assertEqual(len(reader.reads), len(set(reader.reads)))
        self.assertEqual(result['navigation']['links'][0]['href_sha256'], hashlib.sha256(b'one.xhtml#intro').hexdigest())
        result, _, _ = self.audit(include_hrefs=True)
        self.assertEqual(result['navigation']['links'][0]['href'], 'one.xhtml#intro')

    def test_nested_toc_document_order_image_label_and_span(self):
        nav = NAV.replace('<li><a href="one.xhtml#intro">PRIVATE LABEL</a></li>', '<li><span>group</span><ol><li><a href="one.xhtml#intro"><img src="cover.png" alt="label"/></a><ol><li><a href="two.svg#picture" title="label"/></li></ol></li></ol></li>')
        members = publication()
        members['EPUB/nav.xhtml'] = nav.encode()
        result, issues, _ = self.audit(members)
        self.assertFalse(issues.error)
        self.assertEqual([link['target'] for link in result['navigation']['links']], ['EPUB/one.xhtml', 'EPUB/two.svg', 'EPUB/two.svg'])

    def test_utf16_and_arbitrary_prefixes(self):
        members = publication()
        for path, value in list(members.items()):
            text = value.decode()
            if path == 'EPUB/one.xhtml':
                text = text.replace('<html xmlns=', '<h:html xmlns:h=').replace('</html>', '</h:html>')
                # Prefix only the root; its namespace remains XHTML.
            members[path] = text.encode('utf-16')
        result, issues, _ = self.audit(members)
        self.assertFalse(issues.error)
        self.assertFalse(issues.partial)
        self.assertEqual(result['summary']['resolved_links'], 2)

    def test_rootfile_percent_unicode_and_selection(self):
        members = publication()
        members['META-INF/container.xml'] = CONTAINER.replace('EPUB/book.opf', 'EPUB/caf%C3%A9.opf').encode()
        members['EPUB/café.opf'] = members.pop('EPUB/book.opf')
        result, issues, _ = self.audit(members, rootfile='EPUB/café.opf')
        self.assertFalse(issues.error)
        self.assertEqual(result['package']['path'], 'EPUB/café.opf')
        members['META-INF/container.xml'] = CONTAINER.replace('</rootfiles>', '<rootfile full-path="other.opf" media-type="application/oebps-package+xml"/></rootfiles>').encode()
        result, issues, reader = self.audit(members)
        self.assertEqual(self.codes(issues), {'rootfile_selection_required'})
        self.assertEqual(reader.reads, ['META-INF/container.xml'])
        with self.assertRaises(AuditError) as caught:
            self.audit(members, rootfile='absent.opf')
        self.assertEqual(caught.exception.code, 'rootfile_not_listed')

    def test_unicode_path_lookup_preserves_physical_names(self):
        members = publication()
        members['EPUB/cafe\u0301.xhtml'] = members.pop('EPUB/one.xhtml')
        members['EPUB/book.opf'] = members['EPUB/book.opf'].replace(b'one.xhtml', 'caf%C3%A9.xhtml'.encode())
        members['EPUB/nav.xhtml'] = members['EPUB/nav.xhtml'].replace(b'one.xhtml', 'café.xhtml'.encode())
        result, issues, reader = self.audit(members)
        self.assertFalse(issues.error)
        self.assertFalse(issues.partial)
        self.assertEqual(result['navigation']['links'][0]['target'], 'EPUB/cafe\u0301.xhtml')
        self.assertEqual(result['package']['manifest'][1]['path'], 'EPUB/cafe\u0301.xhtml')
        self.assertEqual(reader.reads.count('EPUB/cafe\u0301.xhtml'), 1)
        # Even an exact spelling does not justify guessing between collisions.
        members['EPUB/café.xhtml'] = ONE.encode()
        result, issues, _ = self.audit(members)
        self.assertIn('member_normalization_ambiguous', self.codes(issues))
        self.assertTrue(issues.error)
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'unsupported')

    def test_unicode_fragment_equivalence_is_not_invented(self):
        members = self.changed('EPUB/one.xhtml', 'intro', 'cafe\u0301')
        members['EPUB/nav.xhtml'] = members['EPUB/nav.xhtml'].replace(b'#intro', '#caf%C3%A9'.encode())
        result, issues, _ = self.audit(members)
        self.assertFalse(issues.error)
        self.assertTrue(issues.partial)
        self.assertEqual(result['navigation']['links'][0]['fragment'], 'café')
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'unsupported')
        self.assertIn('fragment_normalization_unsupported', self.codes(issues))

    def test_unsupported_rootfile_reference_is_not_missing(self):
        result, issues, _ = self.audit(self.changed('META-INF/container.xml', 'EPUB/book.opf', '/EPUB/book.opf'))
        self.assertTrue(issues.partial)
        self.assertFalse(issues.error)
        self.assertEqual(result['package']['rootfiles'], [None])

    def test_missing_members_and_wrong_namespaces(self):
        for path, code in [('META-INF/container.xml', 'container_missing'), ('EPUB/book.opf', 'package_missing'), ('EPUB/one.xhtml', 'manifest_member_missing')]:
            members = publication()
            del members[path]
            with self.subTest(path=path):
                _, issues, _ = self.audit(members)
                self.assertIn(code, self.codes(issues))
                self.assertTrue(issues.error)
        members = self.changed('EPUB/nav.xhtml', 'http://www.w3.org/1999/xhtml', 'urn:wrong')
        _, issues, _ = self.audit(members)
        self.assertIn('content_root_invalid', self.codes(issues))

    def test_fragments_are_exact_empty_whole_and_duplicates_invalid(self):
        for fragment, resolution in [('#intro', 'resolved'), ('', 'resolved'), ('#', 'resolved'), ('#Intro', 'missing_fragment'), ('#top', 'missing_fragment')]:
            members = self.changed('EPUB/nav.xhtml', '#intro', fragment)
            result, _, _ = self.audit(members)
            self.assertEqual(result['navigation']['links'][0]['resolution'], resolution)
        members = self.changed('EPUB/one.xhtml', '</body>', '<div id="intro"/></body>')
        result, issues, _ = self.audit(members)
        self.assertIn('duplicate_id', self.codes(issues))
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'target_unavailable')

    def test_missing_unmanifested_nonspine_and_noncontent_targets(self):
        cases = [('one.xhtml#intro', 'absent.xhtml', 'missing_member'),
                 ('one.xhtml#intro', 'orphan.xhtml', 'not_manifested')]
        for old, new, resolution in cases:
            members = self.changed('EPUB/nav.xhtml', old, new)
            members['EPUB/orphan.xhtml'] = ONE.encode()
            result, issues, _ = self.audit(members)
            self.assertEqual(result['navigation']['links'][0]['resolution'], resolution)
            self.assertTrue(issues.error)
        members = self.changed('EPUB/book.opf', '<itemref idref="one"/>', '')
        result, issues, _ = self.audit(members)
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'not_spine')
        self.assertTrue(issues.error)
        members = self.changed('EPUB/book.opf', 'id="one" href="one.xhtml" media-type="application/xhtml+xml"', 'id="one" href="one.xhtml" media-type="application/octet-stream"')
        # Foreign spine is explicitly incomplete rather than inventing invalid.
        result, issues, _ = self.audit(members)
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'unsupported')
        self.assertFalse(issues.error)
        self.assertTrue(issues.partial)
        members['EPUB/book.opf'] = members['EPUB/book.opf'].replace(b'<itemref idref="one"/>', b'')
        result, issues, _ = self.audit(members)
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'not_content')

    def test_fallback_targets_incomplete_never_not_spine(self):
        members = self.changed('EPUB/book.opf', '</manifest>', '<item id="foreign" href="foreign.dat" media-type="application/x-foreign" fallback="one"/></manifest>')
        members['EPUB/book.opf'] = members['EPUB/book.opf'].replace(b'idref="one"', b'idref="foreign"')
        members['EPUB/foreign.dat'] = b'opaque'
        result, issues, _ = self.audit(members)
        self.assertFalse(issues.error)
        self.assertIn('toc_fallback_unsupported', self.codes(issues))
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'unsupported')
        # A direct core spine entry is sufficient even if also a fallback.
        members['EPUB/book.opf'] = members['EPUB/book.opf'].replace(b'<itemref idref="foreign"/>', b'<itemref idref="foreign"/><itemref idref="one"/>')
        result, issues, _ = self.audit(members)
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'resolved')

    def test_duplicate_manifest_id_path_and_bad_spine(self):
        cases = [('id="two"', 'id="one"', 'manifest_id_duplicate'),
                 ('href="two.svg"', 'href="./one.xhtml"', 'manifest_path_duplicate'),
                 ('<itemref idref="two"/>', '<itemref idref="one"/>', 'spine_idref_duplicate'),
                 ('<itemref idref="two"/>', '<itemref idref="absent"/>', 'spine_idref_invalid'),
                 ('<itemref idref="two"/>', '<itemref idref="two" linear="sometimes"/>', 'spine_linear_invalid')]
        for old, new, code in cases:
            with self.subTest(code=code):
                _, issues, _ = self.audit(self.changed('EPUB/book.opf', old, new))
                self.assertIn(code, self.codes(issues))
        members = self.changed('EPUB/book.opf', '<itemref ', '<itemref linear="no" ')
        _, issues, _ = self.audit(members)
        self.assertIn('spine_linear_missing', self.codes(issues))

    def test_remote_assets_not_selected_or_echoed(self):
        members = self.changed('EPUB/book.opf', '</manifest>', '<item id="remote" href="https://u:SECRET@example.invalid/a?token=SECRET" media-type="image/png"/></manifest>')
        result, issues, reader = self.audit(members)
        self.assertFalse(issues.partial)
        self.assertFalse(issues.error)
        self.assertEqual(result['package']['manifest'][-1]['resolution'], 'remote')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertFalse(any('https:' in path for path in reader.reads))

    def test_unsupported_navigation_does_not_fabricate_errors(self):
        for href in ['one.xhtml#epubcfi(/6/2)', 'one.xhtml?version=1', '/one.xhtml', 'https://example.invalid/a?token=SECRET']:
            with self.subTest(href=href):
                result, issues, _ = self.audit(self.changed('EPUB/nav.xhtml', 'one.xhtml#intro', href))
                self.assertFalse(issues.error)
                self.assertTrue(issues.partial)
                self.assertEqual(result['navigation']['links'][0]['resolution'], 'unsupported')
                self.assertNotIn('SECRET', json.dumps(result))

    def test_base_and_dtd_do_not_resolve_ignored_base(self):
        for xml in [NAV.replace('<body>', '<body xml:base="elsewhere/">'), '<!DOCTYPE html>' + NAV]:
            members = publication()
            members['EPUB/nav.xhtml'] = xml.encode()
            result, issues, _ = self.audit(members)
            self.assertFalse(issues.error)
            self.assertTrue(issues.partial)
            self.assertEqual(result['navigation']['links'], [])

    def test_encryption_stops_before_protected_xml(self):
        members = publication()
        members['META-INF/encryption.xml'] = b'ignored encrypted metadata'
        result, issues, reader = self.audit(members)
        self.assertEqual(reader.reads, ['META-INF/container.xml'])
        self.assertEqual(result['package']['path'], 'EPUB/book.opf')
        self.assertEqual(self.codes(issues), {'ocf_encryption_unsupported'})

    def test_unsupported_version_and_toc_structure(self):
        result, issues, _ = self.audit(self.changed('EPUB/book.opf', 'version="3.0"', 'version="2.0"'))
        self.assertEqual(self.codes(issues), {'version_unsupported'})
        self.assertEqual(result['package']['version'], '2.0')
        for old, new, code in [('<h1>PRIVATE TOC</h1>', '<div/>', 'toc_structure'),
                               ('<a href="one.xhtml#intro">PRIVATE LABEL</a>', '<span>group</span>', 'toc_structure'),
                               ('<a href="one.xhtml#intro">', '<a>', 'toc_href_missing'),
                               ('e:type="toc"', 'e:type="landmarks"', 'toc_count_invalid')]:
            with self.subTest(code=code):
                _, issues, _ = self.audit(self.changed('EPUB/nav.xhtml', old, new))
                self.assertIn(code, self.codes(issues))

    def test_spine_doc_without_toc_link_is_allowed_and_order_is_warning(self):
        members = self.changed('EPUB/nav.xhtml', '<li><a href="two.svg#picture">SVG</a></li>', '')
        _, issues, _ = self.audit(members)
        self.assertFalse(issues.error)
        members = self.changed('EPUB/book.opf', '<itemref idref="one"/><itemref idref="two"/>', '<itemref idref="two"/><itemref idref="one"/>')
        _, issues, _ = self.audit(members)
        self.assertEqual(self.codes(issues), {'toc_order'})
        self.assertFalse(issues.error)
        self.assertFalse(issues.partial)

    def test_reference_and_xml_budgets_preserve_partial_inventory(self):
        result, issues, reader = self.audit(limits=AuditLimits(max_links=3))
        self.assertIn('reference_limit', self.codes(issues))
        self.assertEqual(result['summary']['manifest_items'], 2)
        self.assertEqual(reader.reads, ['META-INF/container.xml', 'EPUB/book.opf'])
        result, issues, reader = self.audit(limits=AuditLimits(max_xml_nodes=6))
        self.assertTrue(issues.partial)
        self.assertIn('xml_node_limit', self.codes(issues))
        self.assertTrue(result['summary']['xml_documents'] >= 2)
        self.assertEqual(reader.reads[-1], 'EPUB/book.opf')
        result, issues, _ = self.audit(limits=AuditLimits(max_issues=1), members={})
        self.assertTrue(issues.error)
        self.assertEqual(self.codes(issues), {'issue_limit'})
        self.assertEqual(result['package']['rootfiles'], [])

    def test_failed_target_not_retried_and_no_missing_fabricated(self):
        reader = Reader(publication(), failures=['EPUB/one.xhtml'])
        result, issues, _ = self.audit(reader=reader)
        self.assertEqual(reader.reads.count('EPUB/one.xhtml'), 1)
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'target_unavailable')
        self.assertNotIn('toc_member_missing', self.codes(issues))

    def test_malformed_selected_document_marks_overall_coverage_partial(self):
        from epub_navigation_audit import audit_epub

        for path in ['META-INF/container.xml', 'EPUB/book.opf', 'EPUB/nav.xhtml', 'EPUB/one.xhtml']:
            members = publication()
            members[path] = b'<html'
            with self.subTest(path=path):
                result, issues, _ = self.audit(members)
                self.assertTrue(issues.error)
                self.assertTrue(issues.partial)
                self.assertIn('xml_invalid', self.codes(issues))
                if path in {'EPUB/nav.xhtml', 'EPUB/one.xhtml'}:
                    self.assertFalse(next(d for d in result['documents'] if d['path'] == path)['complete'])
        members = publication()
        members['EPUB/nav.xhtml'] = b'<html'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.epub'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('mimetype', b'application/epub+zip')
                for member, data in members.items():
                    archive.writestr(member, data)
            report = audit_epub(path)
        self.assertEqual(report['status'], 'invalid')
        self.assertFalse(report['complete'])
        self.assertFalse(next(d for d in report['documents'] if d['path'] == 'EPUB/nav.xhtml')['complete'])

    def test_structural_abort_is_partial_but_completed_fragment_check_is_not(self):
        cases = [('META-INF/container.xml', 'version="1.0"', 'version="2.0"'),
                 ('EPUB/book.opf', '<manifest>', '<other>'),
                 ('EPUB/book.opf', '<spine>', '<other>'),
                 ('EPUB/nav.xhtml', 'e:type="toc"', 'e:type="landmarks"'),
                 ('EPUB/nav.xhtml', '<h1>PRIVATE TOC</h1>', '<div/>'),
                 ('EPUB/nav.xhtml', 'http://www.w3.org/1999/xhtml', 'urn:wrong')]
        for path, old, new in cases:
            with self.subTest(path=path, old=old):
                _, issues, _ = self.audit(self.changed(path, old, new))
                self.assertTrue(issues.error)
                self.assertTrue(issues.partial)
        _, issues, _ = self.audit(self.changed('EPUB/nav.xhtml', '#intro', '#absent'))
        self.assertTrue(issues.error)
        self.assertFalse(issues.partial)

    def test_cached_metadata_cannot_bypass_content_root_check(self):
        members = self.changed('EPUB/book.opf', 'href="one.xhtml"', 'href="book.opf"')
        members['EPUB/nav.xhtml'] = members['EPUB/nav.xhtml'].replace(b'one.xhtml#intro', b'book.opf#intro')
        result, issues, reader = self.audit(members)
        self.assertTrue(issues.error)
        self.assertTrue(issues.partial)
        self.assertIn('content_root_invalid', self.codes(issues))
        self.assertEqual(result['navigation']['links'][0]['resolution'], 'target_unavailable')
        self.assertEqual(reader.reads.count('EPUB/book.opf'), 1)
