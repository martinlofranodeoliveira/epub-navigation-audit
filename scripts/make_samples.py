"""Generate original, deterministic small EPUB fixtures; never overwrite files."""
import argparse
import os
from pathlib import Path
import tempfile
from urllib.parse import quote
import zipfile


VARIANTS = ('valido', 'fragmento-ausente', 'arquivo-ausente', 'id-duplicado',
            'mimetype-incorreto', 'fora-spine', 'doctype', 'ordem-diferente',
            'svg', 'multiplas-rendicoes', 'unicode-decomposto', 'normalizacao-divergente')


def sample_files(variant='valido'):
    if variant not in VARIANTS:
        raise ValueError('Variante sintética desconhecida.')
    filename = 'cafe\u0301.xhtml' if variant in {'unicode-decomposto', 'normalizacao-divergente'} else 'café.xhtml'
    linked_name = 'café.xhtml' if variant == 'normalizacao-divergente' else filename
    second_href = 'text/' + quote(linked_name) + '#fim'
    first_target = 'text/inicio.xhtml#ausente' if variant == 'fragmento-ausente' else 'text/inicio.xhtml#inicio'
    first = '<li><a href="' + first_target + '">Introdução fictícia</a></li>'
    second = '<li><span>Continuação fictícia</span><ol><li><a href="' + second_href + '">Capítulo final</a></li></ol></li>'
    nav_items = second + first if variant == 'ordem-diferente' else first + second
    if variant == 'svg':
        nav_items += '<li><a href="mapa.svg#alvo">Mapa geométrico fictício</a></li>'
    doctype = '<!DOCTYPE html>\n' if variant == 'doctype' else ''
    nav = ('<?xml version="1.0" encoding="UTF-8"?>\n' + doctype +
           '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="pt-BR" xml:lang="pt-BR">'
           '<head><title>Sumário fictício</title></head><body><nav epub:type="toc" id="sumario">'
           '<h1>Sumário</h1><ol>' + nav_items + '</ol></nav></body></html>')
    extra_id = '<p id="inicio">Outro elemento sintético com ID repetido.</p>' if variant == 'id-duplicado' else ''
    intro = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<html xmlns="http://www.w3.org/1999/xhtml" lang="pt-BR" xml:lang="pt-BR">'
             '<head><title>Introdução fictícia</title></head><body><h1 id="inicio">Um livro demonstrativo</h1>'
             '<p id="detalhe">Este texto foi criado para testar referências locais. Não pertence a um livro real.</p>'
             + extra_id + '</body></html>')
    final = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<html xmlns="http://www.w3.org/1999/xhtml" lang="pt-BR" xml:lang="pt-BR">'
             '<head><title>Final fictício</title></head><body><h1 id="fim">Fim do exemplo</h1>'
             '<p>Os exemplos desta publicação são originais e inteiramente sintéticos.</p></body></html>')
    manifest_extra = '<item id="mapa" href="mapa.svg" media-type="image/svg+xml"/>' if variant == 'svg' else ''
    spine_extra = '<itemref idref="mapa" properties="rendition:layout-pre-paginated"/>' if variant == 'svg' else ''
    second_spine = '' if variant == 'fora-spine' else '<itemref idref="final"/>'
    opf = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="pt-BR">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:identifier id="book-id">urn:uuid:10892133-1aa4-4ae0-b03d-202611080001</dc:identifier>'
           '<dc:title>Guia fictício de navegação</dc:title><dc:language>pt-BR</dc:language>'
           '<dc:creator>Projeto demonstrativo</dc:creator><dc:rights>Exemplo original sob licença MIT.</dc:rights>'
           '<meta property="dcterms:modified">2026-11-08T00:00:00Z</meta></metadata>'
           '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
           '<item id="intro" href="text/inicio.xhtml" media-type="application/xhtml+xml"/>'
           '<item id="final" href="text/' + quote(linked_name) + '" media-type="application/xhtml+xml"/>'
           + manifest_extra + '</manifest><spine><itemref idref="intro"/>' + second_spine + spine_extra + '</spine></package>')
    extra_root = '<rootfile full-path="EPUB/alternativa.opf" media-type="application/oebps-package+xml"/>' if variant == 'multiplas-rendicoes' else ''
    container = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
                 '<rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/>'
                 + extra_root + '</rootfiles></container>')
    files = {'mimetype': b'application/epub+zip' + (b'\n' if variant == 'mimetype-incorreto' else b''),
             'META-INF/container.xml': container.encode(), 'EPUB/package.opf': opf.encode(),
             'EPUB/nav.xhtml': nav.encode(), 'EPUB/text/inicio.xhtml': intro.encode()}
    if variant != 'arquivo-ausente':
        files['EPUB/text/' + filename] = final.encode()
    if variant == 'svg':
        files['EPUB/mapa.svg'] = ('<?xml version="1.0" encoding="UTF-8"?>'
                                 '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">'
                                 '<title>Mapa fictício</title><rect id="alvo" x="10" y="10" width="80" height="40" fill="black"/></svg>').encode()
    if variant == 'multiplas-rendicoes':
        files['EPUB/alternativa.opf'] = opf.encode()
    return files


def write_sample(destination, variant='valido'):
    destination = Path(destination)
    files = sample_files(variant)
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.epub-sample-', suffix='.tmp', dir=destination.parent)
        os.close(fd); temporary = Path(name)
        with zipfile.ZipFile(temporary, 'w') as archive:
            for filename in ['mimetype', *sorted(name for name in files if name != 'mimetype')]:
                info = zipfile.ZipInfo(filename, (2026, 11, 8, 0, 0, 0))
                info.create_system = 0
                method = zipfile.ZIP_STORED if filename == 'mimetype' else zipfile.ZIP_DEFLATED
                info.extract_version = 10 if method == zipfile.ZIP_STORED else 20
                archive.writestr(info, files[filename], compress_type=method, compresslevel=9)
        with temporary.open('r+b') as stream:
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Gera EPUBs sintéticos NOVOS, sem livros de terceiros.')
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        args.directory.mkdir(parents=True, exist_ok=True)
        destinations = [(args.directory / (variant + '.epub'), variant) for variant in VARIANTS]
        if any(path.exists() or path.is_symlink() for path, _ in destinations):
            parser.exit(3, 'Há um destino existente. Escolha outra pasta; arquivos existentes não são sobrescritos.\n')
        for path, variant in destinations:
            write_sample(path, variant)
    except (OSError, ValueError, zipfile.BadZipFile):
        parser.exit(3, 'Não foi possível criar os exemplos novos. Confira a pasta e o suporte a links exclusivos.\n')
    print('Criados ' + str(len(VARIANTS)) + ' EPUBs inteiramente sintéticos.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
