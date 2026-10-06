#!/usr/bin/env python3
"""FX_STALE_LDOCS — generated L docs are reused only when they are what the
CURRENT phase-1 producer would write (reworked after review wave8).

MEASURED on subservient (8HD-4, 2026-09-28, lane fxtb FX_P2 arm f4): an exact
fresh copy of a tree whose L1 had been written by the pre-fix producer kept
FAILing `l1_pin_table_aliases_typed_check` after the producer was fixed,
because the front door skipped phase 1 whenever 13 L docs existed.

Review wave8 (LDOCS: correctness DO_NOT_LAND, integrity LAND_AFTER_FIX) found
the mechanism right and its inputs wrong; each finding has a test here:
  B1  the design-input digest hashed files the FLOW rewrites (phase 3's
      tapeout declaration), so REUSE was unreachable after a full run;
  B2  a later FLOW rewrite of a doc (A8's rail synth, restamp_l_doc_skeletons)
      read as a hand edit and halted the next run;
  M3  plugin DATA files, `tools/`, `-m` launches and the --pdk/--ic-name knobs
      were outside the identity;
  M4  the stamp blessed docs the run did not write; an interrupted
      regeneration left the old stamp vouching; handed docs were judged stale
      by window runs;
  §4.05  the input digest restated its own off-limits list.

A tiny fake PLUGIN is built per test (programs/ + data/): its producer reads a
data file and the design input, lists the input dir, and writes the L docs --
all under phase 1's own `ProducerRecorder`. chip-AGNOSTIC.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from programs.tests.test_execution_receipt_chain import real_entry, isolated_transport  # noqa: F401

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _step_identity as SI  # noqa: E402
import vibe_ic_one_shot_runner as ORCH  # noqa: E402

try:                                   # absent on the unfixed tree
    import _phase1_producer_identity as PID  # noqa: E402
except ImportError:                    # pragma: no cover - main arm
    PID = None

_REFUSED = getattr(ORCH, "_P1_MODE_REFUSED", "refused_generated_doc_edited")
KNOBS = {"ic_name": "chip", "pdk": "", "mode": "docs"}

PRODUCER = '''
import json, os
from pathlib import Path
HERE = Path(__file__).resolve().parent

def produce(project, n=13, skip=(), declaration=False, raise_after=None):
    table = json.loads((HERE.parent / "data" / "table.json").read_text())
    docs = Path(project) / "input" / "docs"
    spec = (docs / "spec.md").read_text()
    list(os.scandir(docs))
    if declaration:
        d = Path(project) / "input" / "submission_template"
        d.mkdir(parents=True, exist_ok=True)
        (d / "tapeout_declaration.json").write_text('{"answers": {}}')
        (d / "tapeout_declaration.json").read_text()   # phase 1 reads its own
        list(os.scandir(d))
    gd = Path(project) / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        if i in skip:
            continue
        if raise_after is not None and i > raise_after:
            raise RuntimeError("layer step died")
        (gd / f"L{i}_DOC.json").write_text(
            json.dumps({"doc": i, "t": table["v"], "len": len(spec)}))
'''


def _plugin(tmp_path: Path) -> Path:
    plug = tmp_path / "plugin"
    (plug / "programs").mkdir(parents=True)
    (plug / "data").mkdir()
    (plug / "programs" / "fake_l_producer.py").write_text(PRODUCER)
    (plug / "data" / "table.json").write_text('{"v": 1}')
    return plug


def _project(tmp_path: Path, design_input=True) -> Path:
    proj = tmp_path / "proj"
    if design_input:
        (proj / "input" / "docs").mkdir(parents=True)
        (proj / "input" / "docs" / "spec.md").write_text("# spec\n")
        (proj / "input" / "unread_notes.txt").write_text("never read\n")
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    return proj


def _load(plug: Path):
    # keyed by the PATH: `id()` is reused across tests, and a cached module
    # from another test's plugin would run that plugin's producer.
    import hashlib
    name = "fake_l_producer_" + hashlib.sha1(
        str(plug.resolve()).encode()).hexdigest()[:12]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, plug / "programs" / "fake_l_producer.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _phase1(proj: Path, plug: Path, knobs=KNOBS, **kw) -> None:
    """Phase 1 as `main_recorded` runs it: snapshot the input tree, void the
    old stamp, extract under the recorder, stamp."""
    mod = _load(plug)
    if PID is None:                                 # unfixed tree: just write
        mod.produce(proj, **kw)
        return
    before = PID.input_tree_snapshot(proj)
    rec = PID.ProducerRecorder(plug)
    with rec:
        PID.void(proj)
        mod.produce(proj, **kw)
    PID.stamp(proj, rec, input_before=before, knobs=knobs)


def _fresh(proj: Path, plug: Path, knobs=KNOBS):
    return PID.assess(proj, plug / "programs", knobs) if PID else {}


def _decide(proj: Path, plug: Path, monkeypatch, knobs=KNOBS):
    monkeypatch.setattr(ORCH, "PROGRAMS_DIR", plug / "programs")
    try:
        return ORCH._phase1_decision(proj, False, knobs)
    except TypeError:                               # unfixed signature
        return ORCH._phase1_decision(proj, False)


# ---------------------------------------------------------------------------
# the measured case, the old project, and the control
# ---------------------------------------------------------------------------
def test_docs_written_by_an_older_producer_are_regenerated(tmp_path,
                                                           monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    src = plug / "programs" / "fake_l_producer.py"
    src.write_text(src.read_text() + "\n# the producer fix lands\n")
    assert _decide(proj, plug, monkeypatch) == (True, "docs")
    assert _fresh(proj, plug)["reason"] == "PRODUCER_CHANGED"


def test_docs_with_no_producer_identity_are_regenerated(tmp_path,
                                                        monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _load(plug).produce(proj)
    assert _decide(proj, plug, monkeypatch) == (True, "docs")
    assert _fresh(proj, plug)["reason"] == "NO_PRODUCER_IDENTITY"


def test_docs_the_current_producer_wrote_are_reused(tmp_path, monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    assert _decide(proj, plug, monkeypatch) == (False, "")


# ---------------------------------------------------------------------------
# B1 — design input is what phase 1 READ, not what the flow rewrites
# ---------------------------------------------------------------------------
def test_a_file_phase1_wrote_and_phase3_rewrites_does_not_regenerate(
        tmp_path, monkeypatch):
    """review wave8 B1: phase 3's `publish_tapeout_declarations` rewrites the
    declaration step 0.5ic wrote; that is not a design-input change."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug, declaration=True)
    decl = proj / "input" / "submission_template" / "tapeout_declaration.json"
    decl.write_text('{"answers": {"deliverable": "HARDMACRO"}}')   # phase 3
    assert _fresh(proj, plug)["state"] == "REUSE"
    assert _decide(proj, plug, monkeypatch) == (False, "")


def test_an_input_file_phase1_never_read_does_not_regenerate(tmp_path):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (proj / "input" / "unread_notes.txt").write_text("edited\n")
    assert _fresh(proj, plug)["state"] == "REUSE"


def test_a_design_input_phase1_read_changes_regenerates(tmp_path,
                                                        monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (proj / "input" / "docs" / "spec.md").write_text("# spec, revised\n")
    assert _decide(proj, plug, monkeypatch) == (True, "docs")
    assert _fresh(proj, plug)["reason"] == "DESIGN_INPUT_CHANGED"


def test_a_new_document_in_a_listed_input_dir_regenerates(tmp_path):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (proj / "input" / "docs" / "addendum.md").write_text("# more\n")
    assert _fresh(proj, plug)["reason"] == "DESIGN_INPUT_CHANGED"


def test_an_oracle_path_is_never_design_input(tmp_path):
    """§4.05 through the ONE authority (`step_input_scope.oracle_reason`):
    a file under input/expected_output/ is excluded even if something read
    it, so its edits move nothing."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    ora = proj / "input" / "expected_output" / "answer.txt"
    ora.parent.mkdir(parents=True)
    ora.write_text("golden\n")
    mod = _load(plug)
    before = PID.input_tree_snapshot(proj)
    assert "input/expected_output/answer.txt" not in before
    rec = PID.ProducerRecorder(plug)
    with rec:
        mod.produce(proj)
        ora.read_text()                     # even if something opens it
    PID.stamp(proj, rec, input_before=before, knobs=KNOBS)
    record = SI.read_sidecar(proj / "phase1", "phase1")["input_record"]
    assert not any("expected_output" in f for f in record["files"])
    ora.write_text("changed golden\n")
    assert _fresh(proj, plug)["state"] == "REUSE"


# ---------------------------------------------------------------------------
# M3 — plugin data, knobs, -m launches, top-level closure only
# ---------------------------------------------------------------------------
def test_a_plugin_data_file_edit_regenerates(tmp_path):
    """review wave8 M3: a known-answer-vector / registry edit must reach an
    existing project exactly as a code edit does."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (plug / "data" / "table.json").write_text('{"v": 2}')
    assert _fresh(proj, plug)["reason"] == "PRODUCER_CHANGED"


@pytest.mark.parametrize("change", ["add", "remove", "rename"])
def test_a_listed_plugin_data_member_change_regenerates(tmp_path, change):
    """The producer globs a data directory; membership is an input too."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    src = plug / "programs" / "fake_l_producer.py"
    src.write_text(src.read_text().replace(
        'table = json.loads((HERE.parent / "data" / "table.json").read_text())',
        'table = {"v": sum(json.loads(f.read_text())["v"] for f in '
        'sorted((HERE.parent / "data").glob("*.json")))}'))
    extra = plug / "data" / "extra.json"
    if change != "add":
        extra.write_text('{"v": 2}')
    _phase1(proj, plug)
    if change == "add":
        extra.write_text('{"v": 2}')
    elif change == "remove":
        extra.unlink()
    else:
        extra.rename(plug / "data" / "renamed.json")
    fresh = _fresh(proj, plug)
    assert fresh["state"] == "REGENERATE", fresh
    assert fresh["reason"] == "PRODUCER_CHANGED"


def test_a_different_pdk_knob_regenerates(tmp_path):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    f = _fresh(proj, plug, dict(KNOBS, pdk="other_pdk"))
    assert f["reason"] == "KNOBS_CHANGED" and "other_pdk" in f["why"]


def test_a_module_launch_is_recorded(tmp_path):
    plug = _plugin(tmp_path)
    eng = plug / "tools" / "engine"
    eng.mkdir(parents=True)
    (eng / "__init__.py").write_text("")
    (eng / "cli.py").write_text("print('engine')\n")
    rec = PID.ProducerRecorder(plug)
    with rec:
        _load(plug)
        subprocess.run([sys.executable, "-c", "pass", "-m", "engine.cli"],
                       capture_output=True, timeout=60)
    record, why = rec.recorded()
    assert record is not None, why
    assert "launched:tools/engine/cli.py" in record


def test_a_launched_scripts_lazy_import_is_not_followed(tmp_path):
    """review wave8 MINOR: a checker's function-local imports made the
    identity 366 files, so any phase-3 landing demoted every window run."""
    plug = _plugin(tmp_path)
    progs = plug / "programs"
    (progs / "top_dep.py").write_text("X = 1\n")
    (progs / "lazy_dep.py").write_text("Y = 1\n")
    (progs / "a_checker.py").write_text(
        "import top_dep\n\ndef run():\n    import lazy_dep\n")
    rec = PID.ProducerRecorder(plug)
    with rec:
        _load(plug)
        subprocess.run([sys.executable, str(progs / "a_checker.py")],
                       capture_output=True, timeout=60)
    record, _ = rec.recorded()
    assert "launched:programs/top_dep.py" in record
    assert "launched:programs/lazy_dep.py" not in record


def test_the_recorder_installs_no_profiler(tmp_path):
    plug = _plugin(tmp_path)
    with PID.ProducerRecorder(plug):
        assert sys.getprofile() is None


# ---------------------------------------------------------------------------
# M4 — only what this run wrote; an interrupted run; handed docs
# ---------------------------------------------------------------------------
def test_a_doc_this_run_did_not_write_is_not_blessed(tmp_path, monkeypatch):
    """A failing layer step leaves an OLDER producer's doc in place: the stamp
    must not vouch for it (review wave8 M4)."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    _phase1(proj, plug, skip=(5,))              # L5 kept from the older run
    f = _fresh(proj, plug)
    assert f["reason"] == "GENERATED_DOC_NOT_WRITTEN" and "L5_DOC.json" in f["docs"]
    assert _decide(proj, plug, monkeypatch) == (True, "docs")


def test_an_interrupted_regeneration_regenerates_not_refuses(tmp_path,
                                                             monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    src = plug / "programs" / "fake_l_producer.py"
    src.write_text(src.read_text().replace('"t": table["v"]',
                                           '"t": table["v"], "new": 1'))
    with pytest.raises(RuntimeError):
        _phase1(proj, plug, raise_after=2)      # dies after rewriting L1, L2
    f = _fresh(proj, plug)
    assert f["state"] == "REGENERATE", f
    assert f["reason"] == "NO_PRODUCER_IDENTITY"


def test_handed_docs_are_never_judged_stale_by_a_window_run():
    note = ORCH._stale_generated_docs_note(
        False, {"state": "REGENERATE", "reason": "NO_PRODUCER_IDENTITY",
                "why": "x"}, False, "--skip-phase1")
    assert note is None
    assert ORCH._demote_for_stale_generated_docs("PASS", note, []) == "PASS"


def test_a_window_run_over_stale_docs_discloses_and_is_not_green():
    stale = {"state": "REGENERATE", "reason": "PRODUCER_CHANGED",
             "why": "code a -> b"}
    note = ORCH._stale_generated_docs_note(False, stale, True, "--skip-phase1")
    assert note.startswith("STALE_GENERATED_DOCS") and "PRODUCER_CHANGED" in note
    reasons = []
    assert ORCH._demote_for_stale_generated_docs("PASS", note, reasons) \
        == "NOT_MEASURED" and reasons == [note]
    assert ORCH._demote_for_stale_generated_docs("FAIL", note, []) == "FAIL"
    assert ORCH._stale_generated_docs_note(True, stale, True, "x") is None
    assert ORCH._stale_generated_docs_note(
        False, {"state": "REUSE"}, True, "x") is None


# ---------------------------------------------------------------------------
# B2 — a FLOW rewrite after phase 1 is recorded, a hand edit refuses
# ---------------------------------------------------------------------------
def test_a_rewrite_through_the_dump_chokepoint_is_a_flow_derivation(
        tmp_path, monkeypatch):
    """review wave8 B2: analog A8's rail synth and phase 2's
    `restamp_l_doc_skeletons` rewrite L docs through `dump`."""
    import l_doc_generator_stamp as STAMP
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    l2 = proj / "phase1" / "generated_docs" / "L2_DOC.json"
    STAMP.dump(l2, {"doc": 2, "rails": ["VDDA"]}, emitter="a8_rail_synth")
    f = _fresh(proj, plug)
    assert f["state"] == "REUSE", f
    chain = SI.read_sidecar(proj / "phase1", "phase1")["derivations"]
    assert chain[-1]["doc"] == "L2_DOC.json"
    assert "a8_rail_synth" in chain[-1]["writer"]
    assert _decide(proj, plug, monkeypatch) == (False, "")


def test_a_rewrite_by_a_later_phase_of_this_run_is_recorded(tmp_path):
    """The front door records any doc a later phase changed while it ran,
    whether or not the writer went through `dump`."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    before = PID.docs_snapshot(proj)
    (proj / "phase1" / "generated_docs" / "L3_DOC.json").write_text("{}")
    assert PID.record_flow_changes(proj, before, "phase2") == ["L3_DOC.json"]
    assert _fresh(proj, plug)["state"] == "REUSE"


def test_a_hand_edited_generated_doc_is_refused_not_overwritten(
        tmp_path, monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    doc = proj / "phase1" / "generated_docs" / "L1_DOC.json"
    doc.write_text(json.dumps({"doc": 1, "edited": True}))
    assert _decide(proj, plug, monkeypatch) == (False, _REFUSED)
    f = _fresh(proj, plug)
    assert f["reason"] == "GENERATED_DOC_EDITED" and "L1_DOC.json" in f["why"]
    assert "input/" in f["why"] and "delete the doc" in f["why"]
    assert json.loads(doc.read_text())["edited"] is True


def test_a_doc_the_producer_never_wrote_is_refused(tmp_path, monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (proj / "phase1" / "generated_docs" / "L99_HANDMADE.json").write_text("{}")
    assert _decide(proj, plug, monkeypatch) == (False, _REFUSED)


def test_deleting_the_edited_doc_is_a_way_out(tmp_path, monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug, n=14)
    (proj / "phase1" / "generated_docs" / "L1_DOC.json").unlink()
    assert _decide(proj, plug, monkeypatch) == (True, "docs")
    assert _fresh(proj, plug)["reason"] == "GENERATED_DOC_REMOVED"


def test_the_refusal_halts_the_run_by_name():
    src = Path(ORCH.__file__).read_text()
    assert 'plan.append(("phase1", "NOT_MEASURED", 1))' in src
    assert "p1_mode == _P1_MODE_REFUSED" in src


# ---------------------------------------------------------------------------
# design input itself; supersede; the second track; the sibling entry
# ---------------------------------------------------------------------------
def test_L_docs_with_no_design_input_are_input_and_kept(tmp_path,
                                                        monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path, design_input=False)
    gd = proj / "phase1" / "generated_docs"
    for i in range(1, 14):
        (gd / f"L{i}_DOC.json").write_text("{}")
    assert _decide(proj, plug, monkeypatch) == (False, "")


def test_assessing_never_writes_the_design_input(tmp_path, monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    spec = proj / "input" / "docs" / "spec.md"
    before = (spec.read_bytes(), spec.stat().st_mtime_ns)
    _decide(proj, plug, monkeypatch)
    assert (spec.read_bytes(), spec.stat().st_mtime_ns) == before


def test_a_regeneration_moves_the_stale_docs_aside_not_away(tmp_path):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    dest = PID.supersede_docs(proj, "PRODUCER_CHANGED: test")
    assert dest is not None and len(list(dest.glob("L*.json"))) == 13
    assert not list((proj / "phase1" / "generated_docs").glob("L*.json"))
    assert ".vibeic-state" in dest.parts
    assert SI.read_sidecar(proj / "phase1", "phase1") is None


def test_archive_failure_refuses_and_keeps_live_docs(tmp_path):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (proj / ".vibeic-state").write_text("blocks archive directory")
    with pytest.raises(OSError, match="archive|supersede"):
        PID.supersede_docs(proj, "PRODUCER_CHANGED: test")
    assert (proj / "phase1/generated_docs/L1_DOC.json").is_file()


def test_partial_archive_failure_restores_every_live_doc(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    gd = proj / "phase1/generated_docs"
    first, second = gd / "L1_DOC.json", gd / "L2_DOC.json"
    first.write_text("first")
    second.write_text("second")
    replace = PID.os.replace
    forward = 0

    def fail_second_forward(src, dst):
        nonlocal forward
        if Path(src).parent == gd:
            forward += 1
            if forward == 2:
                raise OSError("injected second move failure")
        return replace(src, dst)

    monkeypatch.setattr(PID.os, "replace", fail_second_forward)
    with pytest.raises(OSError, match="injected second move failure"):
        PID.supersede_docs(proj, "producer changed")
    assert first.read_text() == "first"
    assert second.read_text() == "second"


def test_phase2_entry_refuses_archive_failure_before_dispatch(tmp_path,
                                                               monkeypatch):
    import design_one_shot_runner as DESIGN
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (proj / ".vibeic-state").write_text("blocks archive directory")
    monkeypatch.setattr(DESIGN, "_run", lambda *_a, **_k:
                        pytest.fail("phase1 must not dispatch after archive failure"))
    row = DESIGN.step_phase1(proj)
    assert row.status == "NOT_MEASURED"
    assert "SUPERSEDE_FAILED" in row.detail
    assert (proj / "phase1/generated_docs/L1_DOC.json").is_file()


def test_front_door_halts_when_stale_docs_cannot_be_archived(tmp_path,
                                                              monkeypatch):
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    # owner route rule 2026-09-28 (ICROUTE)
    from _route_fixture import stage_owner_route
    stage_owner_route(proj, "ic")
    real_entry('IC', 'default', proj)
    _phase1(proj, plug)
    (proj / ".vibeic-state").write_text("blocks archive directory")
    monkeypatch.setattr(ORCH, "_capture_container_image",
                        lambda *_a, **_k: {"verdict": "PASS"})
    monkeypatch.setattr(ORCH, "_phase_runner", lambda *_a, **_k:
                        pytest.fail("front door must not dispatch phase1"))
    monkeypatch.setattr(sys, "argv", [
        "vibe_ic_one_shot_runner.py", str(proj), "--route", "ic",
        "--no-dashboard",
        "--entry-step", "D1", "--exit-step", "D1", "--skip-phase3"])
    assert ORCH.main() == 1
    report = json.loads((proj / "reports/orchestrator/vibe_ic_one_shot.json")
                        .read_text())
    assert report["halted_at"] == "phase1"
    assert any("SUPERSEDE_FAILED" in note for note in report["advisories"])
    assert (proj / "phase1/generated_docs/L1_DOC.json").is_file()


def test_two_archives_in_one_second_never_overwrite(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    doc = proj / "phase1/generated_docs/L1_DOC.json"
    monkeypatch.setattr(PID.time, "strftime", lambda *_: "20260928T120000")
    doc.write_text("first")
    first = PID.supersede_docs(proj, "first")
    doc.write_text("second")
    second = PID.supersede_docs(proj, "second")
    assert first != second
    assert (first / doc.name).read_text() == "first"
    assert (second / doc.name).read_text() == "second"


def test_a_second_track_rewrite_keeps_the_producers_inputs(tmp_path):
    """review wave8 MINOR: the restamp re-hashed the inputs and every doc,
    laundering an input edit made meanwhile."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    _phase1(proj, plug)
    (proj / "input" / "docs" / "spec.md").write_text("# spec v2\n")
    (proj / "phase1" / "generated_docs" / "L4_DOC.json").write_text('{"x":1}')
    PID.restamp_outputs(proj, ["L4_DOC.json"])
    assert _fresh(proj, plug)["reason"] == "DESIGN_INPUT_CHANGED"


def test_the_front_door_and_phase2_share_one_design_input_predicate(tmp_path):
    proj = _project(tmp_path)
    assert ORCH._phase1_decision_from_inputs(proj) \
        == PID.design_input_mode(proj) == (True, "docs")


# ---------------------------------------------------------------------------
# the producer side: phase 1 stamps what it ran, and only when it ran D1
# ---------------------------------------------------------------------------
def _p1(monkeypatch, body):
    import phase1_one_shot_runner as P1
    monkeypatch.setattr(P1, "main", body)
    return P1


def test_phase1_stamps_its_identity_when_it_dispatches_d1(tmp_path,
                                                          monkeypatch):
    proj = _project(tmp_path)
    gd = proj / "phase1" / "generated_docs"

    def extract(project):
        for i in range(1, 14):
            (gd / f"L{i}_DOC.json").write_text(json.dumps({"doc": i}))
        return 0

    def body():
        P1._RUN.update(project=proj, second_track_only=False, knobs=KNOBS)
        return P1._as_the_producer(extract)(proj)

    P1 = _p1(monkeypatch, body)
    assert P1.main_recorded() == 0
    rec = SI.read_sidecar(proj / "phase1", "phase1")
    assert rec and rec.get("code") and rec.get("recording")
    assert set(rec["outputs"]) == {f"L{i}_DOC.json" for i in range(1, 14)}


def test_phase1_that_never_dispatched_d1_claims_nothing(tmp_path,
                                                        monkeypatch):
    proj = _project(tmp_path)
    for i in range(1, 14):
        (proj / "phase1" / "generated_docs" / f"L{i}_DOC.json").write_text("{}")

    def body():
        P1._RUN.update(project=proj, second_track_only=False)
        return 1                      # D1 refused: the gate never called it

    P1 = _p1(monkeypatch, body)
    P1.main_recorded()
    assert SI.read_sidecar(proj / "phase1", "phase1") is None


def test_an_interrupted_phase1_leaves_no_stamp_vouching(tmp_path,
                                                        monkeypatch):
    proj = _project(tmp_path)
    import _p1_identity_fixture as FIX
    gd = proj / "phase1" / "generated_docs"
    for i in range(1, 14):
        (gd / f"L{i}_DOC.json").write_text("{}")
    FIX.stamp_current(proj)

    def extract(project):
        (gd / "L1_DOC.json").write_text('{"half": "new"}')
        raise RuntimeError("stalled")

    def body():
        P1._RUN.update(project=proj, second_track_only=False, knobs=KNOBS)
        return P1._as_the_producer(extract)(proj)

    P1 = _p1(monkeypatch, body)
    with pytest.raises(RuntimeError):
        P1.main_recorded()
    assert PID.assess(proj, PROGRAMS)["reason"] == "NO_PRODUCER_IDENTITY"


def test_a_release_version_bump_is_not_a_producer_change(tmp_path):
    """The manifest's version reaches a doc only through the `_generator`
    stamp, whose drift `l_doc_generator_stamp` judges; recording it made
    every landing demote every window run (measured on subservient)."""
    plug, proj = _plugin(tmp_path), _project(tmp_path)
    man = plug / ".claude-plugin" / "plugin.json"
    man.parent.mkdir()
    man.write_text('{"version": "1.0.0"}')
    rec = PID.ProducerRecorder(plug)
    before = PID.input_tree_snapshot(proj)
    with rec:
        PID.void(proj)
        _load(plug).produce(proj)
        man.read_text()
    PID.stamp(proj, rec, input_before=before, knobs=KNOBS)
    man.write_text('{"version": "1.0.1"}')
    assert _fresh(proj, plug)["state"] == "REUSE"
