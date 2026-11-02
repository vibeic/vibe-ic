"""The D30 audit hook must release subprocesses after its module finishes.

Run after test_d30_capture_stamp_order in the same pytest process. Importing
that module keeps the registered hook present when this file runs alone.
"""
import subprocess
import sys

import test_d30_capture_stamp_order as _capture


def test_a_later_module_can_launch_a_benign_subprocess():
    result = subprocess.run([sys.executable, '-c', "print('later module allowed')"],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'later module allowed\n'
