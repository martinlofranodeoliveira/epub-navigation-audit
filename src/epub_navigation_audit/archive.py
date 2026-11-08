"""Bounded, non-extracting access to selected EPUB ZIP members.

The central-directory preflight and independent member decompressor were
adapted from LOFRANO TECNOLOGIA's MIT wheel-record-audit (2026). Only ZIP
structure is reused; this module implements no wheel-specific checks.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
import stat
import struct
import tempfile
import unicodedata
import zipfile
import zlib

from .model import AuditError, AuditLimits, StopAudit

_BLOCK = 64 * 1024


class _UnsupportedZip(Exception):
    pass


@dataclass(frozen=True)
class Entry:
    name: str
    size: int
    compressed_size: int
    crc32: int
    compression: int
    header_offset: int
    flags: int
    directory: bool
    local_extra_size: int


def _exact(stream, size):
    """Read a structural field without issuing a read larger than 64 KiB."""
    chunks = []
    while size:
        block = stream.read(min(size, _BLOCK))
        if not block:
            raise EOFError
        chunks.append(block)
        size -= len(block)
    return b"".join(chunks)

def _preflight(stream, size, limits, issues):
    """Count the actual central records before ZipFile allocates ZipInfo objects."""
    if size < 22:
        issues.stop("error", "zip_invalid", "O arquivo não contém um ZIP completo.")
    tail_size = min(size, 22 + 65535)
    stream.seek(size - tail_size)
    tail = _exact(stream, tail_size)
    candidates = []
    pos = tail.find(b"PK\x05\x06")
    while pos >= 0:
        if pos + 22 <= len(tail):
            comment = struct.unpack_from("<H", tail, pos + 20)[0]
            candidates.append((pos, pos + 22 + comment))
        pos = tail.find(b"PK\x05\x06", pos + 1)
    exact = [p for p, end in candidates if end == len(tail)]
    if not exact:
        if candidates:
            _, end = candidates[-1]
            if end < len(tail):
                issues.stop("incomplete", "zip_trailer_unsupported", "Dados após o ZIP estão fora do perfil.")
        issues.stop("error", "zip_structure", "O encerramento do ZIP está truncado ou é contraditório.")
    end_pos = exact[-1]
    if tail.rfind(b"PK\x05\x06") != end_pos:
        issues.stop("incomplete", "zip_eocd_ambiguous", "Assinaturas de encerramento ZIP ambíguas estão fora do perfil.")
    eocd = size - tail_size + end_pos
    _, disk, central_disk, disk_count, reported, central_size, offset, _ = struct.unpack_from(
        "<4s4H2IH", tail, end_pos
    )
    if eocd >= 20:
        stream.seek(eocd - 20)
        if _exact(stream, 4) == b"PK\x06\x07":
            issues.stop("incomplete", "zip64_unsupported", "O diretório ZIP64 está fora do perfil.")
    if 65535 in (disk_count, reported) or 0xffffffff in (central_size, offset):
        issues.stop("incomplete", "zip64_unsupported", "O diretório ZIP64 está fora do perfil.")
    if disk or central_disk or disk_count != reported:
        issues.stop("incomplete", "zip_multidisk_unsupported", "Volumes ZIP múltiplos estão fora do perfil.")
    if offset + central_size > eocd:
        issues.stop("error", "zip_structure", "Os limites do diretório central são contraditórios.")
    if offset + central_size < eocd:
        issues.stop("incomplete", "zip_layout_unsupported", "Prefixos ou extensões do diretório ZIP estão fora do perfil.")
    stream.seek(offset)
    central_end = offset + central_size
    count = 0
    first_local = None
    while stream.tell() < central_end:
        remaining = central_end - stream.tell()
        if remaining >= 4:
            signature = _exact(stream, 4)
            stream.seek(-4, os.SEEK_CUR)
            if signature in {b"PK\x05\x05", b"PK\x06\x06"}:
                issues.stop("incomplete", "zip_directory_extension_unsupported", "Uma extensão do diretório ZIP está fora do perfil.")
        if central_end - stream.tell() < 46:
            issues.stop("error", "zip_structure", "Uma entrada do diretório central está truncada.")
        header = _exact(stream, 46)
        if header[:4] != b"PK\x01\x02":
            if header[:4] in {b"PK\x05\x05", b"PK\x06\x06"}:
                issues.stop("incomplete", "zip_directory_extension_unsupported", "Uma extensão do diretório ZIP está fora do perfil.")
            issues.stop("error", "zip_structure", "Uma entrada do diretório central é inválida.")
        count += 1
        if count > limits.max_members:
            issues.stop("incomplete", "limit_members", "O inventário excede o limite de entradas ZIP.")
        flags = struct.unpack_from("<H", header, 8)[0]
        compressed, uncompressed = struct.unpack_from("<II", header, 20)
        name_size, extra_size, comment_size, start_disk = struct.unpack_from("<4H", header, 28)
        local_offset = struct.unpack_from("<I", header, 42)[0]
        if 0xffffffff in (compressed, uncompressed, local_offset) or start_disk == 65535:
            issues.stop("incomplete", "zip64_unsupported", "O diretório ZIP64 está fora do perfil.")
        if start_disk:
            issues.stop("incomplete", "zip_multidisk_unsupported", "Volumes ZIP múltiplos estão fora do perfil.")
        if stream.tell() + name_size + extra_size + comment_size > central_end:
            issues.stop("error", "zip_structure", "Os comprimentos de uma entrada ZIP são contraditórios.")
        if name_size > limits.max_name_bytes:
            issues.stop("incomplete", "limit_name_bytes", "Um nome de membro excede o limite de bytes.")
        raw_name = _exact(stream, name_size)
        if flags & 0x800:
            try:
                raw_name.decode("utf-8", errors="strict")
            except UnicodeError:
                issues.stop("error", "zip_path", "Um caminho ZIP não é Unicode válido.")
        extra = _exact(stream, extra_size)
        cursor = 0
        while cursor < len(extra):
            if cursor + 4 > len(extra):
                issues.stop("error", "zip_structure", "Um campo extra do diretório ZIP está truncado.")
            kind, length = struct.unpack_from("<HH", extra, cursor)
            cursor += 4
            if cursor + length > len(extra):
                issues.stop("error", "zip_structure", "Um campo extra do diretório ZIP está truncado.")
            if kind == 1:
                issues.stop("incomplete", "zip64_unsupported", "O diretório ZIP64 está fora do perfil.")
            cursor += length
        stream.seek(comment_size, os.SEEK_CUR)
        if local_offset >= offset:
            issues.stop("error", "zip_structure", "Um cabeçalho local está fora da área de membros.")
        first_local = local_offset if first_local is None else min(first_local, local_offset)
    if count != reported:
        issues.stop("error", "zip_structure", "O contador ZIP diverge das entradas do diretório central.")
    if (first_local is not None and first_local != 0) or (first_local is None and offset != 0):
        issues.stop("incomplete", "zip_prefix_unsupported", "Um prefixo antes do ZIP está fora do perfil.")
    return offset

def _member_blocks(stream, archive, info, boundary, output_limit):
    # zipfile verifies local names, supported flags and overlapping member bounds.
    # Decompress independently: ZipExtFile truncates to a claimed file_size, which
    # must not hide extra output from the effective-byte budgets or CRC check.
    with archive.open(info, "r"):
        pass
    stream.seek(info.header_offset)
    header = _exact(stream, 30)
    if header[:4] != b"PK\x03\x04":
        raise zipfile.BadZipFile("local header")
    flags, method = struct.unpack_from("<HH", header, 6)
    if method != info.compress_type or flags != info.flag_bits:
        raise zipfile.BadZipFile("local fields")
    local_crc, local_compressed, local_size = struct.unpack_from("<III", header, 14)
    name_size, extra_size = struct.unpack_from("<HH", header, 26)
    _exact(stream, name_size)
    extra = _exact(stream, extra_size)
    zip64 = None
    cursor = 0
    while cursor < len(extra):
        if cursor + 4 > len(extra):
            raise zipfile.BadZipFile("truncated local extra")
        kind, length = struct.unpack_from("<HH", extra, cursor)
        cursor += 4
        if cursor + length > len(extra):
            raise zipfile.BadZipFile("truncated local extra")
        if kind == 1:
            if zip64 is not None:
                raise zipfile.BadZipFile("duplicate local zip64 extra")
            zip64 = extra[cursor:cursor + length]
        cursor += length
    cursor = 0
    if local_size == 0xffffffff:
        if zip64 is None or len(zip64) < cursor + 8:
            raise zipfile.BadZipFile("missing local zip64 size")
        local_size = struct.unpack_from("<Q", zip64, cursor)[0]
        cursor += 8
    if local_compressed == 0xffffffff:
        if zip64 is None or len(zip64) < cursor + 8:
            raise zipfile.BadZipFile("missing local zip64 compressed size")
        local_compressed = struct.unpack_from("<Q", zip64, cursor)[0]
    if flags & 8:
        if (local_crc not in {0, info.CRC} or local_compressed not in {0, info.compress_size}
                or local_size not in {0, info.file_size}):
            raise zipfile.BadZipFile("contradictory local placeholders")
    elif (local_crc, local_compressed, local_size) != (info.CRC, info.compress_size, info.file_size):
        raise zipfile.BadZipFile("contradictory local fields")
    data_start = stream.tell()
    remaining = info.compress_size
    decompressor = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
    produced = 0
    while remaining:
        block = _exact(stream, min(_BLOCK, remaining, max(1, output_limit - produced + 1)) if decompressor is None else min(_BLOCK, remaining))
        remaining -= len(block)
        if decompressor is None:
            produced += len(block)
            yield block
            continue
        pending = block
        while pending:
            data = decompressor.decompress(pending, min(_BLOCK, max(1, output_limit - produced + 1)))
            pending = decompressor.unconsumed_tail
            if data:
                produced += len(data)
                yield data
            if decompressor.eof:
                if decompressor.unused_data or remaining:
                    raise zipfile.BadZipFile("compressed trailing bytes")
                break
    if decompressor is not None:
        while True:
            data = decompressor.decompress(b"", min(_BLOCK, max(1, output_limit - produced + 1)))
            if not data:
                break
            produced += len(data)
            yield data
        if not decompressor.eof:
            raise zipfile.BadZipFile("truncated deflate stream")
    if flags & 8:
        stream.seek(data_start + info.compress_size)
        # The descriptor has no independent length field. Both classic forms
        # and local ZIP64 forms are bounded, and their values must agree with
        # the central record. A signature is optional, including when the CRC
        # itself happens to equal the descriptor signature.
        descriptor = stream.read(24)
        matches = False
        prefix_matches = False
        for start in (0, 4) if descriptor[:4] == b"PK\x07\x08" else (0,):
            for fmt in (("<IQQ",) if zip64 is not None else ("<III",)):
                length = struct.calcsize(fmt)
                if len(descriptor) >= start + length:
                    values = struct.unpack_from(fmt, descriptor, start)
                    if values == (info.CRC, info.compress_size, info.file_size):
                        prefix_matches = True
                        matches |= data_start + info.compress_size + start + length == boundary
        if not matches:
            if prefix_matches:
                raise _UnsupportedZip
            raise zipfile.BadZipFile("contradictory data descriptor")
    elif data_start + info.compress_size != boundary:
        raise _UnsupportedZip


def _valid_path(name, max_bytes):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        return False
    try:
        if len(name.encode('utf-8', errors='strict')) > max_bytes:
            return False
    except UnicodeError:
        return False
    if any(unicodedata.category(c) in {'Cc', 'Cs'} for c in name):
        return False
    path = name[:-1] if name.endswith('/') else name
    return bool(path) and all(part not in {'', '.', '..'} for part in path.split('/'))


def _stat_identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


class ArchiveSnapshot:
    """Read-only ZIP metadata plus cached, bounded selected-member reads.

    The context owns the underlying snapshot and closes it on every exit.
    No member is extracted and no caller-supplied member name becomes a path
    on the host filesystem. Counters describe attempted unique reads and the
    actual bytes produced, including a one-byte budget-exhaustion witness.
    """

    def __init__(self, stream, *, limits, issues, archive_bytes, sha256):
        self._stream = stream
        self._limits = limits
        self._issues = issues
        self._zip = None
        self._closed = False
        self._cache = {}
        self._infos = {}
        self._boundaries = {}
        self._unsupported = set()
        self._read_exhausted = False
        self.entries = {}
        self.archive_bytes = archive_bytes
        self.sha256 = sha256
        self.read_bytes = 0
        self.selected_member_reads = 0

    def _prepare(self):
        central = _preflight(self._stream, self.archive_bytes, self._limits, self._issues)
        self._stream.seek(0)
        self._zip = zipfile.ZipFile(self._stream, 'r')
        infos = self._zip.infolist()
        logical = {}
        canonical_names = {}
        offsets = set()
        for info in infos:
            name = info.orig_filename
            if not _valid_path(name, self._limits.max_name_bytes):
                self._issues.stop('incomplete', 'zip_path_unsupported',
                                  'Um caminho ZIP está fora do perfil de nomes relativos.')
            directory = name.endswith('/')
            if name in self._infos:
                self._issues.stop('error', 'zip_duplicate',
                                  'Há nomes de membros ZIP repetidos.', name)
            key = name[:-1] if directory else name
            if key in logical:
                self._issues.stop('error', 'zip_ambiguous',
                                  'Um nome lógico identifica arquivo e diretório.', name)
            # OCF file names must remain unique under canonical Unicode
            # equivalence and full case folding. Preserve physical spelling;
            # this is only a collision check, never a lookup rewrite.
            canonical = unicodedata.normalize('NFC', unicodedata.normalize('NFC', key).casefold())
            if canonical in canonical_names:
                self._issues.stop('error', 'zip_name_collision',
                                  'Dois caminhos ZIP colidem após equivalência canônica e case folding Unicode.', name)
            canonical_names[canonical] = name
            if info.header_offset in offsets:
                self._issues.stop('error', 'zip_structure',
                                  'Dois membros compartilham um cabeçalho local.')
            offsets.add(info.header_offset)
            logical[key] = directory
            self._infos[name] = info
            if not info.flag_bits & 0x800 and any(ord(c) > 127 for c in name):
                self._unsupported.add(name)
                self._issues.add('incomplete', 'zip_encoding_unsupported',
                                 'Um nome ZIP não ASCII sem sinalização UTF-8 está fora do perfil.', name)
            if info.flag_bits & (1 | 0x40 | 0x2000):
                self._unsupported.add(name)
                self._issues.partial = True
                self._issues.add('error', 'zip_encryption_forbidden',
                                 'A criptografia do próprio formato ZIP não é permitida no perfil OCF.', name)
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                self._unsupported.add(name)
                self._issues.add('incomplete', 'zip_compression_unsupported',
                                 'O método de compressão está fora do perfil.', name)
            if info.flag_bits & ~(0x1 | 0x2 | 0x4 | 0x8 | 0x40 | 0x800 | 0x2000):
                self._unsupported.add(name)
                self._issues.add('incomplete', 'zip_feature_unsupported',
                                 'Sinalizadores ZIP estão fora do perfil.', name)
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode) if info.create_system == 3 else 0
            if (kind not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or (kind == stat.S_IFDIR and not directory)
                    or (kind == stat.S_IFREG and directory)):
                self._unsupported.add(name)
                self._issues.add('incomplete', 'zip_type_unsupported',
                                 'Links e tipos especiais de membros ZIP estão fora do perfil.', name)
            if directory and info.file_size:
                self._issues.stop('error', 'zip_directory_data',
                                  'Uma entrada de diretório ZIP declara conteúdo.', name)

        for name in self._infos:
            parts = name.rstrip('/').split('/')
            if any(logical.get('/'.join(parts[:end])) is False for end in range(1, len(parts))):
                self._issues.stop('error', 'zip_ambiguous',
                                  'Um arquivo ZIP é usado como diretório pai.', name)

        ordered = sorted((info.header_offset, name) for name, info in self._infos.items())
        self._boundaries = {
            name: ordered[index + 1][0] if index + 1 < len(ordered) else central
            for index, (_, name) in enumerate(ordered)
        }
        for name, info in self._infos.items():
            self._stream.seek(info.header_offset)
            header = _exact(self._stream, 30)
            if header[:4] != b'PK\x03\x04':
                self._issues.stop('error', 'zip_structure',
                                  'Um cabeçalho local está corrompido.', name)
            name_size, extra_size = struct.unpack_from('<HH', header, 26)
            if info.header_offset + 30 + name_size + extra_size > self._boundaries[name]:
                self._issues.stop('error', 'zip_structure',
                                  'Um cabeçalho local invade a próxima estrutura ZIP.', name)
            _exact(self._stream, name_size)
            extra = _exact(self._stream, extra_size)
            cursor = 0
            while cursor < len(extra):
                if cursor + 4 > len(extra):
                    self._issues.stop('error', 'zip_structure',
                                      'Um campo extra local está truncado.', name)
                kind, length = struct.unpack_from('<HH', extra, cursor)
                cursor += 4
                if cursor + length > len(extra):
                    self._issues.stop('error', 'zip_structure',
                                      'Um campo extra local está truncado.', name)
                if kind == 1:
                    self._unsupported.add(name)
                    self._issues.add('incomplete', 'zip64_unsupported',
                                     'Campos locais ZIP64 estão fora do perfil.', name)
                cursor += length
            self.entries[name] = Entry(name, info.file_size, info.compress_size,
                                       info.CRC, info.compress_type, info.header_offset,
                                       info.flag_bits, name.endswith('/'), extra_size)

    def read(self, name, *, max_bytes=None):
        """Return checked member bytes once, or None after a recorded failure."""
        if self._closed:
            raise ValueError('O snapshot já foi fechado.')
        if self._read_exhausted or (self._issues.items and self._issues.items[-1].code == 'issue_limit'):
            raise StopAudit
        if not isinstance(name, str):
            raise ValueError('Nome de membro inválido.')
        if max_bytes is None:
            max_bytes = self._limits.max_xml_bytes
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('Limite de leitura inválido.')
        max_bytes = min(max_bytes, self._limits.max_xml_bytes)
        if name not in self.entries or self.entries[name].directory:
            return None
        if name in self._cache:
            cached = self._cache[name]
            if cached is not None and len(cached) > max_bytes:
                self._issues.add('incomplete', 'limit_xml_bytes',
                                 'O membro excede o orçamento desta leitura.', name)
                return None
            return cached
        self._cache[name] = None
        if name in self._unsupported:
            return None
        info = self._infos[name]
        self.selected_member_reads += 1
        if info.file_size > max_bytes:
            self._issues.add('incomplete', 'limit_xml_bytes',
                             'O tamanho declarado excede o limite desta leitura.', name)
            return None
        remaining = self._limits.max_total_read_bytes - self.read_bytes
        if info.file_size > remaining:
            self._read_exhausted = True
            self._issues.stop('incomplete', 'limit_total_read_bytes',
                              'O orçamento global impede a leitura de outro membro.', name)
        output_limit = min(max_bytes, remaining)
        size = 0
        checksum = 0
        chunks = []
        try:
            for block in _member_blocks(self._stream, self._zip, info,
                                        self._boundaries[name], output_limit):
                size += len(block)
                self.read_bytes += len(block)
                if size > output_limit:
                    if size > info.file_size:
                        self._issues.add('error', 'zip_size',
                                         'Os bytes produzidos excedem o tamanho ZIP declarado.', name)
                    if self.read_bytes > self._limits.max_total_read_bytes:
                        self._read_exhausted = True
                        self._issues.stop('incomplete', 'limit_total_read_bytes',
                                          'Os bytes efetivos excedem o orçamento global de leitura.', name)
                    self._issues.add('incomplete', 'limit_xml_bytes',
                                     'Os bytes efetivos excedem o limite desta leitura.', name)
                    return None
                checksum = zlib.crc32(block, checksum)
                chunks.append(block)
            if size != info.file_size:
                self._issues.partial = True
                self._issues.add('error', 'zip_size',
                                 'O tamanho ZIP declarado diverge dos bytes descomprimidos.', name)
                return None
            if checksum & 0xffffffff != info.CRC:
                self._issues.partial = True
                self._issues.add('error', 'zip_crc',
                                 'O CRC do membro diverge dos bytes descomprimidos.', name)
                return None
        except (zipfile.BadZipFile, EOFError, zlib.error, UnicodeError, struct.error):
            self._issues.partial = True
            self._issues.add('error', 'zip_member_invalid',
                             'O membro ZIP está corrompido ou possui estrutura contraditória.', name)
            return None
        except (NotImplementedError, RuntimeError):
            self._issues.add('incomplete', 'zip_feature_unsupported',
                             'Um recurso do membro ZIP está fora do perfil.', name)
            return None
        except _UnsupportedZip:
            self._issues.add('incomplete', 'zip_member_extension_unsupported',
                             'Dados adicionais entre membros ZIP estão fora do perfil.', name)
            return None
        result = b''.join(chunks)
        self._cache[name] = result
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._cache.clear()
        if self._zip is not None:
            self._zip.close()


@contextmanager
def open_snapshot(path, *, limits=AuditLimits(), issues):
    """Open a bounded private snapshot and always close every owned handle."""
    if not isinstance(limits, AuditLimits):
        raise ValueError('Limites devem ser AuditLimits.')
    try:
        raw_path = os.fspath(path)
    except TypeError:
        raise ValueError('Caminho inválido.') from None
    if not isinstance(raw_path, (str, bytes)) or ('\x00' in raw_path if isinstance(raw_path, str) else b'\x00' in raw_path):
        raise ValueError('Caminho inválido.')
    descriptor = None
    try:
        descriptor = os.open(raw_path, os.O_RDONLY | getattr(os, 'O_BINARY', 0)
                             | getattr(os, 'O_NONBLOCK', 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            os.close(descriptor)
            descriptor = None
            raise AuditError('file_not_regular', 'A origem deve ser um arquivo regular.')
        source = os.fdopen(descriptor, 'rb')
        descriptor = None
    except FileNotFoundError:
        if descriptor is not None:
            os.close(descriptor)
        raise AuditError('file_not_found', 'O arquivo de origem não existe.') from None
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        # Windows refuses opening directories before fstat can classify them.
        # This fallback affects only the error code; successful opens still
        # require descriptor-based regular-file validation above.
        try:
            regular = stat.S_ISREG(os.stat(raw_path).st_mode)
        except OSError:
            regular = True
        if not regular:
            raise AuditError('file_not_regular', 'A origem deve ser um arquivo regular.') from None
        raise AuditError('file_unreadable', 'Não foi possível abrir o arquivo de origem.') from None
    archive = None
    try:
        with source, tempfile.TemporaryFile(mode='w+b') as snapshot:
            if before.st_size > limits.max_archive_bytes:
                issues.stop('incomplete', 'limit_archive_bytes',
                            'A origem excede o limite de bytes do snapshot.')
            digest = hashlib.sha256()
            copied = 0
            while True:
                block = source.read(min(_BLOCK, limits.max_archive_bytes - copied + 1))
                if not block:
                    break
                copied += len(block)
                if copied > limits.max_archive_bytes:
                    issues.stop('incomplete', 'limit_archive_bytes',
                                'A origem excede o limite de bytes do snapshot.')
                snapshot.write(block)
                digest.update(block)
            after = os.fstat(source.fileno())
            if _stat_identity(before) != _stat_identity(after) or copied != before.st_size:
                issues.stop('incomplete', 'source_changed',
                            'Os metadados da origem mudaram durante a cópia; a auditoria foi interrompida.')
            snapshot.flush()
            archive = ArchiveSnapshot(snapshot, limits=limits, issues=issues,
                                      archive_bytes=copied, sha256=digest.hexdigest())
            try:
                archive._prepare()
            except (zipfile.BadZipFile, EOFError, UnicodeError, struct.error):
                issues.stop('error', 'zip_invalid',
                            'O arquivo ZIP está corrompido ou possui estrutura contraditória.')
            yield archive
    except AuditError:
        raise
    except OSError:
        raise AuditError('input_read', 'Não foi possível ler ou copiar o arquivo de origem.') from None
    finally:
        if archive is not None:
            archive.close()
