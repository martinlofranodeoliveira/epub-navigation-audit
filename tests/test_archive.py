"""Synthetic ZIP evidence; no real books, extraction, network or executable input."""
import io
import os
from pathlib import Path
import stat
import struct
import tempfile
import types
import unittest
from unittest.mock import patch
import warnings
import zipfile

from epub_navigation_audit import archive as backend
from epub_navigation_audit.model import AuditError, AuditLimits, Issues, StopAudit


class _NonSeekable(io.BytesIO):
    def seekable(self):
        return False

    def seek(self, *args):
        raise io.UnsupportedOperation


def zip_bytes(entries=(('chapter.xhtml', b'<html id="a"/>'),), *, compression=zipfile.ZIP_DEFLATED,
              descriptor=False, comment=b''):
    stream = _NonSeekable() if descriptor else io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(stream, 'w', compression=compression) as archive:
            for name, content in entries:
                archive.writestr(name, content)
            archive.comment = comment
    return stream.getvalue()


def positions(raw):
    end = raw.rfind(b'PK\x05\x06')
    central = struct.unpack_from('<I', raw, end + 16)[0]
    records = []
    cursor = central
    while raw[cursor:cursor + 4] == b'PK\x01\x02':
        records.append(cursor)
        a, b, c = struct.unpack_from('<HHH', raw, cursor + 28)
        cursor += 46 + a + b + c
    return end, central, records


def alter_header(raw, *, local=None, central=None, value=0, fmt='<I'):
    result = bytearray(raw)
    _, _, records = positions(raw)
    if local is not None:
        struct.pack_into(fmt, result, local, value)
    if central is not None:
        struct.pack_into(fmt, result, records[0] + central, value)
    return bytes(result)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / 'synthetic.epub'

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, raw=None):
        self.path.write_bytes(raw if raw is not None else zip_bytes())

    def opened(self, limits=None):
        issues = Issues((limits or AuditLimits()).max_issues)
        return backend.open_snapshot(self.path, limits=limits or AuditLimits(), issues=issues), issues

    def stops(self, raw, code, *, limits=None, error=None):
        self.write(raw)
        context, issues = self.opened(limits)
        with self.assertRaises(StopAudit):
            with context:
                self.fail('Unexpected successful archive opening')
        self.assertIn(code, [item.code for item in issues.items])
        self.assertTrue(issues.partial)
        if error is not None:
            self.assertEqual(issues.error, error)
        return issues

    def test_stored_and_deflated_entries_match_independent_zipfile_reads(self):
        entries = [('mimetype', b'application/epub+zip'), ('chapter.xhtml', b'<html id="a"/>'),
                   ('text/', b''), ('text/nota\u00e7\u00e3o.xhtml', '<p>Fictício</p>'.encode())]
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(compression=compression):
                raw = zip_bytes(entries, compression=compression)
                self.write(raw)
                context, issues = self.opened()
                with context as archive, zipfile.ZipFile(io.BytesIO(raw)) as oracle:
                    self.assertEqual(archive.archive_bytes, len(raw))
                    import hashlib
                    self.assertEqual(archive.sha256, hashlib.sha256(raw).hexdigest())
                    self.assertEqual(set(archive.entries), set(oracle.namelist()))
                    self.assertEqual(archive.read_bytes, 0)
                    self.assertEqual(archive.selected_member_reads, 0)
                    for name, content in entries:
                        entry = archive.entries[name]
                        info = oracle.getinfo(name)
                        self.assertEqual(entry.size, info.file_size)
                        self.assertEqual(entry.compressed_size, info.compress_size)
                        self.assertEqual(entry.crc32, info.CRC)
                        self.assertEqual(entry.compression, info.compress_type)
                        self.assertEqual(entry.header_offset, info.header_offset)
                        self.assertEqual(entry.flags, info.flag_bits)
                        self.assertEqual(entry.local_extra_size, 0)
                        self.assertEqual(entry.directory, name.endswith('/'))
                        self.assertEqual(archive.read(name), None if name.endswith('/') else oracle.read(name))
                    self.assertEqual(archive.selected_member_reads, 3)
                    self.assertEqual(archive.read_bytes, sum(len(content) for name, content in entries))
                self.assertEqual(issues.items, [])
                self.assertEqual(self.path.read_bytes(), raw)

    def test_cache_does_not_repeat_reads_and_returns_immutable_bytes(self):
        self.write()
        context, issues = self.opened()
        with context as archive:
            first = archive.read('chapter.xhtml')
            with patch.object(backend, '_member_blocks', side_effect=AssertionError('Repeated read')):
                self.assertIs(archive.read('chapter.xhtml'), first)
                self.assertIsNone(archive.read('absent.xhtml'))
            self.assertEqual(archive.selected_member_reads, 1)
            self.assertEqual(archive.read_bytes, len(first))
            self.assertIsNone(archive.read('chapter.xhtml', max_bytes=1))
        self.assertTrue(issues.partial)
        self.assertFalse(issues.error)

    def test_snapshot_is_independent_of_later_source_replacement(self):
        original = zip_bytes((('chapter.xhtml', b'ORIGINAL_SYNTHETIC'),))
        self.write(original)
        context, issues = self.opened()
        with context as archive:
            self.path.write_bytes(zip_bytes((('chapter.xhtml', b'CHANGED_SYNTHETIC'),)))
            self.assertEqual(archive.read('chapter.xhtml'), b'ORIGINAL_SYNTHETIC')
        self.assertEqual(issues.items, [])

    def test_only_selected_members_have_data_integrity_checked(self):
        raw = bytearray(zip_bytes((('chapter.xhtml', b'<html/>'), ('image.bin', b'VISIBLE_CANARY')),
                                  compression=zipfile.ZIP_STORED))
        raw[raw.index(b'VISIBLE_CANARY')] ^= 1
        self.write(raw)
        context, issues = self.opened()
        with context as archive:
            with (patch.object(zipfile.ZipFile, 'extract', side_effect=AssertionError('Extraction')),
                  patch.object(zipfile.ZipFile, 'extractall', side_effect=AssertionError('Extraction'))):
                self.assertEqual(archive.read('chapter.xhtml'), b'<html/>')
            self.assertEqual(issues.items, [])
            self.assertEqual(archive.read_bytes, 7)
            self.assertIsNone(archive.read('image.bin'))
        self.assertTrue(issues.error)
        self.assertIn('zip_crc', [item.code for item in issues.items])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['synthetic.epub'])

    def test_empty_zip_is_structurally_available_for_semantic_checks(self):
        self.write(zip_bytes(()))
        context, issues = self.opened()
        with context as archive:
            self.assertEqual(archive.entries, {})
            self.assertIsNone(archive.read('mimetype'))
        self.assertEqual(issues.items, [])

    def test_operational_errors_are_sanitized_and_missing_is_not_created(self):
        missing = self.root / 'PRIVATE_DO_NOT_ECHO.epub'
        with self.assertRaises(AuditError) as caught:
            with backend.open_snapshot(missing, issues=Issues(10)):
                pass
        self.assertEqual(caught.exception.code, 'file_not_found')
        self.assertNotIn('PRIVATE_DO_NOT_ECHO', str(caught.exception))
        self.assertFalse(missing.exists())
        with self.assertRaises(AuditError) as caught:
            with backend.open_snapshot(self.root, issues=Issues(10)):
                pass
        self.assertEqual(caught.exception.code, 'file_not_regular')
        with patch.object(backend.os, 'open', side_effect=PermissionError('PRIVATE_FAILURE')):
            with self.assertRaises(AuditError) as caught:
                with backend.open_snapshot(missing, issues=Issues(10)):
                    pass
        self.assertEqual(caught.exception.code, 'file_unreadable')
        self.assertNotIn('PRIVATE_FAILURE', str(caught.exception))

    def test_arguments_and_read_limits_are_checked(self):
        for path in (True, None, '\x00'):
            with self.subTest(path=repr(path)), self.assertRaises(ValueError):
                with backend.open_snapshot(path, issues=Issues(10)):
                    pass
        with self.assertRaises(ValueError):
            with backend.open_snapshot(self.path, limits={}, issues=Issues(10)):
                pass
        self.write()
        context, _ = self.opened()
        with context as archive:
            for limit in (False, 0, -1, '4'):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    archive.read('chapter.xhtml', max_bytes=limit)
            with self.assertRaises(ValueError):
                archive.read(None)
        with self.assertRaises(ValueError):
            archive.read('chapter.xhtml')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO unavailable on this platform')
    def test_fifo_is_rejected_without_blocking(self):
        fifo = self.root / 'input.pipe'
        os.mkfifo(fifo)
        with self.assertRaises(AuditError) as caught:
            with backend.open_snapshot(fifo, issues=Issues(10)):
                pass
        self.assertEqual(caught.exception.code, 'file_not_regular')

    def test_regular_symlink_may_be_followed(self):
        self.write()
        alias = self.root / 'alias.epub'
        try:
            alias.symlink_to(self.path)
        except OSError:
            self.skipTest('Symlinks unavailable for this test account')
        with backend.open_snapshot(alias, issues=Issues(10)) as archive:
            self.assertEqual(archive.read('chapter.xhtml'), b'<html id="a"/>')

    def test_source_change_during_copy_stops_before_zip_parser(self):
        self.write()
        original = backend.os.fstat
        calls = 0

        def changed(fd):
            nonlocal calls
            value = original(fd)
            calls += 1
            result = {name: getattr(value, name) for name in ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            if calls > 1:
                result['st_mtime_ns'] += 1
            return types.SimpleNamespace(**result)

        with patch.object(backend.os, 'fstat', side_effect=changed), patch.object(backend.zipfile, 'ZipFile', side_effect=AssertionError('Parser must not start')):
            self.stops(self.path.read_bytes(), 'source_changed', error=False)

    def test_archive_size_bound_precedes_zipfile_allocation(self):
        raw = zip_bytes()
        with patch.object(backend.zipfile, 'ZipFile', side_effect=AssertionError('Parser must not start')):
            self.stops(raw, 'limit_archive_bytes', limits=AuditLimits(max_archive_bytes=20), error=False)

    def test_owned_handles_close_after_normal_and_exceptional_contexts(self):
        self.write()
        opened = []
        temporaries = []
        real_fdopen = backend.os.fdopen
        real_temporary = backend.tempfile.TemporaryFile

        def source(*args, **kwargs):
            item = real_fdopen(*args, **kwargs)
            opened.append(item)
            return item

        def snapshot(*args, **kwargs):
            item = real_temporary(*args, **kwargs)
            temporaries.append(item)
            return item

        with patch.object(backend.os, 'fdopen', side_effect=source), patch.object(backend.tempfile, 'TemporaryFile', side_effect=snapshot):
            with self.opened()[0] as archive:
                self.assertEqual(archive.read('chapter.xhtml'), b'<html id="a"/>')
            self.assertTrue(archive._closed)
            self.assertIsNone(archive._zip.fp)
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                with self.opened()[0]:
                    raise RuntimeError('synthetic')
            self.write(b'bad zip')
            with self.assertRaises(StopAudit):
                with self.opened()[0]:
                    pass
        self.assertTrue(all(item.closed for item in opened + temporaries))

    def test_snapshot_storage_failure_is_sanitized_and_closes_source(self):
        self.write()
        captured = []
        real_fdopen = backend.os.fdopen

        def capture(*args, **kwargs):
            result = real_fdopen(*args, **kwargs)
            captured.append(result)
            return result

        with patch.object(backend.os, 'fdopen', side_effect=capture), patch.object(backend.tempfile, 'TemporaryFile', side_effect=OSError('PRIVATE_QUOTA')):
            with self.assertRaises(AuditError) as caught:
                with self.opened()[0]:
                    pass
        self.assertEqual(caught.exception.code, 'input_read')
        self.assertNotIn('PRIVATE_QUOTA', str(caught.exception))
        self.assertTrue(captured[0].closed)

    def test_corrupt_zip_is_a_recorded_finding(self):
        self.stops(b'not a zip', 'zip_invalid', error=True)
        raw = bytearray(zip_bytes())
        _, central, _ = positions(raw)
        raw[central] = 0
        self.stops(raw, 'zip_structure', error=True)

    def test_actual_central_record_count_is_bounded_before_zipinfo_objects(self):
        raw = bytearray(zip_bytes(tuple((f'f{i}', b'x') for i in range(5))))
        end, _, _ = positions(raw)
        struct.pack_into('<HH', raw, end + 8, 1, 1)
        with patch.object(backend.zipfile, 'ZipFile', side_effect=AssertionError('ZipInfo allocation')):
            self.stops(raw, 'limit_members', limits=AuditLimits(max_members=2), error=False)

    def test_reported_count_contradiction_is_error(self):
        raw = bytearray(zip_bytes())
        end, _, _ = positions(raw)
        struct.pack_into('<HH', raw, end + 8, 0, 0)
        self.stops(raw, 'zip_structure', error=True)

    def test_eocd_ambiguity_trailers_and_prefixes_do_not_reach_zipfile(self):
        cases = [(zip_bytes(comment=b'comment PK\x05\x06 hidden'), 'zip_eocd_ambiguous'),
                 (zip_bytes() + b'EXTRA', 'zip_trailer_unsupported'),
                 (b'PREFIX' + zip_bytes(), 'zip_layout_unsupported')]
        with patch.object(backend.zipfile, 'ZipFile', side_effect=AssertionError('ZipInfo allocation')):
            for raw, code in cases:
                with self.subTest(code=code):
                    self.stops(raw, code, error=False)

    def test_zip64_and_directory_extensions_are_incomplete_not_invalid(self):
        raw = bytearray(zip_bytes())
        end, central, _ = positions(raw)
        struct.pack_into('<HH', raw, end + 8, 65535, 65535)
        self.stops(raw, 'zip64_unsupported', error=False)
        original = zip_bytes()
        end, central, _ = positions(original)
        extended = bytearray(original[:end] + b'PK\x05\x05\x00\x00' + original[end:])
        struct.pack_into('<I', extended, end + 6 + 12, end - central + 6)
        self.stops(extended, 'zip_directory_extension_unsupported', error=False)

    def test_invalid_utf8_and_name_byte_budget_precede_zipfile(self):
        raw = bytearray(zip_bytes((('name', b'x'),)))
        _, central, _ = positions(raw)
        struct.pack_into('<H', raw, central + 8, 0x800)
        raw[central + 46] = 255
        with patch.object(backend.zipfile, 'ZipFile', side_effect=AssertionError('ZipInfo allocation')):
            self.stops(raw, 'zip_path', error=True)
        self.stops(zip_bytes((('nota\u00e7\u00e3o.xhtml', b'x'),)), 'limit_name_bytes', limits=AuditLimits(max_name_bytes=5), error=False)

    def test_duplicate_ambiguous_and_directory_data_are_errors(self):
        cases = [((('a', b'x'), ('a', b'y')), 'zip_duplicate'),
                 ((('a', b'x'), ('a/', b'')), 'zip_ambiguous'),
                 ((('a', b'x'), ('a/b', b'y')), 'zip_ambiguous'),
                 ((('folder/', b'not empty'),), 'zip_directory_data')]
        for entries, code in cases:
            with self.subTest(code=code):
                self.stops(zip_bytes(entries), code, error=True)

    def test_canonical_unicode_and_full_casefold_path_collisions_are_errors(self):
        pairs = [('EPUB/café.xhtml', 'EPUB/cafe\u0301.xhtml'),
                 ('EPUB/A.xhtml', 'EPUB/a.xhtml'),
                 ('EPUB/straße.xhtml', 'EPUB/strasse.xhtml'),
                 ('EPUB/Text/', 'EPUB/text/')]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                self.stops(zip_bytes(((first, b''), (second, b''))),
                           'zip_name_collision', error=True)

    def test_single_decomposed_path_keeps_physical_spelling_and_content(self):
        physical = 'EPUB/cafe\u0301.xhtml'
        self.write(zip_bytes(((physical, b'<html/>'),)))
        context, issues = self.opened()
        with context as archive:
            self.assertEqual(list(archive.entries), [physical])
            self.assertEqual(archive.read(physical), b'<html/>')
            self.assertNotIn('EPUB/café.xhtml', archive.entries)
        self.assertEqual(issues.items, [])

    def test_noncanonical_member_paths_are_outside_profile(self):
        for name in ('../a', '/a', 'a\\b', 'a:b', 'a//b', 'a/./b', 'a/../b'):
            with self.subTest(name=name):
                self.stops(zip_bytes(((name, b'x'),)), 'zip_path_unsupported', error=False)
        raw = bytearray(zip_bytes((('abc', b'x'),)))
        _, central, _ = positions(raw)
        raw[31] = raw[central + 47] = 0
        self.stops(raw, 'zip_path_unsupported', error=False)

    def test_duplicate_local_offsets_and_corrupt_local_headers_are_errors(self):
        raw = bytearray(zip_bytes((('a', b'x'), ('b', b'y'))))
        _, _, records = positions(raw)
        struct.pack_into('<I', raw, records[1] + 42, 0)
        self.stops(raw, 'zip_structure', error=True)
        raw = bytearray(zip_bytes())
        raw[0] = 0
        self.stops(raw, 'zip_structure', error=True)

    def test_local_extra_metadata_and_truncation_are_visible(self):
        info = zipfile.ZipInfo('mimetype')
        info.extra = b'\xfe\xca\x00\x00'
        self.write(zip_bytes(((info, b'application/epub+zip'),)))
        context, issues = self.opened()
        with context as archive:
            self.assertEqual(archive.entries['mimetype'].local_extra_size, 4)
            self.assertEqual(archive.read('mimetype'), b'application/epub+zip')
        self.assertFalse(issues.partial)
        raw = bytearray(self.path.read_bytes())
        name_size = struct.unpack_from('<H', raw, 26)[0]
        struct.pack_into('<H', raw, 30 + name_size + 2, 20)
        self.stops(raw, 'zip_structure', error=True)

    def test_local_zip64_is_not_mistaken_for_invalid_epub(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            with archive.open('chapter.xhtml', 'w', force_zip64=True) as member:
                member.write(b'<html/>')
        self.write(stream.getvalue())
        context, issues = self.opened()
        with context as archive:
            self.assertIsNone(archive.read('chapter.xhtml'))
        self.assertTrue(issues.partial)
        self.assertFalse(issues.error)
        self.assertIn('zip64_unsupported', [item.code for item in issues.items])

    def test_unsupported_compression_flags_and_symlinks_are_not_read(self):
        binary = zip_bytes((('chapter.xhtml', b'x'),), compression=zipfile.ZIP_BZIP2)
        flagged = alter_header(zip_bytes(), local=6, central=8, value=0x10, fmt='<H')
        symbolic = zipfile.ZipInfo('link')
        symbolic.create_system = 3
        symbolic.external_attr = (stat.S_IFLNK | 0o777) << 16
        symlink = zip_bytes(((symbolic, b'../../host-file'),))
        for raw, name, code in ((binary, 'chapter.xhtml', 'zip_compression_unsupported'),
                                (flagged, 'chapter.xhtml', 'zip_feature_unsupported'),
                                (symlink, 'link', 'zip_type_unsupported')):
            with self.subTest(code=code):
                self.write(raw)
                context, issues = self.opened()
                with context as archive, patch.object(backend, '_member_blocks', side_effect=AssertionError('Unsupported read')):
                    self.assertIsNone(archive.read(name))
                    self.assertEqual(archive.read_bytes, 0)
                self.assertFalse(issues.error)
                self.assertTrue(issues.partial)
                self.assertIn(code, [item.code for item in issues.items])

    def test_zip_encryption_flag_is_a_proven_ocf_error_without_decryption(self):
        self.write(alter_header(zip_bytes(), local=6, central=8, value=1, fmt='<H'))
        context, issues = self.opened()
        with context as archive, patch.object(backend, '_member_blocks', side_effect=AssertionError('Encrypted read')):
            self.assertIsNone(archive.read('chapter.xhtml'))
        self.assertTrue(issues.error)
        self.assertTrue(issues.partial)

    def test_legacy_non_ascii_filename_is_outside_profile(self):
        raw = bytearray(zip_bytes((('é', b'x'),)))
        _, central, _ = positions(raw)
        raw[30:32] = raw[central + 46:central + 48] = b'\x82x'
        struct.pack_into('<H', raw, 6, 0)
        struct.pack_into('<H', raw, central + 8, 0)
        self.write(raw)
        context, issues = self.opened()
        with context as archive:
            self.assertIn('éx', archive.entries)
            self.assertIsNone(archive.read('éx'))
        self.assertTrue(issues.partial)
        self.assertFalse(issues.error)

    def test_selected_local_method_flags_crc_and_size_must_match_central(self):
        for offset, value, fmt in ((8, 0, '<H'), (6, 2, '<H'), (14, 0, '<I'), (22, 1, '<I')):
            with self.subTest(offset=offset):
                self.write(alter_header(zip_bytes(), local=offset, value=value, fmt=fmt))
                context, issues = self.opened()
                with context as archive:
                    self.assertIsNone(archive.read('chapter.xhtml'))
                self.assertTrue(issues.error)
                self.assertIn('zip_member_invalid', [item.code for item in issues.items])

    def test_selected_crc_and_effective_size_are_independently_checked(self):
        for raw, code in ((alter_header(zip_bytes(), local=14, central=16, value=0), 'zip_crc'),
                          (alter_header(zip_bytes(), local=22, central=24, value=1), 'zip_size')):
            with self.subTest(code=code):
                self.write(raw)
                context, issues = self.opened()
                with context as archive:
                    self.assertIsNone(archive.read('chapter.xhtml'))
                    self.assertEqual(archive.read_bytes, len(b'<html id="a"/>'))
                self.assertTrue(issues.error)
                self.assertIn(code, [item.code for item in issues.items])

    def test_declared_member_limit_is_checked_before_decompression_and_cached(self):
        self.write()
        context, issues = self.opened(AuditLimits(max_xml_bytes=3))
        with context as archive, patch.object(backend, '_member_blocks', side_effect=AssertionError('Read after refusal')):
            self.assertIsNone(archive.read('chapter.xhtml'))
            self.assertIsNone(archive.read('chapter.xhtml', max_bytes=999))
            self.assertEqual(archive.read_bytes, 0)
            self.assertEqual(archive.selected_member_reads, 1)
        self.assertTrue(issues.partial)
        self.assertFalse(issues.error)

    def test_effective_output_above_declaration_cannot_hide_behind_member_budget(self):
        raw = alter_header(zip_bytes((('chapter.xhtml', b'x' * 1000),)), local=22, central=24, value=1)
        self.write(raw)
        context, issues = self.opened(AuditLimits(max_xml_bytes=10))
        with context as archive:
            self.assertIsNone(archive.read('chapter.xhtml'))
            self.assertEqual(archive.read_bytes, 11)
            self.assertIsNone(archive.read('chapter.xhtml'))
            self.assertEqual(archive.read_bytes, 11)
        self.assertTrue(issues.error)
        self.assertTrue(issues.partial)
        self.assertIn('zip_size', [item.code for item in issues.items])
        self.assertIn('limit_xml_bytes', [item.code for item in issues.items])

    def test_global_declared_budget_stops_whole_queue_without_contour(self):
        self.write(zip_bytes((('a', b'123'), ('b', b'456'), ('c', b'7'))))
        context, issues = self.opened(AuditLimits(max_total_read_bytes=4))
        with context as archive:
            self.assertEqual(archive.read('a'), b'123')
            with self.assertRaises(StopAudit):
                archive.read('b')
            with self.assertRaises(StopAudit):
                archive.read('c')
            self.assertEqual(archive.read_bytes, 3)
        self.assertTrue(issues.partial)

    def test_effective_global_budget_counts_one_witness_byte_and_stops_queue(self):
        raw = alter_header(zip_bytes((('a', b'x' * 1000), ('b', b'7'))), local=22, central=24, value=1)
        self.write(raw)
        context, issues = self.opened(AuditLimits(max_total_read_bytes=10))
        with context as archive:
            with self.assertRaises(StopAudit):
                archive.read('a')
            self.assertEqual(archive.read_bytes, 11)
            with self.assertRaises(StopAudit):
                archive.read('b')
            self.assertEqual(archive.read_bytes, 11)
        self.assertTrue(issues.error)
        self.assertTrue(issues.partial)

    def test_signed_and_unsigned_data_descriptors_are_checked(self):
        original = zip_bytes(descriptor=True)
        end, central, _ = positions(original)
        self.assertEqual(original[central - 16:central - 12], b'PK\x07\x08')
        unsigned = bytearray(original[:central - 16] + original[central - 12:])
        struct.pack_into('<I', unsigned, end - 4 + 16, central - 4)
        for raw in (original, unsigned):
            with self.subTest(unsigned=raw is unsigned):
                self.write(raw)
                context, issues = self.opened()
                with context as archive:
                    self.assertEqual(archive.read('chapter.xhtml'), b'<html id="a"/>')
                self.assertEqual(issues.items, [])
        corrupt = bytearray(original)
        corrupt[central - 12] ^= 1
        self.write(corrupt)
        context, issues = self.opened()
        with context as archive:
            self.assertIsNone(archive.read('chapter.xhtml'))
        self.assertTrue(issues.error)

    def test_truncated_or_trailing_deflate_stream_is_not_accepted(self):
        original = zip_bytes((('chapter.xhtml', b'abcdef' * 200),))
        end, central, _ = positions(original)
        size = struct.unpack_from('<I', original, 18)[0]
        for delta in (-1, 1):
            with self.subTest(delta=delta):
                if delta < 0:
                    changed = bytearray(original[:central - 1] + original[central:])
                else:
                    changed = bytearray(original[:central] + b'\x00' + original[central:])
                struct.pack_into('<I', changed, 18, size + delta)
                struct.pack_into('<I', changed, central + delta + 20, size + delta)
                struct.pack_into('<I', changed, end + delta + 16, central + delta)
                self.write(changed)
                context, issues = self.opened()
                with context as archive:
                    self.assertIsNone(archive.read('chapter.xhtml'))
                self.assertTrue(issues.error)
                self.assertIn('zip_member_invalid', [item.code for item in issues.items])

    def test_unexplained_gap_between_members_is_incomplete(self):
        original = zip_bytes()
        end, central, _ = positions(original)
        changed = bytearray(original[:central] + b'GAP!' + original[central:])
        struct.pack_into('<I', changed, end + 4 + 16, central + 4)
        self.write(changed)
        context, issues = self.opened()
        with context as archive:
            self.assertIsNone(archive.read('chapter.xhtml'))
        self.assertTrue(issues.partial)
        self.assertFalse(issues.error)
        self.assertIn('zip_member_extension_unsupported', [item.code for item in issues.items])


if __name__ == '__main__':
    unittest.main()
