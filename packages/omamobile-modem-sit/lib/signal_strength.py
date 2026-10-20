# SPDX-License-Identifier: MIT
"""GET_SIGNAL_STRENGTH (0x0900) as 0-4 bars, and a RAT's generation label.

The 198-byte reply, read from raven's S5123 (2026-10-20) next to AT+CSQ and
the registration state, since the per-RAT layouts in the research note were
low confidence: byte 0 says which blocks are filled (1 GSM, 4 LTE); the GSM
level (0-31, as AT+CSQ) is a u32 at 2; the LTE block is packed u32s from 62:
level (0-31), RSRP and RSRQ as positive dB values, RSSNR in 0.1 dB, CQI,
timing advance. Bars follow Android's defaults (LTE by RSRP -128/-118/-108/
-98 dBm; GSM by level 5/8/12)."""
import struct

GSM, LTE = 0x01, 0x04


def fields(payload):
    """The values this reads, or {} for a short or empty reply."""
    if len(payload) < 86:
        return {}
    kinds = payload[0]
    out = {}
    if kinds & GSM:
        out['gsm_level'] = struct.unpack_from('<I', payload, 2)[0]
    if kinds & LTE:
        level, rsrp, rsrq, snr = struct.unpack_from('<IIIi', payload, 62)
        out.update(lte_level=level, rsrp=-rsrp if rsrp else None, rsrq=-rsrq if rsrq else None,
                   snr=snr / 10)
    return out


def bars(payload):
    """0-4 signal bars."""
    f = fields(payload)
    rsrp = f.get('rsrp')
    if rsrp is not None and -140 <= rsrp <= -44:
        return sum(rsrp >= t for t in (-128, -118, -108, -98))
    level = f.get('gsm_level')
    if level is not None and 0 < level <= 31:
        return 1 + sum(level >= t for t in (5, 8, 12))
    return 0


GENERATIONS = {'LTE': '4G', 'LTE-CA': '4G', 'NR': '5G', 'HSPA+': '3G', 'HSPA': '3G',
               'HSDPA': '3G', 'HSUPA': '3G', 'UMTS': '3G', 'TD-SCDMA': '3G',
               'EDGE': '2G', 'GPRS': '2G', 'GSM': '2G'}


def generation(rat):
    """'4G', '3G', ... for a RAT name from the registration state, or ''."""
    return GENERATIONS.get(rat or '', '')
