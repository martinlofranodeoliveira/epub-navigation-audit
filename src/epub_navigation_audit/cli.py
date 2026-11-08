"""Command line interface and exclusive creation of report files."""
import argparse
from dataclasses import asdict
import os
from pathlib import Path
import sys
import tempfile

from . import __version__
from .api import audit_epub
from .model import AuditError, AuditLimits
from .report import to_json, to_markdown


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError('Argumentos inválidos. Use --help para consultar o formato aceito.')


def _parser():
    parser = _Parser(prog='epub-navigation-audit', allow_abbrev=False,
                     description='Audita sumário, ordem de leitura e referências de um EPUB 3 local sem renderizá-lo.')
    parser.add_argument('epub', metavar='FILE', help='Arquivo EPUB local existente.')
    parser.add_argument('--version', action='version', version='epub-navigation-audit ' + __version__)
    parser.add_argument('--format', choices=['json', 'markdown'], default='json')
    parser.add_argument('--include-hrefs', action='store_true', help='Incluir hrefs originais; podem conter informações sensíveis.')
    parser.add_argument('--rootfile', help='Selecionar um membro OPF decodificado entre as rootfiles declaradas.')
    parser.add_argument('--output', type=Path, help='Arquivo NOVO; diretório pai já deve existir.')
    for key, value in asdict(AuditLimits()).items():
        parser.add_argument('--' + key.replace('_', '-'), type=int, default=value,
                            help='Limite explícito (padrão: %(default)s).')
    return parser


def _publish_new(destination, text):
    # Adapted from LOFRANO TECNOLOGIA's MIT wheel-record-audit publisher.
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix='.epub-navigation-audit-', suffix='.tmp', dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except FileExistsError:
        raise AuditError('output_exists', 'O destino já existe. Escolha um arquivo novo; nada foi sobrescrito.') from None
    except (OSError, UnicodeError, ValueError):
        raise AuditError('output_write', 'Não foi possível publicar um relatório novo. Confira o diretório e o suporte a links exclusivos.') from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        if (not args.epub or '\x00' in args.epub or
                (args.rootfile is not None and (not args.rootfile or '\x00' in args.rootfile))):
            raise _UsageError('O arquivo e a seleção de rootfile devem ser textos não vazios e válidos.')
        try:
            limits = AuditLimits(**{key: getattr(args, key) for key in asdict(AuditLimits())})
        except ValueError:
            raise _UsageError('Limite inválido. Consulte os valores permitidos na documentação.') from None
        report = audit_epub(args.epub, include_hrefs=args.include_hrefs,
                                  rootfile=args.rootfile, limits=limits)
        text = {'json': to_json, 'markdown': to_markdown}[args.format](report)
        if args.output is not None:
            _publish_new(args.output, text)
        else:
            try:
                sys.stdout.write(text)
                sys.stdout.flush()
            except (OSError, UnicodeError):
                # A buffered broken pipe must not be retried by interpreter
                # shutdown (which would otherwise replace exit3 with exit120).
                try:
                    fd = sys.stdout.fileno()
                    sink = os.open(os.devnull, os.O_WRONLY)
                    try:
                        os.dup2(sink, fd)
                    finally:
                        os.close(sink)
                except (OSError, ValueError, AttributeError):
                    pass
                raise AuditError('output_write', 'Não foi possível escrever o relatório na saída padrão.') from None
        return {'consistent': 0, 'invalid': 1, 'incomplete': 2}[report['status']]
    except _UsageError as error:
        print('Erro de uso: ' + str(error), file=sys.stderr)
        return 3
    except AuditError as error:
        print('Erro operacional (' + error.code + '): ' + str(error), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
