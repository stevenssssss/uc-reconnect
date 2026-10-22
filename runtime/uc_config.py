"""Validated local configuration shared by the installer and monitor."""
import json
from pathlib import Path
import re
import sys


def runtime_dir(home=None):
    return (Path(home) if home is not None else Path.home()) / 'Library/Application Support/UCReconnect'


def validate_config(value):
    if not isinstance(value, dict) or set(value) != {'version', 'target_id', 'target_name'}:
        raise ValueError('Configuration must contain version, target_id and target_name only.')
    if type(value['version']) is not int or value['version'] != 1:
        raise ValueError('Unsupported configuration version.')
    target = value['target_id']
    name = value['target_name']
    if not isinstance(target, str) or not re.fullmatch(r'[0-9A-Fa-f]{8}', target):
        raise ValueError('Target ID must be the eight hexadecimal digits from UC input logs.')
    if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('Target name must be one nonempty line, at most 200 characters.')
    return {'version': 1, 'target_id': target.upper(), 'target_name': name}


def load_config(path):
    return validate_config(json.loads(Path(path).read_text(encoding='utf-8')))


if __name__ == '__main__':
    try:
        config = load_config(sys.argv[1])
        print(config['target_id'])
        print(config['target_name'])
    except (OSError, ValueError, IndexError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
