"""Exercise the wheel in a new environment outside the source tree."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def main(argv=None):
    parser = argparse.ArgumentParser(description='Confere a distribuição instalada fora dos fontes.')
    parser.add_argument('--wheel', type=Path, required=True)
    args = parser.parse_args(argv)
    wheel = args.wheel.resolve(strict=True)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='epub-navigation-installed-') as temporary:
        work = Path(temporary); environment = work / 'environment'
        venv.EnvBuilder(with_pip=True).create(environment)
        binaries = environment / ('Scripts' if os.name == 'nt' else 'bin')
        python = binaries / ('python.exe' if os.name == 'nt' else 'python')
        entry = binaries / ('epub-navigation-audit.exe' if os.name == 'nt' else 'epub-navigation-audit')
        subprocess.run([str(python), '-I', '-m', 'pip', 'install', '--disable-pip-version-check', str(wheel)], cwd=work, check=True)
        samples = work / 'samples'
        subprocess.run([sys.executable, str(root / 'scripts/make_samples.py'), '--directory', str(samples)], cwd=work, check=True)
        expected = {'valido': 0, 'fragmento-ausente': 1, 'arquivo-ausente': 1, 'id-duplicado': 1,
                    'mimetype-incorreto': 1, 'fora-spine': 1, 'doctype': 2, 'ordem-diferente': 0,
                    'svg': 0, 'multiplas-rendicoes': 2, 'unicode-decomposto': 0, 'normalizacao-divergente': 0}
        for name, exit_code in expected.items():
            result = subprocess.run([str(python), '-I', '-m', 'epub_navigation_audit', str(samples / (name + '.epub'))], cwd=work, text=True, capture_output=True)
            assert result.returncode == exit_code, (name, result.returncode, result.stderr, result.stdout)
            report = json.loads(result.stdout)
            assert report['status'] == {0: 'consistent', 1: 'invalid', 2: 'incomplete'}[exit_code]
            assert 'Guia fict' not in result.stdout and 'Introdu' not in result.stdout
        selected = subprocess.run([str(entry), str(samples / 'multiplas-rendicoes.epub'), '--rootfile', 'EPUB/package.opf'], cwd=work, text=True, capture_output=True, check=True)
        assert json.loads(selected.stdout)['package']['path'] == 'EPUB/package.opf'
        partial = subprocess.run([str(entry), str(samples / 'valido.epub'), '--max-xml-nodes', '1'], cwd=work, text=True, capture_output=True)
        assert partial.returncode == 2 and json.loads(partial.stdout)['complete'] is False
        version = subprocess.check_output([str(entry), '--version'], cwd=work, text=True).strip()
        assert version == 'epub-navigation-audit 1.0.0'
        location = subprocess.check_output([str(python), '-I', '-c', 'import epub_navigation_audit; print(epub_navigation_audit.__file__)'], cwd=work, text=True).strip()
        assert Path(location).is_relative_to(environment)
        print(json.dumps({'installedDistribution': True, 'outsideSourceTree': True,
                          'syntheticCases': len(expected), 'selectedRendition': True,
                          'boundedPartial': True, 'entryPoint': True}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
