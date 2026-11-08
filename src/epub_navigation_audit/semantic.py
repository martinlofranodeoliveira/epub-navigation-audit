"""Inventory one selected rendition and audit its bounded navigation profile."""
import hashlib
import re
import unicodedata

from .model import AuditError, StopAudit
from .urls import resolve_reference
from .xmlsafe import XmlBudget, parse_xml


C = '{urn:oasis:names:tc:opendocument:xmlns:container}'
O = '{http://www.idpf.org/2007/opf}'
H = '{http://www.w3.org/1999/xhtml}'
S = '{http://www.w3.org/2000/svg}'
EPUB_TYPE = '{http://www.idpf.org/2007/ops}type'
XML_ID = '{http://www.w3.org/XML/1998/namespace}id'
CONTENT = {'application/xhtml+xml': H + 'html', 'image/svg+xml': S + 'svg'}
_SPACE = re.compile(r'[\t\n\f\r ]+')


def _tokens(value):
    return sorted(set(filter(None, _SPACE.split(value))))


def _href(value, include):
    result = {'href_sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()}
    if include:
        result['href'] = value
    return result


class _Inspector:
    def __init__(self, archive, rootfile, include_hrefs, limits, issues):
        self.archive, self.rootfile, self.include_hrefs = archive, rootfile, include_hrefs
        self.limits, self.issues = limits, issues
        self.budget = XmlBudget(limits, issues)
        self.result = {
            'package': {'path': None, 'version': None, 'rootfiles': [], 'manifest': [], 'spine': [], 'nav_path': None},
            'navigation': {'path': None, 'toc_count': 0, 'links': []},
            'documents': [],
            'summary': {'manifest_items': 0, 'spine_items': 0, 'nav_links': 0,
                        'resolved_links': 0, 'xml_documents': 0, 'xml_nodes': 0},
        }
        self.package = self.result['package']
        self.navigation = self.result['navigation']
        self.trees, self.documents, self.ids = {}, {}, {}
        self.content_results = {}
        self.normalized_ids = {}
        self.normalized_members = {}
        for name in archive.entries:
            self.normalized_members.setdefault(unicodedata.normalize('NFC', name), []).append(name)
        self.references = 0
        self.by_id, self.by_path = {}, {}
        self.direct_spine = set()
        self.fallback_paths = set()
        self.fallback_scanned = set()
        self.foreign_paths = set()
        self.linear_positions = {}

    def finding(self, severity, code, message, path=None, location=None):
        self.issues.add(severity, code, message, path, location)

    def count(self, path, location):
        if self.references >= self.limits.max_links:
            self.issues.stop('incomplete', 'reference_limit', 'O limite global de referências foi atingido.', path, location)
        self.references += 1

    def regular(self, path):
        entry = self.archive.entries.get(path)
        return entry is not None and not entry.directory

    def resolve(self, base, raw, path, location):
        resolved = resolve_reference(base, raw)
        if resolved['kind'] == 'local':
            matches = self.normalized_members.get(unicodedata.normalize('NFC', resolved['path']), [])
            if len(matches) > 1:
                self.finding('error', 'member_normalization_ambiguous', 'Há nomes de membros equivalentes por normalização Unicode; o destino é ambíguo.', path, location)
                return {'kind': 'unsupported', 'path': None, 'fragment': None, 'reason': 'ambiguous_member'}
            if matches:
                resolved['path'] = matches[0]
        return resolved

    def xml(self, path, media_type=None):
        if media_type in CONTENT and path not in self.documents:
            self.documents[path] = {'path': path, 'media_type': media_type, 'ids': 0, 'complete': False}
        if path in self.trees:
            tree = self.trees[path]
            if tree is not None and media_type in CONTENT:
                return self.content(tree, path, media_type)
            return tree
        self.trees[path] = None
        self.result['summary']['xml_documents'] += 1
        data = self.archive.read(path)
        if data is None:
            self.issues.partial = True
            return None
        tree = parse_xml(data, path=path, budget=self.budget)
        if tree is None:
            self.issues.partial = True
            return None
        self.trees[path] = tree
        if media_type in CONTENT:
            return self.content(tree, path, media_type)
        return tree

    def content(self, tree, path, media_type):
        key = (path, media_type)
        if key in self.content_results:
            return tree if self.content_results[key] else None
        self.content_results[key] = False
        if tree.tag != CONTENT[media_type]:
            self.issues.partial = True
            self.finding('error', 'content_root_invalid', 'A raiz do documento de conteúdo não corresponde ao tipo declarado.', path)
            return None
        if path not in self.ids:
            counts = {}
            for element in tree.iter():
                # id and xml:id are aliases on one element, not two anchors.
                for value in {element.get('id'), element.get(XML_ID)} - {None}:
                    counts[value] = counts.get(value, 0) + 1
            if any(value > 1 for value in counts.values()):
                self.finding('error', 'duplicate_id', 'Um identificador está repetido em elementos diferentes.', path)
            self.ids[path] = counts
            self.normalized_ids[path] = {unicodedata.normalize('NFC', value) for value in counts}
            self.documents[path]['ids'] = len(counts)
            self.documents[path]['complete'] = True
        self.content_results[key] = True
        return tree

    def container(self):
        path = 'META-INF/container.xml'
        if not self.regular(path):
            self.issues.partial = True
            self.finding('error', 'container_missing', 'O documento container.xml não foi encontrado.', path)
            return None
        tree = self.xml(path)
        if tree is None:
            return None
        if tree.tag != C + 'container' or tree.get('version') != '1.0':
            self.issues.partial = True
            self.finding('error', 'container_invalid', 'A raiz, o namespace ou a versão do container são inválidos.', path)
            return None
        rootfiles = tree.findall(C + 'rootfiles')
        if len(rootfiles) != 1:
            self.issues.partial = True
            self.finding('error', 'rootfiles_invalid', 'O container deve possuir um único elemento rootfiles.', path)
            return None
        elements = rootfiles[0].findall(C + 'rootfile')
        if not elements:
            self.issues.partial = True
            self.finding('error', 'rootfiles_empty', 'O container não declara uma rendição.', path)
            return None
        selectable = []
        for index, item in enumerate(elements, 1):
            self.count(path, index)
            raw = item.get('full-path')
            resolved = self.resolve('', raw, path, index) if raw else {'kind': 'unsupported', 'path': None, 'fragment': None}
            supported = resolved['kind'] == 'local' and resolved['path'] and resolved['fragment'] is None
            member = resolved['path'] if supported else None
            self.package['rootfiles'].append(member)
            if item.get('media-type') != 'application/oebps-package+xml':
                self.finding('error', 'rootfile_media_type', 'Uma rendição tem media-type inválido.', path, index)
            if not raw:
                self.finding('error', 'rootfile_path_missing', 'Uma rendição não declara full-path.', path, index)
            elif not supported:
                self.finding('incomplete', 'rootfile_reference_unsupported', 'O caminho de uma rendição está fora do perfil de URLs.', path, index)
            else:
                selectable.append(member)
        if self.rootfile is not None:
            if self.rootfile not in selectable:
                raise AuditError('rootfile_not_listed', 'A rendição selecionada não consta do container.')
            selected = self.rootfile
        elif len(elements) != 1:
            self.finding('incomplete', 'rootfile_selection_required', 'Há várias rendições; selecione explicitamente uma rootfile.', path)
            return None
        else:
            selected = selectable[0] if selectable else None
        self.package['path'] = selected
        return selected

    def manifest(self, tree, path):
        groups = tree.findall(O + 'manifest')
        if len(groups) != 1:
            self.issues.partial = True
            self.finding('error', 'manifest_invalid', 'O package deve possuir um único manifest.', path)
            return False
        for index, item in enumerate(groups[0].findall(O + 'item'), 1):
            self.count(path, index)
            identifier, raw, media = item.get('id', ''), item.get('href', ''), item.get('media-type', '')
            resolved = self.resolve(path, raw, path, index)
            # Fragments on manifest item references are outside this profile.
            if resolved['kind'] == 'local' and resolved['fragment'] is not None:
                resolved = {'kind': 'unsupported', 'path': None}
            record = {'id': identifier, 'media_type': media,
                      'properties': _tokens(item.get('properties', '')),
                      'fallback': item.get('fallback'), 'path': resolved['path'],
                      **_href(raw, self.include_hrefs), 'resolution': resolved['kind']}
            self.package['manifest'].append(record)
            self.by_id.setdefault(identifier, []).append(record)
            if not identifier or not raw or not media:
                self.issues.partial = True
                self.finding('error', 'manifest_item_required', 'Um item do manifest não contém os atributos obrigatórios.', path, index)
            if len(self.by_id[identifier]) > 1:
                self.finding('error', 'manifest_id_duplicate', 'Um identificador do manifest está repetido.', path, index)
            if record['resolution'] == 'unsupported':
                self.finding('incomplete', 'manifest_reference_unsupported', 'Uma referência do manifest está fora do perfil de URLs.', path, index)
            elif record['resolution'] == 'local':
                self.by_path.setdefault(record['path'], []).append(record)
                if len(self.by_path[record['path']]) > 1:
                    self.finding('error', 'manifest_path_duplicate', 'Um recurso local aparece mais de uma vez no manifest.', path, index)
                if not self.regular(record['path']):
                    self.finding('error', 'manifest_member_missing', 'Um recurso local declarado no manifest não existe como arquivo.', record['path'], index)
        return True

    def spine(self, tree, path):
        groups = tree.findall(O + 'spine')
        if len(groups) != 1:
            self.issues.partial = True
            self.finding('error', 'spine_invalid', 'O package deve possuir um único spine.', path)
            return False
        seen = set()
        for index, element in enumerate(groups[0].findall(O + 'itemref'), 1):
            self.count(path, index)
            identifier = element.get('idref', '')
            matches = self.by_id.get(identifier, [])
            item = matches[0] if len(matches) == 1 else None
            linear_raw = element.get('linear', 'yes')
            record = {'index': index, 'idref': identifier, 'linear': linear_raw != 'no',
                      'path': item['path'] if item else None, 'media_type': item['media_type'] if item else None}
            self.package['spine'].append(record)
            if linear_raw not in {'yes', 'no'}:
                self.finding('error', 'spine_linear_invalid', 'Um itemref possui valor linear inválido.', path, index)
            if identifier in seen:
                self.finding('error', 'spine_idref_duplicate', 'O spine repete um idref.', path, index)
            seen.add(identifier)
            if item is None:
                self.issues.partial = True
                self.finding('error', 'spine_idref_invalid', 'Um idref do spine não identifica um item único.', path, index)
                continue
            if item['media_type'] not in CONTENT:
                if item['path']:
                    self.foreign_paths.add(item['path'])
                self.finding('incomplete', 'spine_foreign_content', 'Conteúdo estrangeiro e sua cadeia de fallback não são auditados por este perfil.', path, index)
                current, chain = item, set()
                while current and current['id'] not in chain and current['id'] not in self.fallback_scanned:
                    chain.add(current['id'])
                    self.fallback_scanned.add(current['id'])
                    fallback = self.by_id.get(current['fallback'], [])
                    current = fallback[0] if len(fallback) == 1 else None
                    if current and current['path']:
                        self.fallback_paths.add(current['path'])
                continue
            if item['resolution'] != 'local':
                self.finding('incomplete', 'spine_reference_unsupported', 'Um documento do spine não é um recurso local resolvido.', path, index)
                continue
            self.direct_spine.add(item['path'])
            if record['linear']:
                self.linear_positions.setdefault(item['path'], index)
        if not any(item['linear'] for item in self.package['spine']):
            self.finding('error', 'spine_linear_missing', 'O spine deve conter ao menos um item linear.', path)
        return True

    def toc_links(self, nav, path):
        tocs = [element for element in nav.iter(H + 'nav') if 'toc' in _tokens(element.get(EPUB_TYPE, ''))]
        self.navigation['toc_count'] = len(tocs)
        if len(tocs) != 1:
            self.issues.partial = True
            self.finding('error', 'toc_count_invalid', 'O documento de navegação deve conter exatamente um nav toc.', path)
            return
        children = list(tocs[0])
        if children and children[0].tag in {H + 'h' + str(i) for i in range(1, 7)}:
            children.pop(0)
        if len(children) != 1 or children[0].tag != H + 'ol':
            self.issues.partial = True
            self.finding('error', 'toc_structure', 'O nav toc deve possuir uma lista ol primária e título opcional.', path)
            return
        stack = [('ol', children[0])]
        while stack:
            kind, element = stack.pop()
            if kind == 'ol':
                entries = list(element)
                if not entries or any(child.tag != H + 'li' for child in entries):
                    self.issues.partial = True
                    self.finding('error', 'toc_structure', 'Uma lista do toc deve conter um ou mais elementos li.', path)
                stack.extend(('li', child) for child in reversed(entries) if child.tag == H + 'li')
                continue
            parts = list(element)
            valid = (1 <= len(parts) <= 2 and parts[0].tag in {H + 'a', H + 'span'}
                     and (len(parts) == 1 or parts[1].tag == H + 'ol'))
            if not valid:
                self.issues.partial = True
                self.finding('error', 'toc_structure', 'Um li do toc deve começar com a ou span e ter no máximo uma sublista ol.', path)
                continue
            label = parts[0]
            if len(parts) == 2:
                stack.append(('ol', parts[1]))
            if label.tag == H + 'a':
                if 'href' not in label.attrib:
                    self.issues.partial = True
                    self.finding('error', 'toc_href_missing', 'Um link do toc não declara href.', path)
                else:
                    yield label.get('href')
            elif len(parts) != 2:
                self.issues.partial = True
                self.finding('error', 'toc_structure', 'Um span do toc exige uma sublista ol.', path)

    def link(self, raw, path):
        index = len(self.navigation['links']) + 1
        self.count(path, index)
        resolved = self.resolve(path, raw, path, index)
        record = {'index': index, **_href(raw, self.include_hrefs), 'target': resolved['path'],
                  'fragment': resolved['fragment'], 'resolution': 'unsupported'}
        self.navigation['links'].append(record)
        target = resolved['path']
        if resolved['kind'] != 'local':
            self.finding('incomplete', 'toc_reference_unsupported', 'Um destino do toc está fora do perfil de URLs locais.', path, index)
            return
        if not self.regular(target):
            self.issues.partial = True
            record['resolution'] = 'missing_member'
            self.finding('error', 'toc_member_missing', 'Um destino do toc não existe como arquivo.', target, index)
            return
        matches = self.by_path.get(target, [])
        if not matches:
            self.issues.partial = True
            record['resolution'] = 'not_manifested'
            self.finding('error', 'toc_not_manifested', 'Um destino do toc não consta do manifest.', target, index)
            return
        if len(matches) != 1:
            record['resolution'] = 'target_unavailable'
            self.finding('incomplete', 'toc_target_ambiguous', 'Um destino do toc possui declaração ambígua no manifest.', target, index)
            return
        item = matches[0]
        if target in self.foreign_paths or (target in self.fallback_paths and target not in self.direct_spine):
            self.finding('incomplete', 'toc_fallback_unsupported', 'Um destino do toc depende de uma cadeia de fallback fora deste perfil.', target, index)
            return
        if item['media_type'] not in CONTENT:
            record['resolution'] = 'not_content'
            self.finding('error', 'toc_not_content', 'Um destino do toc não é um documento de conteúdo XHTML ou SVG.', target, index)
            return
        if target not in self.direct_spine:
            self.issues.partial = True
            record['resolution'] = 'not_spine'
            self.finding('error', 'toc_not_spine', 'Um destino do toc não é um documento top-level do spine.', target, index)
            return
        tree = self.xml(target, item['media_type'])
        if tree is None:
            record['resolution'] = 'target_unavailable'
            self.finding('incomplete', 'toc_target_unavailable', 'Não foi possível confirmar os identificadores de um destino do toc.', target, index)
            return
        fragment = record['fragment']
        count = self.ids[target].get(fragment, 0) if fragment else 1
        if not count:
            if unicodedata.normalize('NFC', fragment) in self.normalized_ids[target]:
                record['resolution'] = 'unsupported'
                self.finding('incomplete', 'fragment_normalization_unsupported', 'Um fragmento difere de identificador existente somente na normalização Unicode; a equivalência não foi confirmada.', target, index)
            else:
                record['resolution'] = 'missing_fragment'
                self.finding('error', 'toc_fragment_missing', 'Um fragmento do toc não corresponde a um identificador do destino.', target, index)
        elif count > 1:
            record['resolution'] = 'target_unavailable'
        else:
            record['resolution'] = 'resolved'

    def run(self):
        path = self.container()
        if path is None:
            return
        if 'META-INF/encryption.xml' in self.archive.entries:
            self.finding('incomplete', 'ocf_encryption_unsupported', 'O container declara criptografia fora deste perfil; o conteúdo não foi interpretado.', 'META-INF/encryption.xml')
            return
        if not self.regular(path):
            self.issues.partial = True
            self.finding('error', 'package_missing', 'A rendição selecionada não existe como arquivo.', path)
            return
        tree = self.xml(path)
        if tree is None:
            return
        if tree.tag != O + 'package':
            self.issues.partial = True
            self.finding('error', 'package_root_invalid', 'A raiz ou o namespace do package são inválidos.', path)
            return
        self.package['version'] = tree.get('version')
        if tree.get('version') != '3.0':
            self.finding('incomplete', 'version_unsupported', 'A versão do package está fora deste perfil EPUB 3.', path)
            return
        if not self.manifest(tree, path):
            return
        if not self.spine(tree, path):
            return
        navs = [item for item in self.package['manifest'] if 'nav' in item['properties']]
        if len(navs) != 1:
            self.issues.partial = True
            self.finding('error', 'nav_count_invalid', 'O manifest deve declarar exatamente um documento nav.', path)
            return
        nav = navs[0]
        if nav['media_type'] != 'application/xhtml+xml':
            self.issues.partial = True
            self.finding('error', 'nav_media_type', 'O documento nav deve ser XHTML.', path)
            return
        self.package['nav_path'] = nav['path']
        self.navigation['path'] = nav['path']
        # Read all direct core spine documents, including those absent in toc.
        for item in self.package['spine']:
            if item['path'] in self.direct_spine and self.regular(item['path']):
                self.xml(item['path'], item['media_type'])
        if nav['resolution'] != 'local':
            self.finding('incomplete', 'nav_reference_unsupported', 'O documento nav não é um recurso local resolvido.', path)
            return
        if not self.regular(nav['path']):
            self.issues.partial = True
            return  # The manifest inventory already proved its absence.
        nav_tree = self.xml(nav['path'], nav['media_type'])
        if nav_tree is None:
            return
        for raw in self.toc_links(nav_tree, nav['path']):
            self.link(raw, nav['path'])
        previous, seen = -1, set()
        for link in self.navigation['links']:
            target = link['target']
            if link['resolution'] == 'resolved' and target in self.linear_positions and target not in seen:
                seen.add(target)
                position = self.linear_positions[target]
                if position < previous:
                    self.finding('warning', 'toc_order', 'A primeira ocorrência de destinos no toc difere da ordem linear do spine.', nav['path'], link['index'])
                previous = position

    def finish(self):
        self.result['documents'] = [self.documents[path] for path in sorted(self.documents)]
        summary = self.result['summary']
        summary.update(manifest_items=len(self.package['manifest']), spine_items=len(self.package['spine']),
                       nav_links=len(self.navigation['links']),
                       resolved_links=sum(item['resolution'] == 'resolved' for item in self.navigation['links']),
                       xml_nodes=self.budget.nodes)
        return self.result


def inspect_publication(archive, *, rootfile=None, include_hrefs=False, limits, issues):
    """Return an incremental result even after an already-recorded global stop."""
    inspector = _Inspector(archive, rootfile, include_hrefs, limits, issues)
    try:
        inspector.run()
    except StopAudit:
        pass
    return inspector.finish()
