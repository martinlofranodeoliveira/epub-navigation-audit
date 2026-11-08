"""Integration checks using only original, small synthetic EPUB publications."""
import copy
import errno
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from epub_navigation_audit import AuditError, AuditLimits, audit_epub, to_json, to_markdown
from epub_navigation_audit import cli


PROJECT = Path(__file__).resolve().parents[1]
GENERATOR = runpy.run_path(str(PROJECT / 'scripts' / 'make_samples.py'))
sample_files = GENERATOR['sample_files']
write_sample = GENERATOR['write_sample']


class CliApiReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / 'synthetic.epub'

    def tearDown(self):
        self.temporary.cleanup()

    def create(self, variant='valido', name='synthetic.epub'):
        path = self.root / name
        write_sample(path, variant)
        return path

    def create_files(self, files, *, order=None, methods=None, extras=None, name='synthetic.epub'):
        """A transparent ZIP writer, independent of the auditor's archive parser."""
        path = self.root / name
        order = order or ['mimetype', *sorted(key for key in files if key != 'mimetype')]
        methods, extras = methods or {}, extras or {}
        with zipfile.ZipFile(path, 'w') as archive:
            for filename in order:
                info = zipfile.ZipInfo(filename, (2026, 11, 8, 0, 0, 0))
                info.create_system = 0
                info.extra = extras.get(filename, b'')
                method = methods.get(filename, zipfile.ZIP_STORED if filename == 'mimetype' else zipfile.ZIP_DEFLATED)
                archive.writestr(info, files[filename], compress_type=method)
        return path

    def environment(self):
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(PROJECT / 'src')
        environment['PYTHONIOENCODING'] = 'utf-8'
        return environment

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, '-m', 'epub_navigation_audit', *map(str, arguments)],
            cwd=self.root, env=self.environment(), capture_output=True,
            text=True, encoding='utf-8', timeout=20,
        )

    def assert_no_temporary_reports(self):
        self.assertEqual(list(self.root.glob('.epub-navigation-audit-*.tmp')), [])

    def test_public_api_composes_archive_package_navigation_and_documents(self):
        self.create()
        original = self.path.read_bytes()
        report = audit_epub(self.path)
        self.assertEqual(report['status'], 'consistent', report['issues'])
        self.assertTrue(report['complete'])
        self.assertEqual(report['profile'], 'epub-navigation-audit-v1')
        self.assertEqual(report['archive']['bytes'], len(original))
        self.assertEqual(report['archive']['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(report['package']['path'], 'EPUB/package.opf')
        self.assertEqual(report['package']['version'], '3.0')
        self.assertEqual([item['path'] for item in report['package']['spine']],
                         ['EPUB/text/inicio.xhtml', 'EPUB/text/café.xhtml'])
        self.assertEqual(report['navigation']['path'], 'EPUB/nav.xhtml')
        self.assertEqual(report['navigation']['toc_count'], 1)
        self.assertEqual([link['fragment'] for link in report['navigation']['links']], ['inicio', 'fim'])
        self.assertTrue(all(link['resolution'] == 'resolved' for link in report['navigation']['links']))
        self.assertEqual(report['summary']['resolved_links'], 2)
        self.assertEqual(report['summary']['xml_documents'], 5)
        self.assertEqual(len(report['documents']), 3)
        self.assertEqual([item['path'] for item in report['documents']],
                         sorted(item['path'] for item in report['documents']))
        self.assertEqual(self.path.read_bytes(), original)

    def test_all_twelve_original_variants_have_contract_results_and_preserve_input(self):
        expected = {
            'valido': 'consistent', 'fragmento-ausente': 'invalid',
            'arquivo-ausente': 'invalid', 'id-duplicado': 'invalid',
            'mimetype-incorreto': 'invalid', 'fora-spine': 'invalid',
            'doctype': 'incomplete', 'ordem-diferente': 'consistent',
            'svg': 'consistent', 'multiplas-rendicoes': 'incomplete',
            'unicode-decomposto': 'consistent', 'normalizacao-divergente': 'consistent',
        }
        self.assertEqual(set(expected), set(GENERATOR['VARIANTS']))
        for variant, status in expected.items():
            with self.subTest(variant=variant):
                path = self.create(variant, variant + '.epub')
                before = path.read_bytes()
                report = audit_epub(path)
                self.assertEqual(report['status'], status, report['issues'])
                self.assertEqual(report['archive']['sha256'], hashlib.sha256(before).hexdigest())
                self.assertEqual(path.read_bytes(), before)
                if status == 'consistent':
                    self.assertTrue(report['complete'])
                elif status == 'incomplete':
                    self.assertFalse(report['complete'])
                # NFC/NFD-equivalent member paths resolve to their physical
                # ZIP spelling; this does not normalize document IDs.

    def test_rootfile_selection_covers_only_the_explicit_declared_rendition(self):
        self.create('multiplas-rendicoes')
        unselected = audit_epub(self.path)
        self.assertEqual(unselected['status'], 'incomplete')
        self.assertTrue(any(issue['code'] == 'rootfile_selection_required'
                            for issue in unselected['issues']))
        self.assertIsNone(unselected['package']['path'])
        self.assertEqual(set(unselected['package']['rootfiles']),
                         {'EPUB/package.opf', 'EPUB/alternativa.opf'})
        for member in unselected['package']['rootfiles']:
            with self.subTest(member=member):
                report = audit_epub(self.path, rootfile=member)
                self.assertEqual(report['status'], 'consistent', report['issues'])
                self.assertEqual(report['package']['path'], member)
                self.assertEqual(report['options']['rootfile'], member)
        with self.assertRaises(AuditError) as caught:
            audit_epub(self.path, rootfile='PRIVATE_UNDECLARED_MEMBER.opf')
        self.assertEqual(caught.exception.code, 'rootfile_not_listed')
        self.assertNotIn('PRIVATE_UNDECLARED_MEMBER', str(caught.exception))

    def test_reversed_toc_is_not_mistaken_for_spine_order_or_an_invalid_book(self):
        self.create('ordem-diferente')
        report = audit_epub(self.path)
        self.assertEqual(report['status'], 'consistent', report['issues'])
        self.assertEqual([item['idref'] for item in report['package']['spine']], ['intro', 'final'])
        self.assertEqual([link['fragment'] for link in report['navigation']['links']], ['fim', 'inicio'])
        self.assertFalse(any(issue['severity'] == 'error' for issue in report['issues']))

    def test_href_privacy_is_explicit_and_editorial_text_is_never_exported(self):
        files = sample_files()
        href = 'https://reader:PRIVATE_SYNTHETIC_SECRET@example.invalid/image.png?token=PRIVATE_QUERY_VALUE'
        files['EPUB/package.opf'] = files['EPUB/package.opf'].replace(
            b'</manifest>', ('<item id="remote-art" href="' + href +
                            '" media-type="image/png"/></manifest>').encode())
        for name in list(files):
            if name.endswith(('.xhtml', '.opf')):
                files[name] = files[name].replace('Guia fictício de navegação'.encode(), b'EDITORIAL_TITLE_CANARY_7832')
                files[name] = files[name].replace('Projeto demonstrativo'.encode(), b'EDITORIAL_AUTHOR_CANARY_7832')
                files[name] = files[name].replace('Introdução fictícia'.encode(), b'TOC_LABEL_CANARY_7832')
                files[name] = files[name].replace('Este texto foi criado para testar referências locais.'.encode(), b'CHAPTER_TEXT_CANARY_7832')
        self.create_files(files)
        hidden = audit_epub(self.path)
        shown = audit_epub(self.path, include_hrefs=True)
        hidden_entry = next(item for item in hidden['package']['manifest'] if item['id'] == 'remote-art')
        shown_entry = next(item for item in shown['package']['manifest'] if item['id'] == 'remote-art')
        self.assertNotIn('href', hidden_entry)
        self.assertEqual(hidden_entry['href_sha256'], hashlib.sha256(href.encode()).hexdigest())
        self.assertEqual(shown_entry['href'], href)
        self.assertEqual(shown_entry['href_sha256'], hidden_entry['href_sha256'])
        self.assertTrue(all('href' not in link for link in hidden['navigation']['links']))
        canaries = ('EDITORIAL_TITLE_CANARY_7832', 'EDITORIAL_AUTHOR_CANARY_7832',
                    'TOC_LABEL_CANARY_7832', 'CHAPTER_TEXT_CANARY_7832')
        combined_input = b''.join(files.values())
        for canary in canaries:
            self.assertIn(canary.encode(), combined_input)
        for render in (to_json, to_markdown):
            hidden_text, shown_text = render(hidden), render(shown)
            self.assertNotIn('PRIVATE_SYNTHETIC_SECRET', hidden_text)
            self.assertNotIn('PRIVATE_QUERY_VALUE', hidden_text)
            self.assertIn('PRIVATE_SYNTHETIC_SECRET', shown_text.replace('\\_', '_'))
            for canary in canaries:
                self.assertNotIn(canary, hidden_text.replace('\\_', '_'))
                self.assertNotIn(canary, shown_text.replace('\\_', '_'))

    def test_json_is_ascii_deterministic_and_renderers_do_not_mutate_the_report(self):
        self.create()
        report = audit_epub(self.path, include_hrefs=True)
        original = copy.deepcopy(report)
        encoded = to_json(report)
        self.assertTrue(encoded.isascii())
        self.assertTrue(encoded.endswith('\n'))
        self.assertEqual(json.loads(encoded), report)
        self.assertNotIn(str(self.root), encoded)
        self.assertEqual(encoded, to_json(report))
        self.assertEqual(to_markdown(report), to_markdown(report))
        self.assertEqual(report, original)

    def test_markdown_escapes_technical_names_hrefs_and_controls(self):
        self.create()
        report = audit_epub(self.path, include_hrefs=True)
        payload = 'unsafe|<img src=x onerror=alert(1)>`*_[go](javascript:evil)\\\n\t\u202e'
        report['filename'] = payload
        report['package']['manifest'][0]['id'] = payload
        report['package']['manifest'][0]['href'] = payload
        report['navigation']['links'][0]['fragment'] = payload
        report['issues'].append({'severity': 'warning', 'code': 'synthetic', 'message': payload,
                                 'path': payload, 'location': 1})
        text = to_markdown(report)
        self.assertNotIn('<img', text)
        self.assertNotIn(payload, text)
        self.assertNotIn('\u202e', text)
        self.assertEqual(text.count('## Achados\n'), 1)
        for escaped in ('&lt;img', r'\|', r'\`', r'\[go\]\(javascript:evil\)',
                        r'\\u000a', r'\\u0009', r'\\u202e'):
            self.assertIn(escaped, text)

    def test_mimetype_is_exactly_twenty_bytes_and_rejects_padding(self):
        files = sample_files()
        self.assertEqual(files['mimetype'], b'application/epub+zip')
        self.assertEqual(len(files['mimetype']), 20)
        self.create('mimetype-incorreto')
        report = audit_epub(self.path)
        self.assertEqual(report['status'], 'invalid')
        codes = {issue['code'] for issue in report['issues']}
        self.assertIn('mimetype_size', codes)
        self.assertIn('mimetype_content', codes)

    def test_mimetype_must_be_first_physically_not_only_in_a_sorted_listing(self):
        files = sample_files()
        order = ['META-INF/container.xml', 'mimetype',
                 *sorted(name for name in files if name not in {'mimetype', 'META-INF/container.xml'})]
        self.create_files(files, order=order)
        report = audit_epub(self.path)
        self.assertEqual(report['status'], 'invalid', report['issues'])
        self.assertTrue(any(issue['code'] == 'mimetype_order' for issue in report['issues']))

    def test_mimetype_cannot_be_deflated_or_have_a_local_extra_field(self):
        for name, methods, extras, expected in (
            ('compressed.epub', {'mimetype': zipfile.ZIP_DEFLATED}, {}, 'mimetype_encoding'),
            ('extra.epub', {}, {'mimetype': struct.pack('<HH', 0xcafe, 0)}, 'mimetype_extra'),
        ):
            with self.subTest(name=name):
                path = self.create_files(sample_files(), methods=methods, extras=extras, name=name)
                report = audit_epub(path)
                self.assertEqual(report['status'], 'invalid', report['issues'])
                self.assertTrue(any(issue['code'] == expected for issue in report['issues']))

    def test_missing_mimetype_is_a_visible_error(self):
        files = sample_files(); del files['mimetype']
        self.create_files(files, order=sorted(files))
        report = audit_epub(self.path)
        self.assertEqual(report['status'], 'invalid', report['issues'])
        self.assertTrue(any(issue['code'] == 'mimetype_missing' for issue in report['issues']))

    def test_budget_interruption_is_visible_and_preserves_the_source(self):
        self.create()
        original = self.path.read_bytes()
        report = audit_epub(self.path, limits=AuditLimits(max_total_read_bytes=21))
        self.assertFalse(report['complete'])
        self.assertEqual(report['status'], 'incomplete', report['issues'])
        self.assertTrue(any(issue['severity'] == 'incomplete' for issue in report['issues']))
        self.assertLessEqual(report['archive']['read_bytes'], 22)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertIn('incomplete', to_markdown(report))

    def test_proven_invalidity_keeps_priority_after_a_later_budget_stop(self):
        self.create('mimetype-incorreto')
        report = audit_epub(self.path, limits=AuditLimits(max_total_read_bytes=22))
        self.assertFalse(report['complete'])
        self.assertEqual(report['status'], 'invalid', report['issues'])
        self.assertTrue(any(issue['severity'] == 'error' for issue in report['issues']))
        self.assertTrue(any(issue['severity'] == 'incomplete' for issue in report['issues']))

    def test_api_rejects_invalid_option_types_and_bounds(self):
        self.create()
        for options in ({'include_hrefs': 1}, {'include_hrefs': None}, {'rootfile': False},
                        {'rootfile': ''}, {'limits': None}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                audit_epub(self.path, **options)
        for path in (None, b'bytes.epub', '', '\x00'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                audit_epub(path)
        for options in ({'max_links': True}, {'max_members': 0}, {'max_xml_depth': 513},
                        {'max_archive_bytes': 268_435_457}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                AuditLimits(**options)

    def test_cli_all_four_exit_classes_and_operational_privacy(self):
        for variant, expected in [('valido', 0), ('fragmento-ausente', 1), ('doctype', 2)]:
            with self.subTest(variant=variant):
                path = self.create(variant, variant + '.epub')
                result = self.run_cli(path)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertEqual(json.loads(result.stdout), audit_epub(path))
        absent = self.root / 'PRIVATE_ABSENT_INPUT.epub'
        failed = self.run_cli(absent)
        self.assertEqual(failed.returncode, 3)
        self.assertEqual(failed.stdout, '')
        self.assertIn('Erro operacional', failed.stderr)
        self.assertNotIn('PRIVATE_ABSENT_INPUT', failed.stderr)
        self.assertNotIn(str(self.root), failed.stderr)
        self.assertNotIn('Traceback', failed.stderr)
        self.assertFalse(absent.exists())

    def test_cli_help_version_and_sanitized_usage_errors(self):
        for option in ('--help', '--version'):
            result = self.run_cli(option)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout)
            self.assertEqual(result.stderr, '')
        self.create()
        for arguments in ([], [self.path, '--format', 'PRIVATE_BAD_FORMAT'],
                          [self.path, '--max-xml-bytes', '0'], [self.path, '--max-links', '100001'],
                          [self.path, '--max-members', '1.5'], [self.path, '--include-h']):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(result.returncode, 3)
                self.assertEqual(result.stdout, '')
                self.assertIn('Erro de uso:', result.stderr)
                self.assertNotIn('PRIVATE_BAD_FORMAT', result.stderr)
                self.assertNotIn(str(self.root), result.stderr)

    def test_cli_rootfile_hrefs_limit_and_markdown_are_wired_to_the_api(self):
        self.create('multiplas-rendicoes')
        result = self.run_cli(self.path, '--rootfile', 'EPUB/alternativa.opf',
                              '--include-hrefs', '--max-links', '100')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = audit_epub(self.path, rootfile='EPUB/alternativa.opf', include_hrefs=True,
                              limits=AuditLimits(max_links=100))
        self.assertEqual(json.loads(result.stdout), expected)
        markdown = self.run_cli(self.path, '--rootfile', 'EPUB/alternativa.opf',
                                '--include-hrefs', '--max-links', '100', '--format', 'markdown')
        self.assertEqual(markdown.returncode, 0, markdown.stderr)
        self.assertEqual(markdown.stdout, to_markdown(expected))
        unknown = self.run_cli(self.path, '--rootfile', 'PRIVATE_UNDECLARED_MEMBER.opf')
        self.assertEqual(unknown.returncode, 3)
        self.assertNotIn('PRIVATE_UNDECLARED_MEMBER', unknown.stderr)

    def test_cli_rejects_empty_or_nul_input_and_rootfile_without_tracebacks(self):
        self.create()
        for arguments in ([''], ['\x00PRIVATE_INPUT'],
                          [str(self.path), '--rootfile', ''],
                          [str(self.path), '--rootfile', '\x00PRIVATE_ROOTFILE']):
            with self.subTest(arguments=arguments):
                output, diagnostic = io.StringIO(), io.StringIO()
                with patch.object(cli.sys, 'stdout', output), patch.object(cli.sys, 'stderr', diagnostic):
                    result = cli.main(arguments)
                self.assertEqual(result, 3)
                self.assertEqual(output.getvalue(), '')
                self.assertIn('Erro de uso:', diagnostic.getvalue())
                self.assertNotIn('PRIVATE_', diagnostic.getvalue())
                self.assertNotIn('Traceback', diagnostic.getvalue())

    def test_cli_publishes_all_result_classes_without_overwriting(self):
        for variant, expected in [('valido', 0), ('fragmento-ausente', 1), ('doctype', 2)]:
            with self.subTest(variant=variant):
                path = self.create(variant, variant + '.epub')
                destination = self.root / (variant + '.json')
                result = self.run_cli(path, '--output', destination)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(destination.read_bytes(), to_json(audit_epub(path)).encode())
                before = destination.read_bytes()
                repeated = self.run_cli(path, '--output', destination)
                self.assertEqual(repeated.returncode, 3)
                self.assertIn('output_exists', repeated.stderr)
                self.assertEqual(destination.read_bytes(), before)
        self.assert_no_temporary_reports()

    def test_output_cannot_overwrite_the_input_epub(self):
        self.create(); original = self.path.read_bytes()
        result = self.run_cli(self.path, '--output', self.path)
        self.assertEqual(result.returncode, 3)
        self.assertIn('output_exists', result.stderr)
        self.assertEqual(self.path.read_bytes(), original)
        self.assert_no_temporary_reports()

    def test_concurrent_destination_is_preserved_and_temporary_is_removed(self):
        destination = self.root / 'raced.json'; original_link = os.link

        def race(source, target):
            Path(target).write_text('CONCURRENT_SYNTHETIC_WRITER', encoding='utf-8')
            return original_link(source, target)

        with patch.object(cli.os, 'link', side_effect=race) as operation:
            with self.assertRaises(AuditError) as caught:
                cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(caught.exception.code, 'output_exists')
        self.assertEqual(operation.call_count, 1)
        self.assertEqual(destination.read_text(), 'CONCURRENT_SYNTHETIC_WRITER')
        self.assert_no_temporary_reports()

    def test_fsync_failure_publishes_nothing_and_sanitizes_backend_details(self):
        destination = self.root / 'unpublished.json'
        with patch.object(cli.os, 'fsync', side_effect=OSError('PRIVATE_FSYNC_BACKEND')):
            with self.assertRaises(AuditError) as caught:
                cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(caught.exception.code, 'output_write')
        self.assertNotIn('PRIVATE_FSYNC_BACKEND', str(caught.exception))
        self.assertFalse(destination.exists())
        self.assert_no_temporary_reports()

    def test_link_failure_has_no_overwrite_fallback(self):
        destination = self.root / 'unpublished.json'
        with patch.object(cli.os, 'link', side_effect=OSError(errno.ENOTSUP, 'PRIVATE_LINK_BACKEND')) as operation:
            with self.assertRaises(AuditError) as caught:
                cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(operation.call_count, 1)
        self.assertEqual(caught.exception.code, 'output_write')
        self.assertNotIn('PRIVATE_LINK_BACKEND', str(caught.exception))
        self.assertFalse(destination.exists())
        self.assert_no_temporary_reports()

    def test_output_parent_and_utf8_failures_leave_no_partial_report(self):
        destination = self.root / 'missing-parent/report.json'
        with self.assertRaises(AuditError) as missing:
            cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(missing.exception.code, 'output_write')
        self.assertFalse(destination.parent.exists())
        destination = self.root / 'encoding.json'
        with self.assertRaises(AuditError) as invalid:
            cli._publish_new(destination, '\ud800')
        self.assertEqual(invalid.exception.code, 'output_write')
        self.assertFalse(destination.exists())
        self.assert_no_temporary_reports()

    def test_output_nul_path_failure_is_sanitized_and_cleans_temporary(self):
        destination = self.root / 'PRIVATE_OUTPUT\x00.json'
        with self.assertRaises(AuditError) as caught:
            cli._publish_new(destination, 'NEW_REPORT')
        self.assertEqual(caught.exception.code, 'output_write')
        self.assertNotIn('PRIVATE_OUTPUT', str(caught.exception))
        self.assert_no_temporary_reports()

    def test_publisher_syncs_complete_bytes_before_exclusive_link(self):
        destination = self.root / 'ordered.json'; events = []
        original_fsync, original_link = os.fsync, os.link

        def sync(descriptor):
            events.append('fsync'); original_fsync(descriptor)

        def link(source, target):
            events.append('link')
            self.assertEqual(Path(source).parent, destination.parent)
            self.assertEqual(Path(source).read_bytes(), b'NEW_REPORT\n')
            original_link(source, target)

        with patch.object(cli.os, 'fsync', side_effect=sync), patch.object(cli.os, 'link', side_effect=link):
            cli._publish_new(destination, 'NEW_REPORT\n')
        self.assertEqual(events, ['fsync', 'link'])
        self.assertEqual(destination.read_bytes(), b'NEW_REPORT\n')
        self.assert_no_temporary_reports()

    def test_cli_closed_stdout_pipe_returns_three_without_shutdown_traceback(self):
        self.create()
        reader, writer = os.pipe(); os.close(reader)
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'epub_navigation_audit', str(self.path)],
                cwd=self.root, env=self.environment(), stdout=writer, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', timeout=20,
            )
        finally:
            os.close(writer)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn('output_write', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('Exception ignored', result.stderr)
        self.assertNotIn(str(self.path), result.stderr)

    def test_cli_stdout_write_failure_is_sanitized(self):
        self.create()

        class BrokenOutput(io.StringIO):
            def write(self, text):
                raise OSError('PRIVATE_STDOUT_BACKEND')

        diagnostic = io.StringIO()
        with patch.object(cli.sys, 'stdout', BrokenOutput()), patch.object(cli.sys, 'stderr', diagnostic):
            result = cli.main([str(self.path)])
        self.assertEqual(result, 3)
        self.assertIn('output_write', diagnostic.getvalue())
        self.assertNotIn('PRIVATE_STDOUT_BACKEND', diagnostic.getvalue())

    def test_synthetic_generator_is_deterministic_and_refuses_existing_files(self):
        first = self.create('valido', 'first.epub')
        second = self.create('valido', 'second.epub')
        self.assertEqual(first.read_bytes(), second.read_bytes())
        original = first.read_bytes()
        with self.assertRaises(FileExistsError):
            write_sample(first)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.epub-sample-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
