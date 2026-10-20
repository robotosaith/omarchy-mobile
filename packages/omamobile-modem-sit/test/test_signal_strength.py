# SPDX-License-Identifier: MIT
import env  # noqa: F401  (paths and sys.path first)
import struct
import unittest
import signal_strength


def reply(kinds=0, gsm=0, lte=None):
    b = bytearray(198)
    b[0] = kinds
    struct.pack_into('<I', b, 2, gsm)
    if lte:
        struct.pack_into('<IIIiII', b, 62, *lte)
    return bytes(b)


class SignalTests(unittest.TestCase):
    def test_raven_samples(self):
        # SIM 2 on LTE and SIM 1 on EDGE, 2026-10-20.
        lte = reply(4, lte=(27, 86, 7, 20, 1, 11))
        self.assertEqual(signal_strength.fields(lte)['rsrp'], -86)
        self.assertEqual(signal_strength.bars(lte), 4)
        self.assertEqual(signal_strength.bars(reply(1, gsm=26)), 4)

    def test_thresholds(self):
        self.assertEqual(signal_strength.bars(reply(4, lte=(10, 110, 12, 0, 0, 0))), 2)
        self.assertEqual(signal_strength.bars(reply(4, lte=(1, 130, 18, 0, 0, 0))), 0)
        self.assertEqual(signal_strength.bars(reply(1, gsm=6)), 2)
        self.assertEqual(signal_strength.bars(reply(1, gsm=99)), 0)
        self.assertEqual(signal_strength.bars(b''), 0)

    def test_generation(self):
        self.assertEqual(signal_strength.generation('LTE'), '4G')
        self.assertEqual(signal_strength.generation('EDGE'), '2G')
        self.assertEqual(signal_strength.generation(''), '')


if __name__ == '__main__':
    unittest.main()
