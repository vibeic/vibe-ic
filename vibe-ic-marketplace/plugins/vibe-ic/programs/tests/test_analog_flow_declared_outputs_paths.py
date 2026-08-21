#!/usr/bin/env python3
"""Analog A1-A9: the flow's DECLARED artefact paths must be the ones a real
run produces, and A6/A9's declared evidence must be broad enough that the
step's own gate is actually reached.

Every assertion here is a behavioural property of a project directory laid out
the way the producers lay it out — never a source substring, never a private
symbol. Four defects are covered:

  * A1-A4 declared `phase{1,2}/analog/...`, a path NO producer writes.
    `analog_one_shot_runner` and `phase1_doc_one_shot_runner` both emit through
    `_path_layout.analog_dir()` = `phase3/analog/`, and the A-gates read there.
    The declaration appeared to work only because
    `flow_compliance_check._glob_first` carries a hidden phase{1,2,3}/analog →
    canonical remap; `flow_dashboard_data`, which has no such remap, resolved
    every A1-A4 artefact of a REAL analog run to "absent".

  * `flow_dashboard_data._lane_applicability` probed only
    `phase1/analog/analog_block_list.json`, so on a real analog run the whole
    Analog + Mixed-Signal lane rendered `na — design declares no analog blocks`.

  * A6 declared ONLY the two sign-off .flag files, while
    `analog_a6_block_pv_check` treats drc.report / *.lyrdb / comp.json /
    lvs.report as its PRIMARY evidence. Because `check_step` uses
    required_outputs as a cheap pre-check and returns MISSING before fetching
    the gate, a block with real DRC/LVS reports was reported MISSING while the
    gate itself returned PASS on the identical directory.

  * A9 declared `*_cosim_results.json`, which never matches
    `mixed_signal_results.json` — the aggregate report `mixed_signal_cosim_check`
    itself cites as authoritative evidence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

yaml = pytest.importorskip("yaml")

import flow_compliance_check as fcc  # noqa: E402
import flow_dashboard_data as fdd  # noqa: E402


def _steps_by_id() -> dict:
    data = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    return {str(s.get("id")): s for s in data["steps"]}


def _block_list(project: Path, where: str = "phase3", blocks=("ldo",)) -> None:
    d = project / where / "analog"
    d.mkdir(parents=True, exist_ok=True)
    (d / "analog_block_list.json").write_text(json.dumps({"blocks": list(blocks)}))


def _canonical_a1_a4_artefacts(project: Path, block: str = "ldo") -> None:
    """Exactly what `analog_one_shot_runner` writes for A1-A4."""
    b = project / "phase3" / "analog" / block
    b.mkdir(parents=True, exist_ok=True)
    (b / "spec.json").write_text(json.dumps({"block": block, "specs": []}))
    (b / "topology.md").write_text("# topology\ncascode amplifier\n")
    (b / f"{block}.sp").write_text(f".subckt {block} vdd vss\n.ends\n")
    (b / "corner_results.json").write_text(json.dumps({"corners": []}))


def _legacy_a1_a4_artefacts(project: Path, block: str = "ldo") -> None:
    """The phase-distributed layout `migrate_to_layout_p` can leave behind."""
    p1 = project / "phase1" / "analog" / block
    p1.mkdir(parents=True, exist_ok=True)
    (p1 / "spec.json").write_text(json.dumps({"block": block, "specs": []}))
    p2 = project / "phase2" / "analog" / block
    p2.mkdir(parents=True, exist_ok=True)
    (p2 / "topology.md").write_text("# topology\ncascode amplifier\n")
    (p2 / f"{block}.sp").write_text(f".subckt {block} vdd vss\n.ends\n")
    (p2 / "corner_results.json").write_text(json.dumps({"corners": []}))


def _declared_resolves(project: Path, sid: str) -> list:
    """(spec, resolved?) for every required_outputs entry of step `sid`,
    resolved through `flow_dashboard_data` — a consumer that carries NO
    analog-path remap, so it sees the declaration exactly as written."""
    step = _steps_by_id()[sid]
    return [(spec, fdd._resolve_spec(project, spec)[0])
            for spec in step.get("required_outputs", [])]


# ─── A1-A4: the declaration must match where the producer writes ───────────

@pytest.mark.parametrize("sid", ["A1", "A2", "A3", "A4"])
def test_declared_outputs_resolve_on_a_canonical_run(tmp_path: Path, sid: str):
    """THE discriminator. A project laid out the way the analog runner lays it
    out must satisfy every A1-A4 required_outputs entry in a tool with no
    analog remap. Before the fix these declared phase1//phase2/analog and all
    four resolved False on a run that had produced every artefact."""
    _block_list(tmp_path)
    _canonical_a1_a4_artefacts(tmp_path)
    resolved = _declared_resolves(tmp_path, sid)
    assert resolved, f"{sid} declares no required_outputs"
    unresolved = [spec for spec, ok in resolved if not ok]
    assert not unresolved, (
        f"{sid} declares outputs a canonical run does not satisfy: "
        f"{unresolved}")


@pytest.mark.parametrize("sid", ["A1", "A2", "A3", "A4"])
def test_guard_legacy_phase_distributed_layout_still_resolves(
        tmp_path: Path, sid: str):
    """Direction-1 guard: the phase1//phase2 spelling must stay ACCEPTED.
    `migrate_to_layout_p` moves a legacy project-root analog/ tree there, and
    the A-gates list it as a second artefact candidate. Widening the
    declaration must not have replaced one exclusive path with another."""
    _block_list(tmp_path, where="phase1")
    _legacy_a1_a4_artefacts(tmp_path)
    unresolved = [spec for spec, ok in _declared_resolves(tmp_path, sid)
                  if not ok]
    assert not unresolved, (
        f"{sid} no longer accepts the legacy phase-distributed layout: "
        f"{unresolved}")


@pytest.mark.parametrize("sid", ["A1", "A2", "A3", "A4"])
def test_guard_absent_artefacts_still_do_not_resolve(tmp_path: Path, sid: str):
    """Direction-1 guard: widening the accepted locations must not make the
    declaration satisfiable by nothing. An empty project resolves none."""
    _block_list(tmp_path)
    assert all(not ok for _, ok in _declared_resolves(tmp_path, sid))


# ─── dashboard lane applicability ─────────────────────────────────────────

def test_analog_lane_applicable_from_canonical_block_list(tmp_path: Path):
    """THE discriminator. The block list is written to phase3/analog by both
    producers; the dashboard must not call the analog lane `na` on a project
    that declares blocks there."""
    _block_list(tmp_path, where="phase3")
    analog, _ = fdd._lane_applicability(tmp_path)
    assert analog is True


def test_guard_analog_lane_applicable_from_legacy_block_list(tmp_path: Path):
    """Direction-1 guard: the phase1 location the flow yaml conditions on
    keeps working."""
    _block_list(tmp_path, where="phase1")
    analog, _ = fdd._lane_applicability(tmp_path)
    assert analog is True


def test_guard_pure_digital_project_keeps_analog_lane_not_applicable(
        tmp_path: Path):
    """Direction-1 guard: a design with NO analog block list anywhere must
    still be `na`. Accepting a second location must not make every project
    look analog."""
    analog, silicon = fdd._lane_applicability(tmp_path)
    assert analog is False
    assert silicon is False


def test_guard_phantom_block_list_does_not_make_the_analog_lane_applicable(
        tmp_path: Path):
    """Direction-1 guard on the MIRROR IMAGE of the defect this file fixes.

    The empty-directory guard above never exercises the interesting case: a
    pure-digital project that DOES carry an `analog_block_list.json`, whose
    only entry is a `low_confidence` keyword phantom. 8 of the 17 tracked
    projects in this repo that carry a block list are exactly that shape. Made
    applicable on `.exists()` alone, their dashboards would render the whole
    Analog A1-A9 + Mixed-Signal M1-M4 lane as work-in-progress. The dashboard
    must give the SAME answer as the ORGANIC #676 predicate the analog P0
    gates already use."""
    d = tmp_path / "phase3" / "analog"
    d.mkdir(parents=True)
    (d / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "dac", "low_confidence": True}]}))
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "ic_class.json").write_text(json.dumps({"has_analog": False}))

    import _analog_a_check_common as aac
    assert aac.analog_class_is_na(tmp_path) is True     # the #676 answer
    assert fdd._lane_applicability(tmp_path)[0] is False  # must agree


def test_spec_backed_block_on_a_digital_class_stays_applicable(
        tmp_path: Path):
    """§4.05 no-leak half: the #676 consult must not become a blanket bypass.
    A block that is NOT low_confidence keeps the lane applicable even when the
    IC-class verdict says non-analog — the same asymmetry `analog_class_is_na`
    enforces for the gates.

    Deliberately NOT named `test_guard_…`: it reddens on origin/main, for the
    unrelated reason that the pre-fix probe cannot see a `phase3/analog/` list
    at all. It is a discriminator that happens to assert the no-leak direction,
    not a both-trees guard."""
    d = tmp_path / "phase3" / "analog"
    d.mkdir(parents=True)
    (d / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "ldo"}]}))
    rd = tmp_path / "reports"
    rd.mkdir(parents=True)
    (rd / "ic_class.json").write_text(json.dumps({"has_analog": False}))

    import _analog_a_check_common as aac
    assert aac.analog_class_is_na(tmp_path) is False
    assert fdd._lane_applicability(tmp_path)[0] is True


# ─── A6: declared evidence must reach the gate ────────────────────────────

def _a6_reports_project(tmp_path: Path) -> Path:
    _block_list(tmp_path)
    b = tmp_path / "phase3" / "analog" / "ldo"
    b.mkdir(parents=True, exist_ok=True)
    (b / "drc.report").write_text("Total DRC violations: 0\n")
    (b / "lvs.report").write_text("LVS match: true\nnetlists match\n")
    return tmp_path


def _a6_flags_project(tmp_path: Path) -> Path:
    _block_list(tmp_path)
    b = tmp_path / "phase3" / "analog" / "ldo"
    b.mkdir(parents=True, exist_ok=True)
    (b / "drc_clean.flag").write_text("# ldo DRC clean\nviolations: 0\n")
    (b / "lvs_match.flag").write_text("# ldo LVS\nlvs: match\n")
    return tmp_path


def test_a6_report_evidence_reaches_the_gate(tmp_path: Path):
    """THE discriminator. drc.report + lvs.report is what
    `analog_a6_block_pv_check` calls PRIMARY evidence, and it returns PASS on
    this directory standalone. Before the fix `check_step` short-circuited to
    MISSING on the flag-only declaration and never ran the gate."""
    project = _a6_reports_project(tmp_path)
    res = fcc.check_step(project, _steps_by_id()["A6"], {})
    assert res.status != "MISSING", res.reasons
    assert res.status == "PASS", (res.status, res.reasons)


def test_guard_a6_flag_evidence_still_accepted(tmp_path: Path):
    """Direction-1 guard: the original flag-file evidence keeps working."""
    project = _a6_flags_project(tmp_path)
    res = fcc.check_step(project, _steps_by_id()["A6"], {})
    assert res.status == "PASS", (res.status, res.reasons)


def test_guard_a6_with_no_pv_evidence_is_not_certified(tmp_path: Path):
    """Direction-1 guard, and the load-bearing one: broadening WHAT SATISFIES
    the declaration must not let a block with no DRC/LVS evidence at all be
    signed off. It must still be non-PASS."""
    _block_list(tmp_path)
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True, exist_ok=True)
    res = fcc.check_step(tmp_path, _steps_by_id()["A6"], {})
    assert res.status != "PASS", (res.status, res.reasons)


def test_guard_a6_dirty_drc_report_still_fails(tmp_path: Path):
    """Direction-1 guard: a block whose DRC report shows violations must not
    be certified merely because the declaration now names drc.report."""
    _block_list(tmp_path)
    b = tmp_path / "phase3" / "analog" / "ldo"
    b.mkdir(parents=True, exist_ok=True)
    (b / "drc.report").write_text("Total DRC violations: 7\n")
    (b / "lvs.report").write_text("LVS match: true\nnetlists match\n")
    res = fcc.check_step(tmp_path, _steps_by_id()["A6"], {})
    assert res.status != "PASS", (res.status, res.reasons)


# ─── A9: the aggregate cosim report is declared evidence ──────────────────

def _passing_aggregate(project: Path, block: str = "ldo") -> None:
    d = project / "phase3" / "mixed_signal" / "cosim"
    d.mkdir(parents=True, exist_ok=True)
    (d / "mixed_signal_results.json").write_text(json.dumps({
        "scenarios": [
            {"name": f"{block}_startup", "status": "PASS"},
            {"name": f"{block}_load_step", "status": "PASS"},
        ],
    }))


def test_a9_aggregate_cosim_report_reaches_the_gate(tmp_path: Path):
    """THE discriminator. `mixed_signal_cosim_check` reads
    phase3/mixed_signal/cosim/mixed_signal_results.json as its authoritative
    aggregate; that filename never matched A9's `*_cosim_results.json` glob, so
    a project whose only cosim substance was the aggregate short-circuited to
    MISSING before the gate ran."""
    _block_list(tmp_path)
    _passing_aggregate(tmp_path)
    res = fcc.check_step(tmp_path, _steps_by_id()["A9"], {})
    assert res.status != "MISSING", res.reasons


def test_guard_a9_per_block_cosim_results_still_accepted(tmp_path: Path):
    """Direction-1 guard: the per-block `<block>_cosim_results.json` shape the
    mixed-signal-cosim skill instructs must stay declared evidence."""
    _block_list(tmp_path)
    d = tmp_path / "phase3" / "mixed_signal" / "cosim"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo_cosim_results.json").write_text(json.dumps(
        {"block": "ldo", "scenarios": [{"name": "s1", "status": "PASS"}]}))
    res = fcc.check_step(tmp_path, _steps_by_id()["A9"], {})
    assert res.status != "MISSING", res.reasons


def test_a9_hw_measurements_alternative_names_the_gates_own_path(
        tmp_path: Path):
    """Discriminator (not a guard): A9's own optional hardware gate conditions
    on `phase3/analog/*/hw_measurements.json`, but required_outputs spelled the
    alternative `analog/*/hw_measurements.json`, which resolves only through
    `_glob_first`'s hidden analog remap. A bench-verified run must satisfy the
    declaration in a tool that has no such remap."""
    _block_list(tmp_path)
    b = tmp_path / "phase3" / "analog" / "ldo"
    b.mkdir(parents=True, exist_ok=True)
    (b / "hw_measurements.json").write_text(json.dumps({"measurements": []}))
    resolved = _declared_resolves(tmp_path, "A9")
    assert any(ok for _, ok in resolved), resolved


def test_guard_a9_empty_project_still_missing(tmp_path: Path):
    """Direction-1 guard: adding alternatives must not make A9 satisfiable by
    an empty project."""
    _block_list(tmp_path)
    res = fcc.check_step(tmp_path, _steps_by_id()["A9"], {})
    assert res.status == "MISSING", (res.status, res.reasons)
