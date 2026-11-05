"""Focused runner schedule controls; no analog/native verdict is measured.

The checks prove dispatch ordering and test-producer timing only. They do not
establish a typed-current A7-to-A8 consumer binding; that remains unresolved.
"""
import os
from pathlib import Path
import sys
import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS.parent))

import analog_one_shot_runner as runner
import execution_policy as policy
from programs.tests import test_execution_receipt_chain as live


@pytest.fixture(autouse=True)
def isolated_execution(monkeypatch):
    saved_runtime = policy._ordinary_runtime
    names = (policy.ENV, policy._CAPABILITY_FD_ENV, 'VIBEIC_EXECUTION_AUTH_SOCKET')
    saved_environment = {name: os.environ.get(name) for name in names}
    for name in names:
        monkeypatch.delenv(name, raising=False)
    policy._ordinary_runtime = None
    yield
    for proc, fd, channel in live._launchers:
        channel.close()
        proc.wait(timeout=10)
        if proc.stderr:
            proc.stderr.close()
        try:
            os.close(fd)
        except OSError:
            pass
    live._launchers.clear()
    policy._ordinary_runtime = saved_runtime
    # Close this fixture's issuer transport without leaking its closed FD.
    for name, value in saved_environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _source_regions():
    source = Path(runner.__file__).read_text()
    body = source[source.index("    if execution.request()['mode'] == 'ultra':"):]
    ultra, default = body.split("    else:\n        # Default deliberately", 1)
    default = default.split("    # q5 — A9's co-simulation", 1)[0]
    return ultra, default


def test_two_block_schedule_is_ultra_step_major_and_default_block_major():
    ultra, default = _source_regions()
    ultra_steps = ('"A1"', '"A2"', '"A3"', '"A4"', '"A5"',
                   '"A6"', '"A7"', '"A8"', '"A9"')
    positions = [ultra.index(step) for step in ultra_steps]
    assert positions == sorted(positions)
    # Ultra gets all upstream opportunities first, then each unified row gets
    # its whole block population before the next row.
    assert ultra.count('for blk in blocks:') == 5
    default_steps = ('"A1"', '"A2"', '"A3"', '"A4"', '"A5"',
                     '"A6"', '"A7"', '"A8"', '"A9"')
    positions = [default.index(step) for step in default_steps]
    assert positions == sorted(positions)
    # Default contract migration: each complete row now owns all blocks.
    assert default.count('for blk in blocks:') == 9
    # A one-element declared list follows the same loops; no second runner or
    # special multi-block-only state is introduced.
    assert 'for blk in blocks:' in ultra
