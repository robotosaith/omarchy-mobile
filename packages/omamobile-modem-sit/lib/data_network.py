#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""omamobile-sit-data: the internet bearer (CID 1) as a fallback behind Wi-Fi.

CPIF's rmnet devices are raw-IP links that NetworkManager doesn't manage
(the package marks rmnet* unmanaged). This owns only rmnet0's /32 address,
a metric-700 default route (Wi-Fi's default is 600, so Wi-Fi wins while it
is up) and the carrier's DNS while rmnet0 is the only way out. All state and
rollback records stay in RAM; nothing here is logged with an address.

The carrier's DNS is used only while rmnet0 is the only way out. A bearer
that sends but receives nothing, and then answers no ping either, loses its
default route, and gets it back as soon as nothing else is left: otherwise a
dead bearer's route plus its DNS can outlive a short Wi-Fi outage, make
NetworkManager's connectivity check fail through it and keep the phone
offline with Wi-Fi up.
"""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

import cp
import paths

# The data SIM's internet bearer (CID 1): rmnet0 on either stack
# (paths.interface).
IF = paths.interface(1)
from data_call import RESPONSE

RESOLVER = Path('/etc/resolv.conf')


def run(*args):
    p = subprocess.run(args, capture_output=True, timeout=20)
    if p.returncode:
        raise RuntimeError('Cellular network operation failed: ' + args[0])
    return p.stdout


def configuration(data):
    if len(data) < 132:
        raise ValueError('Short internet bearer response')
    status, cid, active, pdp = struct.unpack_from('<HBBB', data)
    if status or cid != 1 or active not in (1, 2) or pdp not in (1, 3):
        raise ValueError('An active IPv4 internet bearer is required')
    addr = ipaddress.IPv4Address(data[5:9])
    dns = list(dict.fromkeys(str(ipaddress.IPv4Address(data[i:i+4])) for i in (0x1a, 0x2e) if any(data[i:i+4])))
    if addr.is_unspecified or addr.is_multicast or not dns:
        raise ValueError('Missing internet address or carrier DNS')
    return str(addr), dns


def counters(stats):
    """(received bytes, sent packets) from `ip -j -s link` output for rmnet0."""
    link = stats[0]['stats64']
    return link['rx']['bytes'], link['tx']['packets']


def looks_silent(routed, before, after):
    """The routed bearer sent packets but received nothing since the last
    check. Not proof: a few router solicitations get no answer on a live one."""
    return routed and after[1] > before[1] and after[0] == before[0]


RECOVERY = paths.RUN / 'bearer-recovery'
RECOVERY_GAP = 600


def call_live():
    """Whether this SIM's sitd has a call that isn't over (a restart would
    drop it)."""
    try:
        calls = json.loads((paths.RUN / 'state.json').read_text()).get('calls') or []
    except (OSError, ValueError):
        return False
    return any(c.get('state') != 'terminated' for c in calls)


def recover(now=time.time):
    """A bearer that carries nothing: have this SIM's sitd set up a new one
    (restart its unit; the bearer record of the old run is cleared at its
    start). Never during a call, at most once per RECOVERY_GAP seconds.
    True if a restart was asked for: the caller then exits, and its unit
    starts it again once the new bearer is up. On raven a bearer set up at
    boot sometimes carried nothing until sitd restarted (MODEM-PLAN D3)."""
    if call_live():
        print('Cellular bearer carries nothing; a call is up, so it stays', flush=True)
        return False
    try:
        last = float(RECOVERY.read_text())
    except (OSError, ValueError):
        last = 0
    if now() - last < RECOVERY_GAP:
        return False
    RECOVERY.write_text(str(now()))
    unit = 'omamobile-sitd.service' if paths.SIM == 1 else f'omamobile-sitd-{paths.SIM}.service'
    print(f'Cellular bearer carries nothing; restarting {unit} for a new one', flush=True)
    subprocess.run(['systemctl', 'restart', '--no-block', unit], capture_output=True, timeout=20)
    return True


def guarded(step):
    """One pass of the route watch; the error of a failed or stalled `ip`, or
    None. Such a failure is retried: when this service exits the cellular
    fallback is gone until someone restarts it, and one stalled `ip route`
    must not cost hours without cellular."""
    try:
        step()
    except (subprocess.SubprocessError, RuntimeError, ValueError) as error:
        return error
    return None


def answers():
    """Whether the bearer carries anything: a ping out through rmnet0."""
    for target in ('1.1.1.1', '8.8.8.8'):
        p = subprocess.run(['ping', '-n', '-q', '-c', '1', '-W', '3', '-I', IF, target],
                           capture_output=True, timeout=10)
        if p.returncode == 0:
            return True
    return False


class Resolver:
    """The carrier's DNS in /etc/resolv.conf while cellular is the only way
    out; the previous file comes back unless something (NetworkManager) has
    written a newer one meanwhile."""
    def __init__(self, path):
        self.path = path.resolve()
        self.original = None
        self.owned = None

    def update(self, cellular, servers):
        if cellular:
            content = '# Omarchy Mobile cellular fallback (session only)\n' + ''.join('nameserver ' + s + '\n' for s in servers)
            current = self.path.read_text()
            if self.owned is None or current != self.owned:
                self.original = current
            if current != content:
                self.path.write_text(content)
            self.owned = content
        else:
            self.restore()

    def restore(self):
        if self.owned is not None:
            if self.path.read_text() == self.owned:
                self.path.write_text(self.original)
            self.owned = None


class ResolvedLink:
    """The same with systemd-resolved: rmnet0's DNS servers are set once and
    the link is the default DNS route only while cellular is the only way out."""
    def __init__(self, servers):
        run('resolvectl', 'dns', IF, *servers)
        self.cellular = None

    def update(self, cellular, servers):
        if cellular != self.cellular:
            run('resolvectl', 'default-route', IF, 'yes' if cellular else 'no')
            self.cellular = cellular

    def restore(self):
        subprocess.run(['resolvectl', 'revert', IF], capture_output=True, timeout=20)


def resolver_for(servers):
    target = str(RESOLVER.resolve()) if RESOLVER.exists() else ''
    if target.startswith('/run/systemd/resolve/'):
        return ResolvedLink(servers)
    return Resolver(RESOLVER)


def wait_for_bearer(seconds):
    deadline = time.monotonic() + seconds
    while not RESPONSE.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError('No internet bearer: omamobile-sitd has not set one up')
        time.sleep(1)


def main():
    os.umask(0o077)
    lock = os.open(paths.RUN / 'data-network.lock', os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    wait_for_bearer(60)
    address, dns = configuration(RESPONSE.read_bytes())
    info = json.loads(run('ip', '-j', 'address', 'show', 'dev', IF))[0]
    if 'UP' in info['flags'] or info['addr_info']:
        raise RuntimeError(f'{IF} already configured; refusing to replace it')
    resolver = resolver_for(dns)
    stopping = False
    renew = False
    addressed = False

    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        run('ip', 'link', 'set', 'dev', IF, 'up')
        run('ip', 'addr', 'add', address + '/32', 'dev', IF)
        addressed = True
        run('ip', 'route', 'add', 'default', 'dev', IF, 'src', address, 'metric', '700')
        print('Cellular fallback ready; Wi-Fi remains preferred', flush=True)
        last = None
        seen = counters(json.loads(run('ip', '-j', '-s', 'link', 'show', 'dev', IF)))
        check_at = time.monotonic() + 30
        probed = False

        def watch():
            nonlocal last, seen, check_at, probed, renew, stopping
            routes = json.loads(run('ip', '-j', 'route', 'show', 'default'))
            routed = any(r.get('dev') == IF for r in routes)
            others = [r for r in routes if r.get('dev') != IF]
            # With Wi-Fi up but rated limited, the carrier's DNS would keep
            # NetworkManager's own check failing and Wi-Fi penalised.
            cellular = routed and not others
            resolver.update(cellular, dns)
            if cellular != last:
                print('Default internet path', 'cellular' if cellular else 'Wi-Fi/other', flush=True)
                last = cellular
            if not routed and not others:
                run('ip', 'route', 'add', 'default', 'dev', IF, 'src', address, 'metric', '700')
                print('Nothing else leads out; the cellular default route is back', flush=True)
            elif time.monotonic() >= check_at:
                now = counters(json.loads(run('ip', '-j', '-s', 'link', 'show', 'dev', IF)))
                # Once, 30 s in, whatever the route: a dead bearer from boot
                # would otherwise only show when Wi-Fi goes.
                first = not probed
                probed = True
                if (first or looks_silent(routed, seen, now)) and not answers():
                    if recover():
                        renew = True
                        stopping = True
                        return
                    if routed:
                        run('ip', 'route', 'del', 'default', 'dev', IF, 'metric', '700')
                        print('Cellular bearer carries nothing; its default route is removed', flush=True)
                    now = counters(json.loads(run('ip', '-j', '-s', 'link', 'show', 'dev', IF)))
                seen = now
                check_at = time.monotonic() + 30
        failing = None
        while not stopping and cp.online() and RESPONSE.exists():
            error = guarded(watch)
            if error and not failing:
                print('Network check failed, retrying:', type(error).__name__, flush=True)
            elif failing and not error:
                print('Network checks work again', flush=True)
            failing = error
            time.sleep(2 if error else .5)
    finally:
        resolver.restore()
        routes = json.loads(run('ip', '-j', 'route', 'show', 'default'))
        if any(r.get('dev') == IF and r.get('metric') == 700 for r in routes):
            run('ip', 'route', 'del', 'default', 'dev', IF, 'metric', '700')
        if addressed:
            run('ip', 'addr', 'del', address + '/32', 'dev', IF)
        run('ip', 'link', 'set', 'dev', IF, 'down')
        os.close(lock)
        print('Cellular fallback configuration removed', flush=True)
    if renew or not stopping:
        # Non-zero: the bearer was renewed, or it went away (sitd restarted,
        # the CP left ONLINE). The unit (Restart=on-failure) brings this back
        # on the next bearer, and the owner's "data on" stays remembered.
        sys.exit(3)


if __name__ == '__main__':
    main()
