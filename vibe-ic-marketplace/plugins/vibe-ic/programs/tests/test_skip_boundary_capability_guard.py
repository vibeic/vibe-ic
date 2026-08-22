"""Unit tests for the `--skip-boundary` binary-capability guard in
fault_scan_chain_insert.py.

BLOCKING: `run_chain` returns rc=1 (a scan-insertion failure) when the
deterministic decision is skip-boundary but the `fault` binary predates the
flag. The guard does NOT change that rc — it upgrades the *diagnosis* from the
generic "produced no scan netlist" to an ACTIONABLE cause+remedy, and records
`skip_boundary_unsupported_by_binary=true`. Degrade loudly, never silently.

WHY this exists (MEASURED, round 15): `--skip-boundary` is absent from `fault
chain --help` on image 0.2.52 and present on 0.2.54+ (same 0.9.4 binary string,
rebuilt between tags). The boundary decision is PURE / image-independent, so a
fixed-pinout wrapper decides skip=True on ANY image; run against 0.2.52 the
binary rejects the flag —
    `Error: Unknown option '--skip-boundary'`  -> RC=64, no netlist.
Without this classifier the fixed-pinout wrapper that MOST needs skip-boundary
silently loses its scan chain and the real cause (stale image pin) is buried in
log_tail. A stale `--container ...:0.2.52` default is a real hazard.

BIDIRECTIONAL NEGATIVE CONTROL — the load-bearing case is that the flag NAME
`--skip-boundary` ALSO appears in the tool's SUCCESS line ("Boundary scan
register NOT inserted (--skip-boundary)"), so a naive `"--skip-boundary" in log`
would false-positive on a healthy run. The guard must fire ONLY on the reject
error, never on success. chip-AGNOSTIC — keys on the tool's own error string,
carries no design/PDK/vendor literal.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import fault_scan_chain_insert as SCI          # noqa: E402


# ---- the REAL measured strings from each image (VERIFY, DO NOT INHERIT) ----
LOG_0252_REJECT = (
    "Error: Unknown option '--skip-boundary'\n"
    "Usage: fault chain [<options>] --liberty <liberty> --clock <clock> <file>\n"
    "  See 'fault chain --help' for more information.\n")
LOG_0254_SUCCESS = (
    "Processing module user_project_wrapper\n"
    "Chaining internal flip-flops...\n"
    "Internal scan chain successfully constructed. Length: 33\n"
    "Boundary scan register NOT inserted (--skip-boundary): the chain is the "
    "33 internal flip-flop(s) only.\n"
    "Total scan-chain length:  33\n")


# ---------------- POSITIVE: guard MUST fire on the reject error ----------------

def test_detects_real_0252_reject_string():
    assert SCI.skip_boundary_unsupported_in_log(LOG_0252_REJECT) is True


def test_detects_argparser_wording_variants():
    for word in ("Unknown", "Unrecognized", "unexpected", "invalid"):
        log = f"Error: {word} option '--skip-boundary'\n"
        assert SCI.skip_boundary_unsupported_in_log(log) is True, word
    # bare "-b" long spelling in a differently-formatted message
    assert SCI.skip_boundary_unsupported_in_log(
        "error: unrecognized option: --skip-boundary") is True


# ------------- NEGATIVE CONTROL: guard must NOT fire on healthy runs -----------

def test_does_not_fire_on_success_line_that_mentions_the_flag():
    # The flag NAME is in the SUCCESS message — a naive substring match would
    # false-positive here. This is the whole point of the regex.
    assert SCI.skip_boundary_unsupported_in_log(LOG_0254_SUCCESS) is False


def test_does_not_fire_on_unrelated_failure():
    assert SCI.skip_boundary_unsupported_in_log(
        "ERROR: liberty file not found: /pdk/does_not_exist.lib") is False
    assert SCI.skip_boundary_unsupported_in_log(
        "yosys: internal error while resynthesizing") is False


def test_does_not_fire_on_empty_or_none():
    assert SCI.skip_boundary_unsupported_in_log("") is False
    assert SCI.skip_boundary_unsupported_in_log(None) is False  # type: ignore[arg-type]


def test_unknown_option_for_a_DIFFERENT_flag_does_not_fire():
    # Only --skip-boundary should trigger the skip-boundary-specific remedy.
    assert SCI.skip_boundary_unsupported_in_log(
        "Error: Unknown option '--some-other-flag'") is False
