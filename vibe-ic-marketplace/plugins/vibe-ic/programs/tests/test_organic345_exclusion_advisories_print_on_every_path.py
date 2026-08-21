#!/usr/bin/env python3
"""ORGANIC #345 salvage 1 — the exclusion advisories printed only on PASS.

`l9_rtl_pin_consistency_check` emits a set of `WARN (advisory)` lines that all
say the same KIND of thing: this pin was taken OUT of the mismatch
comparison, and here is the ground — doc-optional, config-gated by the chosen
reused-IP variant, a documented tie-off, a faithful IP passthrough, a
struct-bus flatten, an L3 alias.

Every one of them lived inside `if not findings:`. So they appeared only when
the check PASSED, and were silent on FAIL — the one moment they matter. A
reader looking at N findings could not see what had been excluded from the
comparison that produced them, and if an exclusion rule is wrong the finding
list is wrong. The evidence that would show it was being suppressed exactly
then.

Recorded as salvageable when #345 was closed as a duplicate of #781, and
never harvested until the branch it lived on came up for deletion.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l9_rtl_pin_consistency_check.py")


def _run(project: Path):
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _project(tmp_path: Path, l9_ports, rtl_ports, top="test_dtop") -> Path:
    p = tmp_path / "p"
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "layer": "L9", "ic_name": "TEST",
        "dtop_top_level": {"module_name": top},
        "top_level_ports": l9_ports,
    }, indent=2))
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / f"{top}.sv").write_text(
        f"module {top} (\n  " + ",\n  ".join(rtl_ports) + "\n);\nendmodule\n")
    return p


_CLK = {"name": "clk", "direction": "input", "width": 1}
_OPT = {"name": "dbg_en", "direction": "input", "width": 1, "optional": True}
_ADV = "L9 doc-OPTIONAL pin(s) not in RTL top"


def test_the_advisory_still_prints_on_PASS(tmp_path):
    """The behaviour that already worked must keep working — otherwise the
    fix traded one silence for another."""
    p = _project(tmp_path, [_CLK, _OPT], ["input clk"])
    r = _run(p)
    assert r.returncode == 0, r.stdout
    assert _ADV in r.stdout, r.stdout


def test_the_advisory_ALSO_prints_on_FAIL(tmp_path):
    """THE DEFECT. Same optional pin, plus a real mismatch. Before the fix the
    advisory vanished the moment there was a finding to explain it against."""
    p = _project(tmp_path, [_CLK, _OPT,
                            {"name": "ghost", "direction": "input",
                             "width": 1}],
                 ["input clk"])
    r = _run(p)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout
    assert "ghost" in r.stdout, "the real finding must still be reported"
    assert _ADV in r.stdout, (
        "the exclusion advisory was suppressed on the FAIL path", r.stdout)


def test_the_advisory_ALSO_prints_on_PASS_WITH_WAIVER(tmp_path):
    """The third path. A waiver suppresses the VERDICT, and used to suppress
    the exclusions as well — so the reader signing the waiver could not see
    what the comparison had left out."""
    p = _project(tmp_path, [_CLK, _OPT,
                            {"name": "ghost", "direction": "input",
                             "width": 1}],
                 ["input clk"])
    (p / "waivers.json").write_text(json.dumps({
        "l9_rtl_pin_consistency_intentional": {
            "rationale": "ghost is a TEST-mode pin intentionally declared in "
                         "L9 ahead of the RTL wrapper; tracked separately.",
        }}))
    r = _run(p)
    out = r.stdout
    assert "PASS_WITH_WAIVER" in out, out
    assert r.returncode == 0
    assert _ADV in out, ("the exclusion advisory was suppressed on the "
                         "waiver path", out)


def test_a_clean_run_emits_no_advisory_at_all(tmp_path):
    """The paired half. Printing the WARN unconditionally would make every
    run noisy and the line meaningless — it must fire only when something was
    actually excluded."""
    p = _project(tmp_path, [_CLK], ["input clk"])
    r = _run(p)
    assert r.returncode == 0
    assert "WARN (advisory)" not in r.stdout, r.stdout


def test_the_advisory_text_is_identical_across_paths(tmp_path):
    """One builder, not three copies — the reason the fix is a helper rather
    than a paste. Two paths that drift produce two different accounts of the
    same exclusion."""
    clean = _project(tmp_path / "a", [_CLK, _OPT], ["input clk"])
    failing = _project(tmp_path / "b",
                       [_CLK, _OPT, {"name": "ghost", "direction": "input",
                                     "width": 1}],
                       ["input clk"])
    a = [l for l in _run(clean).stdout.splitlines() if "WARN (advisory)" in l]
    b = [l for l in _run(failing).stdout.splitlines() if "WARN (advisory)" in l]
    assert a and a == b, (a, b)
