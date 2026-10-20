# SPDX-License-Identifier: MIT
"""Data-call layouts (the stock 983-byte version-2 setup request) and an
owned bearer lifecycle: CID 1 (internet, rmnet0) and CID 2 (IMS, rmnet1).

The APN comes from /etc/omamobile/modem-sit.conf. Ownership is recorded in
RAM before a setup is sent: a setup or release with an unknown outcome
keeps its record and its PDU session, and nothing is retried blindly.
"""
import json
import os
from pathlib import Path
import re
import struct

from paths import RUN

STATE = RUN / 'data-session.json'
RESPONSE = RUN / 'data-call-response.bin'
# IP types in SETUP_DATA_CALL and the data profile.
IP_TYPES = {'ipv4': 1, 'ipv6': 2, 'ipv4v6': 3}


def paths(cid):
    if cid == 1:
        return STATE, RESPONSE
    if cid == 2:
        return STATE.with_name('ims-session.json'), RESPONSE.with_name('ims-response.bin')
    raise ValueError('unsupported bearer CID')


def check_apn(apn):
    """An APN as a carrier publishes it: labels of letters, digits and '-',
    joined by dots, at most 99 characters (the request's field is 100 bytes)."""
    if not isinstance(apn, str) or not re.fullmatch(r'[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*', apn) \
            or len(apn) > 99:
        raise ValueError('APN missing or not a plain carrier APN; set [network] apn')
    return apn


def call_ids(payload):
    # Stock DataCallUtil::DetermineDCTypeBySize. Reject variable
    # traffic-descriptor records until their full framing is implemented.
    if not payload or payload[0] > 15:
        raise RuntimeError('invalid data-call list')
    count = payload[0]
    if count == 0:
        if len(payload) != 1:
            raise RuntimeError('unexpected empty data-call list')
        return set()
    size, remainder = divmod(len(payload) - 1, count)
    if remainder or size not in (132, 234, 239, 246, 280, 292):
        raise RuntimeError('unsupported data-call list layout')
    cids = [payload[1 + index * size + 2] for index in range(count)]
    if len(set(cids)) != count or any(not 1 <= cid <= 15 for cid in cids):
        raise RuntimeError('invalid or duplicate data-call CID')
    return set(cids)


def owned_ids():
    result = set()
    for cid in (1, 2):
        state, _ = paths(cid)
        if state.exists():
            owned = json.loads(state.read_text())
            if owned.get('cid') != cid or not 1 <= owned.get('session', 0) <= 15:
                raise RuntimeError('invalid bearer ownership record')
            result.add(cid)
    return result


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)


def setup_payload(cid, radio_technology, pdu_session, apn, *, ims=False, ip_type=None):
    ip_type = ip_type or ('ipv6' if ims else 'ipv4v6')
    # Absolute request offsets below include the 12-byte request header.
    check_apn(apn)
    full = bytearray(983)
    full[12] = cid
    full[13] = radio_technology
    full[14] = 0  # stock converter: only tethering maps to 1
    full[15] = 1 if ims else 0  # IMS/default APN type
    encoded = apn.encode('ascii')
    full[16:16 + len(encoded)] = encoded
    full[0xd9] = 0  # no authentication
    full[0xda] = IP_TYPES[ip_type]  # IMS: [network] ims_ip_type (ipv6 by default)
    full[0xdb] = 2 if ims else 0  # IPv6 P-CSCF request
    # No handover addresses, roaming override or slice.
    # MTU at 0xf1 stays zero (network/default choice).
    full[0xf5] = 2  # stock caller selects the v3/983-byte form
    struct.pack_into('<i', full, 0xf6, pdu_session)
    # No requested network slice: SST 0, SD -1, mapped SST 0, mapped SD -1.
    struct.pack_into('<i', full, 0xfc, -1)
    struct.pack_into('<i', full, 0x101, -1)
    full[0x105] = 1  # match-all rule allowed, no traffic descriptor supplied
    return bytes(full[12:])


def initial_attach(client, apn, ip_type='ipv4v6'):
    """SET_INITIAL_ATTACH_APN (251 bytes). Without it, setup requests on this
    phone returned status 36 and no bearer."""
    attach = bytearray(251)
    attach[12:245] = setup_payload(1, 14, 1, apn, ip_type=ip_type)[:233]
    attach[0xf8] = 3
    client.request(0x0603, bytes(attach[12:]), timeout=30)


def allow_data(client):
    previous = client.request(0x0711)
    print('PS service permission before', previous[0] if len(previous) == 1 else 'unexpected', flush=True)
    client.request(0x0625, b'\x01\x00')
    client.request(0x0710, b'\x01')
    if client.request(0x0711) != b'\x01':
        raise RuntimeError('PS service permission is not enabled')
    print('PS service permission enabled', flush=True)


# Android's data profile IDs and APN-type bits (ApnSetting): default 0, IMS 2.
PROFILE_DEFAULT, PROFILE_IMS = 0, 2
APN_TYPE_DEFAULT, APN_TYPE_IMS = 1, 64


def provision_profile(client, apn, ip_type='ipv4v6', *, profile=PROFILE_DEFAULT,
                      types=APN_TYPE_DEFAULT, name='default'):
    # Stock BuildSetDataProfile, 246-byte request, one profile per request.
    # This configures the network APN profile, not a SIM subscription or UICC
    # operation.
    encoded = check_apn(apn).encode('ascii')
    full = bytearray(246)
    struct.pack_into('<I', full, 12, profile)  # Android profile ID
    full[16:16 + len(encoded)] = encoded
    full[0x75] = full[0x76] = IP_TYPES[ip_type]  # home/roaming IP type
    full[0xe9] = 1  # enabled
    struct.pack_into('<I', full, 0xea, types)  # APN-type bitmap
    client.request(0x0613, bytes(full[12:]), timeout=30)
    print(name, 'data profile accepted', flush=True)


def provision_default_profile(client, apn, ip_type='ipv4v6'):
    provision_profile(client, apn, ip_type)


def provision_ims_profile(client, apn='ims', ip_type='ipv4v6'):
    # Stock Android hands the modem every carrier profile, IMS's among them.
    # Without it raven's modem refused the IMS bearer with status 2253
    # (COMPANION_IFACE_IN_USE): it had only the internet profile to use.
    provision_profile(client, apn, ip_type, profile=PROFILE_IMS, types=APN_TYPE_IMS, name='IMS')


def activate(client, apn, *, ims=False, ip_type=None, lte_access=False):
    ip_type = ip_type or ('ipv6' if ims else 'ipv4v6')
    requested_cid = 2 if ims else 1
    state_path, response_path = paths(requested_cid)
    state = client.request(0x0701)
    if len(state) < 4 or state[0] not in (1, 5):
        raise RuntimeError('PS network is not registered')
    calls = call_ids(client.request(0x0602))
    owned = owned_ids()
    if not ims and state_path.exists() and requested_cid not in calls:
        # A record from a previous run whose bearer the modem no longer
        # lists (the restart cycled the radio): release its PDU session and
        # drop it.
        try:
            session = json.loads(state_path.read_text()).get('session', 0)
            if 1 <= session <= 15:
                client.request(0x061b, struct.pack('<i', session))
        except (OSError, ValueError, RuntimeError, TimeoutError):
            pass
        state_path.unlink(missing_ok=True)
        response_path.unlink(missing_ok=True)
        print(f'Stale data bearer record CID {requested_cid} cleared', flush=True)
        owned = owned_ids()
    if not ims and state_path.exists() and requested_cid in calls and calls == owned:
        # sitd restarted: the bearer from its previous run is still up and
        # still ours (the run directory is preserved). Keep it.
        print(f'Data bearer CID {requested_cid} from the previous run kept', flush=True)
        return None
    if state_path.exists() or requested_cid in calls or calls != owned:
        raise RuntimeError('existing target or unresolved bearer ownership')
    allow_data(client)
    allocated = client.request(0x061a)
    if len(allocated) != 4:
        raise RuntimeError('unexpected PDU-session response')
    session = struct.unpack('<i', allocated)[0]
    if not 1 <= session <= 15:
        raise RuntimeError('invalid PDU session')
    if any(json.loads(paths(cid)[0].read_text())['session'] == session for cid in owned):
        # Never release a duplicate allocation belonging to the other bearer.
        raise RuntimeError('modem reused an owned PDU session')
    # Persist ownership before setup. A timeout has an unknown outcome; do
    # not recycle its PDU session while the modem may still be activating it.
    try:
        private_write(state_path, json.dumps({'cid': requested_cid, 'session': session}).encode())
    except OSError:
        client.request(0x061b, struct.pack('<i', session))
        raise
    released = False
    try:
        rat = 14 if lte_access else state[3]
        print('data setup access RAT', rat, 'registered RAT', state[3], flush=True)
        result = client.request(0x0600, setup_payload(requested_cid, rat, session, apn,
                                                      ims=ims, ip_type=ip_type), timeout=45)
        if len(result) < 132:
            raise RuntimeError('unexpected data-call layout')
        status, cid, raw_active, pdp = struct.unpack_from('<HBBB', result)
        print('data-call status', status, 'CID', cid, 'active raw', raw_active, 'PDP type', pdp, flush=True)
        if cid == requested_cid and raw_active == 0:
            client.request(0x061b, struct.pack('<i', session))
            released = True
        if status or cid != requested_cid or raw_active not in (1, 2):
            raise RuntimeError('data call did not become active')
        private_write(response_path, result)
        print('owned data bearer active; private IP configuration retained in RAM', flush=True)
        if ims:
            # Base response layout: family then 3 v4 and 3 v6 P-CSCF
            # addresses. Report presence only, never their values.
            print('IMS IPv6 present', any(result[9:25]),
                  'P-CSCF family', result[0x42],
                  'base IPv6 P-CSCF count', sum(bool(any(result[i:i+16])) for i in (0x4f, 0x5f, 0x6f)), flush=True)
    finally:
        if released:
            state_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)


def deactivate(client, cid=1):
    state_path, response_path = paths(cid)
    if cid == 2 and state_path.with_name('ims-registration.json').exists():
        raise RuntimeError('unregister IMS before releasing its bearer')
    owned = json.loads(state_path.read_text())
    if owned.get('cid') != cid or not 1 <= owned.get('session', 0) <= 15:
        raise RuntimeError('invalid bearer ownership record')
    import paths as sit_paths
    flags = int(Path(f"/sys/class/net/{sit_paths.interface(owned['cid'])}/flags").read_text(), 16)
    if flags & 1:
        raise RuntimeError('remove host data configuration first')
    # Stock BuildDeactDataCall: CID and normal-release reason.
    client.request(0x0601, bytes([owned['cid'], 0]), timeout=30)
    calls = call_ids(client.request(0x0602))
    if cid in calls:
        raise RuntimeError('deactivated bearer still listed; retaining reservation')
    client.request(0x061b, struct.pack('<i', owned['session']))
    state_path.unlink()
    response_path.unlink(missing_ok=True)
    if calls != owned_ids():
        raise RuntimeError('unexpected remaining data-call ownership')
    print('owned data bearer deactivated; PDU session released', flush=True)
