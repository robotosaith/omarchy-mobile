# SPDX-License-Identifier: MIT
"""omamobile-sims-set: the defaults file and the per-SIM data key."""
import env  # noqa: F401  (paths and sys.path first)
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BIN = Path(__file__).resolve().parent.parent / 'bin' / 'omamobile-sims-set'


def load():
    # No bin/__pycache__: test/all parses every file in bin/.
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader('sims_set', str(BIN))
    spec = importlib.util.spec_from_loader('sims_set', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class SimsSetTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        os.environ['OMAMOBILE_SIMS_ETC'] = str(self.root)
        os.environ['OMAMOBILE_SIMS_CONF'] = str(self.root / 'sims.conf')
        self.m = load()
        (self.root / 'modem-sit.conf').write_text('[network]\n# the tray\napn = a\ndata = yes\n[audio]\ncard = auto\n')
        (self.root / 'modem-sit-2.conf').write_text('[network]\napn = b\n')

    def tearDown(self):
        os.environ.pop('OMAMOBILE_SIMS_ETC')
        os.environ.pop('OMAMOBILE_SIMS_CONF')
        self.dir.cleanup()

    def test_set_key_keeps_comments_and_sections(self):
        path = str(self.root / 'modem-sit.conf')
        self.m.set_key(path, 'network', 'data', 'no')
        self.m.set_key(path, 'network', 'label', 'Tray')
        text = Path(path).read_text()
        self.assertIn('# the tray', text)
        self.assertEqual(text.count('data ='), 1)
        self.assertIn('data = no', text)
        self.assertLess(text.index('label = Tray'), text.index('[audio]'))

    def test_calls_and_texts_only_record(self):
        with patch.object(self.m, 'systemctl') as systemctl:
            self.m.main(['calls-2'])
            self.m.main(['texts-1'])
        # Only the bridge follows the calls SIM; no SIM service restarts.
        systemctl.assert_called_once_with('try-restart', '--no-block', 'omamobile-mmd.service')
        text = (self.root / 'sims.conf').read_text()
        self.assertIn('calls = 2', text)
        self.assertIn('texts = 1', text)

    def test_data_moves_the_key_and_restarts_the_other_first(self):
        calls = []
        result = type('R', (), {'returncode': 3})()
        with patch.object(self.m, 'systemctl', side_effect=lambda *a: calls.append(a) or result), \
             patch.object(self.m.time, 'sleep'), patch.object(self.m, 'stage', return_value='running'):
            self.m.main(['data-2'])
        self.assertIn('data = no', (self.root / 'modem-sit.conf').read_text())
        self.assertIn('data = yes', (self.root / 'modem-sit-2.conf').read_text())
        restarts = [a[-1] for a in calls if a[0] == 'restart']
        self.assertEqual(restarts, ['omamobile-sitd.service', 'omamobile-sitd-2.service'])

    def test_data_creates_a_missing_sim_file(self):
        (self.root / 'modem-sit-2.conf').unlink()
        result = type('R', (), {'returncode': 3})()
        with patch.object(self.m, 'systemctl', return_value=result), \
             patch.object(self.m.time, 'sleep'), patch.object(self.m, 'stage', return_value='running'):
            self.m.main(['data-2'])
        self.assertIn('data = yes', (self.root / 'modem-sit-2.conf').read_text())

    def test_refuses_bad_arguments(self):
        for arg in ('data-3', 'voice-1', 'data'):
            with self.assertRaises(SystemExit):
                self.m.main([arg])


if __name__ == '__main__':
    unittest.main()
