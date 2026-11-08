"""A deliberately bounded subset of container-relative WHATWG URL references.

No host paths are opened. Percent decoding is applied once to names after dot
segments have been recognized. Ambiguous forms stay explicitly unsupported.
"""
import re
import unicodedata
from urllib.parse import unquote_to_bytes, urlsplit


_HEX = frozenset('0123456789abcdefABCDEF')
_FORBIDDEN_SCHEMES = frozenset({'file', 'data', 'javascript', 'js', 'local'})
_MICRO = re.compile(r'^(?:epubcfi|xpointer|svgview|element|xmlns)\(', re.I)


def _result(kind, path=None, fragment=None, reason=None):
    return {'kind': kind, 'path': path, 'fragment': fragment, 'reason': reason}


def _bad(reason):
    return _result('unsupported', reason=reason)


def _escapes_valid(value):
    for index, char in enumerate(value):
        if char == '%' and (index + 2 >= len(value)
                            or value[index + 1] not in _HEX or value[index + 2] not in _HEX):
            return False
    return True


def _decode(value):
    return unquote_to_bytes(value).decode('utf-8', errors='strict')


def _controls(value):
    return any(unicodedata.category(char) in {'Cc', 'Cs'} for char in value)


def resolve_reference(base_path, reference):
    """Resolve the accepted local subset, or classify a reference without I/O."""
    if type(base_path) is not str or type(reference) is not str:
        raise ValueError('A base e a referência devem ser textos.')
    if (base_path.startswith('/') or '\\' in base_path or _controls(base_path)
            or any(part in {'', '.', '..'} for part in base_path.split('/')) and base_path):
        raise ValueError('O membro de base deve ser um caminho canônico.')
    if _controls(reference) or '\\' in reference:
        return _bad('control_or_backslash')
    # WHATWG trims some ASCII whitespace; treating such boundary whitespace as
    # a literal ZIP name would resolve a different resource.
    if reference != reference.strip(' '):
        return _bad('boundary_space')
    if not _escapes_valid(reference):
        return _bad('percent_escape')
    try:
        parts = urlsplit(reference)
    except (ValueError, UnicodeError):
        return _bad('url_syntax')
    if parts.scheme:
        if parts.scheme.lower() in _FORBIDDEN_SCHEMES:
            return _bad('scheme')
        return _result('remote')
    if parts.netloc or reference.startswith('//'):
        return _result('remote')
    # A trailing bare '?' is still a query, despite urlsplit.query == ''.
    if '?' in reference.split('#', 1)[0]:
        return _bad('query')
    if parts.path.startswith('/'):
        return _bad('rooted_path')
    fragment = None
    if '#' in reference:
        try:
            fragment = _decode(parts.fragment)
        except (UnicodeError, ValueError):
            return _bad('fragment_encoding')
        if _controls(fragment):
            return _bad('fragment_control')
        if _MICRO.match(fragment) or ':~:' in fragment or '=' in fragment:
            return _bad('fragment_syntax')
    if not parts.path:
        return _result('local', path=base_path, fragment=fragment)
    segments = base_path.split('/')[:-1] if base_path else []
    last = parts.path.rsplit('/', 1)[-1].lower()
    trailing_directory = parts.path.endswith('/') or last in {'.', '%2e', '..', '.%2e', '%2e.', '%2e%2e'}
    raw_parts = parts.path.split('/')
    if parts.path.endswith('/'):
        raw_parts.pop()
    for raw in raw_parts:
        folded = raw.lower()
        if folded in {'.', '%2e'}:
            continue
        if folded in {'..', '.%2e', '%2e.', '%2e%2e'}:
            if not segments:
                return _bad('above_root')
            segments.pop()
            continue
        if not raw:
            return _bad('empty_segment')
        if re.search(r'%(?:2f|5c)', raw, re.I):
            return _bad('encoded_separator')
        try:
            decoded = _decode(raw)
        except (UnicodeError, ValueError):
            return _bad('path_encoding')
        if _controls(decoded) or any(char in decoded for char in '/\\:'):
            return _bad('path_character')
        segments.append(decoded)
    path = '/'.join(segments)
    if trailing_directory and path:
        path += '/'
    return _result('local', path=path, fragment=fragment)
