# SPDX-License-Identifier: MIT
"""Where the SIT RIL finds its devices and keeps its files.

Every path can be overridden from the environment, which is how the offline
tests run the whole stack against tools/sit-sim (OMAMOBILE_SIT_DEVICE=unix:...,
OMAMOBILE_SIT_BOOT=none).
"""
import configparser
import os
from pathlib import Path

# Which SIM this sitd instance serves: SIM 1 is modem stack 0 (the original
# paths), SIM 2 is stack 1 with "-2" paths (omamobile-sitd-2.service).
SIM = int(os.environ.get('OMAMOBILE_SIT_SIM', '1'))
SUFFIX = '' if SIM == 1 else f'-{SIM}'

# RAM only: bearer ownership records, the data call's response (addresses),
# the IMS registration record, the socket. Gone at reboot, as the modem's
# own state is.
RUN = Path(os.environ.get('OMAMOBILE_SIT_RUN', f'/run/omamobile-sit{SUFFIX}'))
# Persistent, root-only (0700): received SMS (before they are acknowledged)
# and the apps database. Holds numbers and message text: never copy it into
# the repository or a log.
STATE = Path(os.environ.get('OMAMOBILE_SIT_STATE', f'/var/lib/omamobile-sit{SUFFIX}'))
INBOX = STATE / 'inbox'
CONFIG = Path(os.environ.get('OMAMOBILE_SIT_CONFIG', f'/etc/omamobile/modem-sit{SUFFIX}.conf'))
# The slot table stack 0's instance reads at start-up (card, active,
# logical per physical slot; no identifiers), for every instance's label.
SLOTS = Path(os.environ.get('OMAMOBILE_SIT_SLOTS', '/run/omamobile-sit/slots.json'))

# CPIF's character devices. "unix:PATH" is a SOCK_SEQPACKET socket (the
# simulator); "none" for BOOT means "no CP state ioctl: assume ONLINE".
IPC = os.environ.get('OMAMOBILE_SIT_DEVICE', '/dev/umts_ipc0')
ROUTER = os.environ.get('OMAMOBILE_SIT_ROUTER', '/dev/umts_router')
BOOT = os.environ.get('OMAMOBILE_SIT_BOOT', '/dev/umts_boot0')

DEFAULTS = {
    'network': {'apn': '', 'ip_type': 'ipv4v6', 'ims': 'yes', 'ims_apn': 'ims',
                'nr': 'off', 'sim_timeout': '120', 'register_timeout': '180',
                'radio': 'at', 'sim_slot': '', 'stack': str(SIM - 1), 'stacks': '1', 'label': '', 'data': 'yes',
                'slot_names': '', 'ims_profile': 'no', 'ims_bearer': 'ap', 'ims_ip_type': 'ipv6'},
    'data': {'route': 'yes', 'metric': '700'},
    'control': {'group': 'wheel'},
    'audio': {'card': 'auto', 'mic_boost_db': '6'},
}


# A device package's defaults (e.g. omamobile-device-raven's slot names),
# read before the /etc file, which overrides them.
DEVICE_DEFAULTS = Path(os.environ.get('OMAMOBILE_SIT_DEVICE_DEFAULTS', '/usr/lib/omamobile/modem-sit.d'))


SIMS_CONF = Path(os.environ.get('OMAMOBILE_SIMS_CONF', '/etc/omamobile/sims.conf'))


def data_sim():
    """The data SIM (/etc/omamobile/sims.conf [default] data; SIM 1 if unset)."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(SIMS_CONF)
    try:
        return parser.getint('default', 'data', fallback=1)
    except ValueError:
        return 1


def config(path=None):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_dict(DEFAULTS)
    parser.read(sorted(DEVICE_DEFAULTS.glob('*.conf')) if DEVICE_DEFAULTS.is_dir() else [])
    own = configparser.ConfigParser(interpolation=None)
    own.read(path or CONFIG)
    parser.read(path or CONFIG)
    # With two SIMs only the data SIM asks for packet service; unless this
    # SIM's own file says otherwise, that is the one sims.conf names.
    if not own.has_option('network', 'data'):
        try:
            two = parser.getint('network', 'stacks', fallback=1) > 1
        except ValueError:
            two = False
        if two:
            parser.set('network', 'data', 'yes' if data_sim() == SIM else 'no')
    return parser


def open_channel(path, flags=os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC):
    """A file descriptor for a CPIF channel, or for the simulator's socket."""
    if path.startswith('unix:'):
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        sock.connect(path[5:])
        sock.setblocking(False)
        return sock.detach()
    return os.open(path, flags)


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def slot_name(physical, names=''):
    """A physical slot's name from [network] slot_names (comma-separated,
    in slot order, e.g. "tray, eSIM"), else "slot N" (counting from 1)."""
    listed = [n.strip() for n in names.split(',') if n.strip()]
    return listed[physical] if physical < len(listed) else f'slot {physical + 1}'


def sim_label(stack, settings):
    """How the shell and the CLI name this SIM: [network] label, else
    "SIM n (slot name)" from the slot table, else "SIM n"."""
    net = settings['network']
    if net.get('label', '').strip():
        return net['label'].strip()
    import json
    try:
        slots = json.loads(SLOTS.read_text())
    except (OSError, ValueError):
        slots = []
    for physical, slot in enumerate(slots):
        if slot.get('active') and slot.get('logical') == stack:
            return f"SIM {stack + 1} ({slot_name(physical, net.get('slot_names', ''))})"
    return f'SIM {stack + 1}'


def interface(cid, stack=None):
    """The rmnet link of a bearer: rmnet<CID - 1>, on either modem stack.
    On raven (2026-10-20) SIM 2's internet bearer on stack 1 answered on
    rmnet0, not on the second half of the links that stock's RIL context
    (socket 1's ifstart) suggested. OMAMOBILE_SIT_IFSTART shifts it."""
    return f'rmnet{int(os.environ.get("OMAMOBILE_SIT_IFSTART", "0")) + cid - 1}'
