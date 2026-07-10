"""test_flow_dashboard_data.py — the live-dashboard DATA PROVIDER.

flow_dashboard_data.collect(project, full=False) reads the canonical flow yaml
and resolves each step's required_outputs against a project tree to a fast,
file-stat-only status. These tests are fully synthetic (no docker, no real flow
run): a tiny temp project with a couple of fake outputs + a disclosed-skip
sentinel exercises the status logic and the exact JSON contract the CLI and web
renderers depend on.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import flow_dashboard_data as D  # noqa: E402

_PHASE_ORDER = ["phase1", "phase2", "phase3", "analog", "mixed", "manufacturing"]
# Track the module's canonical status contract so this never silently drifts
# when a new honest status (e.g. "partial") is added.
_STATUSES = list(D._STATUSES)


# --------------------------------------------------------------------------- #
# Contract-shape invariants against the REAL flow yaml
# --------------------------------------------------------------------------- #
def _find_step(data, sid):
    for ph in data["phases"]:
        for st in ph["steps"]:
            if st["id"] == sid:
                return st, ph
    return None, None


def test_real_flow_empty_project_has_six_phases_and_never_raises(tmp_path):
    # nonexistent/empty project — must not raise, must emit all 6 lanes.
    proj = tmp_path / "does_not_exist_yet"
    data = D.collect(proj)  # dir does not exist
    assert [p["key"] for p in data["phases"]] == _PHASE_ORDER
    # every lane carries its declared label + icon and step count fields
    for p in data["phases"]:
        assert p["label"] and p["icon"]
        assert isinstance(p["steps"], list)
        assert p["total"] == len(p["steps"])
        assert p["done"] == sum(1 for s in p["steps"] if s["status"] == "done")
    total = sum(p["total"] for p in data["phases"])
    assert total > 40, f"expected >40 canonical steps, got {total}"
    assert data["summary"]["total"] == total
    assert data["mode"] == "lightweight"
    assert data["project_name"] == "does_not_exist_yet"


def test_real_flow_key_steps_land_in_expected_lanes(tmp_path):
    data = D.collect(tmp_path)
    # P0 + D1 in phase1
    for sid in ("P0", "D1"):
        st, ph = _find_step(data, sid)
        assert st is not None, f"{sid} missing"
        assert ph["key"] == "phase1"
    # id 39 (FPGA on-board bring-up) claimed by phase2 despite stage4
    st, ph = _find_step(data, "39")
    assert st is not None and ph["key"] == "phase2"
    # analog / mixed / manufacturing exemplars
    assert _find_step(data, "A1")[1]["key"] == "analog"
    assert _find_step(data, "M1")[1]["key"] == "mixed"
    assert _find_step(data, "40")[1]["key"] == "manufacturing"


def test_summary_counts_are_internally_consistent(tmp_path):
    data = D.collect(tmp_path)
    s = data["summary"]
    assert set(s.keys()) == {"total", *(_STATUSES)}
    assert sum(s[k] for k in _STATUSES) == s["total"]
    # every status is one of the canonical values
    for p in data["phases"]:
        for st in p["steps"]:
            assert st["status"] in _STATUSES
            assert st["status_label"] == st["status"].upper()


def _phase_statuses(data, key):
    ph = next(p for p in data["phases"] if p["key"] == key)
    return {s["status"] for s in ph["steps"]}


def test_digital_project_analog_mixed_are_na_not_pending(tmp_path):
    # A project with no analog block list → the analog A1-A9 + mixed M1-M4 lanes
    # NEVER run for this design; they must read `na`, never a misleading pending.
    data = D.collect(tmp_path)
    assert _phase_statuses(data, "analog") == {"na"}
    assert _phase_statuses(data, "mixed") == {"na"}
    # and none of them leaked a bare pending
    assert "pending" not in _phase_statuses(data, "analog")


def test_manufacturing_is_external_not_pending(tmp_path):
    # Manufacturing 40-44 are off-machine until silicon is physically received.
    data = D.collect(tmp_path)
    assert _phase_statuses(data, "manufacturing") == {"external"}


def test_analog_applicable_project_is_not_reclassified(tmp_path):
    # Once the design declares analog blocks, the analog lane is APPLICABLE — it
    # must NOT be forced to `na` (it is genuinely pending until it runs).
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(
        "{}", encoding="utf-8")
    data = D.collect(tmp_path)
    assert "na" not in _phase_statuses(data, "analog")


def test_p0_done_once_synth_netlist_exists(tmp_path):
    # P0 (structural pre-flight umbrella, no output of its own) is proven passed
    # by a produced synth netlist — synthesis runs strictly after pre-flight.
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text("module m(); endmodule\n", encoding="utf-8")
    data = D.collect(tmp_path)
    st, _ = _find_step(data, "P0")
    assert st["status"] == "done"


def test_every_output_entry_has_required_keys(tmp_path):
    data = D.collect(tmp_path)
    for p in data["phases"]:
        for st in p["steps"]:
            assert set(st.keys()) >= {
                "id", "name", "stage", "status", "status_label",
                "blocks_on", "gate", "detail", "outputs",
            }
            assert isinstance(st["blocks_on"], list)
            for o in st["outputs"]:
                assert set(o.keys()) == {"rel", "abs", "exists", "size", "mtime"}
                assert isinstance(o["exists"], bool)


# --------------------------------------------------------------------------- #
# Status logic against a synthetic project with real outputs
# --------------------------------------------------------------------------- #
def _write(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_step_with_all_outputs_present_is_done(tmp_path):
    # Step 1 (Spec-to-RTL) needs an RTL file + two extraction reports.
    _write(tmp_path / "phase2" / "stage1" / "rtl" / "top.sv", "module top; endmodule")
    _write(tmp_path / "reports" / "phase1" / "extraction_coverage_report.md")
    # Second required report — resolve dynamically from the yaml so the test
    # does not hard-code a path that could drift.
    _doc, steps = D._load_flow()
    step1 = next(s for s in steps if str(s.get("id")) == "1")
    for spec in step1.get("required_outputs", []):
        for alt in D._split_alts(spec):
            if "*" not in alt:  # literal path → materialize it
                _write(tmp_path / alt)
    data = D.collect(tmp_path)
    st, ph = _find_step(data, "1")
    assert ph["key"] == "phase2"
    assert st["status"] == "done"
    assert st["status_label"] == "DONE"
    # the RTL glob resolved to a real existing file
    rtl = [o for o in st["outputs"] if o["exists"] and o["rel"].endswith(".sv")]
    assert rtl and rtl[0]["size"] > 0 and rtl[0]["mtime"] > 0


def test_disclosed_skip_sentinel_yields_skipped(tmp_path):
    # Pick a real step and drop a *_not_run.json sentinel in its first output
    # dir while its canonical outputs are ABSENT -> status must be "skipped".
    _doc, steps = D._load_flow()
    # choose a step whose required_outputs have a concrete (non-glob) dir
    target = None
    for s in steps:
        dirs = D._output_dirs(s.get("required_outputs"))
        if dirs and str(s.get("id")) != "1":
            target = s
            break
    assert target is not None
    sid = str(target["id"])
    outdir = D._output_dirs(target["required_outputs"])[0]
    sentinel = tmp_path / outdir / "dft_atpg_not_run.json"
    _write(sentinel, json.dumps({"verdict": "SKIPPED-CONDITION"}))
    data = D.collect(tmp_path)
    st, _ = _find_step(data, sid)
    assert st["status"] == "skipped"
    assert st["detail"], "skipped step should carry a disclosed-skip reason"


def test_verdict_field_skip_yields_skipped(tmp_path):
    # A *.json (not a *_not_run sentinel) whose top-level verdict is SKIP,
    # with _-vs- normalization, also discloses a skip.
    _doc, steps = D._load_flow()
    target = next(
        s for s in steps
        if D._output_dirs(s.get("required_outputs")) and str(s.get("id")) != "1"
    )
    sid = str(target["id"])
    outdir = D._output_dirs(target["required_outputs"])[0]
    _write(tmp_path / outdir / "gate_result.json", json.dumps({"verdict": "skip"}))
    data = D.collect(tmp_path)
    st, _ = _find_step(data, sid)
    assert st["status"] == "skipped"


def test_step_with_no_outputs_is_pending(tmp_path):
    # P0 is the umbrella step with NO required_outputs -> pending (lightweight
    # cannot cheaply judge an umbrella; no reports present).
    data = D.collect(tmp_path)
    st, ph = _find_step(data, "P0")
    assert ph["key"] == "phase1"
    assert st["status"] == "pending"
    assert st["outputs"] == []


def test_partial_outputs_is_running(tmp_path):
    # Materialize SOME but not all of a multi-output step -> running.
    _doc, steps = D._load_flow()
    # step 3 (CDC/RDC) has 3 concrete report outputs
    step3 = next(s for s in steps if str(s.get("id")) == "3")
    specs = step3.get("required_outputs", [])
    assert len(specs) >= 2
    # write only the first
    first_alt = D._split_alts(specs[0])[0]
    _write(tmp_path / first_alt, json.dumps({"ok": True}))
    data = D.collect(tmp_path)
    st, _ = _find_step(data, "3")
    assert st["status"] == "running"


def test_missing_flow_yaml_style_robustness(tmp_path, monkeypatch):
    # collect must not raise even when full-mode compliance is stubbed to fail;
    # it should transparently fall back to lightweight and record a note.
    monkeypatch.setattr(D, "_run_compliance", lambda project: None)
    data = D.collect(tmp_path, full=True)
    assert data["mode"] == "lightweight"
    assert data["note"], "fallback should record a note"
    # shape still intact
    assert [p["key"] for p in data["phases"]] == _PHASE_ORDER


def test_full_mode_structural_mapping(tmp_path, monkeypatch):
    # Structurally exercise the full-mode path with a stubbed compliance result:
    # map PASS->done, FAIL->fail, SKIPPED-CONDITION->skipped, WAIVED->waived.
    fake = [
        {"id": 1, "status": "PASS", "reasons": []},
        {"id": 2, "status": "FAIL", "reasons": ["lint error over threshold"]},
        {"id": 3, "status": "SKIPPED-CONDITION", "reasons": ["no async input"]},
        {"id": "A1", "status": "WAIVED", "reasons": ["analog waived"]},
        {"id": 15, "status": "MISSING", "reasons": []},
        {"id": "D1", "status": "VACUOUS_PASS", "reasons": []},
    ]
    monkeypatch.setattr(D, "_run_compliance", lambda project: fake)
    data = D.collect(tmp_path, full=True)
    assert data["mode"] == "full"
    assert data["note"] == ""
    assert _find_step(data, "1")[0]["status"] == "done"
    assert _find_step(data, "2")[0]["status"] == "fail"
    assert _find_step(data, "2")[0]["detail"] == "lint error over threshold"
    assert _find_step(data, "3")[0]["status"] == "skipped"
    assert _find_step(data, "A1")[0]["status"] == "waived"
    assert _find_step(data, "15")[0]["status"] == "missing"
    assert _find_step(data, "D1")[0]["status"] == "done"  # VACUOUS_PASS


def test_status_mapping_helper_covers_documented_verdicts():
    m = D._map_compliance_status
    assert m("PASS") == "done"
    assert m("VACUOUS_PASS") == "done"
    assert m("VACUOUS-PASS") == "done"
    assert m("SKIPPED-CONDITION") == "skipped"
    assert m("DEFERRED-BY-UPSTREAM") == "skipped"
    assert m("WAIVED") == "waived"
    assert m("WAIVED-DEFERRED") == "waived"
    assert m("FAIL") == "fail"
    assert m("MISSING") == "missing"
    assert m("SOMETHING-ELSE") == "pending"


def test_json_cli_roundtrip(tmp_path):
    out = tmp_path / "dash.json"
    rc = D.main([str(tmp_path), "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert [p["key"] for p in data["phases"]] == _PHASE_ORDER
    assert data["mode"] == "lightweight"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
