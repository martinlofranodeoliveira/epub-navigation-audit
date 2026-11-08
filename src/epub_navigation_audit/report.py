"""Deterministic reports without copying the book's text labels."""
import json
import re
import unicodedata


def to_json(report):
    return json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + '\n'


def _md(value):
    value = '—' if value is None else str(value)
    text = ''.join(('\\u%04x' if ord(c) <= 0xffff else '\\U%08x') % ord(c)
                   if unicodedata.category(c) in {'Cc', 'Cf', 'Cs', 'Zl', 'Zp'} else c for c in value)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~\-])', r'\\\1', text)


def _table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(_md(x) for x in headers) + ' |',
                      '| ' + ' | '.join('---' for _ in headers) + ' |'] +
                     ['| ' + ' | '.join(_md(x) for x in row) + ' |' for row in rows])


def to_markdown(report):
    package, nav = report['package'], report['navigation']
    sections = ['# Auditoria de navegação EPUB', '**Estado:** ' + _md(report['status']),
                '**Checks do perfil completos:** ' + ('sim' if report['complete'] else 'não'),
                '**Arquivo:** ' + _md(report['filename']),
                '**SHA-256 do snapshot:** ' + _md(report['archive']['sha256']),
                'Resultado do perfil epub-navigation-audit-v1. Não é validação integral EPUB nem certificação de acessibilidade, segurança ou procedência.',
                '## Cobertura', _table(['Métrica', 'Valor'], report['summary'].items()),
                _table(['Captura do arquivo', 'Valor'], report['archive'].items()),
                '## Rendição selecionada', '**Package:** ' + _md(package['path']),
                '**Version:** ' + _md(package['version']), '**Nav:** ' + _md(package['nav_path']),
                '### Rootfiles', _table(['Caminho'], ((p,) for p in package['rootfiles'])),
                '### Manifest', _table(['ID', 'Caminho local', 'Media type', 'Propriedades', 'Fallback', 'Resolução', 'SHA-256 do href'],
                                     ((item['id'], item['path'], item['media_type'], ' '.join(item['properties']),
                                       item['fallback'], item['resolution'], item['href_sha256']) for item in package['manifest'])),
                '### Ordem de leitura', _table(['Posição', 'IDref', 'Linear', 'Caminho', 'Media type'],
                                             ((item['index'], item['idref'], 'sim' if item['linear'] else 'não',
                                               item['path'], item['media_type']) for item in package['spine'])),
                '## Links do sumário', '**Navs toc encontrados:** ' + str(nav['toc_count']),
                _table(['Posição', 'Destino', 'Fragmento', 'Resolução', 'SHA-256 do href'],
                       ((link['index'], link['target'], link['fragment'], link['resolution'], link['href_sha256']) for link in nav['links'])),
                '## Documentos selecionados', _table(['Caminho', 'Media type', 'IDs', 'Completo'],
                                                  ((d['path'], d['media_type'], d['ids'], 'sim' if d['complete'] else 'não') for d in report['documents'])),
                '## Achados', _table(['Gravidade', 'Código', 'Membro', 'Posição', 'Mensagem'],
                                    ((i['severity'], i['code'], i['path'], i['location'], i['message']) for i in report['issues']))
                if report['issues'] else 'Nenhum achado neste perfil.']
    if report['options']['include_hrefs']:
        sections.extend(['## Hrefs originais solicitados',
                         'Estes valores podem conter informações sensíveis; revise antes de compartilhar.',
                         _table(['Origem', 'Referência', 'Href'],
                                [('manifest', item['id'], item.get('href')) for item in package['manifest']] +
                                [('toc', link['index'], link.get('href')) for link in nav['links']])])
    return '\n\n'.join(sections) + '\n'
