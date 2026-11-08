"""Compare original fixtures with external EPUBCheck and WHATWG URL behavior.

This development helper explicitly executes the supplied Java/Node tools. The
auditor itself never executes them, and this helper never accepts a user's book.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote, unquote_to_bytes

from epub_navigation_audit import audit_epub
from epub_navigation_audit.urls import resolve_reference
from make_samples import VARIANTS, write_sample


def compare_urls(node):
    cases = [
        ('EPUB/nav.xhtml', 'text/inicio.xhtml#inicio'),
        ('EPUB/nav.xhtml', './text/caf%C3%A9.xhtml#li%C3%A7%C3%A3o'),
        ('EPUB/nav.xhtml', 'text/cafe\u0301.xhtml#fim'),
        ('EPUB/sub/nav.xhtml', '../text/capitulo.xhtml'),
        ('EPUB/sub/nav.xhtml', '%2E%2e/text/capitulo.xhtml'),
        ('EPUB/sub/nav.xhtml', '.%2e/text/capitulo.xhtml'),
        ('EPUB/sub/nav.xhtml', '%2e./text/capitulo.xhtml'),
        ('EPUB/sub/nav.xhtml', 'text/%2e/segundo.xhtml'),
        ('EPUB/nav.xhtml', '#sumario'), ('EPUB/nav.xhtml', '#'),
        ('EPUB/nav.xhtml', ''), ('EPUB/nav.xhtml', 'text/100%25.xhtml'),
        ('EPUB/100%pronto/nav.xhtml', 'capitulo.xhtml'),
        ('EPUB/nav.xhtml', 'text/um espaço.xhtml#seção'),
        ('EPUB/nav.xhtml', 'text/a.xhtml?token#frag'),
        ('EPUB/nav.xhtml', 'https://example.invalid/a?token=value'),
        ('EPUB/nav.xhtml', 'text/a%2Fb.xhtml'),
        ('EPUB/nav.xhtml', 'file:///private/document'),
    ]
    script = ("let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',d=>s+=d);"
              "process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(x=>{"
              "const u=new URL(x.reference,new URL(x.base,'https://publication.invalid/'));"
              "return {pathname:u.pathname,hash:u.hash};}))));")
    payload = [{'base': quote(base, safe='/'), 'reference': ref} for base, ref in cases]
    result = subprocess.run([node, '-e', script], input=json.dumps(payload), text=True, capture_output=True, check=True, timeout=30)
    independent = json.loads(result.stdout)
    accepted = 0
    for (base, reference), target in zip(cases, independent):
        actual = resolve_reference(base, reference)
        if actual['kind'] != 'local':
            continue
        expected_path = unquote_to_bytes(target['pathname'].removeprefix('/')).decode('utf-8')
        expected_fragment = unquote_to_bytes(target['hash'].removeprefix('#')).decode('utf-8') if '#' in reference else None
        assert (actual['path'], actual['fragment']) == (expected_path, expected_fragment), (base, reference, actual, target)
        accepted += 1
    assert accepted == 14, accepted
    return {'cases': len(cases), 'acceptedLocalCompared': accepted, 'outsideLocalProfile': len(cases) - accepted}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Confronta fixtures próprias com EPUBCheck 5.3.0 e Node URL, somente em desenvolvimento.')
    parser.add_argument('--jar', type=Path, required=True)
    parser.add_argument('--java', default='java')
    parser.add_argument('--node', default='node')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    jar = args.jar.resolve(strict=True)
    expected_java = {name: (1 if name in {'fragmento-ausente', 'arquivo-ausente', 'id-duplicado', 'mimetype-incorreto', 'fora-spine'} else 0) for name in VARIANTS}
    expected_profile = {name: ('invalid' if expected_java[name] else 'incomplete' if name in {'doctype', 'multiplas-rendicoes'} else 'consistent') for name in VARIANTS}
    results = []
    with tempfile.TemporaryDirectory(prefix='epub-navigation-oracle-') as temporary:
        directory = Path(temporary)
        for name in VARIANTS:
            candidate = directory / (name + '.epub'); write_sample(candidate, name)
            destination = directory / (name + '.json')
            result = subprocess.run([args.java, '-Xmx256m', '-jar', str(jar), str(candidate), '--json', str(destination)], capture_output=True, text=True, timeout=60)
            oracle = json.loads(destination.read_text(encoding='utf-8'))
            checker = oracle['checker']
            assert checker['checkerVersion'] == '5.3.0', checker['checkerVersion']
            assert result.returncode == expected_java[name], (name, result.returncode, result.stderr)
            profile = audit_epub(candidate)
            assert profile['status'] == expected_profile[name], (name, profile)
            results.append({'sample': name, 'epubcheckExit': result.returncode,
                            'fatals': checker['nFatal'], 'errors': checker['nError'], 'warnings': checker['nWarning'],
                            'epubcheckCodes': [message.get('ID', message.get('id')) for message in oracle['messages']],
                            'profileStatus': profile['status'], 'profileComplete': profile['complete'],
                            'profileCodes': [issue['code'] for issue in profile['issues']]})
            print(name + ': EPUBCheck=' + str(result.returncode) + ', perfil=' + profile['status'], flush=True)
        selected = audit_epub(directory / 'multiplas-rendicoes.epub', rootfile='EPUB/package.opf')
        assert selected['status'] == 'consistent' and selected['complete']
    report = {'epubcheckVersion': '5.3.0', 'epubBasis': 'EPUB 3.3', 'samples': results,
              'explicitRenditionSelection': True, 'urlOracle': compare_urls(args.node)}
    if args.output:
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(report, ensure_ascii=True, indent=2) + '\n')
    print(json.dumps({'epubcheckCases': len(results), 'urlOracle': report['urlOracle'], 'status': 'pass'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
