# SPDX-License-Identifier: MIT
import env  # noqa: F401  (paths and sys.path first)
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import data_network
from data_network import Resolver, configuration, counters, guarded, looks_silent

class ResolverTests(unittest.TestCase):
    def test_fallback_restoration_preserves_new_wifi_dns(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'resolv'; p.write_text('wifi original\n'); r=Resolver(p)
            r.update(True,['192.0.2.53']); self.assertIn('192.0.2.53',p.read_text())
            r.update(False,[]); self.assertEqual(p.read_text(),'wifi original\n')
            r.update(True,['192.0.2.53']); p.write_text('wifi new\n')
            r.update(False,[]); self.assertEqual(p.read_text(),'wifi new\n')
    def test_rejects_inactive_or_wrong_bearer(self):
        for data in (b'',bytes(132),b'\0\0\2\1\3'+bytes(127)):
            with self.assertRaises(ValueError): configuration(data)

class RouteTests(unittest.TestCase):
    def test_counters_read_ip_json(self):
        stats=[{'stats64':{'rx':{'bytes':0,'packets':0},'tx':{'bytes':900,'packets':12}}}]
        self.assertEqual(counters(stats),(0,12))
    def test_sending_without_receiving_looks_silent(self):
        self.assertTrue(looks_silent(True,(0,10),(0,14)))
    def test_receiving_idle_or_unrouted_is_not_silent(self):
        self.assertFalse(looks_silent(True,(100,10),(900,40)))
        self.assertFalse(looks_silent(True,(0,10),(0,10)))
        self.assertFalse(looks_silent(False,(0,10),(0,40)))

class WatchTests(unittest.TestCase):
    def test_a_stalled_or_failed_ip_is_retried(self):
        def stalled(): raise subprocess.TimeoutExpired(('ip','route'),20)
        def failed(): raise RuntimeError('Cellular network operation failed: ip')
        def garbled(): raise ValueError('Expecting value')
        for step in (stalled,failed,garbled):
            self.assertIsNotNone(guarded(step))
        self.assertIsNone(guarded(lambda: None))
    def test_other_errors_still_end_the_service(self):
        def broken(): raise KeyError('dev')
        with self.assertRaises(KeyError): guarded(broken)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.patches = [patch.object(data_network.paths, 'RUN', root),
                        patch.object(data_network, 'RECOVERY', root / 'bearer-recovery'),
                        patch.object(data_network.paths, 'SIM', 2)]
        for p in self.patches:
            p.start()
        self.root = root

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.dir.cleanup()

    def test_restarts_the_data_sims_sitd_once_per_gap(self):
        with patch.object(data_network.subprocess, 'run') as run:
            self.assertTrue(data_network.recover(now=lambda: 1000.0))
            self.assertFalse(data_network.recover(now=lambda: 1300.0))
            self.assertTrue(data_network.recover(now=lambda: 1700.0))
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args[0][0], ['systemctl', 'restart', '--no-block', 'omamobile-sitd-2.service'])

    def test_never_during_a_call(self):
        import json
        (self.root / 'state.json').write_text(json.dumps({'calls': [{'state': 'active'}]}))
        with patch.object(data_network.subprocess, 'run') as run:
            self.assertFalse(data_network.recover(now=lambda: 1000.0))
        run.assert_not_called()

