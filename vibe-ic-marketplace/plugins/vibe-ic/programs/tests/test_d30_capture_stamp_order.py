"""Selected handoff capture ordering with real static producers and consumers.

Neutral subject/upstream readsets are explicit doubles, never native LEC/STA
qualification. The normal gate, capture, stamps, publishers, strict handoff
reader, delivery producer and chain reader execute without substitutes.
Native dispatch is forbidden during this module's fixture and test lifetime.
"""
import subprocess
import sys

import pytest

_native_guard_active = False




sys.addaudithook(no_native)


@pytest.fixture(scope='module', autouse=True)
def _native_guard():
    global _native_guard_active
    _native_guard_active = True
    try:
        yield
    finally:
        _native_guard_active = False
















def test_unapproved_dispatch_is_forbidden_during_this_module():
    with pytest.raises(AssertionError, match='Native/proof/STA/global dispatch forbidden'):
        subprocess.run([sys.executable, '-c', "print('must not execute')"],
                       capture_output=True, text=True, timeout=10)
