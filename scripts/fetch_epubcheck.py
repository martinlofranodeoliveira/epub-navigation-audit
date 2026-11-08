"""Fetch one pinned official development oracle, verify its digest, unpack it."""
import argparse
import hashlib
from pathlib import Path
import urllib.request
import zipfile

VERSION = '5.3.0'
SIZE = 33_071_108
DIGEST = '6c07e68584b2e2ce2f89fe06e1246dfead3eb36b46b340e7d93524f29dcff6c5'
URL = 'https://github.com/w3c/epubcheck/releases/download/v5.3.0/epubcheck-5.3.0.zip'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Baixa apenas EPUBCheck 5.3.0 oficial para o oráculo de desenvolvimento.')
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(argv)
    args.directory.mkdir(parents=True, exist_ok=True)
    archive = args.directory / ('epubcheck-' + VERSION + '.zip')
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open('xb') as stream:
            count = 0
            while block := response.read(min(65536, SIZE - count + 1)):
                count += len(block)
                if count > SIZE:
                    raise ValueError('O artefato excedeu o tamanho oficial fixado.')
                stream.write(block)
    payload = archive.read_bytes()
    if len(payload) != SIZE or hashlib.sha256(payload).hexdigest() != DIGEST:
        raise ValueError('O artefato não corresponde ao digest oficial fixado. Não será executado.')
    # This is the digest-verified tool distribution, never an input EPUB.
    with zipfile.ZipFile(archive) as package:
        package.extractall(args.directory)
    print('EPUBCheck 5.3.0: digest confirmado; disponível em ' + str(args.directory / 'epubcheck-5.3.0/epubcheck.jar'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
