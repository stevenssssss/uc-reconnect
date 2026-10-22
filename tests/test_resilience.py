import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime"))
import importlib.util
import os
import signal
import subprocess
import tempfile
import time
import unittest

root = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('uc_events', root / 'runtime/watch_events.py')
events = importlib.util.module_from_spec(spec)
spec.loader.exec_module(events)


class ResilienceTest(unittest.TestCase):
    def test_helper_deadline_cancels_only_the_named_helper(self):
        source = (root / 'runtime/universal-control-watchdog.zsh').read_text()
        wrapper = source.split("<<'PY'", 1)[1].split('\n', 1)[1].split('\nPY\n', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            launch = base / 'open'
            launch.write_text('#!/bin/sh\nexec /bin/sleep 10\n')
            launch.chmod(0o755)
            cancel = base / 'pkill'
            cancel.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "' + str(base / 'cancel-args') + '"\n')
            cancel.chmod(0o755)
            wrapper = wrapper.replace("'/usr/bin/open'", repr(str(launch)))
            wrapper = wrapper.replace("'/usr/bin/pkill'", repr(str(cancel))).replace('timeout=20', 'timeout=0.15')
            run = base / 'wrapper.py'
            run.write_text(wrapper)
            started = time.monotonic()
            subprocess.run(['/usr/bin/python3', str(run), '/tmp/Only This Helper.app', str(base / 'result')], check=True)
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual((base / 'result').read_text().strip(), 'helper-timeout')
            pattern = (base / 'cancel-args').read_text()
            self.assertIn('Only\\ This\\ Helper', pattern)
            self.assertIn('Contents/MacOS/applet($| )', pattern)

    def test_worker_timeout_releases_process_group(self):
        child = subprocess.Popen(['/bin/sleep', '30'], start_new_session=True)
        try:
            events.stop_worker(child)
            self.assertIsNotNone(child.poll())
            self.assertLess(child.returncode, 0)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()

    def test_real_loop_busy_event_fallback_and_silent_process_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'logs').mkdir()
            state = base / 'logs/universal-control-link.state'
            state.write_text('0 connected 0 0 0 0\n')
            feed = base / 'feed'
            feed.touch()
            stream = base / 'fake-log'
            stream.write_text('#!/usr/bin/python3\nimport time\nf=open(' + repr(str(feed)) + ')\nwhile True:\n line=f.readline()\n if line: print(line,end="",flush=True)\n else: time.sleep(.01)\n')
            stream.chmod(0o755)
            worker = base / 'universal-control-watchdog.zsh'
            worker.write_text('''#!/bin/zsh
base=${0:h}
printf '%s\\n' "$*" >> "$base/calls"
if [[ "$2" == disconnected && -e "$base/busy" ]]; then
  rm "$base/busy"
  exit 75
fi
if [[ "$2" == disconnected ]]; then
  print '0 disconnected 0 0 1 0' > "$base/logs/universal-control-link.state"
elif [[ "$2" == connected ]]; then
  print '0 connected 0 0 0 0' > "$base/logs/universal-control-link.state"
fi
''')
            uc = subprocess.Popen(['/bin/sleep', '30'])
            finder = base / 'pgrep'
            finder.write_text('#!/bin/sh\n/bin/kill -0 ' + str(uc.pid) + ' 2>/dev/null || exit 1\necho ' + str(uc.pid) + '\n')
            finder.chmod(0o755)
            import json
            (base / 'config.json').write_text(json.dumps({'version': 1, 'target_id': 'ABCD1234', 'target_name': 'Test Mac'}))
            source = (root / 'runtime/watch_events.py').read_text()
            source = source.replace("BASE = runtime_dir()", 'BASE = Path(' + repr(str(base)) + ')')
            source = source.replace('from uc_config import', 'import sys\nsys.path.insert(0, ' + repr(str(root / 'runtime')) + ')\nfrom uc_config import')
            source = source.replace("'/usr/bin/log'", repr(str(stream))).replace("'/usr/bin/pgrep'", repr(str(finder)))
            daemonfile = base / 'daemon.py'
            daemonfile.write_text(source)
            out = open(base / 'output', 'w')
            daemon = subprocess.Popen(['/usr/bin/python3', str(daemonfile)], stdout=out, stderr=out)

            def await_condition(check, timeout=4):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    if check(): return
                    if daemon.poll() is not None:
                        self.fail((base / 'output').read_text())
                    time.sleep(.03)
                self.fail((base / 'output').read_text())

            def emit(message):
                with feed.open('a') as f:
                    f.write('UniversalControl[' + str(uc.pid) + ':ab] ' + message + '\n')

            try:
                await_condition(lambda: (base / 'calls').exists())
                (base / 'busy').touch()
                emit('Connected Devices IDS: []')
                await_condition(lambda: (base / 'calls').read_text().count('--event disconnected') >= 2)
                self.assertEqual(state.read_text().split()[1], 'disconnected')
                emit('Connected Devices IDS: [ABCD1234]')
                await_condition(lambda: state.read_text().split()[1] == 'connected')
                count = len((base / 'calls').read_text().splitlines())
                state.write_text('0 disconnected 0 0 1 0\n')
                await_condition(lambda: len((base / 'calls').read_text().splitlines()) > count)
                emit('Connected Devices IDS: [ABCD1234]')
                await_condition(lambda: state.read_text().split()[1] == 'connected')
                uc.terminate()
                uc.wait()
                await_condition(lambda: 'UC process changed' in (base / 'output').read_text())
                self.assertIsNone(daemon.poll())
            finally:
                daemon.terminate()
                daemon.wait(timeout=5)
                if uc.poll() is None:
                    uc.terminate()
                    uc.wait()
                out.close()


if __name__ == '__main__':
    unittest.main()
