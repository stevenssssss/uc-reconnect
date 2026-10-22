import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime"))
import os
import re
import subprocess
import tempfile

source = Path(__file__).resolve().parent.parent / 'runtime/universal-control-watchdog.zsh'
fixture = Path(__file__).parent / 'fixtures/input-failure.log'

with tempfile.TemporaryDirectory(prefix='uc-watchdog-test-') as tmp:
    root = Path(tmp)
    tools = root / 'bin'
    tools.mkdir()
    scripts = {
        'date': 'if [[ "$1" == "+%s" ]]; then echo "$TEST_NOW"; else exec /bin/date "$@"; fi',
        'log': '[[ "${TEST_LOG_FAIL:-0}" == 1 ]] && exit 1; if [[ "${TEST_LIVE_RECOVERY:-0}" == 1 ]]; then zmodload zsh/datetime; print "$EPOCHREALTIME connected $TEST_UC_PID" > "$HOME/Library/Application Support/UCReconnect/logs/live-input.state"; fi; cat "$TEST_LOG"',
        'ping': 'exit "$TEST_PING_EXIT"',
        'pgrep': '[[ "$TEST_UC_PID" == 0 ]] && exit 1; echo "$TEST_UC_PID"',
        'killall': 'echo "$*" >> "$TEST_KILLS"',
        'launchctl': 'exit 0',
        'sleep': 'exit 0',
        'open': 'echo connect >> "$TEST_CONNECTS"; echo "${TEST_RESULT:-connection-requested}" > "$HOME/Library/Application Support/UCReconnect/logs/reconnect-result"',
    }
    for name, body in scripts.items():
        path = tools / name
        path.write_text('#!/bin/zsh\n' + body + '\n')
        path.chmod(0o755)
    # Substitute only external effects; execute the complete production logic.
    text = source.read_text().replace('/usr/bin/log show', f'"{tools}/log" show')
    text = text.replace('/sbin/ping ', f'"{tools}/ping" ')
    text = text.replace("'/usr/bin/open'", repr(str(tools / 'open')))
    text = text.replace('/usr/bin/pgrep ', f'"{tools}/pgrep" ')
    text = text.replace('/usr/bin/killall ', f'"{tools}/killall" ')
    text = text.replace('/bin/launchctl ', f'"{tools}/launchctl" ')
    (root / 'Applications/UC Reconnect Helper.app').mkdir(parents=True)
    import shutil, json
    runtime = root / 'Library/Application Support/UCReconnect'
    runtime.mkdir(parents=True)
    shutil.copy2(source.parent / 'uc_config.py', runtime / 'uc_config.py')
    (runtime / 'python-path').write_text(sys.executable + '\n')
    (runtime / 'config.json').write_text(json.dumps({'version': 1, 'target_id': 'ABCD1234', 'target_name': 'Test Mac'}))
    script = root / 'watchdog.zsh'
    script.write_text(text)
    env = dict(os.environ, HOME=str(root), PATH=f'{tools}:' + os.environ['PATH'],
               TEST_CONNECTS=str(root / 'connects'), TEST_LOG=str(root / 'events'), TEST_KILLS=str(root / 'kills'),
               TEST_PING_EXIT='0', TEST_LOG_FAIL='0', TEST_UC_PID='100')
    state_file = root / 'Library/Application Support/UCReconnect/logs/universal-control-link.state'

    def tick(now, events='', online=True, fail=False, event=None, busy=False, preserve_pids=False, event_pid=None):
        env.update(TEST_NOW=str(now), TEST_PING_EXIT='0' if online else '1',
                   TEST_LOG_FAIL='1' if fail else '0')
        if not preserve_pids:
            events = re.sub(r'UniversalControl\[\d+:', 'UniversalControl[' + env['TEST_UC_PID'] + ':', events)
        Path(env['TEST_LOG']).write_text(events)
        args = (['--event', event] if event else []) + ([str(event_pid)] if event_pid else [])
        result = subprocess.run(['/bin/zsh', str(script)] + args, env=env, capture_output=True, text=True)
        assert result.returncode == (75 if busy else 1 if fail and event is None else 0), (result.returncode, result.stderr)
        assert not result.stderr, result.stderr
        return state_file.read_text().split()

    def kills():
        path = Path(env['TEST_KILLS'])
        return path.read_text().splitlines() if path.exists() else []

    connected = 'Connected Devices IDS: [ABCD1234]\nIDS ABCD1234: Connected\n'
    disconnected = 'IDS ABCD1234: Disconnected (connectionControllerUpdateConfiguredDevices)\n'
    def connects():
        path = Path(env['TEST_CONNECTS'])
        return len(path.read_text().splitlines()) if path.exists() else 0

    assert tick(1000, fixture.read_text() + connected)[1] == 'connected'
    assert connects() == 0 and kills() == []
    assert tick(1001, connected + disconnected)[1] == 'disconnected'
    assert connects() == 1, 'a newly detected disconnect must connect in the same tick'
    tick(1001)
    assert connects() == 1, 'do not overlap or hammer connection requests'
    tick(1004)
    assert connects() == 2
    tick(1007)
    assert connects() == 3 and kills() == ['-KILL UniversalControl']
    tick(1010, online=False)
    assert connects() == 4, 'ping failure must not block native UC discovery'
    tick(1012)
    assert connects() == 5, 'retry immediately when network returns'
    assert tick(1013, disconnected + connected)[1] == 'connected'
    tick(1014, 'AWDL enabled with no data connection, clink:0\nIDS OTHER: Disconnected\n')
    assert connects() == 5
    assert tick(1015, fail=True)[0] == '1014'

    env['TEST_RESULT'] = 'add-menu-not-found'
    tick(1016, disconnected)
    assert connects() == 6
    tick(1019)
    assert len(kills()) == 2, 'missing menu must restart on the next attempt, not the third'
    tick(1020, connected)
    before_kills = len(kills())
    env['TEST_RESULT'] = 'error:-25211'
    tick(1021, disconnected)
    for now in [1024, 1027, 1030]: tick(now)
    assert len(kills()) == before_kills, 'permission failures must not restart services'
    tick(1031, connected)
    env['TEST_RESULT'] = 'settings-in-use'
    tick(1032, disconnected)
    for now in [1035, 1038]: tick(now)
    assert len(kills()) == before_kills, 'do not restart while user is using Settings'
    tick(1039, connected)
    env['TEST_RESULT'] = 'connection-requested'
    before_connects = connects()
    tick(1040, disconnected)
    assert connects() == before_connects + 1, 'new disconnect must not inherit the last retry delay'
    lock = root / 'Library/Application Support/UCReconnect/watchdog.lock'
    before_state = state_file.read_text()
    holder = subprocess.Popen(['/bin/zsh', '-fc', 'zmodload zsh/system; zsystem flock -f fd "$1"; print locked; /bin/sleep 30', 'test-lock', str(lock)], stdout=subprocess.PIPE, text=True, start_new_session=True)
    assert holder.stdout.readline().strip() == 'locked'
    import signal
    try:
        tick(1043, busy=True)
        assert state_file.read_text() == before_state, 'another owner must exclude overlapping work'
    finally:
        os.killpg(holder.pid, signal.SIGKILL)
        holder.wait()
    tick(1044, connected)
    assert state_file.read_text().split()[0] == '1044', 'a killed owner must not leave a stale lock'
    before_connects = connects()
    tick(1100, connected)
    tick(1101, online=False, fail=True, event='disconnected')
    assert connects() == before_connects + 1, 'new live event must bypass log query and ping latency'
    assert tick(1102, fail=True, event='connected')[1] == 'connected'
    invalid = subprocess.run(['/bin/zsh', str(script), '--event', 'invalid'], env=env, capture_output=True)
    assert invalid.returncode == 2
    before_connects = connects()
    before_kills = len(kills())
    env['TEST_RESULT'] = 'already-selected'
    failure = Path(__file__).parent / 'fixtures/input-failure.log'
    assert tick(1200, failure.read_text())[1] == 'disconnected'
    assert connects() == before_connects + 1, 'synthetic failure must trigger despite missing CONN Disconnected'
    assert tick(1201, 'IDS ABCD1234: Connected\n')[1] == 'disconnected'
    assert len(kills()) == before_kills + 1, 'checked menu without input must reset UC on the next attempt'
    assert tick(1202, connected)[1] == 'connected'
    before_connects = connects()
    tick(1203, 'Excluded the following unavailable devices: [OTHER]\n')
    assert connects() == before_connects, 'unrelated unavailable peers must not trigger repair'
    tick(1204, 'Connected Devices IDS: []\nIDS ABCD1234: Connected\n')
    assert connects() == before_connects + 1, 'transport connection must not hide an empty input channel'
    tick(1205, connected)
    tick(1210, 'Connected Devices IDS: []\n')
    before_recovered_connects = connects()
    before_recovered_kills = len(kills())
    env['TEST_LIVE_RECOVERY'] = '1'
    assert tick(1211, 'Connected Devices IDS: []\n')[1] == 'connected'
    assert connects() == before_recovered_connects and len(kills()) == before_recovered_kills, 'fresh recovery must cancel a queued stale repair before reset or menu action'
    env['TEST_LIVE_RECOVERY'] = '0'
    before_connects = connects()
    env['TEST_UC_PID'] = '101'
    old_ready = 'UniversalControl[100:abcd] Connected Devices IDS: [ABCD1234]\n'
    assert tick(1299, fail=True)[5] == '100', 'failed log reads must not validate a new process generation'
    assert tick(1300, old_ready, preserve_pids=True)[1] == 'disconnected'
    assert connects() == before_connects + 1, 'a new UC process must not inherit an old healthy log'
    assert tick(1301, old_ready, event='connected', event_pid=100, preserve_pids=True)[1] == 'disconnected'
    assert tick(1302, event='connected', event_pid=101)[1] == 'connected'
    env['TEST_UC_PID'] = '0'
    assert tick(1303, event='connected', event_pid=101)[1] == 'disconnected', 'missing process must override queued old success'
    print('PASS: busy lock is retryable, ping failure does not block repair, PID generation isolation and absent-process recovery')
    print('PASS: synthetic silent failure replay, checked-but-unusable escalation, input-channel-only recovery, unrelated-peer immunity')
    print('PASS: immediate first attempt, 1s retry bound and event fast path, network return, early missing-menu recovery, stop on Connected, permission and foreground safety, latest event, failed-read cursor, auto-released lock')
