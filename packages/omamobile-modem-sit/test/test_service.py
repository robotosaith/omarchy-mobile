# SPDX-License-Identifier: MIT
import env  # noqa: F401  (paths and sys.path first)
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
import paths
import service as app_service

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.paths=patch.object(paths,'RUN',self.root); self.paths.start()
        self.db=app_service.database(self.root/'db')
        self.client=Mock(); self.client.next_indication.return_value=None
        self.service=app_service.Service(self.client,self.db)
        self.service.ready=Mock()
    def tearDown(self):
        self.db.close(); self.paths.stop(); self.temp.cleanup()
    def test_send_idempotency_after_success_and_unknown_response(self):
        for i,reply in enumerate((bytes(253),TimeoutError())):
            self.client.request.side_effect=[bytes([1])+bytes(12),reply]
            req=dict(request_id=str(i)*32,number='+12025550123',text='Hello €')
            result=self.service.send_sms(req)
            self.assertEqual(result['state'],'sent' if i==0 else 'unknown')
            before=self.client.request.call_count
            repeated=self.service.send_sms(req)
            self.assertEqual(repeated['state'],result['state'])
            self.assertEqual(self.client.request.call_count,before)
    def test_cs_sms_without_ims(self):
        # [network] ims = no: GET_CS_REG_STATE must say registered, then SEND_SMS
        # carries domain 0, the SMSC from GET_SMSC_ADDR and the TPDU.
        self.service.settings['network']['ims']='no'
        smsc=bytes([7])+bytes.fromhex('914477')+bytes(9)
        sent=[]
        def request(ident,payload=b'',timeout=8):
            if ident==0x0700: return bytes([1])+bytes(75)
            if ident==0x0108: return smsc
            if ident==0x0100: sent.append(payload); return bytes(253)
            raise AssertionError(hex(ident))
        self.client.request.side_effect=request
        result=self.service.send_sms(dict(request_id='c'*32,number='+12025550123',text='Hi'))
        self.assertEqual(result['state'],'sent')
        self.assertEqual(len(sent),1)
        p=sent[0]
        self.assertEqual((len(p),p[0],p[1:14],p[15:15+p[14]][:1]),(259,0,smsc,bytes([0x01])))
        self.service.ready.assert_not_called()
    def test_cs_sms_network_refusal_fails(self):
        # The SIT error is 0 even when the network refuses (RP-cause 28 seen on
        # raven); the cause at 249 decides.
        self.service.settings['network']['ims']='no'
        def request(ident,payload=b'',timeout=8):
            if ident==0x0700: return bytes([1])+bytes(75)
            if ident==0x0108: return bytes([7])+bytes.fromhex('914477')+bytes(9)
            if ident==0x0100: return bytes(249)+struct.pack('<I',28)
            raise AssertionError(hex(ident))
        self.client.request.side_effect=request
        result=self.service.send_sms(dict(request_id='e'*32,number='+12025550123',text='Hi'))
        self.assertEqual(result['state'],'failed')
    def test_cs_sms_needs_cs_registration(self):
        self.service.settings['network']['ims']='no'
        self.client.request.side_effect=lambda ident,payload=b'',timeout=8: bytes(76) if ident==0x0700 else bytes(13)
        with self.assertRaisesRegex(RuntimeError,'not registered'):
            self.service.send_sms(dict(request_id='d'*32,number='+12025550123',text='Hi'))
    def test_wap_push_parts_join_into_data(self):
        inbox=self.root/'inbox'; inbox.mkdir()
        pieces=[bytes(range(0,100)),bytes(range(100,160))]
        for seq,piece in enumerate(pieces,1):
            ud=bytes.fromhex('0b05040b8423f000030902')+bytes([seq])+piece
            tpdu=bytes.fromhex('440b912120550521f3000462909221436500')+bytes([len(ud)])+ud
            data=bytes.fromhex('07912120550521f3')+tpdu
            path=inbox/f'{seq}.sit'
            path.write_bytes(bytes(2)+struct.pack('<H',0x0d1e)+bytes(5)+bytes([len(data)])+data)
            self.service.ingest(path)
        listed=self.service.dispatch(dict(action='sms-list'))
        self.assertEqual(len(listed),1)
        self.assertEqual((listed[0]['number'],listed[0]['text'],listed[0]['data']),('+12025550123','',b''.join(pieces).hex()))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM parts').fetchone()[0],0)
    def test_restart_does_not_retry_pending_sms(self):
        self.db.execute('INSERT INTO outgoing VALUES (?,?,?,?,?)',('a'*32,'digest','sending','',0)); self.db.commit()
        other=app_service.database(self.root/'db')
        self.assertEqual(other.execute('SELECT state FROM outgoing').fetchone()[0],'unknown'); other.close()
    def test_ring_does_not_autoanswer_and_release_restores_audio(self):
        n=b'+12025550123'; body=struct.pack('<HBH',1,7,len(n))+n
        packet=struct.pack('<BBHHH',2,0,0x0d01,8+len(body),0)+body
        self.service.event(packet)
        self.client.request.assert_not_called()
        call=self.service.live()[0]
        self.assertEqual(call['state'],'ringing-in')
        audio=MagicMock(); self.service.audio=audio
        body=struct.pack('<HBBBBBBB',1,7,6,0,0,0,16,0)+bytes(2)
        self.service.event(struct.pack('<BBHHH',2,0,0x0d04,8+len(body),0)+body)
        audio.__exit__.assert_called_once()
        self.assertFalse(self.service.live())

    def test_keypad_only_targets_an_active_owned_call(self):
        call=self.service.new_call('+12025550123','outgoing','active',7)
        self.service.dispatch(dict(action='dtmf',id=call['id'],keys='5#'))
        self.assertEqual([c.args for c in self.client.request.call_args_list],[(0x0d0a,bytes([7,0,53])),(0x0d0a,bytes([7,0,35]))])
        call['state']='terminated'
        with self.assertRaises(RuntimeError): self.service.dispatch(dict(action='dtmf',id=call['id'],keys='5'))

    def test_screen_state_blocks_sleep_during_calls_and_only_caches_success(self):
        self.client.request.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):
            self.service.dispatch(dict(action='screen-state',on=False))
        self.assertIsNone(self.service.screen_on)
        self.client.request.side_effect=None
        self.service.dispatch(dict(action='screen-state',on=False))
        self.assertEqual([c.args for c in self.client.request.call_args_list[-2:]],
                         [(0x0902,bytes(4)),(0x0928,bytes(4))])
        count=self.client.request.call_count
        self.service.dispatch(dict(action='screen-state',on=False))
        self.assertEqual(count,self.client.request.call_count)
        self.service.new_call('+12025550123','incoming','ringing-in',7)
        with self.assertRaises(RuntimeError):
            self.service.dispatch(dict(action='screen-state',on=False))
        self.service.dispatch(dict(action='screen-state',on=True))
        self.assertEqual([c.args for c in self.client.request.call_args_list[-2:]],
                         [(0x0902,b'\x01\0\0\0'),(0x0928,b'\xff'*4)])
        with self.assertRaises(ValueError):
            self.service.dispatch(dict(action='screen-state',on=2))

    def test_failed_filter_does_not_hide_partial_screen_change(self):
        self.service.screen_on=True
        self.client.request.side_effect=[b'',TimeoutError()]
        with self.assertRaises(TimeoutError):
            self.service.dispatch(dict(action='screen-state',on=False))
        self.assertIsNone(self.service.screen_on)
        self.client.request.side_effect=None
        self.service.dispatch(dict(action='screen-state',on=True))
        self.assertTrue(self.service.screen_on)
        self.client.request.assert_called_with(0x0928,b'\xff'*4,timeout=5)

    def test_public_state_has_no_numbers(self):
        self.service.new_call('+12025550123','incoming','ringing-in',7)
        state=json.loads((self.root/'state.json').read_text())
        self.assertNotIn('2025550123',json.dumps(state))
        self.assertEqual(state['calls'],[dict(state='ringing-in',direction='incoming')])
        self.assertEqual((self.root/'state.json').stat().st_mode&0o777,0o644)

    def test_operator_name_is_display_only_and_defensive(self):
        payload=bytearray(0x77-12); payload[:6]=b'00101#'; payload[6:10]=b'Test'
        self.assertEqual(app_service.operator_name(bytes(payload)),dict(plmn='00101',name='Test'))
        self.assertEqual(app_service.operator_name(bytes(8)),dict(plmn='',name=''))

    def test_unconfirmed_release_stops_the_modem(self):
        call=self.service.new_call('+12025550123','outgoing','active',7)
        with patch.object(app_service.cp,'stop_modem') as stop:
            self.service.dispatch(dict(action='hangup',id=call['id']))
            stop.assert_not_called()
            self.service.hangup_deadline=0.001
            with self.assertRaises(RuntimeError): self.service.pump()
            stop.assert_called_once()


def sim_payload(state=2, pin_retries=3, aid=bytes(range(16))):
    app = bytearray(63)
    app[0], app[1], app[3] = 2, state, len(aid)
    app[4:4 + len(aid)] = aid
    app[59], app[60] = pin_retries, 10
    return bytes([1, 0, 1]) + bytes(app)


class SimPinTests(unittest.TestCase):
    def service(self, statuses, verify_error=None):
        svc = app_service.Service.__new__(app_service.Service)
        svc.client = Mock()
        sent = []

        def request(ident, payload=b'', timeout=8):
            if ident == 0x0200:
                return statuses.pop(0)
            sent.append((ident, payload))
            if verify_error:
                raise app_service.ModemError(verify_error, b'')
            return b''
        svc.client.request.side_effect = request
        svc.publish = Mock()
        return svc, sent

    def test_startup_publishes_the_pin_prompt(self):
        svc, _ = self.service([])
        svc.note_sim(sim_payload())
        self.assertEqual(svc.sim['state'], 'pin')
        self.assertEqual(svc.sim['pin_retries'], 3)
        svc.publish.assert_called_once()

    def test_startup_socket_refuses_other_actions(self):
        import json, os, socket
        svc = Mock()
        ours, theirs = socket.socketpair()
        with ours, theirs:
            theirs.sendall(json.dumps(dict(action='sms-send', number='+0', text='x')).encode() + b'\n')
            app_service.serve_one(svc, ours, {os.getuid()}, app_service.STARTUP_ACTIONS)
            reply = json.loads(theirs.recv(4096))
        self.assertFalse(reply['ok'])
        self.assertEqual(reply['error'], 'The modem is still starting')
        svc.dispatch.assert_not_called()

    def test_payload_layout(self):
        payload = app_service.verify_pin_payload('1234', bytearray(sim_payload()[3:]))
        self.assertEqual(len(payload), 26)
        self.assertEqual(payload[0], 4)
        self.assertEqual(payload[1:9], b'1234\0\0\0\0')
        self.assertEqual(payload[9], 16)
        self.assertEqual(payload[10:26], bytes(range(16)))

    def test_pin_must_be_digits(self):
        for pin in ('123', '123456789', '12a4', '', None, '１２３４'):
            with self.assertRaises(ValueError):
                app_service.verify_pin_payload(pin, bytearray(sim_payload()[3:]))

    def test_unlock(self):
        svc, sent = self.service([sim_payload(), sim_payload(state=5)])
        self.assertEqual(svc.sim_pin('1234', False)['sim']['state'], 'ready')
        self.assertEqual([i for i, _ in sent], [0x0201])

    def test_wrong_pin(self):
        svc, sent = self.service([sim_payload(), sim_payload(pin_retries=2)], verify_error=12)
        with self.assertRaisesRegex(RuntimeError, '^Wrong PIN$'):
            svc.sim_pin('1234', False)

    def test_refusal_without_a_try(self):
        svc, sent = self.service([sim_payload(), sim_payload()], verify_error=2)
        with self.assertRaisesRegex(RuntimeError, 'no try was used'):
            svc.sim_pin('1234', False)

    def test_last_try_needs_consent(self):
        svc, sent = self.service([sim_payload(pin_retries=1)])
        with self.assertRaisesRegex(RuntimeError, 'One PIN try left'):
            svc.sim_pin('1234', False)
        self.assertEqual(sent, [])

    def test_not_locked(self):
        svc, sent = self.service([sim_payload(state=5)])
        with self.assertRaises(RuntimeError):
            svc.sim_pin('1234', False)
        self.assertEqual(sent, [])

    def test_gate(self):
        import sit
        with self.assertRaises(ValueError):
            sit.check(0x0201)
        sit.check(0x0201, pin=True)
        for ident in (0x0202, 0x0205, 0x020a):  # PUK, PIN change, the lock
            with self.assertRaises(ValueError):
                sit.check(ident, pin=True)
