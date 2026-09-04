"""A rejected power-aware LVS model must say WHY it was rejected.

THE DEFECT
----------
`_try_power_aware_lvs` tries the WELL-TIED power model first and falls back to
the 4-rail one. Every rejection was a bare `return None`, at all four exits
(emit raised / nothing patched / netgen raised / classifier said not-MATCH). A
run that fell through to the plain path therefore left NO record at all, which
makes these indistinguishable after the fact:

  * power-aware was never attempted (unrecognised PDK, nothing patched);
  * netgen reported a conclusive non-match — a genuine power-network defect;
  * netgen exited 0 and matched, but its report read back empty — the #184
    read/flush race, which is a READ defect, not a power-network one.

The third is not hypothetical. Re-running netgen by hand on two digital ICs'
own artefacts, the WELL-TIED model matched uniquely (369=369 nets / 339=339
devices; 978=978 on the second) while the 4-rail reference carries exactly two
extra well-body nets and so cannot match a layout that ties the wells to the
rails — yet both runs were recorded as power-aware MISMATCHES, and a whole
campaign attributed that to pin ordering in the power network.

The fix records the per-model outcome in
`reports/phase3/lvs_power_aware_attempts.json` and in the PASS verdict extras,
and NAMES the `rc == 0` + no-terminal-verdict signature as a read/flush symptom.

WHAT THIS MUST NOT DO
---------------------
It must not change WHICH model is selected, and it must never upgrade a
verdict. `test_selection_is_unchanged_*` and
`test_a_conclusive_mismatch_is_not_relabelled_a_read_problem` are the guards:
they fail if the record-keeping ever starts deciding anything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P  # noqa: E402

_ATTEMPTS_REL = "reports/phase3/lvs_power_aware_attempts.json"

_MATCH_RPT = "Final result: Circuits match uniquely.\n"
_MISMATCH_RPT = ("Final result:\n"
                 "Top level cell failed pin matching.\n")


def _project(tmp_path: Path) -> Path:
    p = tmp_path / "proj"
    (p / "reports" / "phase3").mkdir(parents=True)
    (p / "phase3" / "stage3" / "extracted").mkdir(parents=True)
    return p


def _wire(monkeypatch, tmp_path, *, report_by_model, rc=0, patched=1,
          layout_ports=()):
    """Drive `_try_power_aware_lvs` with no docker and no netgen.

    `report_by_model` maps "well_tied"/"four_rail" -> the report text netgen
    would have left on disk (or "" for the empty read the race produces).
    """
    project = _project(tmp_path)
    seen: list = []
    spice = (project / "phase3" / "stage3" / "extracted"
             / "chip_top.spice")
    spice.write_text(".subckt chip_top " + " ".join(layout_ports)
                     + "\n.ends chip_top\n")

    # `cell_lef` is accepted because the real `emit_to_file` gained it
    # (vibe-ic#719: a project-staged PDK has no table entry, so its power model
    # is derived from its own std-cell LEF). A stub that refuses the kwarg
    # raises TypeError inside the caller's `except Exception`, the attempt is
    # discarded, and the whole power-aware path silently returns None — which
    # is what these tests measured before the signature was matched.
    def _emit_to_file(netlist, pdk_name, out_path, top=None,
                      rails_as_ports=False, tie_wells_to_rails=False,
                      cell_lef=None):
        Path(out_path).write_text(
            f"// power-aware netlist rails_as_ports={rails_as_ports}\n")
        return {"modules_patched": patched, "instances_patched": 1191,
                "rails": ["VPWR", "VGND"],
                "rails_as_ports": rails_as_ports}

    def _exec(container, cmd, marker=None, **_kw):
        model = "well_tied" if "pwraware_welltied" in cmd else "four_rail"
        seen.append(model)
        (project / "reports" / "phase3" / "lvs_power_aware.rpt").write_text(
            report_by_model.get(model, ""))
        return rc, "", ""

    monkeypatch.setattr(P._lvs_pa, "emit_to_file", _emit_to_file)
    monkeypatch.setattr(P, "_docker_exec", _exec)
    monkeypatch.setattr(P, "_to_container_path", lambda s, c: str(s))
    monkeypatch.setattr(P._pl, "extracted_dir",
                        lambda pr: pr / "phase3" / "stage3" / "extracted")
    # Read the report straight off disk — the flush retry is #184's concern,
    # already fixed and tested elsewhere; here it would only add wall-clock.
    monkeypatch.setattr(
        P, "_read_lvs_report_flushed",
        lambda rpt, **kw: rpt.read_text() if rpt.is_file() else "")
    return project, seen


def _pdk() -> "P.PdkConfig":
    return P.PdkConfig(name="sky130A", liberty="", tech_lef="", cell_lef="",
                       cell_gds="", site="", drc_deck=None)


def _run(project):
    return P._try_power_aware_lvs(
        project, "chip_top", _pdk(), "vibeic-eda",
        project / "phase3" / "stage3" / "extracted" / "chip_top.spice",
        "/w/chip_top.spice", "chip_top",
        project / "phase3" / "stage3" / "extracted" / "chip_top_pnr.v",
        "/w/setup.tcl", project / "reports" / "phase3" / "lvs.rpt", None, 0.0)


def _attempts(project) -> dict:
    return json.loads((project / _ATTEMPTS_REL).read_text())


# --------------------------------------------------------------------------
# DEFECT — no record survives a fall-through
# --------------------------------------------------------------------------

def test_a_run_that_fell_through_still_records_both_models(tmp_path,
                                                           monkeypatch):
    """Both models rejected -> the runner falls through to the plain path, and
    THAT is exactly when the record is needed. Nothing is written today."""
    project, seen = _wire(monkeypatch, tmp_path,
                          report_by_model={"well_tied": _MISMATCH_RPT,
                                           "four_rail": _MISMATCH_RPT})
    assert _run(project) is None, "premise: neither model matched"
    rec = _attempts(project)
    assert rec["accepted"] is False
    assert [a["model"] for a in rec["attempts"]] == ["well_tied", "four_rail"]
    assert all(a["rejected_at"] == "classify" for a in rec["attempts"])


def test_an_empty_report_on_a_clean_exit_is_named_a_read_problem(tmp_path,
                                                                 monkeypatch):
    """The signature that was mis-attributed to the power network: netgen
    exited 0 and the report read back empty. The record must say so."""
    project, _ = _wire(monkeypatch, tmp_path, rc=0,
                       report_by_model={"well_tied": "", "four_rail": ""})
    assert _run(project) is None
    for a in _attempts(project)["attempts"]:
        assert a["netgen_rc"] == 0
        assert a["report_had_terminal_verdict"] is False
        assert "read/flush" in a["reason"]


def test_a_conclusive_mismatch_is_not_relabelled_a_read_problem(tmp_path,
                                                                monkeypatch):
    """The no-leak boundary. A report that DOES carry netgen's terminal verdict
    and still does not match must be recorded as a real non-match — otherwise
    the record would launder a genuine power-network defect."""
    project, _ = _wire(monkeypatch, tmp_path,
                       report_by_model={"well_tied": _MISMATCH_RPT,
                                        "four_rail": _MISMATCH_RPT})
    assert _run(project) is None
    for a in _attempts(project)["attempts"]:
        assert a["report_had_terminal_verdict"] is True
        assert "read/flush" not in a["reason"]
        assert a["reason"] == "netgen reported a conclusive non-match"


def test_an_emit_that_patched_nothing_is_recorded_at_the_emit_stage(
        tmp_path, monkeypatch):
    """'power-aware was never really attempted' must be distinguishable from
    'it was attempted and rejected' — that is the whole point."""
    project, _ = _wire(monkeypatch, tmp_path, patched=0,
                       report_by_model={"well_tied": _MATCH_RPT,
                                        "four_rail": _MATCH_RPT})
    assert _run(project) is None
    for a in _attempts(project)["attempts"]:
        assert a["rejected_at"] == "emit"
        assert a["modules_patched"] == 0


def test_the_accepted_model_is_recorded_and_surfaced_in_the_verdict(
        tmp_path, monkeypatch):
    project, _ = _wire(monkeypatch, tmp_path,
                       report_by_model={"well_tied": _MATCH_RPT,
                                        "four_rail": _MATCH_RPT})
    res = _run(project)
    assert res is not None and res.status == "PASS"
    rec = _attempts(project)
    assert rec["accepted"] is True
    accepted = rec["attempts"][-1]
    assert accepted["model"] == "well_tied"
    assert accepted["accepted"] is True
    assert accepted["rails_as_ports"] is False
    assert accepted["effective_rails"] == ["VPWR", "VGND"]
    assert accepted["layout_power_ports"] == []
    assert accepted["netlist"]
    verdict = json.loads(
        (project / "reports" / "phase3" / "lvs_verdict.json").read_text())
    assert verdict["power_aware_attempts"] == rec["attempts"]


# --------------------------------------------------------------------------
# GUARD — recording must not decide anything
# --------------------------------------------------------------------------

@pytest.mark.parametrize("reports,expected_calls,expect_pass", [
    ({"well_tied": _MATCH_RPT, "four_rail": _MATCH_RPT},
     ["well_tied"], True),                       # first model wins, no fallback
    ({"well_tied": _MISMATCH_RPT, "four_rail": _MATCH_RPT},
     ["well_tied", "four_rail"], True),          # fallback still reachable
    ({"well_tied": _MISMATCH_RPT, "four_rail": _MISMATCH_RPT},
     ["well_tied", "four_rail"], False),         # both rejected -> plain path
])
def test_selection_is_unchanged_by_the_record_keeping(
        tmp_path, monkeypatch, reports, expected_calls, expect_pass):
    """WHICH model runs, in WHICH order, and whether the step PASSes must be
    exactly what they were before any of this was recorded."""
    project, seen = _wire(monkeypatch, tmp_path, report_by_model=reports)
    res = _run(project)
    assert seen == expected_calls
    assert (res is not None) is expect_pass


def test_no_verdict_is_upgraded_by_the_record(tmp_path, monkeypatch):
    """A run where neither model matched must return None — the record exists,
    but it buys the caller nothing."""
    project, _ = _wire(monkeypatch, tmp_path, rc=0,
                       report_by_model={"well_tied": "", "four_rail": ""})
    assert _run(project) is None
    assert (project / _ATTEMPTS_REL).is_file()


# --------------------------------------------------------------------------
# PAD-RING TOP-PORT AUTHORITY — measured extraction decides the interface
# --------------------------------------------------------------------------

@pytest.mark.parametrize("layout_ports,expected", [
    ((), False),
    (("VPWR",), False),       # incomplete rail set fails closed
    (("VPWR", "VGND"), True),
])
def test_extracted_top_requires_the_complete_effective_rail_set(
        tmp_path, monkeypatch, layout_ports, expected):
    project, _ = _wire(
        monkeypatch, tmp_path, layout_ports=layout_ports,
        report_by_model={"well_tied": _MATCH_RPT,
                         "four_rail": _MATCH_RPT})
    assert _run(project) is not None
    attempt = _attempts(project)["attempts"][0]
    assert attempt["effective_rails"] == ["VPWR", "VGND"]
    assert attempt["layout_power_ports"] == sorted(layout_ports)
    assert attempt["rails_as_ports"] is expected
    emitted = (project / "phase3" / "stage3" / "extracted"
               / "chip_top_pwraware_welltied.v").read_text()
    assert f"rails_as_ports={expected}" in emitted
