# SPDX-License-Identifier: MIT
"""Imported first by every test: the library on sys.path, and every path the
library uses moved into a private temporary directory (no /run, /var or
device access from the tests)."""
import atexit
import os
import shutil
import sys
import tempfile

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib')
TMP = tempfile.mkdtemp(prefix='omamobile-sit-test-')
atexit.register(shutil.rmtree, TMP, True)
os.environ.update({
    'OMAMOBILE_SIT_RUN': os.path.join(TMP, 'run'),
    'OMAMOBILE_SIT_STATE': os.path.join(TMP, 'state'),
    'OMAMOBILE_SIT_CONFIG': os.path.join(TMP, 'modem-sit.conf'),
    'OMAMOBILE_SIT_DEVICE': 'unix:' + os.path.join(TMP, 'ipc0'),
    'OMAMOBILE_SIT_ROUTER': 'unix:' + os.path.join(TMP, 'router'),
    'OMAMOBILE_SIT_BOOT': 'none',
    'OMAMOBILE_SIT_SLOTS': os.path.join(TMP, 'run', 'slots.json'),
    'OMAMOBILE_SIT_SIM': '1',
    'OMAMOBILE_SIMS_CONF': os.path.join(TMP, 'sims.conf'),
    'OMAMOBILE_SIT_DEVICE_DEFAULTS': os.path.join(TMP, 'modem-sit.d'),
})
os.makedirs(os.path.join(TMP, 'run'), mode=0o700)
if LIB not in sys.path:
    sys.path.insert(0, os.path.abspath(LIB))
