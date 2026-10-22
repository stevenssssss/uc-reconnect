#!/usr/bin/env python3
"""Configure, stage, install and manage UC Reconnect for the current user."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'runtime'))
from uc_config import load_config, runtime_dir, validate_config
from build import APP_NAME, HELPER_ID, VERSION, build

LABELS = ('org.uc-reconnect.events', 'org.uc-reconnect.watchdog')
LEGACY_LABELS = ('com.local.universal-control-events', 'com.local.universal-control-watchdog')
MARKER = 'uc-reconnect-install.json'


class Layout:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.runtime = runtime_dir(self.home)
        self.app = self.home / 'Applications' / APP_NAME
        self.agents = self.home / 'Library/LaunchAgents'

    def plist(self, label):
        return self.agents / (label + '.plist')


def safe_path(path):
    # Never let an install or uninstall traverse a symlink into another app's data.
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('Refusing a symlink in managed path ' + str(item))


def loaded(label):
    return subprocess.run(['/bin/launchctl', 'print', f'gui/{os.getuid()}/{label}'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def ensure_no_conflict():
    for label in LEGACY_LABELS:
        if loaded(label):
            raise ValueError('An existing Universal Control monitor is active. Leave it running or stop it yourself before enabling this version. No changes were made to it.')


def verify_managed(layout):
    safe_path(layout.runtime)
    marker = layout.runtime / MARKER
    if not marker.is_file() or json.loads(marker.read_text()).get('project') != 'uc-reconnect':
        raise ValueError('This directory is not a managed UC Reconnect installation.')


def assert_stopped():
    if any(loaded(label) for label in LABELS):
        raise ValueError('Run stop before updating or uninstalling this installation.')


def install(layout, config, built, staged=False):
    config = validate_config(config)
    for path in (layout.runtime, layout.app, layout.agents):
        safe_path(path)
    if layout.runtime.exists():
        verify_managed(layout)
    for name in ('config.json', 'target-name.txt', 'python-path', MARKER, 'reconnect.scpt', 'logs'):
        safe_path(layout.runtime / name)
    for label in LABELS:
        safe_path(layout.plist(label))
    if not staged:
        assert_stopped()
    for label in LABELS:
        if layout.plist(label).exists() and not (layout.runtime / MARKER).exists():
            raise ValueError('Refusing to overwrite an unmanaged LaunchAgent.')
    if layout.app.exists():
        info = plistlib.loads((layout.app / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != HELPER_ID or not (layout.runtime / MARKER).exists():
            raise ValueError('Refusing to replace an unmanaged helper app.')
    layout.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(layout.runtime, 0o700)
    (layout.runtime / 'logs').mkdir(exist_ok=True, mode=0o700)
    layout.agents.mkdir(parents=True, exist_ok=True)
    layout.app.parent.mkdir(parents=True, exist_ok=True)
    # Preserve the fixed launcher on updates so existing TCC grants can remain valid.
    if not layout.app.exists():
        shutil.copytree(built / APP_NAME, layout.app)
    for source in (ROOT / 'runtime').iterdir():
        if source.suffix in ('.py', '.zsh'):
            shutil.copy2(source, layout.runtime / source.name)
    shutil.copy2(built / 'reconnect.scpt', layout.runtime / 'reconnect.scpt')
    (layout.runtime / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    os.chmod(layout.runtime / 'config.json', 0o600)
    (layout.runtime / 'target-name.txt').write_text(config['target_name'], encoding='utf-8')
    (layout.runtime / 'python-path').write_text(sys.executable + '\n')
    (layout.runtime / MARKER).write_text(json.dumps({'project': 'uc-reconnect', 'version': VERSION}) + '\n')
    # Reconfiguration must not inherit an old target's healthy state or pending action.
    for name in ('universal-control-link.state', 'live-input.state', 'reconnect-result'):
        (layout.runtime / 'logs' / name).unlink(missing_ok=True)
    for label in LABELS:
        is_events = label == LABELS[0]
        arguments = [sys.executable, str(layout.runtime / 'watch_events.py')] if is_events else ['/bin/zsh', str(layout.runtime / 'universal-control-watchdog.zsh')]
        plist = {'Label': label, 'ProgramArguments': arguments, 'Disabled': True,
                 'StandardOutPath': str(layout.runtime / 'logs' / (label + '.stdout.log')),
                 'StandardErrorPath': str(layout.runtime / 'logs' / (label + '.stderr.log')),
                 'Umask': 0o077, 'ThrottleInterval': 2 if is_events else 1}
        if is_events:
            plist.update(RunAtLoad=True, KeepAlive=True)
        else:
            plist['StartInterval'] = 30
        layout.plist(label).write_bytes(plistlib.dumps(plist))
    if not staged:
        # A prior launchctl enable override takes precedence over Disabled in a plist.
        for label in LABELS:
            subprocess.run(['/bin/launchctl', 'disable', f'gui/{os.getuid()}/{label}'], check=True)


def start(layout):
    verify_managed(layout)
    load_config(layout.runtime / 'config.json')
    ensure_no_conflict()
    assert_stopped()
    started = []
    enabled = []
    try:
        for label in LABELS:
            subprocess.run(['/bin/launchctl', 'enable', f'gui/{os.getuid()}/{label}'], check=True)
            enabled.append(label)
            subprocess.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(layout.plist(label))], check=True)
            started.append(label)
    except subprocess.CalledProcessError:
        for label in started:
            subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{label}'])
        for label in enabled:
            subprocess.run(['/bin/launchctl', 'disable', f'gui/{os.getuid()}/{label}'])
        raise


def stop(layout):
    verify_managed(layout)
    for label in LABELS:
        subprocess.run(['/bin/launchctl', 'disable', f'gui/{os.getuid()}/{label}'], check=True)
        if loaded(label):
            subprocess.run(['/bin/launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], check=True)


def uninstall(layout, purge=False, staged=False):
    verify_managed(layout)
    for path in (layout.app, layout.agents):
        safe_path(path)
    if not staged:
        assert_stopped()
    if layout.app.exists():
        info = plistlib.loads((layout.app / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != HELPER_ID:
            raise ValueError('Refusing to remove a different helper app.')
    for label in LABELS:
        layout.plist(label).unlink(missing_ok=True)
    if layout.app.exists():
        shutil.rmtree(layout.app)
    if purge:
        shutil.rmtree(layout.runtime)


def discover():
    output = subprocess.run(['/usr/bin/log', 'show', '--last', '20m', '--style', 'compact',
                             '--predicate', 'process == "UniversalControl" AND category == "EVNT" AND eventMessage CONTAINS "Connected Devices IDS:"'],
                            check=True, capture_output=True, text=True, timeout=30).stdout
    ids = set()
    for match in re.finditer(r'Connected Devices IDS: \[([^\]]*)\]', output):
        ids.update(re.findall(r'\b[0-9A-F]{8}\b', match[1]))
    if not ids:
        print('No peer IDs found. Connect your intended Mac once through Displays, then run discover again.')
    else:
        print('Recent input peer IDs. These are candidates, not a verified name mapping.')
        print('\n'.join(sorted(ids)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    config_parser = sub.add_parser('configure')
    config_parser.add_argument('--target-name')
    config_parser.add_argument('--target-id')
    config_parser.add_argument('--output', type=Path, default=ROOT / 'config.local.json')
    sub.add_parser('discover')
    installer = sub.add_parser('install')
    installer.add_argument('--config', type=Path, default=ROOT / 'config.local.json')
    installer.add_argument('--stage', type=Path, help='Prepare an isolated home directory without loading any LaunchAgents.')
    installer.add_argument('--build-dir', type=Path)
    remover = sub.add_parser('uninstall')
    remover.add_argument('--purge', action='store_true', help='Also remove this installation\'s saved configuration and logs.')
    remover.add_argument('--stage', type=Path)
    for name in ('start', 'stop', 'status', 'permissions'):
        sub.add_parser(name)
    args = parser.parse_args()
    if args.command == 'configure':
        value = validate_config({'version': 1, 'target_name': args.target_name or input('Exact name in the UC keyboard/mouse menu / 菜单中的设备名称\n'),
                                 'target_id': args.target_id or input('Peer ID from discover / discover 查到的设备 ID\n')})
        if args.output.exists():
            raise ValueError('Configuration output exists. Choose a new --output path to avoid overwriting it.')
        args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.chmod(args.output, 0o600)
        print('Configuration saved. Nothing has been installed or started.')
        return
    if args.command == 'discover':
        discover()
        return
    stage = getattr(args, 'stage', None)
    if stage is not None and stage.resolve() == Path.home().resolve():
        raise ValueError('A staging home must differ from the real home directory.')
    layout = Layout(stage or Path.home())
    if args.command == 'install':
        config = load_config(args.config)
        if args.build_dir:
            install(layout, config, args.build_dir.resolve(), staged=stage is not None)
        else:
            with tempfile.TemporaryDirectory(prefix='uc-reconnect-build-') as tmp:
                built = build(Path(tmp) / 'bundle')
                install(layout, config, built, staged=stage is not None)
        print('Files prepared. Monitoring has not been started. Grant helper permissions, then run start.')
    elif args.command == 'uninstall':
        uninstall(layout, purge=args.purge, staged=stage is not None)
        print('Removed this project\'s helper and LaunchAgents. Configuration and logs ' + ('removed.' if args.purge else 'retained.'))
    elif args.command == 'start':
        start(layout)
        print('Monitoring started for this user. It will also start at login.')
    elif args.command == 'stop':
        stop(layout)
        print('Monitoring stopped and disabled at login. Run start to enable it again.')
    elif args.command == 'permissions':
        verify_managed(layout)
        ensure_no_conflict()
        print('Opening the helper. It may request Accessibility and Automation access and attempt to select the configured Mac.')
        subprocess.run(['/usr/bin/open', '-g', str(layout.app)], check=True)
    elif args.command == 'status':
        verify_managed(layout)
        for label in LABELS:
            print(label + ' ' + ('loaded' if loaded(label) else 'stopped'))
        state = layout.runtime / 'logs/universal-control-link.state'
        print('Saved input state ' + (state.read_text().split()[1] if state.exists() else 'unknown'))
        result = layout.runtime / 'logs/reconnect-result'
        if result.exists():
            print('Last helper result ' + result.read_text().strip())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
