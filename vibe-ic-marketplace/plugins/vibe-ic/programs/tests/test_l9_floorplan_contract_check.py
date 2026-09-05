#!/usr/bin/env python3
"""Negative-control smoke tests for l9_floorplan_contract_check.py.

EVERY fixture is SYNTHESIZED neutral data — no real design's files are
copied, and no design name / PDK name / vendor part number / pin literal
from any real project appears. The "design" is ``fixture_top``, its
macro is ``fixture_sram_block``.

Each rule is asserted in BOTH directions: a gutted / impossible
floorplan must FAIL, a well-formed one must PASS.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "l9_floorplan_contract_check.py"


def _run(project: Path, *extra: str):
    rep = project / "rep.json"
    cmd = [sys.executable, str(PROG), str(project), "--json", str(rep), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    report = json.loads(rep.read_text()) if rep.is_file() else {}
    return proc, report


def _rules(report: dict) -> set[str]:
    return {f["rule"] for f in report.get("findings", [])}


def _docs(project: Path) -> Path:
    d = project / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gen(project: Path) -> Path:
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _l9_md(project: Path, body: str, name: str = "L9_constraints_floorplan.md"):
    (_docs(project) / name).write_text(body)


def _die_rect_doc(w: int, h: int, util_row: str = "") -> str:
    return (
        "# fixture_top floorplan contract\n\n"
        "| Key | Value | Note |\n"
        "|---|---|---|\n"
        f"| `DIE_AREA` | 0 0 {w} {h} | mandated by the fixture harness |\n"
        f"{util_row}"
    )


def _l19(project: Path, die_budget):
    (_gen(project) / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "doc_id": "L19",
        "fields": {"die_area_budget_um": die_budget},
    }))


def _lef(project: Path, macro: str, w: float, h: float):
    d = project / "input" / "pdk_local"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{macro}.lef").write_text(
        "VERSION 5.7 ;\n"
        f"MACRO {macro}\n"
        "  CLASS BLOCK ;\n"
        f"  SIZE {w} BY {h} ;\n"
        f"END {macro}\n"
    )


def _l9_json(project: Path, **kw):
    doc = {"doc_class": "integration_spec", "ic_name": "fixture_top"}
    doc.update(kw)
    (_gen(project) / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(doc))


# ─────────────────────────── POSITIVE CONTROLS ───────────────────────────

def test_no_floorplan_mandate_skips(tmp_path):
    """The common case: the design mandates no die, phase3 auto-sizes.
    Nothing is consumed verbatim, so nothing to gate."""
    _l9_md(tmp_path, "# fixture_top\n\nNo floorplan is mandated; the tool "
                     "decides the die.\n")
    proc, report = _run(tmp_path)
    # vibe-ic#1051 follow-up: an input-missing skip is the DISCLOSED tier, not a
    # plain pass. rc 2 is `_vacuous_exit.RC_VACUOUS`, which `flow_compliance_check`
    # records as VACUOUS_PASS; the `VACUOUS_PASS:` sentinel is the second,
    # rc-independent channel the same consumer reads. Asserting BOTH is the point —
    # either one alone can regress silently while the other keeps the test green.
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "VACUOUS_PASS:" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
    # The token CHANGED and the change is the point. This branch READ the
    # design's L9 / L19 layer and found it mandates no floorplan; calling that
    # `input-missing` collapsed it with the branch where no such layer exists
    # at all, and left the flow classifying a gate that answered as one that
    # errored. Both facts are still disclosed, now under their own names.
    assert report["summary"]["skip_kind"] == "class-not-applicable"
    assert report["summary"]["reason_class"] == "DESIGN_DECLARED_NA"
    assert report["reason_class"] == "DESIGN_DECLARED_NA"
    assert report["summary"]["skipped_reason"]


def test_wellformed_single_die_passes(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400,
                                   "| `FP_CORE_UTIL` | 45 | percent |\n"))
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["passed"] is True
    assert report["summary"]["resolved_die"] == "400x400"
    assert report["findings"] == []


def test_die_agreeing_with_l19_passes(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _l19(tmp_path, "400x400")
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []


def test_l19_only_die_is_nonvacuous_and_passes(tmp_path):
    """phase3's documented precedence consumes L19 when L9 has no direct
    rectangle; the floorplan gate must inspect that value, not rc=2 skip."""
    _l19(tmp_path, "420x360")
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VACUOUS_PASS:" not in (proc.stdout + proc.stderr)
    assert report["summary"]["resolved_die"] == "420x360"
    assert report["summary"]["l19_die"] == "420x360"
    assert report["findings"] == []


def test_NEGATIVE_l19_only_die_too_small_for_macro_fails(tmp_path):
    """The L19-only path reaches the same physical-fit rule as direct L9."""
    _l19(tmp_path, "120x120")
    _l9_json(tmp_path, submodules=[{"name": "fixture_sram_block"}])
    _lef(tmp_path, "fixture_sram_block", 500.0, 80.0)
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "L9_DIE_TOO_SMALL_FOR_MACROS" in _rules(report)
    assert report["summary"]["resolved_die"] == "120x120"


def test_macro_that_fits_passes(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400,
                                   "| `FP_CORE_UTIL` | 60 | percent |\n"))
    _l9_json(tmp_path, submodules=[{"name": "fixture_sram_block"}])
    _lef(tmp_path, "fixture_sram_block", 100.0, 80.0)
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["summary"]["macros_considered"] == {
        "fixture_sram_block": [100.0, 80.0]}
    assert report["findings"] == []


def test_stdcell_lef_is_never_treated_as_a_macro(tmp_path):
    """A LEF macro the design's own L9 does NOT declare must be ignored —
    otherwise a standard-cell library would blow up every floorplan."""
    _l9_md(tmp_path, _die_rect_doc(50, 50))
    _l9_json(tmp_path, submodules=[{"name": "fixture_alu"}])
    _lef(tmp_path, "fixture_stdcell_huge", 9000.0, 9000.0)
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["summary"]["macros_considered"] == {}
    assert report["findings"] == []


def test_two_declarations_that_agree_pass(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _l9_md(tmp_path, _die_rect_doc(400, 400), name="L9_constraints_extra.md")
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []


# ───────────────────────── NEGATIVE CONTROLS ─────────────────────────────

def test_NEGATIVE_two_different_die_rects_fail(tmp_path):
    """GUTTED LAYER: two contradicting DIE_AREA rects in the file set
    phase3 scans — the pinned die becomes a function of glob order."""
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _l9_md(tmp_path, _die_rect_doc(900, 900), name="L9_floorplan_alt.md")
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L9_DIE_AREA_AMBIGUOUS" in _rules(report)
    msg = next(f["message"] for f in report["findings"]
               if f["rule"] == "L9_DIE_AREA_AMBIGUOUS")
    assert "400x400" in msg and "900x900" in msg


def test_NEGATIVE_die_contradicts_l19_budget_fails(tmp_path):
    """Two layers carrying the same requirement with different values —
    phase3 honours L9 and silently drops L19."""
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _l19(tmp_path, "900x900")
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L9_DIE_AREA_CONTRADICTS_L19" in _rules(report)


def test_NEGATIVE_macro_wider_than_die_fails(tmp_path):
    """A hallucinated WxH that cannot physically hold the design's own
    macro. Derived from the macro's OWN LEF SIZE — nothing hardcoded."""
    _l9_md(tmp_path, _die_rect_doc(120, 120))
    _l9_json(tmp_path, submodules=[{"name": "fixture_sram_block"}])
    _lef(tmp_path, "fixture_sram_block", 500.0, 80.0)
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L9_DIE_TOO_SMALL_FOR_MACROS" in _rules(report)
    msg = next(f["message"] for f in report["findings"]
               if f["rule"] == "L9_DIE_TOO_SMALL_FOR_MACROS")
    assert "500" in msg


def test_NEGATIVE_macro_area_exceeds_usable_core_fails(tmp_path):
    """Each macro fits individually, but together they exceed the usable
    core implied by the design's OWN declared utilisation."""
    _l9_md(tmp_path, _die_rect_doc(300, 300,
                                   "| `FP_CORE_UTIL` | 40 | percent |\n"))
    _l9_json(tmp_path, submodules=[{"name": "fixture_sram_a"},
                                   {"name": "fixture_sram_b"}])
    _lef(tmp_path, "fixture_sram_a", 200.0, 150.0)   # 30000
    _lef(tmp_path, "fixture_sram_b", 200.0, 150.0)   # 30000 -> 60000
    # usable = 300*300*0.40 = 36000 < 60000
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L9_DIE_TOO_SMALL_FOR_MACROS" in _rules(report)


def test_NEGATIVE_same_knob_declared_twice_differently_fails(tmp_path):
    """One knob, two answers — the consumer takes the first by file
    order."""
    _l9_md(tmp_path, _die_rect_doc(400, 400,
                                   "| `PL_TARGET_DENSITY` | 0.35 | frac |\n"))
    _l9_md(tmp_path, "| `PL_TARGET_DENSITY` | 0.75 | frac |\n",
           name="L9_floorplan_alt_util.md")
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L9_CORE_UTIL_AMBIGUOUS" in _rules(report)


def test_different_knobs_with_different_values_pass(tmp_path):
    """SWEEP-DRIVEN NARROWING: FP_CORE_UTIL and PL_TARGET_DENSITY are
    DIFFERENT OpenLane knobs and legitimately differ (37 swept runs
    declare 20% / 0.25 deliberately). Firing here would be a false
    positive."""
    _l9_md(tmp_path, _die_rect_doc(400, 400,
                                   "| `PL_TARGET_DENSITY` | 0.25 | frac |\n"
                                   "| `FP_CORE_UTIL` | 20 | percent |\n"))
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L9_CORE_UTIL_AMBIGUOUS" not in _rules(report)


def test_widely_different_knobs_still_pass(tmp_path):
    """Even a wide cross-knob gap is legitimate — placement density is
    routinely set well above core utilisation."""
    _l9_md(tmp_path, _die_rect_doc(400, 400,
                                   "| `PL_TARGET_DENSITY` | 0.60 | frac |\n"
                                   "| `FP_CORE_UTIL` | 35 | percent |\n"))
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "L9_CORE_UTIL_AMBIGUOUS" not in _rules(report)


def test_NEGATIVE_implausible_util_fails(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400,
                                   "| `PL_TARGET_DENSITY` | 0.99 | frac |\n"))
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L9_CORE_UTIL_IMPLAUSIBLE" in _rules(report)


def test_NEGATIVE_die_width_height_pair_contradicts_rect(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _l9_md(tmp_path,
           "| `DIE_WIDTH` | 1000 um |\n| `DIE_HEIGHT` | 1000 um |\n",
           name="L9_floorplan_pair.md")
    proc, report = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout
    assert "L9_DIE_AREA_AMBIGUOUS" in _rules(report)


# ───────────────────── BLOCK / ADVISE + ESCAPE HATCHES ───────────────────

def test_default_run_declares_that_it_blocks(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _proc, report = _run(tmp_path)
    assert report["blocks"] is True


def test_advise_flag_downgrades_exit_code_but_keeps_findings(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _l19(tmp_path, "900x900")
    proc, report = _run(tmp_path, "--advise")
    assert proc.returncode == 0, proc.stdout
    assert report["blocks"] is False
    assert report["passed"] is False
    assert "L9_DIE_AREA_CONTRADICTS_L19" in _rules(report)


def test_util_max_flag_is_overridable(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400,
                                   "| `PL_TARGET_DENSITY` | 0.96 | frac |\n"))
    proc, _report = _run(tmp_path, "--util-max", "0.99")
    assert proc.returncode == 0, proc.stdout


def test_waiver_suppresses(tmp_path):
    _l9_md(tmp_path, _die_rect_doc(400, 400))
    _l19(tmp_path, "900x900")
    (tmp_path / "waivers.json").write_text(json.dumps({"waivers": [{
        "id": "l9_floorplan_contract_override",
        "rationale": "synthesized fixture: the L19 budget is a stale "
                     "placeholder and the L9 rect is authoritative",
    }]}))
    proc, report = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert report["findings"] == []
