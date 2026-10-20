# SPDX-License-Identifier: MIT
import env  # noqa: F401  (paths and sys.path first)
import unittest
from unittest.mock import Mock, patch
import bringup
import paths

SETTINGS = paths.config('/nonexistent')
SETTINGS['network']['apn'] = 'internet.example'



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

class BringupTests(unittest.TestCase):
    def test_sim_requires_ready_usim_and_rejects_truncation(self):
        self.assertTrue(bringup.sim_ready(bytes([1, 0, 1, 2, 5]) + bytes(61)))
        self.assertFalse(bringup.sim_ready(bytes([1, 0, 1, 2, 2]) + bytes(61)))
        self.assertFalse(bringup.sim_ready(bytes([0, 0, 0])))
        with self.assertRaises(ValueError):
            bringup.sim_ready(bytes([1, 0, 1, 2, 5]))

    def test_actual_lte_registration_required(self):
        self.assertTrue(bringup.packet_registered(bytes([5, 0, 0, 14]), lte=True))
        self.assertFalse(bringup.packet_registered(bytes([1, 0, 0, 21]), lte=True))
        self.assertFalse(bringup.packet_registered(bytes([0, 0, 0, 14]), lte=True))

    def test_shutdown_cancels_wait_before_any_query(self):
        service = Mock()
        predicate = Mock()
        with self.assertRaises(InterruptedError):
            bringup.wait_for(service, predicate, 1, lambda: True)
        predicate.assert_not_called()

    def test_failed_data_setup_never_attempts_ims(self):
        service = Mock()
        with patch.object(bringup, 'wait_for'), patch.object(bringup, 'switch_radio'), \
             patch.object(bringup, 'sms_memory_available'), \
             patch.object(bringup, 'initial_attach'), patch.object(bringup, 'provision_default_profile'), \
             patch.object(bringup, 'nr_mode'), patch.object(bringup, 'activate', side_effect=TimeoutError), \
             patch.object(bringup, 'start_stack') as stack, patch.object(bringup, 'register') as register:
            with self.assertRaises(TimeoutError):
                bringup.start(service, SETTINGS)
            stack.assert_not_called()
            register.assert_not_called()
            service.client.request.assert_not_called()

    def test_data_failure_without_ims_is_not_fatal(self):
        settings = paths.config('/nonexistent')
        settings['network'].update(apn='example', ims='no')
        with patch.object(bringup, 'wait_for'), patch.object(bringup, 'switch_radio'), \
             patch.object(bringup, 'sms_memory_available'), \
             patch.object(bringup, 'initial_attach'), patch.object(bringup, 'provision_default_profile'), \
             patch.object(bringup, 'nr_mode'), patch.object(bringup, 'activate', side_effect=TimeoutError):
            bringup.start(Mock(), settings)
        settings['network']['data'] = 'no'
        with patch.object(bringup, 'wait_for'), patch.object(bringup, 'switch_radio'), \
             patch.object(bringup, 'sms_memory_available'), \
             patch.object(bringup, 'initial_attach'), patch.object(bringup, 'provision_default_profile'), \
             patch.object(bringup, 'nr_mode'), patch.object(bringup, 'activate') as activate:
            bringup.start(Mock(), settings)
        activate.assert_not_called()

    def test_no_apn_registers_for_calls_and_texts_only(self):
        settings = paths.config('/nonexistent')
        with patch.object(bringup, 'switch_radio') as radio, patch.object(bringup, 'wait_for'), \
             patch.object(bringup, 'sms_memory_available'), patch.object(bringup, 'nr_mode'), \
             patch.object(bringup, 'initial_attach') as attach, \
             patch.object(bringup, 'provision_default_profile') as profile, \
             patch.object(bringup, 'activate') as activate, patch.object(bringup, 'start_stack') as ims:
            bringup.start(Mock(), settings)
        radio.assert_called()
        attach.assert_not_called()
        profile.assert_not_called()
        activate.assert_not_called()
        ims.assert_not_called()

    def test_wait_keeps_handling_incoming_sms(self):
        service = Mock()
        service.client.next_indication.side_effect = [b'private-sms', None]
        with patch.object(bringup.time, 'monotonic', side_effect=[0, 0, 0, 0, 2, 2]):
            bringup.wait_for(service, Mock(side_effect=[False, True]), 10, lambda: False)
        service.event.assert_called_once_with(b'private-sms')

    def test_wait_serves_the_socket_and_outlasts_a_pin_prompt(self):
        service = Mock()
        service.sim = dict(state='pin')
        service.client.next_indication.return_value = None
        # Past the 10 s deadline twice while the SIM asks for its PIN.
        clock = iter([0, 0, 11, 11, 12, 12, 23, 23, 24, 24])
        with patch.object(bringup.time, 'monotonic', side_effect=lambda: next(clock)):
            bringup.wait_for(service, Mock(side_effect=[False, False, True]), 10, lambda: False)
        self.assertGreaterEqual(service.idle.call_count, 2)

    def test_wait_without_pin_still_times_out(self):
        service = Mock()
        service.sim = dict(state='unknown')
        service.client.next_indication.return_value = None
        clock = iter(range(0, 1000, 6))
        with patch.object(bringup.time, 'monotonic', side_effect=lambda: next(clock)), \
             self.assertRaises(TimeoutError):
            bringup.wait_for(service, Mock(return_value=False), 10, lambda: False)

    def test_readonly_status_timeout_does_not_abort_startup(self):
        service = Mock()
        service.client.next_indication.return_value = None
        with patch.object(bringup.time, 'monotonic', side_effect=[0, 0, 0, 0, 2, 2]):
            bringup.wait_for(service, Mock(side_effect=[TimeoutError(), True]), 10, lambda: False)
