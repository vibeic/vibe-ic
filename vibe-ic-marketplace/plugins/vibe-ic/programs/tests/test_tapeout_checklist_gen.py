#!/usr/bin/env python3
"""Tests for tapeout_checklist_gen.py (v1.6.36 — Step 33 derived inventory)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "tapeout_checklist_gen.py")


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def test_emits_skeleton_with_all_blockers_missing(tmp_path):
    """Bare project → BLOCKER_MISSING verdict + 0/N blockers present."""
    r = _run(tmp_path)
    assert r.returncode == 0
    out = tmp_path / "reports/audit/tapeout_checklist.json"
    assert out.is_file()
    payload = json.loads(out.read_text())
    assert payload["verdict"] == "BLOCKER_MISSING"
    assert payload["summary"]["blockers_present"] == 0
    assert payload["summary"]["blockers_total"] >= 5


def test_detects_present_blockers(tmp_path):
    """Stage some blocker artefacts → blockers_present > 0."""
    (tmp_path / "phase3/stage4/gds").mkdir(parents=True)
    (tmp_path / "phase3/stage4/gds/chip_top.gds").write_bytes(b"FAKEGDS")
    (tmp_path / "phase2/stage2/synth").mkdir(parents=True)
    (tmp_path / "phase2/stage2/synth/netlist.v").write_text("module x; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    payload = json.loads(
        (tmp_path / "reports/audit/tapeout_checklist.json").read_text())
    assert payload["summary"]["blockers_present"] >= 2
    items = {it["name"]: it for it in payload["items"]}
    assert items["gds"]["present"] is True
    assert items["netlist"]["present"] is True


def test_includes_open_waivers(tmp_path):
    """waivers.json entries surface in output as reviewer_todo."""
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [{
            "id": 23, "ticket": "TEST-IR-DROP",
            "reason": "IR drop tool unavailable",
        }],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    payload = json.loads(
        (tmp_path / "reports/audit/tapeout_checklist.json").read_text())
    assert "23" in payload["open_waivers"]
    assert any("TEST-IR-DROP" in t for t in payload["reviewer_todo"])


def test_advisory_items_counted_separately(tmp_path):
    """Advisory items (e.g. ir_drop, em) don't block but are counted."""
    (tmp_path / "reports/phase3").mkdir(parents=True)
    (tmp_path / "reports/phase3/ir_drop.rpt").write_text("openroad ir drop\n")
    r = _run(tmp_path)
    payload = json.loads(
        (tmp_path / "reports/audit/tapeout_checklist.json").read_text())
    assert payload["summary"]["advisory_items_present"] >= 1


def test_vacuous_pass_when_project_missing():
    """Non-existent project → exit 2 (VACUOUS_PASS)."""
    r = subprocess.run(
        [sys.executable, str(PROG), "/no/such/path"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# vibe-ic#562 — the PREMISE the verdict rests on, which nothing was guarding
# ---------------------------------------------------------------------------

def _checklist_items():
    """The module's own constant, loaded the way the program sees it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("tcg_premise", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tcg_premise"] = mod
    spec.loader.exec_module(mod)
    return mod._CHECKLIST_ITEMS


def test_the_blocker_list_is_not_empty():
    """`verdict = "READY_FOR_TAPEOUT" if blockers_present == blockers_total`.

    With an empty blocker list that is `0 == 0` — an empty project would declare
    itself ready to tape out. Today it cannot happen, but not because any code
    says so: `_CHECKLIST_ITEMS` is a module constant that HAPPENS to be non-empty.
    Refactor it to load from a config, or downgrade every blocker to advisory, and
    the most consequential vacuous PASS in this flow appears with no test failing.

    Asserts the PREMISE, not the behaviour — the same reason
    `test_fmeda_readjudication` asserts that `dc_verdict(0.0, None)` really does
    pass zero. A verdict resting on a data structure needs that structure held.
    """
    blockers = [i for i in _checklist_items() if i[2] == "blocker"]
    assert blockers, (
        "the checklist declares no blocker rows, so blockers_total is 0 and "
        "`blockers_present == blockers_total` is vacuously true — every project, "
        "including an empty one, would report READY_FOR_TAPEOUT")


def test_an_empty_project_is_not_ready_for_tapeout(tmp_path):
    """The consequence, end to end, so the premise test cannot be satisfied by a
    constant nobody reads."""
    r = _run(tmp_path)
    # stdout carries the SUMMARY (verdict / counts / out-path); the full report
    # with `summary` and `items` is the file `out` names. Asserting on both, so
    # the two cannot drift apart — the summary is what an operator reads and the
    # file is what the next gate consumes.
    head = json.loads(r.stdout[r.stdout.index("{"):])
    assert head["verdict"] == "BLOCKER_MISSING", head["verdict"]
    assert head["blockers_total"] > 0, "no blocker rows: 0 == 0 would be READY"
    assert head["blockers_present"] == 0
    rep = json.loads(Path(head["out"]).read_text())
    assert rep["verdict"] == head["verdict"]
    assert rep["summary"]["blockers_total"] == head["blockers_total"]
