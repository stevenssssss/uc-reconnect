import importlib.util
import json
from pathlib import Path
import plistlib
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'runtime'))
import uc_reconnect as cli
from uc_config import validate_config

CONFIG = {'version': 1, 'target_id': 'ABCD1234', 'target_name': '工作 MacBook "Test"'}


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.layout = cli.Layout(self.root / 'home')
        self.built = self.root / 'built'
        app = self.built / cli.APP_NAME
        (app / 'Contents').mkdir(parents=True)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': cli.HELPER_ID}))
        (app / 'launcher-sentinel').write_text('stable launcher')
        (self.built / 'reconnect.scpt').write_text('test-only compiled script placeholder')

    def tearDown(self):
        self.temp.cleanup()

    def test_staging_never_calls_system_services(self):
        with patch('uc_reconnect.subprocess.run', side_effect=AssertionError('staging invoked a process')):
            cli.install(self.layout, CONFIG, self.built, staged=True)
        self.assertEqual(json.loads((self.layout.runtime / 'config.json').read_text()), CONFIG)
        self.assertEqual((self.layout.runtime / 'target-name.txt').read_text(), CONFIG['target_name'])
        for label in cli.LABELS:
            data = plistlib.loads(self.layout.plist(label).read_bytes())
            self.assertTrue(data['Disabled'])
            self.assertEqual(data['Label'], label)
            self.assertTrue(all(str(self.layout.home) in value or value in (sys.executable, '/bin/zsh') for value in data['ProgramArguments']))

    def test_update_preserves_launcher_and_invalidates_previous_target_state(self):
        cli.install(self.layout, CONFIG, self.built, staged=True)
        (self.layout.app / 'launcher-sentinel').write_text('existing permission identity')
        for name in ('universal-control-link.state', 'live-input.state', 'reconnect-result'):
            (self.layout.runtime / 'logs' / name).write_text('old target')
        new = dict(CONFIG, target_id='1234ABCD', target_name='Another Mac')
        cli.install(self.layout, new, self.built, staged=True)
        self.assertEqual((self.layout.app / 'launcher-sentinel').read_text(), 'existing permission identity')
        self.assertFalse((self.layout.runtime / 'logs/live-input.state').exists())
        self.assertEqual((self.layout.runtime / 'target-name.txt').read_text(), 'Another Mac')

    def test_real_install_disables_only_own_login_overrides_without_starting(self):
        with patch('uc_reconnect.loaded', return_value=False), patch('uc_reconnect.subprocess.run') as run:
            cli.install(self.layout, CONFIG, self.built)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[1], 'disable')
            self.assertTrue(any(args[-1].endswith('/' + label) for label in cli.LABELS))

    def test_uninstall_preserves_unrelated_files_and_defaults_to_keep_logs(self):
        cli.install(self.layout, CONFIG, self.built, staged=True)
        other = self.layout.agents / 'unrelated.plist'
        other.write_text('keep')
        cli.uninstall(self.layout, staged=True)
        self.assertFalse(self.layout.app.exists())
        self.assertTrue((self.layout.runtime / 'config.json').exists())
        self.assertEqual(other.read_text(), 'keep')
        cli.uninstall(self.layout, purge=True, staged=True)
        self.assertFalse(self.layout.runtime.exists())
        self.assertEqual(other.read_text(), 'keep')

    def test_unmanaged_directory_is_never_overwritten(self):
        self.layout.runtime.mkdir(parents=True)
        sentinel = self.layout.runtime / 'keep'
        sentinel.write_text('unmanaged')
        with self.assertRaises(ValueError):
            cli.install(self.layout, CONFIG, self.built, staged=True)
        with self.assertRaises(ValueError):
            cli.uninstall(self.layout, purge=True, staged=True)
        self.assertEqual(sentinel.read_text(), 'unmanaged')

    def test_symlink_is_rejected(self):
        self.layout.runtime.parent.mkdir(parents=True)
        destination = self.root / 'unrelated'
        destination.mkdir()
        self.layout.runtime.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(ValueError):
            cli.install(self.layout, CONFIG, self.built, staged=True)
        self.assertEqual(list(destination.iterdir()), [])

    def test_legacy_monitor_blocks_start_before_any_mutation(self):
        cli.install(self.layout, CONFIG, self.built, staged=True)
        with patch('uc_reconnect.loaded', side_effect=lambda name: name in cli.LEGACY_LABELS), patch('uc_reconnect.subprocess.run') as run:
            with self.assertRaises(ValueError):
                cli.start(self.layout)
            run.assert_not_called()

    def test_invalid_config_cannot_be_installed(self):
        invalid = [dict(CONFIG, target_id='$(touch /tmp/bad)'), dict(CONFIG, target_name='line\nbreak'),
                   dict(CONFIG, target_id='short'), dict(CONFIG, version=True), dict(CONFIG, extra='unused')]
        for value in invalid:
            with self.assertRaises(ValueError):
                cli.install(self.layout, value, self.built, staged=True)
        self.assertFalse(self.layout.runtime.exists())

    def test_failed_start_rolls_back_only_own_services(self):
        cli.install(self.layout, CONFIG, self.built, staged=True)
        calls = []
        def run(args, **kwargs):
            calls.append(args)
            if args[1] == 'bootstrap' and args[-1].endswith(cli.LABELS[1] + '.plist'):
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0)
        with patch('uc_reconnect.loaded', return_value=False), patch('uc_reconnect.subprocess.run', side_effect=run):
            with self.assertRaises(subprocess.CalledProcessError):
                cli.start(self.layout)
        self.assertEqual(sum(args[1] == 'bootout' for args in calls), 1)
        self.assertEqual(sum(args[1] == 'disable' for args in calls), 2)
        self.assertTrue(all(any(label in args[-1] for label in cli.LABELS) for args in calls))

    def test_shell_metacharacters_in_names_remain_data(self):
        name = 'Mac "quotes" $(echo ignored) & <work>'
        value = validate_config(dict(CONFIG, target_name=name, target_id='abcd1234'))
        cli.install(self.layout, value, self.built, staged=True)
        self.assertEqual((self.layout.runtime / 'target-name.txt').read_text(), name)
        self.assertEqual(value['target_id'], 'ABCD1234')


if __name__ == '__main__':
    unittest.main()
