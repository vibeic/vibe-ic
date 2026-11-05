"""An upstream verdict is THIS RUN's, or it is not a verdict.

R-0915-152. `release_docs_check` excuses 37.5ic's missing release documents when an UPSTREAM
step's own verdict says that step is blocked. The authority is right (R-0915-149); the
RECORD it read was not, in three independent ways, and each one is measured here rather than
argued:

  1. THE NAME. `reports/metrics/{sid}.json` is not what `step_metrics.emit` writes -- it
     normalises the id first, so step `37.4`'s row is `37_4.json` under key
     `37_4__flow__step_status`, and `M1`'s is `m1.json`. Every dotted or suffixed step was
     therefore looked for where nothing writes. The old code returned ABSENT for those, ABSENT
     is not a blocking tier, and a genuinely FAILED upstream step was recorded as passing
     while 37.5ic took the blame.
  2. THE RUN. That file persists across runs, and nothing in it said which invocation
     measured it, so one failed pass excused 37.5ic forever.
  3. THE SELF-FREEZE. `_emit_step_metrics` could not refresh its own `step_status`: the
     no-clobber filter that stops the wrapper overwriting a PROGRAM's measurement also
     stopped it overwriting its OWN previous value. Pass 1 FAIL, pass 2 PASS, file still
     FAIL -- driven twice below, not reasoned about.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as FCC          # noqa: E402
import release_docs_check as RDC             # noqa: E402
import step_metrics as SM                    # noqa: E402
import _path_layout as _PL                   # noqa: E402
from _invocation_fixture import bind_invocation_top

INV_ENV = "VIBEIC_FCC_INVOCATION"


class _Result:
    def __init__(self, status: str) -> None:
        self.status = status


@pytest.fixture()
def mine(monkeypatch):
    """This gate runs as a child of the audit, so it inherits the invocation id."""
    monkeypatch.setenv(INV_ENV, "THIS-RUN-1")
    return "THIS-RUN-1"


# ── 1. the name step_metrics actually writes ─────────────────────────────────

@pytest.mark.parametrize("sid", ["37.4", "37.5ic", "0.5ic", "M1", "23", "33"])
def test_the_verdict_is_read_from_the_file_step_metrics_writes(sid, tmp_path, mine):
    """Driven through `step_metrics.emit`, so the reader and the writer cannot disagree."""
    SM.emit(tmp_path, sid, {"step_status": "FAIL", "invocation": mine})

    written = tmp_path / SM.METRICS_REL / f"{SM.normalize_step(sid)}.json"
    assert written.is_file(), f"emit did not write {written}"

    status, why = RDC.step_verdict_now(tmp_path, sid)
    assert (status, why) == ("FAIL", ""), (
        f"step {sid}'s own FAIL was not read from {written.name}: {status} {why}")
    assert status in RDC._BLOCKING_STEP_STATUSES


def test_the_reader_does_not_spell_the_name_itself():
    """The normalisation is imported from the module that owns it, not reproduced."""
    import inspect
    src = inspect.getsource(RDC._metrics_row)
    assert "normalize_step" in src and "METRICS_REL" in src, src
    # and the un-normalised format string is no longer used to find the row
    assert "_STEP_STATUS_REL_FMT.format" in src, (
        "the fallback for a missing step_metrics import should still name a path")
    body = inspect.getsource(RDC.step_verdict_now)
    assert "_STEP_STATUS_REL_FMT" not in body, (
        "the verdict reader still builds the path itself instead of asking _metrics_row")


# ── 2. this run, not an earlier one ──────────────────────────────────────────

def test_a_row_from_another_invocation_is_not_this_runs_verdict(tmp_path, mine):
    SM.emit(tmp_path, "23", {"step_status": "PASS", "invocation": "AN-EARLIER-RUN"})
    status, why = RDC.step_verdict_now(tmp_path, "23")
    assert status == RDC._VERDICT_UNREADABLE, (status, why)
    assert "AN-EARLIER-RUN" in why and mine in why, why


def test_a_row_naming_no_invocation_cannot_be_shown_to_be_this_runs(tmp_path, mine):
    SM.emit(tmp_path, "23", {"step_status": "PASS"})
    status, why = RDC.step_verdict_now(tmp_path, "23")
    assert status == RDC._VERDICT_UNREADABLE, (status, why)
    assert "names no invocation" in why, why


def test_an_absent_row_is_unreadable_and_says_so(tmp_path, mine):
    """The threaded path: the upstream step may not have been evaluated yet.

    The old code answered "ABSENT", which is not a blocking tier and so was filed as the
    step PASSING -- silence read as a measurement. `UNREADABLE` is neither: it is not a
    blockage and it is not the step passing, and it carries its reason.
    """
    status, why = RDC.step_verdict_now(tmp_path, "33")
    assert status == RDC._VERDICT_UNREADABLE, (status, why)
    assert "no step record" in why and "33.json" in why, why
    assert status not in RDC._BLOCKING_STEP_STATUSES


def test_an_unreadable_upstream_verdict_is_named_in_the_published_record(tmp_path, mine):
    """An excuse may rest on a gap -- but never on an unnamed one.

    Driven through `upstream_blockage_now`, so the published record is the real one: the
    artefact reader names `post_route_summary.json`, the flow says which step declares it,
    and that step has no row at all in this project -- the threaded-path case.
    """
    rel = "reports/phase3/sta/post_route_summary.json"
    sid = RDC._declaring_step(rel)
    assert sid, "the flow no longer declares that path; re-measure this arm's premise"

    status, why = RDC.step_verdict_now(tmp_path, sid)
    assert (status, bool(why)) == (RDC._VERDICT_UNREADABLE, True), (status, why)

    out = RDC.upstream_blockage_now(tmp_path, "a")
    assert "upstream_verdicts_unreadable" in out, sorted(out)
    assert out["upstream_verdicts_unreadable"], (
        "an upstream verdict could not be read and the record does not name it")
    for s_, entry in out["upstream_verdicts_unreadable"].items():
        assert entry["status"] == RDC._VERDICT_UNREADABLE, (s_, entry)
        assert entry["reason"], (s_, entry)
        assert entry["verdict_readable"] is False, (s_, entry)
        # and it is NOT also filed as a blockage or as the step passing
        assert s_ not in (out.get("blocking_steps") or {}), s_
        assert s_ not in (out.get("upstream_steps_passing") or {}), s_


def test_an_unreadable_verdict_does_not_excuse_the_missing_documents(tmp_path, mine):
    """THE DIRECTION, and it is the one 72c's own ruling already fixed.

    `test_a_step_with_no_published_verdict_is_not_an_excuse` holds that "a step that has
    published NOTHING in this run has no verdict, so there is no evidence of blockage and
    the documents are still owed; 'no evidence' must never read as 'blocked'". Reporting an
    unreadable record as `NOT_MEASURED` would have inverted that, because `NOT_MEASURED` is
    one of `_BLOCKING_STEP_STATUSES` -- deleting every `reports/metrics/*.json` would then
    forgive 37.5ic's missing documents for ever. So `UNREADABLE` is its own tier, outside
    that set.
    """
    assert RDC._VERDICT_UNREADABLE not in RDC._BLOCKING_STEP_STATUSES

    out = RDC.upstream_blockage_now(tmp_path, "a")
    assert out["blocked"] is False, (
        "an upstream verdict nobody could read excused this release's missing documents")


# ── 3. the wrapper's own key is not frozen by the wrapper ────────────────────

def test_the_wrapper_can_refresh_its_own_step_status(tmp_path):
    """Two passes over one project, through the real emitter."""
    step = {"id": "23", "required_outputs": []}
    row = tmp_path / SM.METRICS_REL / "23.json"

    FCC._emit_step_metrics(tmp_path, step, _Result("FAIL"))
    assert json.loads(row.read_text())["23__flow__step_status"] == "FAIL"

    FCC._emit_step_metrics(tmp_path, step, _Result("PASS"))
    assert json.loads(row.read_text())["23__flow__step_status"] == "PASS", (
        "the wrapper could not refresh its OWN key, so a step that failed once reads FAIL "
        "for the rest of this tree's life")


def test_a_programs_own_measurement_is_still_protected(tmp_path):
    """The filter's real purpose must not move: only the wrapper's own keys are exempt.

    THE COLLISION HAS TO BE REAL for this to measure anything. My first spelling emitted a
    program's key and then ran the wrapper over a step with NO `required_outputs` -- so the
    wrapper had no value for that key and could not have overwritten it whatever the
    exemption said. The arm passed for a reason unrelated to the rule. Here the step
    DECLARES a report that carries the same key with a different number, so the wrapper
    genuinely wants to write it and the exemption is what stops it.
    """
    rel = "reports/phase3/area.json"
    report = tmp_path / rel
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"instance_area": 999}) + "\n")

    SM.emit(tmp_path, "24", {"instance_area": 42})          # the program's own measurement
    FCC._emit_step_metrics(tmp_path, {"id": "24", "required_outputs": [rel]},
                           _Result("PASS"))

    row = json.loads((tmp_path / SM.METRICS_REL / "24.json").read_text())
    assert row["24__flow__instance_area"] == 42, (
        "the wrapper overwrote a program's own measurement with the value it forwarded "
        "from that step's report -- the exemption is too wide")
    assert row["24__flow__step_status"] == "PASS"


def test_the_wrapper_records_which_invocation_measured_the_step(tmp_path):
    FCC._emit_step_metrics(tmp_path, {"id": "23", "required_outputs": []},
                           _Result("PASS"))
    row = json.loads((tmp_path / SM.METRICS_REL / "23.json").read_text())
    assert row["23__flow__invocation"] == FCC._invocation_id()


def test_the_exemption_names_only_the_wrappers_own_keys():
    """Pinned against the source, so the exemption cannot quietly widen."""
    import inspect
    src = inspect.getsource(FCC._emit_step_metrics)
    assert '_own_keys = ("step_status", "invocation")' in src, (
        "the no-clobber exemption is spelled differently; check it still names only the "
        "keys this wrapper is the sole author of")
    assert "if k in _own_keys" in src


# ── an upstream blockage is not yet scoped to the artefact, and why ──────────

def test_the_presence_check_understands_the_flows_own_spec_shapes(tmp_path):
    """`_artefact_present` is correct and is NOT what decides an excuse.

    R-0915-160 asks that an upstream blockage excuse this step only when it is ABOUT the
    artefact this step needed. Nothing on disk at gate time says which artefact an upstream
    verdict is about -- `reports/metrics/<sid>.json` carries scalars, and this run's compliance
    report is not written until after every step. "Did the step produce it" looked like a proxy
    and the tree refuted it: a GDS PRESENT but carrying no geometry with step 37 FAIL must
    excuse (four arms in `test_a_producers_stated_refusal_is_not_a_documentation_defect` hold
    that), while `power.json` PRESENT and carrying no number by design with step 33
    NOT_MEASURED must not. Both are "blocking tier + artefact present".

    So the helper stays, correct and unused by the classification, and the reason is recorded
    in `upstream_blockage_now`. This arm pins the helper's own behaviour and the fact that the
    classification does not consult it -- so when the producer change that makes the rule
    implementable lands, this is where it starts.
    """
    gds = tmp_path / "phase3/stage4/gds"
    gds.mkdir(parents=True)
    (gds / "zzdie.gds").write_bytes(b"\x00" * 64)
    assert RDC._artefact_present(tmp_path, "phase3/stage4/gds/*.gds") is True
    assert RDC._artefact_present(tmp_path, "nope/*.gds") is False
    assert RDC._artefact_present(tmp_path,
                                 "nope.json OR phase3/stage4/gds/zzdie.gds") is True
    assert RDC._artefact_present(tmp_path, "") is False

    import inspect
    src = inspect.getsource(RDC.upstream_blockage_now)
    assert "_artefact_present" not in src, (
        "the excuse is being scoped by presence, which reverses four accepted arms")
    assert "MEASURED refusal" in src, (
        "the reason the excuse is not scoped must stay written where the rule would go")


# ── the row a dependent step sees must not depend on the worker pool ─────────

def test_the_steps_that_read_another_steps_verdict_are_derived_not_tabled():
    """The set comes from the tree: a new such program is picked up without an edit."""
    import yaml as _yaml
    flow = _yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "flow"
         / "phase1_phase2_phase3.yaml").read_text())
    steps = flow.get("steps") or []

    readers = FCC._reads_another_steps_verdict()
    assert "release_docs_check" in readers, sorted(readers)
    # the EMITTER is not a dependent reader of its own rows
    assert "flow_compliance_check" not in readers
    for wrapper in ("stage2_compliance", "stage3_compliance"):
        assert wrapper not in readers, wrapper

    dependent = FCC.steps_that_read_another_steps_verdict(steps)
    assert dependent == ["37.5ip", "37.5ic"], dependent
    assert len(dependent) < len(steps) / 4, (
        f"{len(dependent)} of {len(steps)} steps in the second wave would cost real "
        f"concurrency; the point of deriving the set is that it is small")


def test_the_dependent_steps_are_evaluated_after_every_other_step():
    """Pinned against the scheduler's source: two waves, dependent ones last.

    A behaviour arm here would need a full 70-step audit twice; what must hold is the
    ORDER, and that is a property of this block.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(getattr(FCC, '_audit_project', FCC.main)))
    assert "steps_that_read_another_steps_verdict" in src, (
        "the parallel path no longer asks which steps depend on another's row")
    assert "_wave1" in src and "_wave2" in src, src[:200]

    # and the results are rebuilt in the ORIGINAL order, so the waves are invisible
    assert "for _step in _eval_steps:" in src and "_by_id[str(_step.get(\"id\"))]" in src, (
        "results are appended per wave, so the parallel path no longer produces the same "
        "list as the sequential one")


def test_a_dependent_step_reads_a_row_written_before_it_runs(tmp_path, mine):
    """The property the waves buy, at the level the reader cares about.

    Wave 1 emits every other step's row; wave 2 then evaluates the dependent ones. So by the
    time `release_docs_check` runs, the rows for the steps it reads are on disk and carry THIS
    invocation -- which is exactly what `step_verdict_now` requires. Here the upstream rows are
    written first, as wave 1 does, and the read is the one the gate performs.
    """
    for sid in ("23", "33", "37", "37.4"):
        SM.emit(tmp_path, sid, {"step_status": "PASS", "invocation": mine})
    for sid in ("23", "33", "37", "37.4"):
        status, why = RDC.step_verdict_now(tmp_path, sid)
        assert (status, why) == ("PASS", ""), (sid, status, why)

    # and with wave 1's rows NOT yet written -- the pre-fix parallel race -- every one of
    # them is UNREADABLE rather than silently passing
    empty = tmp_path / "empty"
    empty.mkdir()
    for sid in ("23", "33", "37", "37.4"):
        assert RDC.step_verdict_now(empty, sid)[0] == RDC._VERDICT_UNREADABLE, sid


# ── what an upstream blockage is ABOUT (R-0915-165) ──────────────────────────

def _record(project: Path, sid: str, status: str, required, reasons) -> None:
    """The per-step output record, written by the auditor's own writer."""
    class _R:
        pass
    r = _R()
    r.status = status
    r.reasons = list(reasons)
    FCC._emit_step_output_record(project, {"id": sid,
                                           "required_outputs": list(required)}, r)


def test_the_power_budget_scenario_is_this_steps_own_defect(tmp_path, mine):
    """THE FIRST TEST R-0915-165 NAMES, and the one my presence proxy could not satisfy.

    Step 33 publishes NOT_MEASURED because no power BUDGET was declared. The runner writes
    `reports/phase3/power.json` regardless -- `eda_report_audit` says so in its own words, "it
    carries no number of its own" -- so 37.5ic's POWER_NO_TOTAL is a complaint about that file's
    CONTENT, which R-0915-149 already ruled is 37.5ic's own defect. Step 33's own gate has no
    complaint about the file at all, and its record says so by naming it in neither list.
    """
    rel = "reports/phase3/power.json"
    assert RDC._declaring_step(rel) == "33"

    for f, body in ((rel, '{"summarises": "power.rpt"}'),
                    ("reports/phase3/power.rpt", "power\n")):
        q = tmp_path / f
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_text(body)
    SM.emit(tmp_path, "33", {"step_status": "NOT_MEASURED", "invocation": mine})
    _record(tmp_path, "33", "NOT_MEASURED",
            ["reports/phase3/power.rpt", rel],
            ["no power budget was declared for this design"])

    about, why = RDC.upstream_blockage_is_about(tmp_path, "33", rel)
    assert about is False, why
    assert "neither" in why and rel in why, why

    out = RDC.upstream_blockage_now(tmp_path, "a")
    assert "33" not in (out.get("blocking_steps") or {}), (
        "step 33's unrelated blockage still excuses this release")


def test_an_upstream_gate_that_named_the_artefact_still_excuses(tmp_path, mine):
    """The other direction, and it is four of 72c's accepted arms: a GDS on disk carrying no
    geometry IS step 37's failure about that artefact. Its gate names it -- measured,
    `gds_substance_check` prints `phase3/stage4/gds/zzdie.gds: [MALFORMED_RECORD] ...`.
    """
    bind_invocation_top(tmp_path, 'zzdie')
    g = tmp_path / "phase3/stage4/gds/zzdie.gds"
    g.parent.mkdir(parents=True, exist_ok=True)
    g.write_bytes(b"\x00" * 448)
    SM.emit(tmp_path, "37", {"step_status": "FAIL", "invocation": mine})
    _record(tmp_path, "37", "FAIL", ["phase3/stage4/gds/*.gds"],
            ["phase3/stage4/gds/zzdie.gds: [MALFORMED_RECORD] length 0"])

    about, why = RDC.upstream_blockage_is_about(
        tmp_path, "37", "phase3/stage4/gds/zzdie.gds")
    assert about is True, why
    assert "unusable" in why, why


def test_a_declaration_pattern_covers_the_concrete_file_the_producer_named(tmp_path):
    """The record holds DECLARATION patterns; the producer names the file it read."""
    assert RDC._entry_covers("phase3/stage4/gds/*.gds",
                             "phase3/stage4/gds/zzdie.gds") is True
    assert RDC._entry_covers("a.json OR b.json", "b.json") is True
    assert RDC._entry_covers("reports/phase3/power.json",
                             "reports/phase3/power.json") is True
    assert RDC._entry_covers("reports/phase3/power.json", "reports/phase3/area.json") is False


def test_no_record_is_no_excuse(tmp_path, mine):
    """FAILS CLOSED, the same direction 72c already ruled for a missing verdict."""
    SM.emit(tmp_path, "23", {"step_status": "FAIL", "invocation": mine})
    about, why = RDC.upstream_blockage_is_about(
        tmp_path, "23", "reports/phase3/sta/post_route_summary.json")
    assert about is False
    assert "published no per-step output record" in why, why


def test_a_record_from_another_invocation_is_no_excuse(tmp_path, mine):
    _record(tmp_path, "23", "FAIL", ["reports/phase3/sta/post_route_summary.json"],
            ["reports/phase3/sta/post_route_summary.json: no slack"])
    rec = _PL.step_output_record_path(tmp_path, "23")
    doc = json.loads(rec.read_text())
    doc["invocation"] = "AN-EARLIER-RUN"
    rec.write_text(json.dumps(doc) + "\n")

    about, why = RDC.upstream_blockage_is_about(
        tmp_path, "23", "reports/phase3/sta/post_route_summary.json")
    assert about is False
    assert "AN-EARLIER-RUN" in why, why


def test_the_step_folders_outputs_json_is_never_consulted():
    """It restates the declaration and it LIES: measured, 7 of 90 entries on a converged run,
    every folder marked "status": "pass", name a `rel` that is not in the run directory."""
    import inspect
    src = inspect.getsource(RDC.upstream_blockage_is_about)
    assert "outputs.json" in src and "lies" in src, (
        "the reason that record is untrusted must stay written where the reader is")
    whole = (PROGRAMS / "release_docs_check.py").read_text()
    assert "/outputs.json" not in whole, "release_docs_check reads the step folders' outputs.json"


def test_the_record_is_written_on_both_branches_of_the_step_loop():
    """Sequential and wave: a record that appears only single-threaded is one nobody can rely on.
    The same contract the metrics row beside it already carries."""
    import inspect
    src = inspect.getsource(getattr(FCC, '_audit_project', FCC.main))
    assert src.count("_emit_step_output_record(project,") == 2, (
        f"the record is written at {src.count('_emit_step_output_record(project,')} of the two "
        f"step-loop branches")
    for line in src.splitlines():
        if "_emit_step_output_record" in line:
            assert "_emit_step_metrics" not in line




# ── the record's own atomic temp ─────────────────────────────────────────────

def test_an_interrupted_record_write_leaves_nothing_that_moves_the_design_hash(tmp_path):
    """THE THIRD TIME THIS SHAPE HAS BITTEN, and it is worth naming as a pattern.

    R-0915-165's per-step record is written temp-then-replace for the same reason the canonical
    audit is: no reader may see a half-written one. A pass killed between the write and the
    replace leaves `<sid>.json.<pid>.tmp`, which is the auditor's own file, carries no content a
    reader could identify it by, and -- unrecognised -- is hashed as a DESIGN INPUT, so the
    design hash moves permanently on an unchanged design.

    The canonical audit's temp was the first (R-0915-151), the authorship note's the second, this
    is the third. Any atomicity mechanism the auditor adds creates a file its own identity rule
    cannot see.
    """
    import os as _os
    import design_input_digest as D

    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input" / "spec.md").write_text("# a counter\n")

    def sha() -> str:
        blk = D.build_digest(D.scan_inputs(project), [])
        assert blk["unusable_reason"] is None, blk
        return blk["sha256"]

    before = sha()
    # named by the WRITER's own path definition, not spelled here
    rec = _PL.step_output_record_path(project, "37.4")
    rec.parent.mkdir(parents=True, exist_ok=True)
    leftover = rec.with_name(f"{rec.name}.{_os.getpid()}.tmp")
    leftover.write_text('{"schema": 1, "writ')          # a half-written record

    assert D.is_auditor_output(project, leftover) is True, leftover
    assert sha() == before, (
        "a temp left by an interrupted record write moved the design hash, so every later pass "
        "reads an unchanged design as changed")


def test_a_producers_temp_is_not_swallowed_by_the_step_output_rule(tmp_path):
    """The rule is that directory plus the writer's exact shape, never `*.tmp`."""
    import design_input_digest as D

    project = tmp_path / "proj"
    (project / "input").mkdir(parents=True)
    (project / "input" / "spec.md").write_text("x\n")
    for rel in ("phase2/stage1/rtl/core.v.99.tmp",
                f"{_PL.STEP_OUTPUT_RECORD_DIR}/37_4.json.tmp",       # no pid
                f"{_PL.STEP_OUTPUT_RECORD_DIR}/37_4.json.abc.tmp",   # pid not digits
                "reports/audit/37_4.json.99.tmp"):                   # wrong directory
        f = project / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
        assert D.is_auditor_output(project, f) is False, rel


def test_the_record_writer_removes_its_temp_however_the_write_ends(tmp_path):
    """R-0915-168 moved WHERE this is guaranteed, not WHETHER it is.

    This writer used to hand-roll temp+replace with its own `finally` -- the third such in the
    module, with the third temp shape, and it cost its own review before `is_auditor_output`
    learned to recognise the leftover. It now goes through `_auditor_write.publish`, so the
    guarantee is asserted of the helper AND of the fact that this writer uses it, which is what
    stops the two drifting.

    The writer's own contract is unchanged and still deliberate: `_emit_step_output_record` is
    BEST-EFFORT BY CONSTRUCTION ("a record that failed to write must never move a verdict"), so it
    swallows the helper's error rather than letting it reach a verdict.
    """
    import ast
    import inspect
    import textwrap

    import _auditor_write as _AW

    tries = [n for n in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(_AW.publish))))
             if isinstance(n, ast.Try) and n.finalbody]
    assert any("_discard" in ast.unparse(ast.Module(body=t.finalbody, type_ignores=[]))
               for t in tries), "the helper's finally does not remove the temp"

    fsrc = (PROGRAMS / "flow_compliance_check.py").read_text()
    assert "_aw.publish(dest, json.dumps({" in fsrc, (
        "the per-step record no longer goes through the one auditor writer")

    # the writer still swallows, so a failed write changes nothing and leaves nothing
    real = os.replace
    try:
        os.replace = lambda a, b: (_ for _ in ()).throw(
            OSError(28, "No space left on device"))
        FCC._emit_step_output_record(
            tmp_path, {"id": "37.4", "required_outputs": ["reports/phase3/x.json"]},
            type("R", (), {"status": "FAIL", "reasons": []})())
    finally:
        os.replace = real
    assert not _PL.step_output_record_path(tmp_path, "37.4").exists()
    recdir = tmp_path / _PL.STEP_OUTPUT_RECORD_DIR
    if recdir.is_dir():
        assert not [q for q in recdir.iterdir()
                    if _PL.AUDITOR_TMP_SUFFIX in q.name], "the temp outlived the write"

def test_the_temp_shape_is_derived_from_the_writers_own_directory():
    """R-0915-168 — ONE declared shape, and the digest asks for it rather than spelling it.

    My R-0915-165 cut had the digest build its own regex from `STEP_OUTPUT_RECORD_DIR` -- better
    than a literal, still a fourth spelling of one idea. `_path_layout.is_auditor_inprogress_name`
    is now the single answer and `_auditor_write` the only minter, so this asserts the digest
    delegates and that the OLD step-output shape is still recognised, because leftovers in it
    exist on every tree written before this change.
    """
    import design_input_digest as D

    dsrc = (PROGRAMS / "design_input_digest.py").read_text()
    assert "is_auditor_inprogress_name" in dsrc, (
        "the digest no longer asks `_path_layout` what an in-progress name is")
    assert "_AUDITOR_STEP_OUTPUT_TMP_RE" not in dsrc, (
        "the per-step temp shape is declared twice again")

    import tempfile
    t = Path(tempfile.mkdtemp())
    for rel, why in (
            (f"{_PL.STEP_OUTPUT_RECORD_DIR}/37_4.json.99.tmp", "the R-0915-165 shape"),
            (f"{_PL.STEP_OUTPUT_RECORD_DIR}/37_4.json.1.2{_PL.AUDITOR_TMP_SUFFIX}",
             "the declared shape"),
            (f"{_PL.STEP_OUTPUT_RECORD_DIR}/37_4.json{_PL.AUDITOR_LOCK_SUFFIX}",
             "its lock")):
        f = t / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("")
        assert D.is_auditor_output(t, f) is True, (rel, why)
