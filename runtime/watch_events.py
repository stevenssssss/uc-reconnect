#!/usr/bin/python3
"""Wake the existing reconnect worker on target-specific UC state changes."""
import fcntl
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time

from uc_config import runtime_dir, load_config

BASE = runtime_dir()
INPUT_PATTERN = re.compile(r'Connected Devices IDS: \[([^\]]*)\]')
UNAVAILABLE_PATTERN = re.compile(r'Excluded the following unavailable devices: \[([^\]]*)\]')
PID_PATTERN = re.compile(r'UniversalControl\[(\d+):')


def event_state(line, target):
    match = INPUT_PATTERN.search(line)
    if match:
        devices = {item.strip() for item in match[1].split(',')}
        return 'connected' if target in devices else 'disconnected'
    match = UNAVAILABLE_PATTERN.search(line)
    if match and target in {item.strip() for item in match[1].split(',')}:
        return 'disconnected'
    if re.search(r'IDS ' + re.escape(target) + r': Disconnected(?=\s|$)', line) or f'Disconnected {target}, update connections:' in line:
        return 'disconnected'
    # A CONN Connected event alone can coexist with an empty input channel.
    return None


class ReconnectSchedule:
    def __init__(self):
        self.state = None
        self.pending = None
        self.retry_at = None
        self.retry_job = []
        self.pid = None
        self.pending_pid = None

    def observe(self, state, pid=None):
        if state != self.state or (pid is not None and pid != self.pid):
            self.state = state
            self.pid = pid
            self.pending = state
            self.pending_pid = pid
            self.retry_at = None

    def completed(self, saved_state, now, returncode=0, job=None):
        if returncode != 0:
            # Busy locks, failed reads and timed-out workers must not erase an event.
            if self.pending is None:
                self.retry_job = job or []
                self.retry_at = now + 1
            return
        if self.pending is None:
            self.state = saved_state
        self.retry_job = []
        self.retry_at = now + 1 if self.state == 'disconnected' else None

    def reconcile(self, now):
        if self.pending is None:
            self.retry_job = []
            self.retry_at = now

    def next_job(self, now):
        if self.pending is not None:
            state, self.pending = self.pending, None
            self.retry_at = None
            return ['--event', state] + ([str(self.pending_pid)] if self.pending_pid else [])
        if self.retry_at is not None and now >= self.retry_at:
            self.retry_at = None
            return self.retry_job
        return None


def find_uc_pid():
    result = subprocess.run(['/usr/bin/pgrep', '-u', str(os.getuid()), '-x', 'UniversalControl'],
                            capture_output=True, text=True, timeout=2)
    return int(result.stdout.split()[0]) if result.returncode == 0 else None


def process_alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def stop_worker(worker):
    # The worker owns a process group, including its log/open subprocesses.
    try:
        os.killpg(worker.pid, signal.SIGTERM)
        worker.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(worker.pid, signal.SIGKILL)
        worker.wait()
    except ProcessLookupError:
        pass


def main():
    target = load_config(BASE / 'config.json')['target_id']
    (BASE / 'logs').mkdir(parents=True, exist_ok=True)
    lock = open(BASE / 'events.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    predicate = (f'process == "UniversalControl" AND ('
                 f'(category == "CONN" AND eventMessage CONTAINS "{target}" AND eventMessage CONTAINS "Disconnected") OR '
                 '(category == "EVNT" AND eventMessage CONTAINS "Connected Devices IDS:") OR '
                 f'(category == "CIRC" AND eventMessage CONTAINS "Excluded the following unavailable devices:" AND eventMessage CONTAINS "{target}"))')
    stream = subprocess.Popen(['/usr/bin/log', 'stream', '--style', 'compact',
                               '--predicate', predicate], stdout=subprocess.PIPE)
    selector = selectors.DefaultSelector()
    selector.register(stream.stdout, selectors.EVENT_READ)
    schedule = ReconnectSchedule()
    worker = None
    buffer = b''

    def start_worker(args):
        print(f'{time.time():.6f} worker-start {args or ["reconcile"]}', flush=True)
        return subprocess.Popen(['/bin/zsh', str(BASE / 'universal-control-watchdog.zsh'), *args],
                                start_new_session=True)

    def saved_state():
        try:
            return (BASE / 'logs/universal-control-link.state').read_text().split()[1]
        except (OSError, IndexError):
            return None

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    uc_pid = find_uc_pid()
    health_at = time.monotonic() + 1
    worker_job = []
    worker_started = time.monotonic()
    worker = start_worker([])
    try:
        while True:
            now = time.monotonic()
            if worker is not None and worker.poll() is None and now - worker_started >= 45:
                print(f'{time.time():.6f} worker-timeout; retrying', flush=True)
                stop_worker(worker)
            if worker is not None and worker.poll() is not None:
                schedule.completed(saved_state(), now, worker.returncode, worker_job)
                worker = None
            if now >= health_at:
                health_at = now + 1
                if not process_alive(uc_pid):
                    uc_pid = find_uc_pid()
                    print(f'{time.time():.6f} UC process changed; reconcile pid={uc_pid}', flush=True)
                    schedule.reconcile(now)
                if worker is None and schedule.pending is None and schedule.retry_at is None:
                    persisted = saved_state()
                    if persisted in ('connected', 'disconnected'):
                        schedule.observe(persisted)
                    else:
                        schedule.reconcile(now)
            if worker is None:
                job = schedule.next_job(now)
                if job is not None:
                    worker_job = job
                    worker_started = now
                    worker = start_worker(job)
            # A tiny process/state check catches silent exits and fallback repairs.
            timeout = max(0, health_at - time.monotonic())
            if worker is not None:
                timeout = min(timeout, 0.1)
            if worker is None and schedule.retry_at is not None:
                timeout = min(timeout, max(0, schedule.retry_at - time.monotonic()))
            for key, _mask in selector.select(timeout):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    raise RuntimeError('UniversalControl log stream ended')
                buffer += chunk
                lines = buffer.split(b'\n')
                buffer = lines.pop()
                for raw in lines:
                    line = raw.decode('utf-8', errors='replace')
                    state = event_state(line, target)
                    pid_match = PID_PATTERN.search(line)
                    pid = int(pid_match[1]) if pid_match else None
                    if state is not None and (state != schedule.state or pid != schedule.pid):
                        live = BASE / 'logs/live-input.state'
                        temporary = live.with_suffix('.tmp')
                        temporary.write_text(f'{time.time():.6f} {state} {pid or 0}\n')
                        temporary.replace(live)
                        print(f'{time.time():.6f} observed {line}', flush=True)
                        schedule.observe(state, pid)
    finally:
        if worker is not None and worker.poll() is None:
            stop_worker(worker)
        stream.terminate()
        stream.wait(timeout=5)
        selector.close()
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
