# SPDX-License-Identifier: MIT
import env  # noqa: F401  (paths and sys.path first)
import struct
import unittest
from unittest.mock import Mock, call, patch
import bringup
import modem_setup
import paths


def slot_reply(*slots):
    """GET_SLOT_STATUS in the 0x111-byte layout: (card, active, logical)."""
    out = bytearray([len(slots)])
    for card, active, logical in slots:
        entry = bytearray(65)
        entry[0], entry[1] = int(card), int(active)
        entry[0x24] = 0xff if logical is None else logical
        out += entry
    return bytes(out + bytes(65 * (4 - len(slots))))



# bringup.start reads the preferred network type from the client; a Mock
# client has no reply, so these start-up tests skip that step and the
# slot table read.
_preferred = patch.object(bringup, 'preferred_type')
_slots = patch.object(bringup, 'read_slots')
_data_modem = patch.object(bringup, 'preferred_data_modem')


def setUpModule():
    _preferred.start()
    _slots.start()
    _data_modem.start()


def tearDownModule():
    _preferred.stop()
    _slots.stop()
    _data_modem.stop()

class SlotTests(unittest.TestCase):
    def client(self, reply):
        c = Mock()
        c.request.side_effect = lambda ident, payload=b'', timeout=8: reply if ident == 0x024d else b''
        return c

    def test_parses_states_only(self):
        c = self.client(slot_reply((True, False, None), (True, True, 0), (False, False, None)))
        self.assertEqual(modem_setup.slot_status(c), [
            dict(card=True, active=False, logical=None), dict(card=True, active=True, logical=0),
            dict(card=False, active=False, logical=None)])

    def test_maps_the_tray(self):
        c = self.client(slot_reply((True, False, None), (True, True, 0)))
        self.assertTrue(modem_setup.select_slot(c, 0))
        c.request.assert_any_call(0x0250, bytes([1, 0]), timeout=15)

    def test_already_in_use_sends_nothing(self):
        c = self.client(slot_reply((True, True, 0), (True, False, None)))
        self.assertFalse(modem_setup.select_slot(c, 0))
        self.assertNotIn(0x0250, [a[0][0] for a in c.request.call_args_list])

    def test_empty_slot_refused(self):
        c = self.client(slot_reply((False, False, None), (True, True, 0)))
        with self.assertRaisesRegex(RuntimeError, 'No card in physical SIM slot 0'):
            modem_setup.select_slot(c, 0, sleep=Mock())

    def test_esim_gets_the_full_mapping(self):
        self.assertEqual(modem_setup.mapping(0), bytes([1, 0]))
        self.assertEqual(modem_setup.mapping(1), bytes([2, 1, 0]))
        self.assertEqual(modem_setup.mapping(1, 1), bytes([2, 0, 1]))
        self.assertEqual(modem_setup.mapping(0, 1), bytes([2, 1, 0]))

    def test_preferred_type_set_only_when_different(self):
        import struct
        c = Mock()
        c.request.side_effect = lambda ident, payload=b'', timeout=8: struct.pack('<I', 9) if ident == 0x070b else b''
        self.assertEqual(modem_setup.preferred_type(c, 9), 9)
        self.assertNotIn(0x070a, [a[0][0] for a in c.request.call_args_list])
        c.request.side_effect = lambda ident, payload=b'', timeout=8: struct.pack('<I', 3) if ident == 0x070b else b''
        modem_setup.preferred_type(c, 9)
        c.request.assert_any_call(0x070a, struct.pack('<I', 9), timeout=15)

    def test_read_slots_waits_for_the_report(self):
        replies = [b'', slot_reply((True, True, 0), (True, True, 1))]
        c = Mock()
        c.request.side_effect = lambda ident, payload=b'', timeout=8: replies.pop(0)
        sleep = Mock()
        with patch.object(modem_setup, 'publish_slots') as publish:
            slots = modem_setup.read_slots(c, sleep=sleep)
        self.assertEqual([s['logical'] for s in slots], [0, 1])
        sleep.assert_called_once()
        publish.assert_called_once()

    def test_preferred_data_modem_layout(self):
        c = Mock()
        modem_setup.preferred_data_modem(c, 1)
        c.request.assert_called_once_with(0x0740, bytes([1]), timeout=15)

    def test_unknown_layout_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'layout'):
            modem_setup.slot_status(self.client(b'\x03' + bytes(10)))


    def test_waits_for_the_slot_report(self):
        replies = [b'', b'\x00', slot_reply((True, False, None), (True, True, 0))]
        c = Mock()
        c.request.side_effect = lambda ident, payload=b'', timeout=8: replies.pop(0) if ident == 0x024d else b''
        sleep = Mock()
        self.assertTrue(modem_setup.select_slot(c, 0, sleep=sleep))
        self.assertEqual(sleep.call_count, 2)
        c.request.assert_any_call(0x0250, bytes([1, 0]), timeout=15)

    def test_switch_in_progress_is_waited_out(self):
        # raven, 2026-10-17: a second switch right after the first got error 7.
        from sit import ModemError
        reports = [slot_reply((True, False, None), (True, True, 0)), slot_reply((True, True, 0), (True, False, None))]
        def request(ident, payload=b'', timeout=8):
            if ident == 0x024d:
                return reports.pop(0)
            raise ModemError(7, b'')
        c = Mock()
        c.request.side_effect = request
        self.assertTrue(modem_setup.select_slot(c, 0, sleep=Mock()))

    def test_other_refusals_still_fail(self):
        from sit import ModemError
        def request(ident, payload=b'', timeout=8):
            if ident == 0x024d:
                return slot_reply((True, False, None), (True, True, 0))
            raise ModemError(2, b'')
        c = Mock()
        c.request.side_effect = request
        with self.assertRaisesRegex(RuntimeError, 'error 2'):
            modem_setup.select_slot(c, 0, sleep=Mock())

class SmsMemoryTests(unittest.TestCase):
    def test_reports_room_for_texts(self):
        client = Mock()
        modem_setup.sms_memory_available(client)
        client.request.assert_called_once_with(0x010a, struct.pack('<I', 1), timeout=15)

    def test_storage_full_reports_room_again(self):
        import service
        svc = service.Service.__new__(service.Service)
        svc.client, svc.indication_counts = Mock(), {}
        svc.event(struct.pack('<HHHH', 0, 0x010f, 8, 0))
        svc.client.request.assert_called_once_with(0x010a, struct.pack('<I', 1), timeout=15)


class RadioTests(unittest.TestCase):
    def test_sit_radio(self):
        c = Mock()
        modem_setup.switch_radio(c, {'radio': 'sit'}, True)
        modem_setup.switch_radio(c, {'radio': 'sit'}, False)
        self.assertEqual(c.request.call_args_list, [
            call(0x0800, struct.pack('<IBB', 2, 0, 0), timeout=30),
            call(0x0800, struct.pack('<IBB', 1, 0, 0), timeout=30)])

    def test_at_radio_is_the_default(self):
        with patch.object(modem_setup.at, 'radio') as radio:
            modem_setup.switch_radio(Mock(), {}, True)
        radio.assert_called_once_with(True)

    def test_sit_startup_order(self):
        settings = paths.config('/nonexistent')
        settings['network'].update(apn='example', radio='sit', sim_slot='0', ims='no')
        service = Mock()
        order = []
        with patch.object(bringup, 'select_slot', side_effect=lambda c, s, l: order.append(('slot', s, l)) or True), \
             patch.object(bringup, 'modem_config', side_effect=lambda c, n: order.append(('config', n))), \
             patch.object(bringup, 'preferred_type', side_effect=lambda c, t: order.append(('type', t))), \
             patch.object(bringup, 'switch_radio', side_effect=lambda c, n, on: order.append(('radio', on))), \
             patch.object(bringup, 'wait_for'), patch.object(bringup, 'initial_attach'), \
             patch.object(bringup, 'provision_default_profile'), patch.object(bringup, 'nr_mode'), \
             patch.object(bringup, 'activate'):
            bringup.start(service, settings)
        self.assertEqual(order, [('slot', 0, 0), ('config', 1), ('type', 9), ('radio', False), ('radio', True)])
        service.client.request.assert_any_call(0x0710, bytes([1]))

    def test_stack_one_configures_through_stack_zero(self):
        settings = paths.config('/nonexistent')
        settings['network'].update(apn='example', radio='sit', sim_slot='1', stack='1', ims='no')
        config = Mock()
        order = []
        with patch.object(bringup, 'radio_config_client', return_value=config), \
             patch.object(bringup, 'select_slot', side_effect=lambda c, s, l: order.append(('slot', c, s, l)) or True), \
             patch.object(bringup, 'modem_config', side_effect=lambda c, n: order.append(('config', c, n))), \
             patch.object(bringup, 'switch_radio'), patch.object(bringup, 'wait_for'), \
             patch.object(bringup, 'initial_attach'), patch.object(bringup, 'provision_default_profile'), \
             patch.object(bringup, 'nr_mode'), patch.object(bringup, 'activate'):
            bringup.start(Mock(), settings)
        self.assertEqual(order, [('slot', config, 1, 1), ('config', config, 2)])
        config.close.assert_called_once()


class ImsProfileTests(unittest.TestCase):
    def test_ims_profile_layout(self):
        import data_call
        c = Mock()
        data_call.provision_ims_profile(c, 'ims')
        ident, payload = c.request.call_args[0][:2]
        self.assertEqual(ident, 0x0613)
        self.assertEqual(len(payload), 234)
        self.assertEqual(struct.unpack_from('<I', payload, 0)[0], 2)      # profile ID 2 (IMS)
        self.assertEqual(payload[4:7], b'ims')
        self.assertEqual(struct.unpack_from('<I', payload, 0xea - 12)[0], 64)  # APN type IMS

    def test_ims_profile_only_when_asked(self):
        for flag, expected in (('no', 0), ('yes', 1)):
            settings = paths.config('/nonexistent')
            settings['network'].update(apn='example', ims='yes', ims_profile=flag)
            with patch.object(bringup, 'provision_ims_profile') as ims, \
                 patch.object(bringup, 'preferred_type'), patch.object(bringup, 'switch_radio'), patch.object(bringup, 'wait_for'), \
                 patch.object(bringup, 'initial_attach'), patch.object(bringup, 'provision_default_profile'), \
                 patch.object(bringup, 'nr_mode'), patch.object(bringup, 'activate', side_effect=TimeoutError):
                with self.assertRaises(TimeoutError):
                    bringup.start(Mock(), settings)
            self.assertEqual(ims.call_count, expected)


class ImsBearerTests(unittest.TestCase):
    def test_modem_bearer_skips_the_ap_request(self):
        settings = paths.config('/nonexistent')
        settings['network'].update(apn='example', ims='yes', ims_bearer='modem')
        with patch.object(bringup, 'activate') as activate, patch.object(bringup, 'register') as ap_register, \
             patch.object(bringup, 'register_modem_bearer') as modem_register, patch.object(bringup, 'start_stack'), \
             patch.object(bringup, 'switch_radio'), patch.object(bringup, 'wait_for'), \
             patch.object(bringup, 'initial_attach'), patch.object(bringup, 'provision_default_profile'), \
             patch.object(bringup, 'nr_mode'):
            bringup.start(Mock(), settings)
        self.assertEqual(activate.call_count, 1)  # the internet bearer only
        ap_register.assert_not_called()
        modem_register.assert_called_once()


class ImsIpTypeTests(unittest.TestCase):
    def test_ims_ip_type_reaches_the_request(self):
        import data_call
        for ip_type, code in (('ipv6', 2), ('ipv4v6', 3)):
            payload = data_call.setup_payload(2, 14, 3, 'ims', ims=True, ip_type=ip_type)
            self.assertEqual(payload[0xda - 12], code)
            self.assertEqual(payload[15 - 12], 1)  # IMS APN type, as stock's GetProtocolApnType

    def test_bringup_passes_the_setting(self):
        settings = paths.config('/nonexistent')
        settings['network'].update(apn='example', ims='yes', ims_ip_type='ipv4v6')
        with patch.object(bringup, 'activate') as activate, patch.object(bringup, 'register'), \
             patch.object(bringup, 'start_stack'), patch.object(bringup, 'switch_radio'), \
             patch.object(bringup, 'wait_for'), patch.object(bringup, 'initial_attach'), \
             patch.object(bringup, 'provision_default_profile'), patch.object(bringup, 'nr_mode'):
            bringup.start(Mock(), settings)
        self.assertEqual(activate.call_args_list[-1].kwargs.get('ip_type'), 'ipv4v6')


if __name__ == '__main__':
    unittest.main()
