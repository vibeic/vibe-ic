#!/usr/bin/env python3
"""Tests for result_md_audit_provenance_check.py (Wave 33, v0.119.65)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "result_md_audit_provenance_check.py"
)


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True,
        text=True,
    )


def test_no_result_md_skip(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout, r.stdout


def test_result_md_with_provenance_pass(tmp_path):
    """RESULT.md claims PASS and cites all three required pieces."""
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n\n"
        "## Burn provenance\n"
        "audit_sha256: sha256:" + "0" * 64 + "\n"
        "audit_verdict: PASS\n"
        "program_response: {success: true, guard_invoked: true, "
        "error_code: program_succeeded}\n"
        "Hardware verdict: byte[6]=0xF2 across 5/5 connect_test runs.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout
    assert "Provenance verifiable" in r.stdout, r.stdout


def test_result_md_missing_audit_sha_fail(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "audit_verdict: PASS\n"
        "program_response: {success: true}\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_SHA" in r.stdout, r.stdout


def test_result_md_missing_program_response_fail(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "audit_sha256: sha256:" + "a" * 64 + "\n"
        "audit_verdict: PASS\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_PROGRAM_RESPONSE" in r.stdout, r.stdout


def test_result_md_missing_audit_verdict_fail(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "audit_sha256: sha256:" + "b" * 64 + "\n"
        "program_response: {success: true}\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_VERDICT" in r.stdout, r.stdout


def test_result_md_claiming_fail_skips(tmp_path):
    """RESULT.md that honestly reports FAIL must SKIP — agent isn't
    claiming a passing burn so provenance citation isn't required."""
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 outcome — FAIL\n\n"
        "Hardware verdict byte[6]=0x02 across 5/5 connect_test runs.\n"
        "Phase 2a 100% but real silicon FAIL.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout, r.stdout


def test_pass_with_waivers_accepted(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS_WITH_WAIVERS\n"
        "audit_sha256: sha256:" + "c" * 64 + "\n"
        "audit_verdict: PASS_WITH_WAIVERS\n"
        "program_response: {success: true}\n"
        "Hardware byte[6]=0xF2.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVERS" in r.stdout or "PASS" in r.stdout


def test_waiver_silences_failure(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "Hardware byte[6]=0xF2.\n"
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "result_md_audit_provenance_intentional":
            "Test rig generated provenance separately; RESULT.md "
            "narrative is summary-only with provenance JSON archived "
            "outside the project tree (see lab journal entry).",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout, r.stdout


def test_burn_provenance_json_reference_accepted(tmp_path):
    """A reference to `burn_provenance.json` carrying success-class
    markers is accepted as program_response evidence."""
    (tmp_path / "RESULT.md").write_text(
        "# Phase 2+3 PASS\n"
        "Burn provenance: see `reports/burn_provenance.json`\n"
        "  audit_sha256: sha256:" + "d" * 64 + "\n"
        "  audit_verdict: PASS\n"
        "  guard_invoked: true\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout


# ── Freshness (STALE rule) must not depend on how many times the compliance
#    flow has run. The flow re-stamps its OWN output tree (`reports/`) on every
#    invocation, so a freshness reference that counts `reports/` made this
#    gate's verdict flip PASS->FAIL between run 1 and run 2 of the SAME tree
#    (measured: subservient_gf180mcuD, plugin 1.9.76). These two tests are a
#    bidirectional control: (1) the flow's own re-stamped reports must NOT be
#    read as a newer design round; (2) a genuinely newer DESIGN artefact must
#    still be caught. Test (1) FAILS against the pre-fix program and PASSES
#    after; test (2) holds on both — proving the rule is anchored, not neutered.
import os  # noqa: E402


def _run_tree(tmp_path: Path, doc_mtime: float):
    """A minimal run tree: a RESULT.md that quotes a compliance tally (so the
    STALE branch is walked) but does NOT claim PASS (so citation rules SKIP and
    only the freshness rule is under test), plus a `reports/` output file and a
    `phase2/` design artefact."""
    (tmp_path / "RESULT.md").write_text(
        "# Compliance run (in progress)\n\n"
        "Structural tally: PASS=7 FAIL=5 MISSING=0\n"
    )
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "gate.json").write_text("{}\n")
    (tmp_path / "phase2").mkdir()
    (tmp_path / "phase2" / "netlist.v").write_text("module top(); endmodule\n")
    os.utime(tmp_path / "RESULT.md", (doc_mtime, doc_mtime))


def test_freshness_ignores_flow_own_reports(tmp_path):
    """The flow re-stamping its OWN `reports/` tree far past the RESULT.md
    mtime must NOT be read as a newer design round. FAILS pre-fix (reports/ was
    in the freshness reference), PASSES post-fix."""
    doc_m = 1_000_000.0
    _run_tree(tmp_path, doc_m)
    # design artefact stays older than the doc; only the flow's own report is
    # stamped far in the future — exactly what an extra umbrella run does.
    os.utime(tmp_path / "phase2" / "netlist.v", (doc_m - 100, doc_m - 100))
    os.utime(tmp_path / "reports" / "gate.json",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "STALE" not in r.stdout, r.stdout


def test_freshness_still_catches_stale_design_artefact(tmp_path):
    """A genuinely newer DESIGN artefact (phase2/) past the grace still trips
    RESULT_MD_STALE_VS_EVIDENCE — the rule is anchored, not neutered."""
    doc_m = 1_000_000.0
    _run_tree(tmp_path, doc_m)
    os.utime(tmp_path / "phase2" / "netlist.v",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_STALE_VS_EVIDENCE" in r.stdout, r.stdout


def test_newest_evidence_excludes_flow_output_root(tmp_path):
    """Directly: `_newest_evidence` must ignore the flow's own `reports/`
    output root, so its result is invariant to the flow re-stamping reports."""
    sys.path.insert(0, str(PROG.parent))
    import result_md_audit_provenance_check as chk
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "gate.json").write_text("{}\n")
    (tmp_path / "phase2").mkdir()
    (tmp_path / "phase2" / "netlist.v").write_text("x\n")
    os.utime(tmp_path / "phase2" / "netlist.v", (1000.0, 1000.0))
    os.utime(tmp_path / "reports" / "gate.json", (9000.0, 9000.0))
    m, p = chk._newest_evidence(tmp_path)
    assert p == "phase2/netlist.v", (m, p)
    assert m == 1000.0, (m, p)


# ── The exclusion must be the FLOW'S OWN OUTPUT, not the whole of reports/ ──
#
# Excluding all of `reports/` fixes the run-count dependence above but takes
# the design round's genuine tool sign-off reports with it. `reports/phase3/
# drc_signoff.rpt` (phase3_one_shot_runner.py:22567, :28296) and
# `reports/phase3/lvs.rpt` (:24241, :24705) are written by the TOOLS, and a
# census of two back-to-back umbrella runs on a real completed tree
# (benchmark-data/ic/subservient, 394 files) shows the flow never re-stamps
# them: 66 files moved, all .json/.md, all under reports/, and 0 of the 14
# .rpt files in the tree. So a sign-off-only re-run moves only `reports/`
# mtimes — and under the wide exclusion a stale RESULT.md beside it became
# invisible, which is the founding failure shape this rule exists for.


def _signoff_tree(tmp_path: Path, doc_mtime: float):
    """A run tree whose ONLY newer artefact will be a genuine tool report."""
    (tmp_path / "RESULT.md").write_text(
        "# Compliance run (in progress)\n\n"
        "Structural tally: PASS=7 FAIL=5 MISSING=0\n"
    )
    for rel in ("reports/audit/phase23_completion_audit.json",
                "reports/phase2/gates/spec_required_artifacts.json",
                "reports/phase3/drc_signoff.rpt",
                "reports/phase3/lvs.rpt",
                "phase2/netlist.v"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n")
        os.utime(p, (doc_mtime - 100, doc_mtime - 100))
    os.utime(tmp_path / "RESULT.md", (doc_mtime, doc_mtime))


def test_newer_drc_signoff_report_is_still_staleness(tmp_path):
    """`reports/phase3/drc_signoff.rpt` is TOOL output, not flow output."""
    doc_m = 1_000_000.0
    _signoff_tree(tmp_path, doc_m)
    os.utime(tmp_path / "reports/phase3/drc_signoff.rpt",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 1, (
        "a sign-off re-run that leaves RESULT.md behind must still FAIL; "
        f"excluding all of reports/ makes it invisible.\n{r.stdout}")
    assert "RESULT_MD_STALE_VS_EVIDENCE" in r.stdout, r.stdout
    assert "drc_signoff.rpt" in r.stdout, r.stdout


def test_newer_lvs_report_is_still_staleness(tmp_path):
    """Same for `reports/phase3/lvs.rpt` — the other sign-off half."""
    doc_m = 1_000_000.0
    _signoff_tree(tmp_path, doc_m)
    os.utime(tmp_path / "reports/phase3/lvs.rpt",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_STALE_VS_EVIDENCE" in r.stdout, r.stdout
    assert "lvs.rpt" in r.stdout, r.stdout


def test_flow_gate_json_under_any_reports_subdir_is_excluded(tmp_path):
    """The idempotence half must survive the narrowing.

    The flow re-stamps gate JSON all over `reports/`, not just under
    `reports/audit/` — measured: 61 under `reports/phase2/gates/`, plus
    `reports/phase1/`, `reports/phase3/` and `reports/` root. Narrowing the
    exclusion to `reports/audit/` ALONE would leave the run-count dependence
    in place, so the `.json`/`.md` rule carries it.
    """
    doc_m = 1_000_000.0
    _signoff_tree(tmp_path, doc_m)
    for rel in ("reports/audit/phase23_completion_audit.json",
                "reports/phase2/gates/spec_required_artifacts.json"):
        os.utime(tmp_path / rel, (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 0, (
        "the flow re-stamping its OWN gate/audit JSON must not read as a "
        f"newer design round.\n{r.stdout}")
    assert "STALE" not in r.stdout, r.stdout


def test_reports_audit_is_excluded_whatever_the_extension(tmp_path):
    """`reports/audit/` is the flow's own bucket — the compliance transcript
    `flow_compliance_check.log` lands there (design_one_shot_runner.py:12030)
    and is not a `.json`, so the subtree rule and not the suffix rule must
    cover it."""
    doc_m = 1_000_000.0
    _signoff_tree(tmp_path, doc_m)
    log = tmp_path / "reports/audit/flow_compliance_check.log"
    log.write_text("compliance transcript\n")
    os.utime(log, (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "STALE" not in r.stdout, r.stdout


def test_is_flow_output_classifies_each_side(tmp_path):
    """Unit-level, both directions, so the boundary itself is pinned."""
    sys.path.insert(0, str(PROG.parent))
    import result_md_audit_provenance_check as chk
    for rel in ("reports/audit/phase23_completion_audit.json",
                "reports/audit/flow_compliance_check.log",
                "reports/audit/phase1/expert_parse_track.json",
                "reports/phase2/gates/spec_required_artifacts.json",
                "reports/phase3/em_signoff.json",
                "reports/phase1/phase1_input_vs_generated_completeness.md"):
        assert chk._is_flow_output(rel) is True, f"{rel} is flow output"
    for rel in ("reports/phase3/drc_signoff.rpt",
                "reports/phase3/lvs.rpt",
                "reports/density.rpt",
                "reports/phase3/em_segments.csv",
                "reports/phase3/erc_chip_top.tcl",
                "phase2/netlist.v",
                "phase3/gds/top.gds",
                "phase1/L1.json"):
        assert chk._is_flow_output(rel) is False, f"{rel} dates the design round"


def test_abstention_is_disclosed_not_rendered_as_clean(tmp_path):
    """A tree holding ONLY flow documents must say the rule did not evaluate.

    `_newest_evidence` returning a bare None, while `_is_run_tree` still
    claims the tree, made "I could not look" indistinguishable from "there is
    nothing there" — the STALE rule kept jurisdiction it could never exercise.
    Measured on 3 real CVDP run trees whose evidence root is `reports/` only.
    """
    doc_m = 1_000_000.0
    (tmp_path / "RESULT.md").write_text(
        "# run\n\nStructural tally: PASS=7 FAIL=5 MISSING=0\n")
    for rel in ("reports/audit/phase23_completion_audit.json",
                "reports/gate_dp.json"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}\n")
        os.utime(p, (doc_m + 10_000, doc_m + 10_000))
    os.utime(tmp_path / "RESULT.md", (doc_m, doc_m))

    out = tmp_path / "o.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
        capture_output=True, text=True)
    assert "RESULT_MD_FRESHNESS_NOT_EVALUATED" in r.stdout, (
        f"the abstention must be stated, not swallowed.\n{r.stdout}")
    s = json.loads(out.read_text())["summary"]
    assert s["is_run_tree"] is True, s
    assert s["newest_evidence"] is None, s
    assert s["freshness_evaluated"] is False, (
        "the artefact must record that the rule did not evaluate", s)
    assert s.get("freshness_abstain_reason"), s


def test_freshness_evaluated_is_true_when_it_did_evaluate(tmp_path):
    """Control for the flag: a tree with real evidence records True."""
    doc_m = 1_000_000.0
    _signoff_tree(tmp_path, doc_m)
    out = tmp_path / "o.json"
    subprocess.run([sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
                   capture_output=True, text=True)
    s = json.loads(out.read_text())["summary"]
    assert s["freshness_evaluated"] is True, s
    assert s["newest_evidence"] is not None, s


# ── ROUND 3: three claims the round-2 shape made that measurement refutes ──
#
# 1. "the flow writes nothing outside `reports/`". FALSE. The fMEDA
#    fault-injection gate RENDERS its testbench into `phase2/stage2/safety/`
#    and compiles it there on every run, and `phase2/` was explicitly in
#    scope. MEASURED, `flow_compliance_check` driven on an untouched copy of
#    `benchmark-data/ic/opentitan_aes` (514 files), the SAME RESULT.md
#    throughout::
#
#        BEFORE any re-run   STALE=False  newest=phase2/stage2/synth/sv2v.err
#        AFTER 1 re-run      STALE=True   newest=…/fmeda_fi_tb.v.vvp
#        AFTER 2, AFTER 3    STALE=True   newest=…/fmeda_fi_tb.v.vvp
#
#    i.e. the run-count-dependent verdict the round-2 change exists to remove,
#    surviving on a different tree.
#
# 2. "each tool report that has a JSON half also has the `.rpt` half, written
#    in the same operation, which dates the round just as well". FALSE
#    corpus-wide: 376 of 520 genuine tool JSONs have no same-stem sibling, and
#    `reports/phase3/metal_density.json` is a KLayout measurement over the
#    final GDS with no `.rpt` half at all.
#
# 3. the abstention "gates". It did not: it went into `warnings`, `main()`
#    returned rc 0 and wrote `"passed": true`, and the only automated
#    consumer (`flow_compliance_check.__check_program_exit_zero`) is rc-ONLY.


def _dated_tree(tmp_path: Path, doc_mtime: float, rels):
    """A run tree whose files all predate RESULT.md, so the ONLY thing that
    can make it stale is what the test re-stamps."""
    (tmp_path / "RESULT.md").write_text(
        "# Compliance run (in progress)\n\n"
        "Structural tally: PASS=7 FAIL=5 MISSING=0\n")
    for rel, body in rels.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        os.utime(p, (doc_mtime - 100, doc_mtime - 100))
    os.utime(tmp_path / "RESULT.md", (doc_mtime, doc_mtime))


#: What a KLayout density measurement over the final GDS looks like: an EDA
#: tool's own numbers, `.json`, under `reports/`, with no `.rpt` half.
_TOOL_JSON = json.dumps({
    "tool": "klayout",
    "measurement": "per_layer_drawn_area_over_die_bbox_area",
    "die_area_um2": 621609.685,
    "layers": {"met1": 0.335435, "met2": 0.309278},
})
#: …and what a GATE document that puts its OWN program name in the same field
#: looks like. MEASURED: `reports/phase3/sta/hold_corner_coverage.json` is
#: rewritten by the flow on every run AND carries
#: `"tool": "hold_corner_coverage_check"`.
_GATE_JSON_WEARING_TOOL = json.dumps({
    "tool": "hold_corner_coverage_check",
    "verdict": "PASS", "project": "x", "reason": "ok",
})
_FMEDA_TB = "phase2/stage2/safety/fmeda_fi_tb.v"


def _base_rels():
    return {
        "reports/audit/phase23_completion_audit.json": "{}\n",
        "reports/phase2/gates/cdc_crossing.json": "{}\n",
        "reports/phase3/drc_signoff.rpt": "drc\n",
        "reports/phase3/metal_density.json": _TOOL_JSON,
        "reports/phase3/sta/hold_corner_coverage.json": _GATE_JSON_WEARING_TOOL,
        _FMEDA_TB: "module fmeda_fi_tb; endmodule\n",
        _FMEDA_TB + ".vvp": "\x00vvp\n",
        "phase2/stage1/rtl/top.v": "module top(); endmodule\n",
    }


def test_a_gate_regenerated_path_outside_reports_does_not_date_the_round(
        tmp_path):
    """HIGH-1. `phase2/stage2/safety/fmeda_fi_tb.v{,.vvp}` are re-rendered and
    re-compiled by the fMEDA gate on EVERY compliance run, so reading them as
    "a newer round of the design" makes the verdict a function of the run
    count. FAILS against the round-2 shape, which excluded only `reports/`."""
    doc_m = 1_000_000.0
    _dated_tree(tmp_path, doc_m, _base_rels())
    for rel in (_FMEDA_TB, _FMEDA_TB + ".vvp"):
        os.utime(tmp_path / rel, (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert "RESULT_MD_STALE_VS_EVIDENCE" not in r.stdout, (
        "the compliance flow re-stamping its OWN injection testbench must not "
        f"read as a newer design round.\n{r.stdout}")
    assert r.returncode == 0, r.stdout


def test_the_excluded_paths_come_from_the_gate_that_writes_them(tmp_path):
    """…and the exclusion is the WRITER'S declaration, not a copy of it.

    A restated path list is the drift shape: the gate could move its testbench
    and this program would go on excluding a path nothing writes while reading
    the one that moved. Asserted by identity against the exporting module, and
    by driving the classifier on each declared path.
    """
    sys.path.insert(0, str(PROG.parent))
    import fmeda_fault_injection_coverage as fi
    import result_md_audit_provenance_check as chk
    assert set(chk._FLOW_REGENERATED_PATHS) == set(fi.REGENERATED_PROJECT_PATHS)
    assert chk._FLOW_REGENERATED_PATHS, "the declaration must not be empty"
    for rel in fi.REGENERATED_PROJECT_PATHS:
        assert chk._is_flow_output(rel) is True, rel
        assert not rel.startswith("reports/"), (
            f"{rel} is already covered by the reports/ rule; this rule is for "
            f"the paths OUTSIDE it, which is the whole reason it exists")


def test_a_design_file_beside_the_regenerated_testbench_still_dates_the_round(
        tmp_path):
    """The anti-green-buy control for HIGH-1: excluding two named paths must
    not excuse the directory or the phase they live in."""
    doc_m = 1_000_000.0
    rels = _base_rels()
    rels["phase2/stage2/safety/ecc_wrapper.v"] = "module w(); endmodule\n"
    _dated_tree(tmp_path, doc_m, rels)
    os.utime(tmp_path / "phase2/stage2/safety/ecc_wrapper.v",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_STALE_VS_EVIDENCE" in r.stdout, r.stdout
    assert "ecc_wrapper.v" in r.stdout, r.stdout


def test_an_eda_tools_own_json_measurement_still_dates_the_round(tmp_path):
    """HIGH-2. `reports/phase3/metal_density.json` is a KLayout measurement
    over the final GDS. The round-2 shape excluded every `.json` under
    `reports/` on the claim that such a report "also has the `.rpt` half,
    written in the same operation" — refuted: this one has none, and 376 of
    the corpus's 520 genuine tool JSONs have no same-stem sibling at all. A
    re-emission of it alone therefore went unseen, and a real stale RESULT.md
    beside it went quiet.
    """
    doc_m = 1_000_000.0
    _dated_tree(tmp_path, doc_m, _base_rels())
    os.utime(tmp_path / "reports/phase3/metal_density.json",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert r.returncode == 1, (
        "a design-round tool measurement re-emitted alone must still be "
        f"seen.\n{r.stdout}")
    assert "RESULT_MD_STALE_VS_EVIDENCE" in r.stdout, r.stdout
    assert "metal_density.json" in r.stdout, r.stdout


def test_a_gate_document_wearing_the_tool_field_is_still_excluded(tmp_path):
    """The negative control that stops the rescue from becoming a hole.

    `reports/phase3/sta/hold_corner_coverage.json` is rewritten on every run
    AND carries `"tool": "hold_corner_coverage_check"` — the gate's own name in
    the field an EDA tool fills with `openroad`. A rescue keyed on the presence
    of `tool` alone reinstates the run-count dependence through it. The name
    must not resolve to a program in this plugin's `programs/` directory.
    """
    doc_m = 1_000_000.0
    _dated_tree(tmp_path, doc_m, _base_rels())
    os.utime(tmp_path / "reports/phase3/sta/hold_corner_coverage.json",
             (doc_m + 10_000, doc_m + 10_000))
    r = _run(tmp_path)
    assert "RESULT_MD_STALE_VS_EVIDENCE" not in r.stdout, (
        "a gate document that names its own program in `tool` is still the "
        f"flow's own output.\n{r.stdout}")
    assert r.returncode == 0, r.stdout


def test_the_tool_rescue_is_content_keyed_not_name_keyed(tmp_path):
    """Same basename, same directory, opposite classification — so the rescue
    cannot be passing on the path."""
    sys.path.insert(0, str(PROG.parent))
    import result_md_audit_provenance_check as chk
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "x.json").write_text(_TOOL_JSON)
    assert chk._is_flow_output("reports/phase3/x.json", d / "x.json") is False
    (d / "x.json").write_text(_GATE_JSON_WEARING_TOOL)
    assert chk._is_flow_output("reports/phase3/x.json", d / "x.json") is True
    (d / "x.json").write_text("{}\n")           # no producer field at all
    assert chk._is_flow_output("reports/phase3/x.json", d / "x.json") is True
    (d / "x.json").write_text("not json at all")
    assert chk._is_flow_output("reports/phase3/x.json", d / "x.json") is True


def test_the_abstention_reaches_the_only_consumer_there_is(tmp_path):
    """MEDIUM-1. Disclosure in `warnings` changed nothing anybody can see.

    `main()` returns rc 0 for warnings and writes `"passed": true`, and the
    ONLY automated consumer — `flow_compliance_check.__check_program_exit_zero`
    — reads the return code and nothing else (rc 0 PASS, rc 2 VACUOUS_PASS,
    rc 3 + sentinel PASS_WITH_WAIVERS, else FAIL). MEASURED on a tree holding
    only flow documents::

        round 2   rc=0  passed=true   freshness_evaluated=false  -> PASS
        round 3   rc=1  passed=false  freshness_evaluated=false  -> FAIL

    An unevaluated gate cannot pass — the umbrella's own words for a timeout.
    """
    doc_m = 1_000_000.0
    _dated_tree(tmp_path, doc_m, {
        "reports/audit/phase23_completion_audit.json": "{}\n",
        "reports/phase2/gates/cdc_crossing.json": "{}\n",
    })
    out = tmp_path / "o.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
        capture_output=True, text=True)
    doc = json.loads(out.read_text())
    assert doc["summary"]["freshness_evaluated"] is False, doc["summary"]
    assert r.returncode == 1, (
        "the abstention must reach a consumer that only reads the return "
        f"code.\n{r.stdout}")
    assert doc["passed"] is False, doc
    assert any(f.startswith("RESULT_MD_FRESHNESS_NOT_EVALUATED")
               for f in doc["failures"]), doc


def test_a_tree_with_real_evidence_is_not_swept_up_by_that(tmp_path):
    """Control: the abstention must fire ONLY when nothing dates the round.
    A tree with one genuine tool measurement and nothing else evaluates."""
    doc_m = 1_000_000.0
    _dated_tree(tmp_path, doc_m, {
        "reports/audit/phase23_completion_audit.json": "{}\n",
        "reports/phase3/metal_density.json": _TOOL_JSON,
    })
    out = tmp_path / "o.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(out)],
        capture_output=True, text=True)
    doc = json.loads(out.read_text())
    assert doc["summary"]["freshness_evaluated"] is True, doc["summary"]
    assert doc["summary"]["newest_evidence"] == \
        "reports/phase3/metal_density.json", doc["summary"]
    assert r.returncode == 0, r.stdout


def test_the_abstention_is_still_waivable(tmp_path):
    """Promoting it to a failure must not remove the documented escape hatch
    for a tree that legitimately has nothing to date."""
    doc_m = 1_000_000.0
    _dated_tree(tmp_path, doc_m, {
        "reports/phase2/gates/cdc_crossing.json": "{}\n"})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "result_md_audit_provenance_intentional":
            "results-only clean-room re-publication: this directory carries "
            "the scorer's own documents and no design tree by design"}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout, r.stdout


# ── the flow's own verdict compounds are not claims of a pass ────────────
#
# `VACUOUS-PASS` and `PASS-VOIDED` are tokens this flow EMITS to say a step
# did NOT earn a pass. They appear in the tally line a RESULT.md quotes as
# evidence. Matching the bare `PASS` inside them turns an honest FAIL report
# into a burn-provenance demand for a burn that never happened.


def test_vacuous_pass_near_hardware_is_not_a_pass_claim(tmp_path):
    """The measured failure: two unrelated clauses, one 40-char window.

    `hardware` and `PASS` sit within 40 characters of each other only because
    a blocker table names absent hardware and the tally names a VACUOUS-PASS.
    The document's verdict is NOT CONVERGED.
    """
    (tmp_path / "RESULT.md").write_text(
        "# VERDICT: NOT CONVERGED\n\n"
        "The gate is an honest FAIL and nothing was burned.\n\n"
        "  PASS=7  FAIL=3  MISSING=5  VACUOUS-PASS=1\n\n"
        "| B9 | 2 steps waived for absent FPGA hardware; "
        "1 VACUOUS-PASS (diagnostic coverage) | process | OPEN |\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "does not claim" in r.stdout, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_SHA" not in r.stdout, r.stdout


def test_pass_voided_near_hardware_is_not_a_pass_claim(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# VERDICT: NOT CONVERGED\n\n"
        "hardware sign-off is PASS-VOIDED by its failed dependency.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "does not claim" in r.stdout, r.stdout


def test_overall_verdict_vacuous_pass_is_not_a_pass_claim(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Report\n\noverall verdict = PASS-VOIDED\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "does not claim" in r.stdout, r.stdout


# ── reverse controls: a REAL claim must still be caught ──────────────────
#
# A filter tightened until nothing matches would pass the three tests above
# and silently stop gating every genuine report. These must keep FAILING for
# missing provenance, which is only possible if the claim is still detected.


def test_genuine_hardware_pass_claim_still_demands_provenance(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Report\n\nhardware regression: PASS on 5/5 runs.\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_SHA" in r.stdout, r.stdout


def test_genuine_phase23_pass_claim_still_demands_provenance(tmp_path):
    (tmp_path / "RESULT.md").write_text("# Phase 2+3 PASS\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_SHA" in r.stdout, r.stdout


def test_genuine_overall_verdict_pass_still_demands_provenance(tmp_path):
    (tmp_path / "RESULT.md").write_text("# Report\n\noverall verdict: PASS\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_SHA" in r.stdout, r.stdout


def test_pass_with_waivers_verdict_still_demands_provenance(tmp_path):
    """`PASS_WITH_WAIVERS` is a credited pass; the underscore compound must
    not be swept up by the hyphen-compound exclusions."""
    (tmp_path / "RESULT.md").write_text(
        "# Report\n\naudit_verdict: PASS_WITH_WAIVERS\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RESULT_MD_MISSING_AUDIT_SHA" in r.stdout, r.stdout
