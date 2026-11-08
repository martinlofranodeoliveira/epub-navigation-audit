"""Check repository distribution inputs, without scanning user directories."""
from pathlib import Path
import json
import re


def main():
    root = Path(__file__).resolve().parents[1]
    ignored = {'.git', '.venv', '__pycache__', 'dist', 'build', '.samples', '.pytest_cache', '.tools'}
    files = []
    problems = []
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(part in ignored or part.endswith('.egg-info') for part in relative.parts):
            continue
        if path.is_symlink():
            problems.append({'file': relative.as_posix(), 'code': 'symlink'})
            continue
        if not path.is_file():
            continue
        if path.name == '.env' or path.name.startswith('.env.') or path.suffix in {'.pem', '.key', '.sqlite', '.db', '.whl', '.epub', '.jar'}:
            problems.append({'file': relative.as_posix(), 'code': 'operational_file'})
        files.append(path)
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
        if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text):
            problems.append({'file': relative.as_posix(), 'code': 'credential_shape'})
        if path.suffix == '.md':
            for href in re.findall(r'\]\(([^)]+)\)', text):
                if '://' in href or href.startswith(('#', 'mailto:')):
                    continue
                target = href.split('#', 1)[0]
                if target and not (path.parent / target).exists():
                    problems.append({'file': relative.as_posix(), 'code': 'missing_local_link'})
    print(json.dumps({'publicFiles': len(files), 'problems': problems}, ensure_ascii=True))
    return int(bool(problems))


if __name__ == '__main__':
    raise SystemExit(main())
