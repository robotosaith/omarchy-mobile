# SPDX-License-Identifier: MIT
"""CS voice call layouts ([network] ims = no), as stock's ProtocolCallBuilder
and ProtocolGetCurrentCallAdapter build and read them.

On raven the network refuses the IMS bearer, so calls go over the CS domain:
DIAL (0x0001), ANSWER (0x0004), HANGUP (0x0008), DTMF (0x0003). The modem
announces every change with IND_CALL_STATE_CHANGED (0x0009, no payload) and
the state is read back with GET_CURRENT_CALLS (0x0000).
"""
import struct

# GET_CURRENT_CALLS entry sizes: stock's V1_1, V1_2 and V1_6 layouts share
# the fields read here (raven's modem answers with 364-byte entries).
ENTRY_SIZES = (327, 331, 364)
# SIT call states; the same numbers as RIL's: active, holding, dialing,
# alerting, incoming, waiting.
STATES = {0: 'active', 1: 'held', 2: 'dialing', 3: 'ringing-out', 4: 'ringing-in', 5: 'waiting'}
# Entry byte 12, the call type: stock's table of the types that are voice.
VOICE = (1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 1)


def dial_payload(destination):
    """DIAL: voice (SIT 1), the number (at most 82 bytes) with its type of
    number (0x10 international with a leading "+", 0x20 unknown), ISDN
    numbering plan, the network's default CLIR; no UUS, no emergency."""
    number = destination.encode('ascii')
    if not 1 <= len(number) <= 82:
        raise ValueError('invalid number length')
    payload = bytearray(92)
    payload[0] = 1
    payload[2] = len(number)
    payload[3:3+len(number)] = number
    payload[85] = 0x10 if number.startswith(b'+') else 0x20
    payload[86] = 1
    return bytes(payload)


def hangup_payload(index):
    """HANGUP: the call's index, then 1 (one call; 2 hangs up a conference)."""
    return struct.pack('<II', index, 1)


def dtmf_payload(keys):
    """DTMF: a length byte, then up to 64 ASCII tones."""
    tones = keys.encode('ascii')
    if not 1 <= len(tones) <= 64:
        raise ValueError('invalid touch tones')
    return bytes([len(tones)]) + tones.ljust(64, b'\0')


def call_list(reply):
    """GET_CURRENT_CALLS: a u32 count, then one entry per call. Returns a
    dict per voice call: index, state (name), incoming, multiparty, number."""
    if len(reply) < 4:
        raise ValueError('short call list')
    count = struct.unpack_from('<I', reply)[0]
    if not count:
        return []
    size = (len(reply) - 4) // count
    if count > 8 or size not in ENTRY_SIZES or len(reply) != 4 + count * size:
        raise ValueError('unexpected call list layout')
    calls = []
    for i in range(count):
        entry = reply[4 + i * size:4 + (i + 1) * size]
        if entry[0] not in STATES or (entry[12] < len(VOICE) and not VOICE[entry[12]]):
            continue
        length = min(entry[14], 82)
        number = entry[15:15+length].rstrip(b'\0').decode('ascii', errors='replace')
        if number and struct.unpack_from('<I', entry, 5)[0] == 0x91 and not number.startswith('+'):
            number = '+' + number
        calls.append(dict(index=struct.unpack_from('<I', entry, 1)[0], state=STATES[entry[0]],
                          incoming=entry[10] == 1, multiparty=entry[9] == 1, number=number))
    return calls
