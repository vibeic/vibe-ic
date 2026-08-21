"""`_gate_usage_exit` must keep a bad command line off the VACUOUS tier.

`_gate_invocation` measured the cost of the collision it removes: of 241
registered structural gates driven by the P0 umbrella, 39 never got past
argument parsing and every one of them was recorded as a benign input-missing
skip, because argparse and the skip tier share exit code 2.

This file asserts the three properties the five Bucket-A gates depend on:
argparse's rejection exits 3, every internal argparse exit of 2 is remapped, and
`--help` still exits 0.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/<this file>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _gate_usage_exit as U          # noqa: E402
import _vacuous_exit as V             # noqa: E402


def _parser():
    p = U.GateArgumentParser(prog="probe")
    p.add_argument("--needed", required=True)
    return p


def test_the_usage_code_is_not_the_vacuous_code():
    """The whole point, stated as an assertion so a future edit to either
    constant reddens instead of silently re-creating the collision."""
    assert U.RC_USAGE != V.RC_VACUOUS
    assert U.RC_USAGE not in (V.RC_PASS, V.RC_FAIL)


def test_a_rejected_command_line_exits_3(capsys):
    with pytest.raises(SystemExit) as exc:
        _parser().parse_args([])
    assert exc.value.code == U.RC_USAGE
    assert U.USAGE_STDOUT_SENTINEL in capsys.readouterr().err


def test_an_unknown_flag_exits_3(capsys):
    with pytest.raises(SystemExit) as exc:
        _parser().parse_args(["--needed", "x", "--nope"])
    assert exc.value.code == U.RC_USAGE


def test_an_internal_argparse_exit_of_2_is_remapped():
    """`error()` is not the only door: argparse calls `exit(2)` directly from
    several internal paths, so the collision could return through one this class
    did not name."""
    with pytest.raises(SystemExit) as exc:
        _parser().exit(2)
    assert exc.value.code == U.RC_USAGE


def test_help_still_exits_zero(capsys):
    """`--help` is a SUCCESSFUL invocation. Remapping it would make every
    wrapper that reads the code report a failure."""
    with pytest.raises(SystemExit) as exc:
        _parser().parse_args(["--help"])
    assert exc.value.code == 0


def test_a_hand_rolled_refusal_carries_the_same_token_and_code(capsys):
    assert U.usage_error("probe", "a path that is not a directory") == U.RC_USAGE
    err = capsys.readouterr().err
    assert err.startswith(U.USAGE_STDOUT_SENTINEL), err
    assert "not a vacuous pass" in err, err


def test_every_bucket_a_gate_uses_this_site_rather_than_its_own_copy():
    """`gate_discloses_denominator_check` recorded fourteen gates each carrying
    an inline copy of a shared convention, with "no shared site to fix". This is
    the site, and this test is what keeps the sixth gate from pasting instead of
    importing."""
    gates = [
        "landing_noop_verdict_check.py",
        "generated_test_list_min_guard.py",
        "doc_table_row_placement_check.py",
        "emitter_population_pin_check.py",
        "attestation_preflight_check.py",
    ]
    for name in gates:
        src = (PROGRAMS / name).read_text(encoding="utf-8")
        assert "import _gate_usage_exit" in src, name
        assert "argparse.ArgumentParser(" not in src, (
            f"{name} builds a bare argparse parser, so its bad-invocation exit "
            f"is 2 and collides with the vacuous tier")
