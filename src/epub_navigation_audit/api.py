"""Compose bounded archive capture and the navigation-specific checks."""
from dataclasses import asdict
import os
from pathlib import Path

from .archive import open_snapshot
from .model import AuditLimits, Issues, StopAudit, sorted_issues
from .semantic import inspect_publication


def _check_mimetype(archive, issues):
    entry = archive.entries.get('mimetype')
    if entry is None or entry.directory:
        issues.add('error', 'mimetype_missing', 'O arquivo mimetype não foi encontrado na raiz do EPUB.')
        return
    if entry.header_offset != 0:
        issues.add('error', 'mimetype_order', 'O arquivo mimetype não é a primeira entrada física do EPUB.', 'mimetype')
    if entry.compression != 0 or entry.flags & 1:
        issues.add('error', 'mimetype_encoding', 'O arquivo mimetype deve estar armazenado sem compressão ou criptografia.', 'mimetype')
    if entry.size != len(b'application/epub+zip'):
        issues.add('error', 'mimetype_size', 'O tamanho declarado do mimetype diverge dos 20 bytes exigidos.', 'mimetype')
    if entry.local_extra_size is None:
        issues.add('incomplete', 'mimetype_header_unavailable', 'Não foi possível confirmar o cabeçalho local do mimetype.', 'mimetype')
    elif entry.local_extra_size:
        issues.add('error', 'mimetype_extra', 'O cabeçalho local do mimetype contém um campo extra.', 'mimetype')
    content = archive.read('mimetype', max_bytes=64)
    if content is not None and content != b'application/epub+zip':
        issues.add('error', 'mimetype_content', 'O conteúdo do mimetype deve ser exatamente application/epub+zip, sem BOM ou padding.', 'mimetype')


def audit_epub(path, *, rootfile=None, include_hrefs=False, limits=AuditLimits()):
    try:
        raw = os.fspath(path)
    except TypeError:
        raise ValueError('Caminho de origem inválido.') from None
    if not isinstance(raw, str) or not raw or '\x00' in raw:
        raise ValueError('Caminho de origem inválido.')
    if type(include_hrefs) is not bool or type(limits) is not AuditLimits:
        raise ValueError('Opções de auditoria inválidas.')
    if rootfile is not None and (not isinstance(rootfile, str) or not rootfile or '\x00' in rootfile):
        raise ValueError('Seleção de rootfile inválida.')
    issues = Issues(limits.max_issues)
    report = {
        'schema_version': 1, 'profile': 'epub-navigation-audit-v1',
        'filename': Path(raw).name, 'status': 'incomplete', 'complete': False,
        'options': {'rootfile': rootfile, 'include_hrefs': include_hrefs}, 'limits': asdict(limits),
        'archive': {'bytes': None, 'sha256': None, 'entries': None, 'selected_member_reads': 0, 'read_bytes': 0},
        'package': {'path': None, 'version': None, 'rootfiles': [], 'manifest': [], 'spine': [], 'nav_path': None},
        'navigation': {'path': None, 'toc_count': 0, 'links': []}, 'documents': [],
        'summary': {'manifest_items': 0, 'spine_items': 0, 'nav_links': 0,
                    'resolved_links': 0, 'xml_documents': 0, 'xml_nodes': 0}, 'issues': [],
    }
    archive = None
    try:
        with open_snapshot(path, limits=limits, issues=issues) as archive:
            _check_mimetype(archive, issues)
            report.update(inspect_publication(archive, rootfile=rootfile, include_hrefs=include_hrefs,
                                               limits=limits, issues=issues))
    except StopAudit:
        pass
    finally:
        if archive is not None:
            report['archive'] = {'bytes': archive.archive_bytes, 'sha256': archive.sha256,
                                 'entries': len(archive.entries), 'selected_member_reads': archive.selected_member_reads,
                                 'read_bytes': archive.read_bytes}
    report['complete'] = not issues.partial
    report['status'] = 'invalid' if issues.error else 'incomplete' if issues.partial else 'consistent'
    report['issues'] = [asdict(issue) for issue in sorted_issues(issues.items)]
    return report
