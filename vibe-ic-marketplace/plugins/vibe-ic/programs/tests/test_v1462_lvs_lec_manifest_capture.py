#!/usr/bin/env python3
"""Regression tests for the v1462 sky130A clean-run capture (4 deterministic
false-fail fixes distilled into the program layer).

FIX 1/2  LVS verdict from the on-disk report TERMINAL line, with a bounded flush
         retry — netgen writes `Final result:` to the report file while stdout
         carries only setup-phase `No such cell!` noise; a read/flush race made
         a genuine MATCH read INCOMPLETE on all six v1462 digital ICs.
FIX 3    LEC: a wall-clock TIMEOUT with no completed verdict + no counterexample
         → INCONCLUSIVE (non-blocking), never a hard FAIL; a COMPLETED miter
         that left points unproven still FAILs (tested doctrine untouched).
FIX 4    SOURCE_MANIFEST.md emitted at the run-dir TOP LEVEL (GENERATED vs
         REUSED-IP), where benchmark_verify_report.py probes.
"""
import json
import re
import sys
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lvs_verdict_tokens as lvt          # noqa: E402
import lec_run                            # noqa: E402
import lec_equivalence_check as lec_gate  # noqa: E402
import source_manifest_md_emit as smme    # noqa: E402


# ── FIX 1/2 — LVS report-terminal-line authoritative + flush retry ──────────
_MATCH_RPT = ("Cell pin lists are equivalent.\n\n"
              "Final result: Circuits match uniquely.\n.\n")
# The runner's transcript tail is setup-phase noise, NOT the verdict.
_SETUP_NOISE = ("Error /x/local_netgen_setup.tcl:50 (ignoring), No such cell!\n"
                "Error /x/local_netgen_setup.tcl:51 (ignoring), No such cell!\n")


def test_has_terminal_verdict_detects_completion_marker():
    assert lvt.has_terminal_verdict(_MATCH_RPT) is True
    assert lvt.has_terminal_verdict(_SETUP_NOISE) is False
    assert lvt.has_terminal_verdict("") is False


def test_report_terminal_line_is_authoritative_over_setup_noise():
    # The proven v1462 false-fail: transcript = setup noise, report = MATCH.
    blob = _SETUP_NOISE + "\n" + _MATCH_RPT
    assert lvt.classify(blob) == "MATCH"


def test_flush_retry_recovers_late_flushed_report(tmp_path):
    from phase3_one_shot_runner import _read_lvs_report_flushed
    rp = tmp_path / "lvs.rpt"
    rp.write_text("")                       # empty at first (flush race)

    def _fill():
        time.sleep(0.05)
        rp.write_text(_MATCH_RPT)
    threading.Thread(target=_fill, daemon=True).start()
    txt = _read_lvs_report_flushed(rp, attempts=30, base_delay=0.02, max_wait=3.0)
    assert lvt.has_terminal_verdict(txt) is True
    assert lvt.classify(_SETUP_NOISE + "\n" + txt) == "MATCH"


def test_flush_retry_leaves_a_truly_incomplete_run_incomplete(tmp_path):
    from phase3_one_shot_runner import _read_lvs_report_flushed
    rp = tmp_path / "killed.rpt"
    rp.write_text("Flattening unmatched instances ...\n")   # never a Final result
    txt = _read_lvs_report_flushed(rp, attempts=3, base_delay=0.01, max_wait=0.1)
    assert lvt.classify(txt) == "INCOMPLETE"


def test_flush_retry_preserves_a_real_mismatch(tmp_path):
    from phase3_one_shot_runner import _read_lvs_report_flushed
    rp = tmp_path / "mismatch.rpt"
    rp.write_text("Final result: Netlists do not match.\n.\n")
    txt = _read_lvs_report_flushed(rp, attempts=3, base_delay=0.01, max_wait=0.1)
    assert lvt.classify(txt) == "MISMATCH"


# ── FIX 3 — LEC timeout-no-verdict → INCONCLUSIVE (safe) ────────────────────
_IBEX_TIMEOUT = (
    "equiv_simple: Starting.\n"
    "Found 13609 unproven $equiv cells (13609 groups) in equiv:\n"
    "  Trying to prove $equiv for \\counter[36]:ezsat\nezsat\n failed.\n"
    "  Trying to prove $equiv for \\\n"
    "[lec_run] ERROR: yosys equiv exceeded its time budget after 7200s\n")
_SHA_COMPLETED = (
    "equiv_status: Found 1986 $equiv cells in equiv:\n"
    "  Of those cells 952 are proven and 1034 are unproven.\n"
    "Found a total of 1034 unproven $equiv cells.\n")


def test_timeout_with_no_completed_verdict_is_inconclusive():
    p = lec_run.parse_equiv_output(_IBEX_TIMEOUT)
    assert p["verdict"] == "INCONCLUSIVE"
    assert p["equivalent"] is False
    assert p["proven"] is None and p["unproven"] is None      # no completed count
    r = lec_run.build_report(p, "ibex_core", "netlist.v", None)
    assert r["verdict"] == "INCONCLUSIVE" and r["inconclusive"] is True


def test_ibex_timeout_report_is_non_blocking_in_gate(tmp_path):
    p = lec_run.parse_equiv_output(_IBEX_TIMEOUT)
    r = lec_run.build_report(p, "ibex_core", "netlist.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    (tmp_path / "reports" / "lec.rpt").write_text(_IBEX_TIMEOUT)
    res = lec_gate.audit(tmp_path)
    assert res.inconclusive is True
    assert res.passed is False                                 # never a vacuous PASS
    rules = {f.rule for f in res.findings}
    assert "LEC_NOT_EQUIVALENT" not in rules                   # not the hard-FAIL path
  # #208 follow-up: still NON-BLOCKING (flow_compliance resolves rc=3 +
    # the PASS_WITH_WAIVERS sentinel to WAIVED-DEFERRED, so the step does
    # not fail and nothing cascades to MISSING) but no longer a BARE PASS,
    # which rc=0 silently was at the `program_exit_zero` gate.
    assert lec_gate.main([str(tmp_path)]) == 3   # non-blocking, not a PASS


def test_completed_miter_unproven_still_fails():
    # sha256-class: equiv_induct COMPLETED, 1034 unproven, NO timeout → FAIL
    # (the tested false-fail-safe doctrine must be untouched).
    p = lec_run.parse_equiv_output(_SHA_COMPLETED)
    assert p["verdict"] == "FAIL"
    assert p["proven"] == 952 and p["unproven"] == 1034


def test_timeout_with_recorded_counterexample_still_fails():
    p = lec_run.parse_equiv_output(
        _IBEX_TIMEOUT + "Result: the circuits are non-equivalent.\n")
    assert p["verdict"] == "FAIL"


def test_timeout_with_partial_completed_verdict_still_fails():
    # A completed per-point verdict (0 proven, 8 unproven) under a timeout is a
    # real unproven result, not a zero-comparison run → stays FAIL.
    p = lec_run.parse_equiv_output(
        "  Of those cells 0 are proven and 8 are unproven.\n"
        "[lec_run] ERROR: yosys equiv exceeded its time budget after 7200s\n")
    assert p["verdict"] == "FAIL"


# ── FIX 4 — SOURCE_MANIFEST.md top-level emit ───────────────────────────────
def _mk_rtl(tmp_path, files, manifest=None):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    for name, body in files.items():
        (rtl / name).write_text(body)
    if manifest is not None:
        (rtl / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest))
    return tmp_path


def _tok(md):
    return (len(re.findall(r"\bGENERATED\b", md)),
            len(re.findall(r"\bREUSED-IP\b", md)))


def test_generated_design_tags_all_generated(tmp_path):
    p = _mk_rtl(tmp_path, {"spm.v": "module spm(input a); endmodule\n"})
    out = smme.emit(p)
    assert out is not None
    md = (p / "SOURCE_MANIFEST.md").read_text()
    g, r = _tok(md)
    # token count == module-row count (no legend inflation)
    rows = len([ln for ln in md.splitlines() if re.match(r"\|\s+`", ln)])
    assert (g, r) == (1, 0) and g + r == rows


def test_reused_ip_design_tags_all_reused(tmp_path):
    p = _mk_rtl(
        tmp_path,
        {"serv_alu.v": "module serv_alu(input a); endmodule\n",
         "subservient.v": "module subservient(input a); endmodule\n"},
        manifest={"reused_ip": True, "ip_list": ["serv", "shared_sram_rf"]})
    smme.emit(p)
    md = (p / "SOURCE_MANIFEST.md").read_text()
    g, r = _tok(md)
    rows = len([ln for ln in md.splitlines() if re.match(r"\|\s+`", ln)])
    # design-level provenance: reused_ip:true → every module REUSED-IP, even
    # ones whose name is not literally in the (IP-family) ip_list.
    assert (g, r) == (0, 2) and g + r == rows


def test_emit_is_non_destructive(tmp_path):
    p = _mk_rtl(tmp_path, {"spm.v": "module spm(input a); endmodule\n"})
    (p / "SOURCE_MANIFEST.md").write_text("HAND AUTHORED\n")
    smme.emit(p)
    assert (p / "SOURCE_MANIFEST.md").read_text() == "HAND AUTHORED\n"


def test_emit_none_when_no_digital_source(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    assert smme.emit(tmp_path) is None
    assert not (tmp_path / "SOURCE_MANIFEST.md").exists()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
