#!/usr/bin/env python3
"""Regression for ORGANIC-20260722 #786 — Step-31 LVS sign-off FAILed on a
report the runner had already DISCARDED, and blamed a file that says MATCH.

Root cause pinned: `_check_lvs` discovers reports with `rglob("*lvs*.rpt")`,
CONCATENATES every hit into one `blob`, classifies that blob, and attributes the
finding to `best_file` — the FIRST file scanned.

`phase3_one_shot_runner._try_power_aware_lvs` writes
`reports/phase3/lvs_power_aware.rpt` once per power model it TRIES. Its
docstring states the contract explicitly:

    Returns None in EVERY other case ... so the caller falls through to the
    UNCHANGED plain-netlist path. This makes the power-aware result STRICTLY
    MONOTONIC — it can only UPGRADE a power-blind or POWER_PIN_ONLY outcome to
    a genuine power-verified match, never regress it.

So on a non-match that file is deliberately-discarded scratch. The glob swept it
into the verdict blob anyway, its "Netlists do not match." token hard-FAILed
Step 31 under #507 — precisely the regression the producer promises cannot
happen — and the finding named `steps/31_.../lvs.rpt`, whose own terminal
verdict is "Circuits match uniquely".

Observed on caravel_user_project x sky130A:
    reports/phase3/lvs.rpt          → "Final result: Circuits match uniquely."
    reports/phase3/lvs_verdict.json → {"status":"PASS","finding":"LVS_MATCH"}
    Step 31 PV                      → FAIL, citing steps/31_.../lvs.rpt
    phase3 verdict                  → FAIL (completion audit), all steps PASS

Fix: drop attempt-scratch reports (stem carries `_power_aware` / `_attempt` /
`_probe` / ...) before the blob is built, FAIL-OPEN so a project whose ONLY
report is such a file is still judged rather than silently unaudited.

#507 IS FULLY PRESERVED — a mismatch in the CANONICAL report still hard-FAILs
(test_real_mismatch_in_canonical_report_still_fails), and an attempt-only
project is still judged (test_failopen_attempt_only_project_still_judged). The
change removes exactly one thing: a discarded attempt's vote.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parent.parent
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import eda_report_audit as A  # noqa: E402

_MATCH_RPT = """\
netgen LVS report
Subcircuit summary:
Circuit 1: caravel_user_project            |Circuit 2: caravel_user_project
Number of devices: 427                     |Number of devices: 427
Number of nets: 512                        |Number of nets: 512
instance summary follows
Cell pin lists are equivalent.
Final result: Circuits match uniquely.
"""

# The discarded power-aware ATTEMPT: netgen ran, did not reach a match, so the
# runner returned None and kept the plain-path result as canonical.
_ATTEMPT_RPT = """\
netgen LVS report
Cell sky130_fd_sc_hd__conb_1 (0) disconnected node: VGND
Subcircuit pins:
Circuit 1: caravel_user_project            |Circuit 2: caravel_user_project
VGND                                       |(no pin, node is net68)
Number of devices: 427                     |Number of devices: 427
Number of nets: 512                        |Number of nets: 512
instance summary follows
Final result: Netlists do not match.
Port matching may fail to disambiguate symmetries.
"""


# netgen reports are large; the audit enforces a >=1536 B anti-stub floor, so
# the fixtures carry a realistic per-net body rather than a few lines.
_NET_BODY = "\n".join(
    f"net_{i:04d}                                 |net_{i:04d}"
    for i in range(60)) + "\n"
_MATCH_RPT = _MATCH_RPT.replace("instance summary follows\n",
                                "instance summary follows\n" + _NET_BODY)
_ATTEMPT_RPT = _ATTEMPT_RPT.replace("instance summary follows\n",
                                    "instance summary follows\n" + _NET_BODY)
assert len(_MATCH_RPT) > 1536 and len(_ATTEMPT_RPT) > 1536


def _mk(tmp_path: Path, files: dict) -> Path:
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    for name, text in files.items():
        (proj / "reports" / "phase3" / name).write_text(text)
    return proj


def _run(proj: Path) -> dict:
    out = proj / "lvs.json"
    subprocess.run(
        [sys.executable, str(PROG_DIR / "lvs_report_check.py"), str(proj),
         "--mode", "lvs", "--json", str(out)],
        capture_output=True, text=True)
    return json.loads(out.read_text())


# ── the defect ──────────────────────────────────────────────────────────
def test_discarded_power_aware_attempt_does_not_fail_signoff(tmp_path):
    """The exact caravel shape: canonical MATCH + discarded attempt MISMATCH."""
    r = _run(_mk(tmp_path, {"lvs.rpt": _MATCH_RPT,
                            "lvs_power_aware.rpt": _ATTEMPT_RPT}))
    assert r["passed"] is True, r["findings"]
    assert r["summary"]["terminal_verdict"] == "MATCH"


def test_no_finding_is_attributed_to_a_matching_report(tmp_path):
    """The mis-attribution itself: a finding must never name a file whose own
    terminal verdict is a MATCH."""
    proj = _mk(tmp_path, {"lvs.rpt": _MATCH_RPT,
                          "lvs_power_aware.rpt": _ATTEMPT_RPT})
    for f in _run(proj)["findings"]:
        named = f.get("file") or ""
        if named and Path(named).name == "lvs.rpt":
            assert False, f"finding attributed to the MATCHING report: {f}"


# ── #507 must survive intact ────────────────────────────────────────────
def test_real_mismatch_in_canonical_report_still_fails(tmp_path):
    """A genuine LVS mismatch in the CANONICAL report is still a hard FAIL."""
    r = _run(_mk(tmp_path, {"lvs.rpt": _ATTEMPT_RPT.replace(
        "netgen LVS report", "netgen LVS report\nCircuits match check")}))
    assert r["passed"] is False
    assert any(f["rule"] == "LVS_NETLISTS_DO_NOT_MATCH"
               for f in r["findings"]), r["findings"]


def test_failopen_attempt_only_project_still_judged(tmp_path):
    """If the ONLY report present is an attempt artifact, it must still be
    judged — dropping it would leave the design silently unaudited, which is
    strictly worse than a false FAIL."""
    r = _run(_mk(tmp_path, {"lvs_power_aware.rpt": _ATTEMPT_RPT}))
    assert r["passed"] is False
    assert r["summary"]["terminal_verdict"] == "MISMATCH"


def test_canonical_mismatch_not_rescued_by_a_matching_attempt(tmp_path):
    """The exemption must not run the other way: a MATCH in an attempt file
    cannot rescue a canonical MISMATCH."""
    r = _run(_mk(tmp_path, {"lvs.rpt": _ATTEMPT_RPT.replace(
        "netgen LVS report", "netgen LVS report\nCircuits match check"),
        "lvs_power_aware.rpt": _MATCH_RPT}))
    assert r["passed"] is False


# ── no-leak ─────────────────────────────────────────────────────────────
def test_noleak_plain_project_unchanged(tmp_path):
    """A project with only a canonical report behaves exactly as before."""
    r = _run(_mk(tmp_path, {"lvs.rpt": _MATCH_RPT}))
    assert r["passed"] is True and r["summary"]["terminal_verdict"] == "MATCH"


# ── predicate contract ──────────────────────────────────────────────────
def test_canonical_names_are_never_attempts():
    for n in ("lvs.rpt", "lvs.log", "LVS.rpt", "comp.out",
              "caravel_user_project_lvs.rpt"):
        assert not A._is_lvs_attempt_artifact(Path(n)), n


def test_attempt_names_are_detected():
    for n in ("lvs_power_aware.rpt", "lvs_pwraware.rpt", "lvs_attempt.rpt",
              "lvs_probe.log", "lvs_prelim.rpt"):
        assert A._is_lvs_attempt_artifact(Path(n)), n


def test_drop_helper_fails_open():
    only = [Path("lvs_power_aware.rpt")]
    assert A._drop_nonauthoritative_lvs_attempts(only) == only
    mixed = [Path("lvs_power_aware.rpt"), Path("lvs.rpt")]
    assert A._drop_nonauthoritative_lvs_attempts(mixed) == [Path("lvs.rpt")]
