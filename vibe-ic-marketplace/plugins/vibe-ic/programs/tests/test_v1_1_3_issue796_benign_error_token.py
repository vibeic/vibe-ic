"""ORGANIC #796 — harness_exact_selfverify Gate C misclassified a benign
lowercase `error` word in a PASSING TB line as a FAIL token, so the SOLE EMIT
PATH silently dropped scorer-PASSING RTL.

`_TB_FAIL_RE` matched `\\bERROR\\b` (IGNORECASE) and `_tb_verdict` checked FAIL
before PASS, so `TEST PASSED: error count = 0` resolved FAIL. Fix: the FAIL
tokens are STRUCTURAL/NONZERO only (`$error`/`$fatal`/`FATAL`, `errors: <nonzero>`,
`<nonzero> errors`, a verdict banner); a clear PASS banner wins over a bare
uppercase ERROR mention; a zero count never blocks.

§4.05 no-leak: a genuinely failing TB (nonzero count / `$error` / `FATAL` /
`FAILED` / bare uppercase ERROR with no PASS) still BLOCKs. chip-AGNOSTIC.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import harness_exact_selfverify as H  # noqa: E402


@pytest.mark.parametrize("s", [
    "TEST PASSED: error count = 0\n",
    "error-flag asserted, then deasserted; test PASSED\n",
    "no errors\nTEST PASSED\n",
    "errors == 0\nALL TESTS PASSED\n",
])
def test_796_benign_error_resolves_pass(s):
    assert H._tb_verdict(s)[0] is True, s


@pytest.mark.parametrize("s", [
    "3 errors\nTEST FAILED\n",
    "errors: 5\n",
    "$error triggered\n",
    "$fatal(1)\n",
    "FATAL: bad state\n",
    "ERROR\n",            # bare UPPERCASE banner, no PASS context
    "  FAIL  \n",
])
def test_796_noleak_genuine_failure_still_blocks(s):
    assert H._tb_verdict(s)[0] is False, s


def test_796_pass_banner_wins_over_bare_uppercase_error_mention():
    # an `ERROR-flag` status noun followed by a PASS banner is a PASS.
    assert H._tb_verdict("ERROR flag toggled\nTEST PASSED\n")[0] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
