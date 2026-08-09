#!/usr/bin/env python3
"""dynamic_ir_drop_check.py — the DIRECTORY form must be able to emit a verdict.

The gate documents `<report>` as "a dynamic-IR report (JSON/.rpt) or a
directory", but the directory search lived under ``if not report.exists():``.
A path that does not exist can never be a directory (both answers come from
the same stat), so the search was dead code for every real invocation: the
gate returned

    IO_ERROR "<dir> is a directory with no dynamic-IR report"   (rc 2)

for EVERY directory — including one holding a 10x-over-budget report — a claim
it never checked. FAIL (and PASS, and SKIPPED_CONDITION) were unreachable
through the documented directory form; the budget comparison was never
reached.

These tests pin BOTH directions:
  * the directory form can now reach FAIL and rc 1 (the missing verdict), and
  * it can still reach PASS/rc 0 and SKIPPED_CONDITION/rc 0, and a directory
    that genuinely holds no dynamic-IR report is still IO_ERROR/rc 2 —
    i.e. the resolver was not made to always-fail nor to always-resolve.

Assertions are on returned verdicts, process exit codes and emitted JSON only
— never on the text of the source file.

chip-AGNOSTIC: synthetic reports, generic flow paths, no design/PDK/part name.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import dynamic_ir_drop_check as G  # noqa: E402

_VDD = 1.8
_BUDGET_PCT = 10.0                       # budget = 10% x 1.8 V = 180 mV


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def _main_json(tmp_path: Path, target: Path, tag: str):
    """Run the CLI on `target`; return (rc, emitted-JSON-dict)."""
    out = tmp_path / f"verdict_{tag}.json"
    rc = G.main([str(target), "--budget-pct", str(_BUDGET_PCT),
                 "--json", str(out)])
    return rc, json.loads(out.read_text())


# ── direction 1: the previously-unreachable verdict ──────────────────────────

def test_directory_form_over_budget_report_reaches_fail(tmp_path):
    """A directory holding an over-budget dynamic-IR report must FAIL (rc 1).

    This is the assertion that fails against the unfixed program, which
    answered IO_ERROR / rc 2 without reading the report.
    """
    run_dir = tmp_path / "run_dir"
    _write(run_dir / "reports" / "phase3" / "dynamic_ir.json",
           {"max_dynamic_drop_mv": 1800.0, "vdd_v": _VDD})   # 10x the budget

    res = G.check(run_dir, None, _BUDGET_PCT)
    assert res["verdict"] == "FAIL", res
    assert res["worst_transient_droop_mv"] == 1800.0
    assert res["budget_mv"] == 180.0
    # the verdict must name the report the search actually resolved
    assert res["report"].endswith("reports/phase3/dynamic_ir.json"), res

    rc, emitted = _main_json(tmp_path, run_dir, "over")
    assert rc == 1
    assert emitted["verdict"] == "FAIL"


def test_directory_form_reaches_fail_on_missing_measurement(tmp_path):
    """A resolved report carrying no droop number is FAIL, not IO_ERROR —
    the §4.05 missing-evidence verdict was equally unreachable by directory."""
    run_dir = tmp_path / "run_dir"
    _write(run_dir / "reports" / "phase3" / "dynamic_ir.json",
           {"vdd_v": _VDD, "note": "solver produced no droop value"})

    res = G.check(run_dir, None, _BUDGET_PCT)
    assert res["verdict"] == "FAIL", res
    rc, emitted = _main_json(tmp_path, run_dir, "noval")
    assert rc == 1
    assert emitted["verdict"] == "FAIL"


# ── direction 2: the other verdicts are still reachable ──────────────────────

def test_directory_form_under_budget_report_reaches_pass(tmp_path):
    """Not always-fail: an under-budget report in a directory still PASSes."""
    run_dir = tmp_path / "run_dir"
    _write(run_dir / "reports" / "phase3" / "dynamic_ir.json",
           {"max_dynamic_drop_mv": 90.0, "vdd_v": _VDD})      # 90 < 180

    res = G.check(run_dir, None, _BUDGET_PCT)
    assert res["verdict"] == "PASS", res
    assert res["budget_mv"] == 180.0

    rc, emitted = _main_json(tmp_path, run_dir, "under")
    assert rc == 0
    assert emitted["verdict"] == "PASS"


def test_directory_form_honest_skip_marker_reaches_skipped_condition(tmp_path):
    """Not always-fail: an explicit emitter skip marker still SKIPs at rc 0."""
    run_dir = tmp_path / "run_dir"
    _write(run_dir / "reports" / "phase3" / "dynamic_ir.json",
           {"status": "SKIPPED_NO_VCD", "dynamic_ir_report_emitted": False,
            "reason": "no switching profile available"})

    res = G.check(run_dir, None, _BUDGET_PCT)
    assert res["verdict"] == "SKIPPED_CONDITION", res

    rc, emitted = _main_json(tmp_path, run_dir, "skip")
    assert rc == 0
    assert emitted["verdict"] == "SKIPPED_CONDITION"


# ── the IO_ERROR claim must now be earned, not assumed ───────────────────────

def test_directory_with_only_a_static_report_is_still_io_error(tmp_path):
    """Not always-resolve: a directory with no DYNAMIC report is IO_ERROR
    (rc 2), and the STATIC ir_drop.json is never resolved as a dynamic
    sign-off (§4.05 — that would be a fabricated dynamic pass)."""
    run_dir = tmp_path / "run_dir"
    _write(run_dir / "reports" / "phase3" / "ir_drop.json",
           {"max_drop_mv": 12.0, "vdd_v": _VDD})

    res = G.check(run_dir, None, _BUDGET_PCT)
    assert res["verdict"] == "IO_ERROR", res

    rc, emitted = _main_json(tmp_path, run_dir, "staticonly")
    assert rc == 2
    assert emitted["verdict"] == "IO_ERROR"
    assert "worst_transient_droop_mv" not in emitted


def test_nonexistent_path_is_still_io_error(tmp_path):
    res = G.check(tmp_path / "nope", None, _BUDGET_PCT)
    assert res["verdict"] == "IO_ERROR", res
    assert G.main([str(tmp_path / "nope")]) == 2


def test_plain_file_form_is_unchanged(tmp_path):
    """The file form (what the signoff ladder passes) keeps both verdicts."""
    over = _write(tmp_path / "over.json",
                  {"max_dynamic_drop_mv": 1800.0, "vdd_v": _VDD})
    under = _write(tmp_path / "under.json",
                   {"max_dynamic_drop_mv": 90.0, "vdd_v": _VDD})
    assert G.check(over, None, _BUDGET_PCT)["verdict"] == "FAIL"
    assert G.check(under, None, _BUDGET_PCT)["verdict"] == "PASS"


# ── resolution quality + the uncaught-PermissionError hole ───────────────────

def test_directory_search_prefers_the_shallowest_report(tmp_path):
    """With several candidates the canonical (shallowest) one decides the
    verdict — a deep stray copy must not silently outrank it."""
    run_dir = tmp_path / "run_dir"
    _write(run_dir / "reports" / "phase3" / "dynamic_ir.json",
           {"max_dynamic_drop_mv": 1800.0, "vdd_v": _VDD})          # over
    _write(run_dir / "reports" / "phase3" / "archive" / "old" /
           "dynamic_ir.json", {"max_dynamic_drop_mv": 5.0, "vdd_v": _VDD})

    res = G.check(run_dir, None, _BUDGET_PCT)
    assert res["verdict"] == "FAIL", res
    assert res["worst_transient_droop_mv"] == 1800.0


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root bypasses directory permissions")
def test_unreadable_path_is_io_error_not_an_uncaught_exception(tmp_path):
    """`Path.exists()`/`is_dir()` raise on EACCES (pathlib only ignores
    ENOENT/ENOTDIR/EBADF/ELOOP), so an unreadable path used to escape the gate
    as a traceback. It must be an honest IO_ERROR at rc 2."""
    locked = tmp_path / "locked"
    locked.mkdir()
    target = locked / "dynamic_ir.json"
    target.write_text(json.dumps({"max_dynamic_drop_mv": 1.0, "vdd_v": _VDD}))
    locked.chmod(0o000)
    try:
        try:
            target.is_file()
        except PermissionError:
            pass
        else:
            pytest.skip("filesystem does not enforce the directory mode")
        res = G.check(target, None, _BUDGET_PCT)
        assert res["verdict"] == "IO_ERROR", res
        assert G.main([str(target)]) == 2
    finally:
        locked.chmod(0o755)
