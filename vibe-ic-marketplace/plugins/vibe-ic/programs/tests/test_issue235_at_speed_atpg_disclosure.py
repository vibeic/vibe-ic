"""vibe-ic#235 — DT2/DT3 producer-side disclosure artefact.

THE DEFECT (measured on real data before the fix)
=================================================
`benchmark-data/ic/sha256/clean_run_v1422_20260715` shipped with
`path_delay_coverage.json` present, `sdd_coverage.json` ABSENT,
`sdd_coverage_gate.json` ABSENT, and NO not-run record anywhere in the tree.
DT3 had vanished, and nothing on disk said whether it was inapplicable, never
launched, or broken. Running the two gates on that real tree gave:

    sdd_coverage_check       -> FAIL "sdd_coverage.json absent or invalid JSON"
    path_delay_coverage_check-> FAIL "path_delay_coverage.json absent or ..."

versus DT1, which was fixed by #219 and answers the same tree with

    transition_coverage_check-> FAIL "... and NO not-run record was left
                                 either — there is no evidence the step ran"

DT1 has a disclosure CHANNEL and reports its own emptiness; DT2/DT3 had none,
so "never ran", "ran and could not measure" and "ran and crashed" were a single
indistinguishable state — three different repairs behind one message. A missing
disclosure is indistinguishable from a step that passed.

WHAT IS ASSERTED HERE
=====================
Producer side  — every self-disable branch WRITES `<step>_atpg_not_run.json`
                 naming the missing inputs and the stage it stopped at, and a
                 REAL measurement DELETES any stale record.
Consumer side  — the DT2/DT3 gates read that record and answer BLOCKED (with
                 the reason) instead of a bare FAIL, while an absent artefact
                 with NO record stays FAIL. BLOCKED never exits 0.
Gating         — UNCHANGED. The helpers make the existing decisions speak; they
                 must not arm or disarm the producer differently, or a design
                 that grades today would stop grading.

Every assertion below names the mutation it catches, because a disclosure test
that passes on a permanently-silent producer is the bug it is testing for.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional, Tuple

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import path_delay_coverage_check as PDF     # noqa: E402
import sdd_coverage_check as SDD            # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

DT_ALL = ("DT1", "DT2", "DT3")


# ---------------------------------------------------------------- fixtures






def _l20_applicability(project: Path, applicability: str) -> Path:
    """Write the design-owned DFT applicability declaration consumed by flow."""
    path = project / "phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "doc_id": "L20",
        "applicability": applicability,
        "fields": ({"dft_present": False, "scan_chains": []}
                   if applicability == "NOT_APPLICABLE" else
                   {"dft_present": True}),
        "extraction_status": "EXTRACTED",
        "extraction_evidence": {"source": "synthetic neutral fixture"},
    }))
    return path












# ================================================================
# PRODUCER — the self-disable branches must speak
# ================================================================









# ================================================================
# PRODUCER — the OTHER direction. Without these, "always write a record"
# would pass every test above and be a new lie on disk.
# ================================================================









# ================================================================
# GATING PARITY — the refactor must not change WHEN the producer runs or HOW
# it is invoked. This is the regression guard on the extraction itself.
# ================================================================











# ================================================================
# CONSUMER — the gates must turn the record into BLOCKED, and must NOT turn
# silence into BLOCKED.
# ================================================================



@pytest.mark.parametrize("step,mod", [("DT2", PDF), ("DT3", SDD)])
def test_gate_still_fails_when_nothing_was_recorded(tmp_path, step, mod):
    """THE DISCRIMINATION, and the control that stops the test above from
    passing on `return BLOCKED` unconditionally. An absent artefact with no
    record is not blocked — nobody knows whether the step ever ran.

    MUTATION THIS CATCHES: returning BLOCKED whenever the coverage is absent,
    which would launder every silently-vanished step into a named deferral.
    """
    report = mod.audit(tmp_path)
    assert report["verdict"] == "FAIL", report
    assert report["not_run_record"] is None
    assert "NO not-run record" in " ".join(report["reasons"])








# ================================================================
# FLOW LEVEL — what the disclosure is allowed to BUY
# ================================================================
# Everything above measures the record and the two gates that read it. None of
# it looks at the VERDICT `flow_compliance_check` prints, which is the number a
# reviewer actually reads — and that gap let a change land that flipped the
# whole flow FAIL -> PASS while every assertion above stayed green. The two
# tests below close it from both sides: the defect input must stay red, and the
# legitimate input must stay green.

FLOW_YAML = PROGS.parent / "flow" / "phase1_phase2_phase3.yaml"
FCC_PY = PROGS / "flow_compliance_check.py"


def _dt_subflow(tmp_path: Path) -> Path:
    """A flow def carrying DT1/DT2/DT3 VERBATIM from the live flow yaml.

    Copied, never hand-written: the point is to measure the shipped step
    definitions, so an edit to the real `condition` / `required_outputs` is
    felt here. `blocks_on` is pruned to the ids present so the subset parses.
    """
    import yaml  # local: only this leg needs it
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    keep = {"DT1", "DT2", "DT3"}
    steps = [s for s in doc["steps"] if str(s.get("id")) in keep]
    assert {str(s["id"]) for s in steps} == keep, (
        f"the live flow yaml no longer declares all of {keep}")
    for s in steps:
        s["blocks_on"] = [b for b in (s.get("blocks_on") or [])
                          if str(b) in keep]
    out = tmp_path / "dt_subflow.yaml"
    out.write_text(yaml.safe_dump(
        {"version": doc.get("version", 2),
         "flow_name": doc.get("flow_name", "phase1_phase2_phase3"),
         "steps": steps},
        sort_keys=False, allow_unicode=True))
    return out


def _fcc(project: Path, flow_def: Path) -> Tuple[int, dict]:
    rep = project / "_fcc.json"
    proc = _pr.run(
        [sys.executable, str(FCC_PY), str(project),
         "--flow-def", str(flow_def), "--strict", "--json", str(rep)],
        capture_output=True, text=True)
    doc = json.loads(rep.read_text())
    doc["_stdout"] = proc.stdout
    return proc.returncode, doc


def _status_of(doc: dict, step: str) -> Optional[str]:
    for s in doc["steps"]:
        if str(s.get("id")) == step:
            return s.get("status")
    return None






def test_a_routed_extracted_design_with_no_dft_does_not_arm_dt2(tmp_path):
    """THE LEGITIMATE INPUT, and the control that stops the test above from
    being satisfied by an over-eager condition.

    A design that routed and extracted parasitics and explicitly declares DFT
    NOT_APPLICABLE is the case where DT1 legitimately self-skips. DT2 must
    self-skip alongside it and cite that design-owned declaration. Merely
    omitting a scan cut is not a no-DFT declaration (vibe-ic#1976).

    MUTATION THIS CATCHES: adding `phase3/stage3/extracted/*.spef` to DT2's
    any-of condition as "DT1's cut_netlist.v analogue". The SPEF alone then
    arms DT2, its `path_delay_coverage.json` is absent, and this tree takes a
    hard MISSING and `Overall: FAIL` rc 1 — a false alarm bought with the
    false clean above. Measured: with the SPEF branch, DT2 MISSING rc 1;
    without it, DT2 SKIPPED-CONDITION rc 0.
    """
    declaration = _l20_applicability(tmp_path, "NOT_APPLICABLE")
    spef = tmp_path / "phase3/stage3/extracted/top.spef"
    spef.parent.mkdir(parents=True, exist_ok=True)
    spef.write_text('*SPEF "IEEE 1481-1998"\n')
    pnr = tmp_path / "phase3/stage3/pnr/top_pnr.v"
    pnr.parent.mkdir(parents=True, exist_ok=True)
    pnr.write_text("module top(); endmodule\n")

    rc, doc = _fcc(tmp_path, _dt_subflow(tmp_path))
    assert _status_of(doc, "DT1") == "NOT_APPLICABLE", doc["_stdout"]
    assert _status_of(doc, "DT2") == "NOT_APPLICABLE", (
        "a routed+extracted design with NO DFT armed DT2 and took a hard "
        "MISSING for a grade no producer was ever asked for:\n"
        + doc["_stdout"])
    dt2 = next(step for step in doc["steps"] if str(step.get("id")) == "DT2")
    assert str(declaration.relative_to(tmp_path)) in "\n".join(dt2["reasons"]), dt2
    assert doc["counts"]["FAIL"] == 0, doc["_stdout"]
    assert doc["overall"] == "PASS", doc["_stdout"]
    assert rc == 0, doc["_stdout"]
