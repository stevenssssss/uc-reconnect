#!/usr/bin/env python3
"""Create a source archive from an explicit allowlist, excluding local configuration."""
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent
TOP_FILES = ('README.md', 'README.zh-CN.md', 'LICENSE', 'NOTICE.md', 'CHANGELOG.md',
             'CONTRIBUTING.md', 'PRIVACY.md', '.gitignore', 'config.example.json')
SOURCE_DIRS = ('runtime', 'helper', 'scripts', 'tests', 'docs', '.github')
SUFFIXES = {'.py', '.zsh', '.applescript', '.md', '.yml', '.json', '.log'}


def source_files():
    paths = [ROOT / name for name in TOP_FILES]
    for directory in SOURCE_DIRS:
        paths.extend(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and p.suffix in SUFFIXES and '__pycache__' not in p.parts)
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError('Source package cannot contain symlinks.')
        if not path.is_file():
            raise ValueError('Missing release file ' + path.name)
        if path.name.endswith('.local.json') or (path.suffix == '.log' and path.parent != ROOT / 'tests/fixtures'):
            raise ValueError('Local configuration or runtime log found in release inputs.')
        yield path


def privacy_check(paths):
    # Conservative checks complement review. No scan can identify every secret.
    patterns = [r'/' + r'Users/[^/\s]+/', r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
                r'\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b',
                r'\bgh[pousr]_[A-Za-z0-9]{20,}\b', r'-----BEGIN ' + r'(?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    for path in paths:
        text = path.read_text(encoding='utf-8')
        if any(re.search(pattern, text) for pattern in patterns):
            raise ValueError('Possible personal data or secret in ' + str(path.relative_to(ROOT)))


def main():
    paths = list(source_files())
    privacy_check(paths)
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    archive = dist / 'uc-reconnect-0.1.0-source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            entry = zipfile.ZipInfo('uc-reconnect/' + path.relative_to(ROOT).as_posix(), (2000, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, path.read_bytes())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / 'SHA256SUMS').write_text(digest + '  ' + archive.name + '\n')
    print(archive)
    print(str(len(paths)) + ' source files packaged; build output and local configuration excluded.')


if __name__ == '__main__':
    main()
