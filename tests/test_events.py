import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runtime"))
import importlib.util
import unittest

spec = importlib.util.spec_from_file_location('events', Path(__file__).resolve().parent.parent / 'runtime/watch_events.py')
events = importlib.util.module_from_spec(spec)
spec.loader.exec_module(events)

def parse_event(line):
    return events.event_state(line, "ABCD1234")


class EventsTest(unittest.TestCase):
    def test_busy_worker_preserves_disconnect_and_retries(self):
        schedule = events.ReconnectSchedule()
        schedule.completed('connected', 100)
        schedule.observe('disconnected')
        job = schedule.next_job(101)
        schedule.completed('connected', 102, returncode=75, job=job)
        self.assertEqual(schedule.state, 'disconnected')
        self.assertIsNone(schedule.next_job(102.5))
        self.assertEqual(schedule.next_job(103), ['--event', 'disconnected'])

    def test_failed_log_read_retries_even_when_saved_connected(self):
        schedule = events.ReconnectSchedule()
        schedule.completed('connected', 100, returncode=1, job=[])
        self.assertEqual(schedule.next_job(101), [])

    def test_newer_event_wins_over_failed_old_worker(self):
        schedule = events.ReconnectSchedule()
        schedule.observe('disconnected')
        job = schedule.next_job(100)
        schedule.observe('connected')
        schedule.completed('disconnected', 101, returncode=75, job=job)
        self.assertEqual(schedule.next_job(101), ['--event', 'connected'])

    def test_only_real_target_states(self):
        for text in ['IDS OTHER: Disconnected', 'AWDL no data connection',
                     'IDS ABCD1234: Connecting', 'IDS ABCD1234: ConnectedElsewhere']:
            self.assertIsNone(parse_event(text))
        self.assertEqual(parse_event('IDS ABCD1234: Disconnected (reason)'), 'disconnected')
        self.assertIsNone(parse_event('IDS ABCD1234: Connected'))
        self.assertIsNone(parse_event('IDS ABCD1234: Accepting (Connected)'))
        self.assertEqual(parse_event('Connected Devices IDS: [ABCD1234]'), 'connected')

    def test_input_health_and_target_boundaries(self):
        self.assertEqual(parse_event('Connected Devices IDS: []'), 'disconnected')
        self.assertEqual(parse_event('Connected Devices IDS: [OTHER, ABCD1234]'), 'connected')
        self.assertEqual(parse_event('Connected Devices IDS: [ABCD1234A]'), 'disconnected')
        self.assertEqual(parse_event('Excluded the following unavailable devices: [ABCD1234]'), 'disconnected')
        self.assertIsNone(parse_event('Excluded the following unavailable devices: [OTHER]'))

    def test_synthetic_failure_replay_does_not_accept_transport_as_recovery(self):
        schedule = events.ReconnectSchedule()
        schedule.completed('connected', 100)
        fixture = Path(__file__).parent / 'fixtures/input-failure.log'
        for line in fixture.read_text().splitlines():
            state = parse_event(line)
            if state is not None:
                schedule.observe(state)
        self.assertEqual(schedule.state, 'disconnected')
        self.assertEqual(schedule.next_job(101), ['--event', 'disconnected'])
        self.assertIsNone(parse_event('IDS ABCD1234: Connected'))
        schedule.observe(parse_event('Connected Devices IDS: [ABCD1234]'))
        self.assertEqual(schedule.next_job(102), ['--event', 'connected'])

    def test_immediate_trigger_no_idle_polling(self):
        schedule = events.ReconnectSchedule()
        schedule.completed('connected', 100)
        self.assertIsNone(schedule.next_job(100000))
        schedule.observe('disconnected')
        self.assertEqual(schedule.next_job(101), ['--event', 'disconnected'])
        self.assertIsNone(schedule.next_job(101))
        schedule.observe('disconnected')
        self.assertIsNone(schedule.next_job(101))

    def test_latest_state_during_worker_wins(self):
        schedule = events.ReconnectSchedule()
        schedule.observe('disconnected')
        schedule.next_job(100)
        schedule.observe('connected')
        schedule.completed('disconnected', 101)
        self.assertEqual(schedule.next_job(101), ['--event', 'connected'])
        schedule.completed('connected', 102)
        self.assertIsNone(schedule.next_job(200))

    def test_failed_attempt_reconciles_before_retry(self):
        schedule = events.ReconnectSchedule()
        schedule.completed('disconnected', 100)
        self.assertIsNone(schedule.next_job(100.5))
        self.assertEqual(schedule.next_job(101), [])
        self.assertIsNone(schedule.next_job(101))

    def test_transient_disconnect_coalesces(self):
        schedule = events.ReconnectSchedule()
        schedule.completed('connected', 100)
        schedule.observe('disconnected')
        schedule.observe('connected')
        self.assertEqual(schedule.next_job(100), ['--event', 'connected'])


if __name__ == '__main__':
    unittest.main()
