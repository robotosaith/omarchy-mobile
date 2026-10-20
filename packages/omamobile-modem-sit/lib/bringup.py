# SPDX-License-Identifier: MIT
"""The start-up sequence for a freshly booted CP, using the service's IPC0
owner. This order registered on LTE with IMS voice and SMS on this phone:

  1. wait for the USIM application to be READY (type 2, state 5);
  2. radio off (AT+CFUN=0), initial attach APN, the default data profile;
  3. radio on (AT+CFUN=1), wait for packet registration;
  4. NR mode 0 ([network] nr = off): stay on LTE (NR registered, but
     carried no traffic on this phone), wait for LTE registration;
  5. the internet bearer (CID 1, rmnet0);
  6. IMS: stack start, the IMS bearer (CID 2, IPv6), ADD_PDN_INFO, then wait
     for an IMS registration with voice and SMS.

No retransmission of SMS/calls and no warm CP restart. A failed or uncertain
step ends start-up; the service exits and the modem stays up for diagnosis.
"""
import os
import time

from sit import ModemError
from modem_setup import activate_subscription, modem_config, preferred_data_modem, preferred_type, read_slots, select_slot, sms_memory_available, switch_radio
from data_call import activate, initial_attach, provision_default_profile, provision_ims_profile
from ims import register, register_modem_bearer, start_stack
from radio_settings import nr_mode


def sim_ready(payload):
    if len(payload) < 3 or payload[2] > 8 or len(payload) < 3 + payload[2] * 63:
        raise ValueError('Unexpected SIM status layout')
    return any(
        payload[i:i + 2] == bytes([2, 5])
        for i in range(3, 3 + payload[2] * 63, 63))


def packet_registered(payload, *, lte=False):
    return len(payload) >= 4 and payload[0] in (1, 5) and (not lte or payload[3] == 14)


def wait_for(service, predicate, seconds, stopped):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if stopped():
            raise InterruptedError('Modem startup stopped')
        service.pump()
        service.idle()
        try:
            ready = predicate()
        except TimeoutError:
            # CP may briefly stop answering status requests while its SIM
            # application initializes. Only these read-only polls retry.
            ready = False
        if ready:
            service.pump()
            return
        if service.sim.get('state') == 'pin':
            # Waiting on the user's PIN (omamobile-sit sim-pin): no deadline
            # here; the unit's TimeoutStartSec still bounds the start.
            deadline = time.monotonic() + seconds
        # Receive and durably handle SMS throughout startup. Calls never
        # auto-answer; the same Service retains them for the user.
        until = time.monotonic() + 1
        while time.monotonic() < until:
            if stopped():
                raise InterruptedError('Modem startup stopped')
            packet = service.client.next_indication(.1)
            if packet:
                service.event(packet)
            service.idle()
    raise TimeoutError('Modem registration deadline exceeded')


def radio_config_client():
    """A second SIT client on stack 0's channel, for the radio-config
    requests when sitd runs on stack 1."""
    from sit import Sit
    return Sit(device=os.environ.get('OMAMOBILE_SIT_CONFIG_DEVICE', '/dev/umts_ipc0'))


def start(service, settings, stopped=lambda: False):
    client = service.client
    net = settings['network']
    apn, ip_type = net.get('apn', ''), net.get('ip_type', 'ipv4v6')
    if not apn:
        # No APN: calls and texts only (the network's default attach); the
        # owner adds one in /etc/omamobile/modem-sit[-2].conf for data.
        print('Startup: no APN set; calls and texts only, no data bearer', flush=True)
    previous = None

    def usim_ready():
        nonlocal previous
        payload = client.request(0x0200)
        ready = sim_ready(payload)
        service.note_sim(payload)
        # Card state and application type/state only: never AIDs or labels.
        state = (payload[0], tuple((payload[i], payload[i + 1])
                 for i in range(3, 3 + payload[2] * 63, 63)))
        if state != previous:
            print('SIM card state and application type/state:', state, flush=True)
            previous = state
        return ready
    slot = net.get('sim_slot', '').strip()
    stack = net.getint('stack', 0)
    sit_radio = net.get('radio', 'at') == 'sit'
    stacks = net.getint('stacks', 1)
    if stack and slot:
        # Slot mapping and modem config are radio-config requests that only
        # stack 0's channel takes (stack 1 answers GET_SLOT_STATUS with
        # error 6), as stock's MiscService sends them; both stacks active.
        config = radio_config_client()
        try:
            if slot and select_slot(config, int(slot), stack):
                previous = None
            if sit_radio:
                # Refused (error 2) right after a mapping with both stacks
                # already active (2026-10-20): logged, not fatal.
                try:
                    modem_config(config, 2)
                except ModemError as failure:
                    print(f'Startup: SET_MODEM_CONFIG 2 refused ({failure}); continuing', flush=True)
        finally:
            config.close()
    elif slot:
        if select_slot(client, int(slot), stack):
            previous = None
    elif not stack:
        # Both SIMs at once (stacks = 2): the modem's own mapping stays;
        # stack 0 publishes the slot table for the SIM labels.
        read_slots(client)
    service.stage('sim')
    print('Startup: waiting for physical USIM ready', flush=True)
    wait_for(service, usim_ready, net.getint('sim_timeout', 120), stopped)
    service.stage('attach')
    if sit_radio:
        if not stack:
            try:
                modem_config(client, stacks)
            except ModemError as failure:
                if stacks == 1:
                    raise
                # Refused (error 2) with both stacks already active.
                print(f'Startup: SET_MODEM_CONFIG {stacks} refused ({failure}); continuing', flush=True)
        activate_subscription(client)
    if stacks > 1 and net.getboolean('data', True):
        preferred_data_modem(client, stack)
    if net.get('preferred_type', '9').strip():
        preferred_type(client, net.getint('preferred_type', 9))
    switch_radio(client, net, False)
    if apn:
        initial_attach(client, apn, ip_type)
        provision_default_profile(client, apn, ip_type)
    if net.getboolean('ims', True) and net.getboolean('ims_profile', False):
        provision_ims_profile(client, net.get('ims_apn', 'ims'))
    service.pump()
    switch_radio(client, net, True)
    # With both stacks active only the data SIM gets packet service: the
    # other SIM disallows it, as stock's allowData(false), and registers for
    # calls and texts (CS) only.
    data_sim = stacks == 1 or net.getboolean('data', True)
    if sit_radio:
        # SET_PS_SERVICE: allow data, as stock does; without it the modem
        # never attaches. Right after the radio comes on it can refuse it
        # (error 2, seen on raven's eSIM), so retry for about 10 s.
        for attempt in range(10):
            try:
                client.request(0x0710, bytes([1 if data_sim else 0]))
                break
            except ModemError as failure:
                print(f'Startup: SET_PS_SERVICE refused ({failure}), try {attempt + 1}', flush=True)
                wait_until = time.monotonic() + 1
                while time.monotonic() < wait_until:
                    if stopped():
                        raise InterruptedError('Modem startup stopped')
                    service.pump()
                    service.idle()
                    time.sleep(.1)
    service.stage('registering')
    print('Startup: waiting for ' + ('packet' if stacks == 1 or net.getboolean('data', True) else 'CS') + ' registration', flush=True)
    timeout = net.getint('register_timeout', 180)
    seen = None

    def registered(lte=False):
        # Reg state, the network's reject cause and the RAT (GET_PS_REG_STATE
        # bytes 0, 1, 3), logged on change: a denial says why.
        nonlocal seen
        payload = client.request(0x0701)
        state = tuple(payload[i] for i in (0, 1, 3) if i < len(payload))
        if state != seen:
            print('Startup: packet registration state, reject cause, RAT:', state, flush=True)
            seen = state
        return packet_registered(payload, lte=lte)
    def cs_registered():
        payload = client.request(0x0700)
        state = tuple(payload[i] for i in (0, 1, 2) if i < len(payload))
        nonlocal seen
        if state != seen:
            print('Startup: CS registration state, reject cause, RAT:', state, flush=True)
            seen = state
        return len(payload) >= 1 and payload[0] in (1, 5)
    wait_for(service, registered if data_sim else cs_registered, timeout, stopped)
    # The modem refuses this (error 1) until it has registered.
    try:
        sms_memory_available(client)
    except ModemError as failure:
        print(f'Startup: SMS memory status refused ({failure}); incoming texts may be held', flush=True)
    if net.get('nr', 'off') == 'off' and data_sim:
        nr_mode(client)
        wait_for(service, lambda: registered(lte=True), 120, stopped)
    ims = net.getboolean('ims', True)
    service.stage('data')
    if net.getboolean('data', True) and apn:
        try:
            activate(client, apn, ip_type=ip_type)
        except (RuntimeError, TimeoutError) as failure:  # ModemError too
            if ims:
                raise  # IMS needs the data bearer
            # With two SIMs only the modem's data SIM gets a bearer; calls
            # and texts over CS don't need one.
            print(f'Startup: no data bearer ({failure}); calls and texts still work', flush=True)
    elif apn:
        print('Startup: no data bearer ([network] data = no)', flush=True)
    service.pump()
    if not apn:
        print('Startup: registered for calls and texts (no APN)', flush=True)
        return
    if not ims:
        print('Startup: registered with data; IMS off ([network] ims = no)', flush=True)
        return
    service.stage('ims')
    start_stack(client)
    if net.get('ims_bearer', 'ap') == 'modem':
        register_modem_bearer(client)
    else:
        # 2253 (PDN_IPV6_CALL_DISALLOWED) on raven's network for an IPv6-only IMS bearer.
        activate(client, net.get('ims_apn', 'ims'), ims=True, ip_type=net.get('ims_ip_type', 'ipv6'))
        register(client)
    print('Startup: waiting for IMS voice and SMS registration', flush=True)
    wait_for(service, lambda: service.registration().get('state') == 2 and
             service.registration().get('features', 0) & 3 == 3, 120, stopped)
    print('Startup: LTE, IMS voice and SMS registered', flush=True)
