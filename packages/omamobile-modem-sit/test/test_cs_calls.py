# SPDX-License-Identifier: MIT
import env  # noqa: F401  (paths and sys.path first)
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import cs_calls
import paths
import service as app_service


def entry(index, state, number=b'', incoming=False, kind=1, toa=0x81, size=364):
    e = bytearray(size)
    e[0] = state
    struct.pack_into('<II', e, 1, index, toa)
    e[10] = int(incoming)
    e[12] = kind
    e[14] = len(number)
    e[15:15+len(number)] = number
    return bytes(e)


def call_list(*entries):
    return struct.pack('<I', len(entries)) + b''.join(entries)


class LayoutTests(unittest.TestCase):
    def test_dial_matches_stock(self):
        p = cs_calls.dial_payload('+12025550123')
        self.assertEqual(len(p), 92)
        self.assertEqual((p[0], p[2], p[3:15], p[85], p[86], p[87]), (1, 12, b'+12025550123', 0x10, 1, 0))
        self.assertEqual(cs_calls.dial_payload('123')[85], 0x20)
        with self.assertRaises(ValueError):
            cs_calls.dial_payload('1' * 83)

    def test_hangup_and_dtmf(self):
        self.assertEqual(cs_calls.hangup_payload(3), struct.pack('<II', 3, 1))
        p = cs_calls.dtmf_payload('5#')
        self.assertEqual((len(p), p[:3]), (65, b'\x025#'))

    def test_call_list_entry_sizes(self):
        for size in cs_calls.ENTRY_SIZES:
            calls = cs_calls.call_list(call_list(entry(0, 3, b'12025550123', toa=0x91, size=size)))
            self.assertEqual(calls, [dict(index=0, state='ringing-out', incoming=False, multiparty=False,
                                          number='+12025550123')])
        self.assertEqual(cs_calls.call_list(bytes(4)), [])
        with self.assertRaisesRegex(ValueError, 'layout'):
            cs_calls.call_list(struct.pack('<I', 1) + bytes(100))

    def test_non_voice_calls_are_skipped(self):
        self.assertEqual(cs_calls.call_list(call_list(entry(1, 0, kind=2))), [])


class CsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = patch.object(paths, 'RUN', self.root)
        self.paths.start()
        self.db = app_service.database(self.root / 'db')
        self.client = Mock()
        self.client.next_indication.return_value = None
        self.service = app_service.Service(self.client, self.db)
        self.service.settings['network']['ims'] = 'no'
        self.service.settings['audio']['card'] = 'none'
        self.list = bytes(4)
        self.sent = []

        def request(ident, payload=b'', timeout=8):
            self.sent.append((ident, payload))
            if ident == 0x0000:
                return self.list
            if ident == 0x0700:
                return bytes([1]) + bytes(75)
            if ident == 0x0002:
                return struct.pack('<I', 16)
            return b''
        self.client.request.side_effect = request

    def tearDown(self):
        self.db.close()
        self.paths.stop()
        self.temp.cleanup()

    def indication(self, ident):
        self.service.event(struct.pack('<BBHHH', 2, 0, ident, 8, 0))

    def test_outgoing_call_follows_the_list(self):
        # raven, 2026-10-17: dialing, alerting at 8 s, active at 12 s, released
        # by the other side at 17 s with cause 16.
        def dial(ident, payload=b'', timeout=8):
            self.sent.append((ident, payload))
            if ident == 0x0001:
                self.list = call_list(entry(0, 2))
                return b''
            return {0x0000: self.list, 0x0700: bytes([1]) + bytes(75), 0x0002: struct.pack('<I', 16)}.get(ident, b'')
        self.client.request.side_effect = dial
        result = self.service.dispatch(dict(action='dial', number='+12025550123'))
        call = self.service.calls[result['call']]
        self.assertEqual((call['state'], call['modem_id']), ('dialing', 0))
        self.assertIn(0x0001, [i for i, _ in self.sent])
        self.assertNotIn(0x0d00, [i for i, _ in self.sent])
        for state, name in ((3, 'ringing-out'), (0, 'active')):
            self.list = call_list(entry(0, state))
            self.indication(0x0009)
            self.assertEqual(call['state'], name)
        self.list = bytes(4)
        self.indication(0x0009)
        self.assertEqual((call['state'], call['reason']), ('terminated', 'terminated'))

    def test_incoming_call_rings_without_answering(self):
        self.list = call_list(entry(1, 4, b'12025550123', incoming=True, toa=0x91))
        self.indication(0x000a)
        call = self.service.live()[0]
        self.assertEqual((call['state'], call['number'], call['direction']), ('ringing-in', '+12025550123', 'incoming'))
        self.assertNotIn(0x0004, [i for i, _ in self.sent])
        self.indication(0x0009)
        self.assertEqual(len(self.service.live()), 1)
        self.service.dispatch(dict(action='accept', id=call['id']))
        self.assertIn((0x0004, b''), self.sent)

    def test_incoming_audio_starts_when_the_call_is_active(self):
        self.list = call_list(entry(1, 4, b'12025550123', incoming=True, toa=0x91))
        self.indication(0x000a)
        call = self.service.live()[0]
        with patch.object(self.service, 'audio_start') as audio:
            self.service.dispatch(dict(action='accept', id=call['id']))
            audio.assert_not_called()
            self.list = call_list(entry(1, 0, b'12025550123', incoming=True, toa=0x91))
            self.indication(0x0009)
            audio.assert_called_once()
        self.assertEqual(self.service.live()[0]['state'], 'active')

    def test_presented_call_is_confirmed(self):
        self.list = call_list(entry(1, 4, b'12025550123', incoming=True, toa=0x91))
        self.indication(0x0010)
        self.assertIn((0x000f, b''), self.sent)
        self.assertEqual(self.service.live()[0]['state'], 'ringing-in')
        self.assertNotIn(0x0004, [i for i, _ in self.sent])

    def test_hangup_and_tones_use_cs_requests(self):
        call = self.service.new_call('+12025550123', 'outgoing', 'active', 0)
        self.service.dispatch(dict(action='dtmf', id=call['id'], keys='5#'))
        self.assertIn((0x0003, cs_calls.dtmf_payload('5#')), self.sent)
        self.list = call_list(entry(0, 0))
        self.service.dispatch(dict(action='hangup', id=call['id']))
        self.assertIn((0x0008, cs_calls.hangup_payload(0)), self.sent)
        self.assertIsNotNone(self.service.hangup_deadline)
        self.list = bytes(4)
        audio = MagicMock()
        self.service.audio = audio
        self.indication(0x0009)
        self.assertIsNone(self.service.hangup_deadline)
        audio.__exit__.assert_called_once()

    def test_failed_call_is_an_error(self):
        call = self.service.new_call('+12025550123', 'outgoing', 'dialing', 0)
        self.client.request.side_effect = lambda ident, payload=b'', timeout=8: \
            bytes(4) if ident == 0x0000 else struct.pack('<I', 34)
        self.indication(0x0009)
        self.assertEqual((call['state'], call['reason']), ('terminated', 'error'))

    def test_ims_mode_ignores_cs_indications(self):
        self.service.settings['network']['ims'] = 'yes'
        self.indication(0x0009)
        self.assertEqual(self.sent, [])


if __name__ == '__main__':
    unittest.main()
