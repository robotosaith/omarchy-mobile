# SPDX-License-Identifier: MIT
"""Modem setup that differs between phones, set in [network]:

  sim_slot  the physical slot logical SIM 0 uses (raven: 0 the tray, 1 the
            eSIM). Empty leaves the modem's own mapping (cheetah).
  radio     "at" switches the radio with AT+CFUN (cheetah), "sit" with SIT
            SET_RADIO_POWER after SET_MODEM_CONFIG 1, as stock's RIL does:
            raven's modem didn't search for a network after AT+CFUN=1 and
            registered on LTE three seconds after the SIT sequence.

All of it lives in the modem's RAM (its NV is a RAM copy), so a reboot
restores the defaults and the start-up sends it every time.
"""
import struct
import time

import at
from sit import ModemError

# GET_SLOT_STATUS, the 0x111-byte reply (stock's legacy format, read by
# fillSlotStatusDataFromModemData): a count, then 65 bytes per slot: card
# state, slot state, ATR length and ATR, the logical slot at +0x24 (0xff:
# none), the ICCID's length and bytes. Only the states are read here.
SLOT_ENTRY = 65


def slot_status(client):
    reply = client.request(0x024d, timeout=10)
    count = reply[0] if reply else 0
    if not 0 < count <= 4 or len(reply) < 1 + count * SLOT_ENTRY:
        raise RuntimeError('Unexpected SIM slot status layout')
    slots = []
    for i in range(count):
        entry = reply[1 + i * SLOT_ENTRY:1 + (i + 1) * SLOT_ENTRY]
        slots.append(dict(card=entry[0] == 1, active=entry[1] == 1,
                          logical=None if entry[0x24] == 0xff else entry[0x24]))
    return slots


def publish_slots(slots):
    """The slot table for every instance's SIM label (world-readable: card,
    active and logical slot only)."""
    import json
    import paths
    try:
        paths.SLOTS.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.SLOTS.with_suffix('.tmp')
        tmp.write_text(json.dumps(slots))
        tmp.chmod(0o644)
        tmp.replace(paths.SLOTS)
    except OSError:
        pass


def read_slots(client, wait=30, sleep=time.sleep):
    """GET_SLOT_STATUS, published. Right after the modem boots the report is
    empty or refused for a few seconds (as select_slot waits out): retry for
    up to `wait` seconds; a failure only costs the SIM labels."""
    deadline = time.monotonic() + wait
    while True:
        try:
            slots = slot_status(client)
            break
        except RuntimeError:  # ModemError too
            if time.monotonic() > deadline:
                print('SIM slots: no usable report; the SIM labels stay plain', flush=True)
                return None
            sleep(2)
    print('SIM slots (card, active, logical):',
          [(x['card'], x['active'], x['logical']) for x in slots], flush=True)
    publish_slots(slots)
    return slots


def mapping(physical, logical=0):
    """SET_LOGICAL_TO_PHYSICAL_SLOT_MAPPING's payload. The tray (0) as
    logical 0 alone is what registered (2026-10-17). Another slot gets the
    full two-entry mapping, as Android sends it: mapping only logical 0 to
    the eSIM left the modem refusing SET_PS_SERVICE and never searching
    (2026-10-20), as if logical 1 still held the eSIM."""
    if physical == 0 and logical == 0:
        return bytes([1, 0])
    entries = [1 - physical, 1 - physical]
    entries[logical] = physical
    return bytes([2] + entries)


def select_slot(client, physical, logical=0, wait=60, sleep=time.sleep):
    """Map a logical SIM (the stack sitd talks to) to a physical slot (SET_LOGICAL_TO_PHYSICAL_SLOT_MAPPING).

    Right after the modem boots, the slot report is empty or unusable for a
    few seconds; while a switch is still settling the modem refuses another
    with error 7. Both are waited out, up to `wait` seconds."""
    deadline = time.monotonic() + wait
    def settled():
        while True:
            try:
                return slot_status(client)
            except RuntimeError:  # ModemError too
                if time.monotonic() > deadline:
                    raise
                sleep(2)
    slots = settled()
    # Card, active and logical slot only: never ICCIDs or labels.
    print('SIM slots (card, active, logical):',
          [(x['card'], x['active'], x['logical']) for x in slots], flush=True)
    publish_slots(slots)
    if not 0 <= physical < len(slots):
        raise ValueError(f'sim_slot {physical}: the modem has {len(slots)} slots')
    if not slots[physical]['card']:
        raise RuntimeError(f'No card in physical SIM slot {physical}')
    if slots[physical]['active'] and slots[physical]['logical'] == logical:
        print(f'SIM slot {physical} already in use', flush=True)
        return False
    while True:
        try:
            client.request(0x0250, mapping(physical, logical), timeout=15)
            break
        except ModemError as failure:
            if failure.error != 7 or time.monotonic() > deadline:
                raise
            # a switch in progress: in use once it settles
            sleep(2)
            slots = settled()
            if slots[physical]['active'] and slots[physical]['logical'] == logical:
                print(f'SIM slot {physical} in use after a switch in progress', flush=True)
                return True
    print(f'SIM: logical slot {logical} -> physical slot {physical}', flush=True)
    return True


def modem_config(client, stacks=1):
    # SET_MODEM_CONFIG: the number of active modem stacks (stock's
    # SetModemsConfig: 1, or 2 on a dual-SIM phone).
    client.request(0x093f, bytes([stacks]), timeout=10)


def activate_subscription(client):
    """SET_UICC_SUBSCRIPTION 1: activate the SIM's subscription on this
    stack (stock's ProtocolSimBuilder::BuildSetUicc: one u8 after the
    header). Android sends it for each SIM it brings up; without it raven's
    eSIM stayed unregistered and never searched (2026-10-20). A refusal is
    logged, not fatal: a stack that is already active may refuse it."""
    try:
        client.request(0x0249, bytes([1]), timeout=15)
        print('SIM subscription activated', flush=True)
    except ModemError as failure:
        print(f'SIM subscription activation refused ({failure})', flush=True)


def preferred_data_modem(client, stack):
    """SET_PREFERRED_DATA_MODEM (stock's ProtocolPsBuilder::
    BuildSetPreferredDataModem: one u8, the modem stack). With both stacks
    active only this stack gets packet service: on raven SIM 1 came up
    first and SIM 2 (the data SIM) then never searched (2026-10-20). A
    refusal is logged."""
    try:
        client.request(0x0740, bytes([stack]), timeout=15)
        print(f'Preferred data modem: stack {stack}', flush=True)
    except ModemError as failure:
        print(f'SET_PREFERRED_DATA_MODEM {stack} refused ({failure})', flush=True)


def preferred_type(client, wanted):
    """GET/SET_PREFERRED_NTW_TYPE (u32; RIL's types, identity for 0-12).
    The type is kept per modem stack: raven's had 38 (2026-10-16), and
    the eSIM's stack scanned only UMTS and GSM (2026-10-20). 9 is
    LTE/GSM/WCDMA. Returns the type found."""
    reply = client.request(0x070b)
    current = struct.unpack_from('<I', reply)[0] if len(reply) >= 4 else None
    print('Preferred network type:', current, flush=True)
    if current != wanted:
        client.request(0x070a, struct.pack('<I', wanted), timeout=15)
        print('Preferred network type set to', wanted, flush=True)
    return current


def switch_radio(client, net, on):
    if net.get('radio', 'at') == 'sit':
        # SET_RADIO_POWER: u32 2 on, 1 off; not for an emergency call.
        client.request(0x0800, struct.pack('<IBB', 2 if on else 1, 0, 0), timeout=30)
    else:
        at.radio(on)


def sms_memory_available(client):
    # SEND_SMS_MEM_STATUS, u32 1 = room for texts. Stock reports it when the
    # radio comes on; until it does, the network may hold incoming texts.
    client.request(0x010a, struct.pack('<I', 1), timeout=15)
