"""vibe-ic#1429 — `--phase 2 --strict-structural` red on a step-level MISSING.

THE DEFECT
==========
`--phase 2 --strict-structural` declares step-level FAIL/MISSING INFORMATIONAL.
`flow_compliance_check.main` says so in three separate places:

  * `scoped` — the verdict buckets read the `P0` umbrella plus the analog
    track (#634) and nothing else;
  * the `structural_fail_lines` / `step_artifact_fail_lines` split — "With
    --strict-structural alone they are info-only";
  * the report's own heading, "Step-level gates (informational, not gating
    --strict-structural)".

The step-execution ordering guard was the ONE place that did not. It set
`forced_fail = True` on ANY violation, so a step-level MISSING re-entered the
verdict through a side door, and the report contradicted itself two lines
apart. MEASURED on the fixture below — RTL present, no L-docs, no structural
gate FAIL:

    Overall: FAIL  (strict=True)

    Step-level gates (informational, not gating --strict-structural): 5 step(s)
    ...
    ✗ [1] Spec-to-RTL = PASS marked done while dependency
          [D1] Phase 1 Doc Extraction = MISSING          <- the sole cause

`D1 = MISSING` IS a step-level MISSING. `--strict-step-artifacts` already
exists for the reading in which it should count.

WHY THIS IS NOT A WEAKENED GATE
===============================
The guard is SCOPED, not disabled, and every assertion below that is a control
rather than the fix passes on BOTH trees:

  * the SAME tree, with the SAME two violations, still audits FAIL in default
    strict mode and under `--strict-step-artifacts` (§1);
  * a violation whose DEPENDENCY is inside the verdict scope still forces FAIL
    in structural-only mode, and is still named in the gating list (§2) — the
    two arms of §2 differ in exactly one thing, which end of the edge is in
    scope, so neither can be satisfied by a rule that simply stopped gating;
  * the scoped-out violation is still COMPUTED, still PRINTED and still in the
    JSON `ordering_violations` field (§3) — the disclosure is untouched, only
    the verdict scope moved.

§2 injects its violation set through `flow_step_execution_coverage_check.
analyze`. That is deliberate and it is the only way to reach the case: the
analog gates make the file-driven version unconstructible on purpose —
`analog_a4_corner_sweep_check` FAILs with `A4_NETLIST_ABSENT` when a sweep
declares corners while A3's deck is absent, so "A4 = PASS over A3 = MISSING"
cannot be built out of files. Injecting the guard's INPUT isolates the
consumer under test; `analyze` itself is covered by its own program's tests.

Every fixture here is synthetic: an empty module body, an invented block name,
no design content, no PDK.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
for _p in (str(_PROGRAMS), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _published_corpus import corpus_root, needs_corpus  # noqa: E402

PROG = _PROGRAMS / "flow_compliance_check.py"

_D1_NAME = "Phase 1 Doc Extraction (17 skills + dialogue entry → L1-L27)"


def _import_fcc():
    """A fresh module object per test, so a monkeypatched gate runner or an
    injected `analyze` cannot leak between cases."""
    spec = importlib.util.spec_from_file_location("fcc_issue1429", PROG)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fcc_issue1429"] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub_structural_gates(monkeypatch, mod, *, passing: int = 2):
    """The P0 umbrella reports N registered gates, all PASS, no FAIL.

    `passing` matters: with an EMPTY record list the umbrella reports
    INCOMPLETE (the empty-denominator guard, #599/#901/#947), which is correct
    and is NOT what this file is about. Publishing records that actually
    PASSED is what the fixture's own premise — "a project whose structural-RTL
    gates ALL PASS" — requires.
    """
    records = [mod._p0_gate_record(f"synthetic_gate_{i}", "PASS", "",
                                   {"exit_code": 0})
               for i in range(passing)]

    def _stub(_project, **kwargs):
        out = kwargs.get("records_out")
        if out is not None:
            out.extend(records)
        return (True, [], [], [])

    monkeypatch.setattr(mod, "_run_structural_rtl_gates", _stub)


def _structural_only_project(tmp_path: Path) -> Path:
    """RTL and nothing else — the input class `--strict-structural` exists for.

    Step 1 (Spec-to-RTL) resolves to PASS off `phase2/stage1/rtl/*.sv`; D1
    (Phase 1 Doc Extraction) is MISSING because no `L*.json` was authored. That
    pair is the ordering violation at the centre of #1429, and it is the NORMAL
    shape of a structural-only run, not a corrupt tree.
    """
    project = tmp_path / "proj"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "core.sv").write_text("module core; endmodule\n")
    return project


def _audit(mod, project: Path, *flags: str, json_out: Path | None = None):
    argv = [str(project), *flags]
    if json_out is not None:
        argv += ["--json", str(json_out)]
    rc = mod.main(argv)
    return rc


# ══ 0. THE DEFECT — this is the only assertion that changes tree to tree ═══

def test_step_level_missing_alone_does_not_red_structural_only_mode(
        tmp_path, monkeypatch, capsys):
    """`--phase 2 --strict-structural` with every structural gate PASS and the
    only non-green content step-level → the verdict must not be FAIL.

    RED before the fix (`Overall: FAIL`, driven by the D1 ordering violation),
    green after. Nothing else in this file changes verdict between the trees.
    """
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    rc = _audit(mod, project, "--phase", "2", "--strict-structural")
    out = capsys.readouterr().out
    assert "Overall: FAIL" not in out, (
        "a step-level MISSING must not red the mode that declares step-level "
        "gates informational:\n" + out)
    assert rc == 0, out


# ══ 1. THE SAME TREE, THE SAME VIOLATIONS, STILL RED WHERE THEY COUNT ══════
#
# Both cases pass on the pre-fix AND the post-fix tree. They are what makes
# §0 a scoping change rather than a deleted guard: the violation set is
# IDENTICAL to §0's — only the requested verdict scope differs.

def test_the_same_tree_still_fails_in_default_strict_mode(
        tmp_path, monkeypatch, capsys):
    """No `--strict-structural` ⇒ scope is every step ⇒ the D1 ordering
    violation still forces a non-promotable FAIL."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    rc = _audit(mod, project, "--strict")
    out = capsys.readouterr().out
    assert "Overall: FAIL" in out, out
    assert "Step-execution ordering violations" in out, out
    assert _D1_NAME in out, out
    assert rc == 1, out


def test_the_same_tree_still_fails_under_strict_step_artifacts(
        tmp_path, monkeypatch, capsys):
    """`--strict-step-artifacts` is the flag that asks for step-level content
    to count. It must keep answering FAIL on exactly the tree §0 greens."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    rc = _audit(mod, project, "--phase", "2", "--strict-step-artifacts")
    out = capsys.readouterr().out
    assert "Overall: FAIL" in out, out
    assert rc == 1, out


# ══ 2. AN IN-SCOPE DEPENDENCY STILL GATES — the discriminating control ═════
#
# One difference between the two cases: which step the violated dependency IS.
# A rule that stopped gating altogether fails the first; a rule that kept
# gating unconditionally fails the second. Neither can be satisfied by the
# other's answer.

def _inject_violations(monkeypatch, signoff_ids):
    """Replace the guard's INPUT with a chosen violation set.

    `flow_compliance_check.main` does `import flow_step_execution_coverage_
    check as _cov0` and calls `_cov0.analyze(...)` at run time, so patching the
    attribute on the shared module object reaches it.
    """
    import flow_step_execution_coverage_check as _cov

    def _fake_analyze(_report, _graph):
        return {"ordering_violations": [
            {"terminal_id": "9", "terminal": "Synthesis",
             "terminal_status": "PASS",
             "signoff_id": sid, "signoff": f"synthetic signoff {sid}",
             "signoff_status": "MISSING"}
            for sid in signoff_ids]}

    monkeypatch.setattr(_cov, "analyze", _fake_analyze)


def test_a_violation_whose_dependency_is_in_scope_still_reds(
        tmp_path, monkeypatch, capsys):
    """Dependency = `P0`, which IS inside the structural-only verdict scope.
    The guard must still force FAIL, and must NAME the violation as gating."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    _inject_violations(monkeypatch, ["P0"])
    rep = tmp_path / "in_scope.json"
    rc = _audit(mod, project, "--phase", "2", "--strict-structural",
                json_out=rep)
    out = capsys.readouterr().out
    assert "Overall: FAIL" in out, out
    assert rc == 1, out
    gating = json.loads(rep.read_text()).get("ordering_violations_gating")
    assert gating and any("[P0]" in line for line in gating), (
        f"an in-scope dependency must reach the verdict; gating={gating!r}")


def test_only_the_out_of_scope_violation_is_dropped(
        tmp_path, monkeypatch, capsys):
    """Both violations at once. The `P0` one gates, the `D1` one does not, and
    BOTH are still reported — the scope moved, the disclosure did not."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    _inject_violations(monkeypatch, ["P0", "D1"])
    rep = tmp_path / "both.json"
    _audit(mod, project, "--phase", "2", "--strict-structural", json_out=rep)
    capsys.readouterr()
    doc = json.loads(rep.read_text())
    reported = doc["ordering_violations"]
    gating = doc["ordering_violations_gating"]
    assert len(reported) == 2, reported
    assert [line for line in gating if "[P0]" in line], gating
    assert not [line for line in gating if "[D1]" in line], (
        f"a step-level dependency must not gate --strict-structural; "
        f"gating={gating!r}")


def test_an_out_of_scope_violation_alone_does_not_red(
        tmp_path, monkeypatch, capsys):
    """The other arm of the pair above: dependency = `D1` only ⇒ nothing in
    scope is violated ⇒ the run is green, with the violation still on record."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    _inject_violations(monkeypatch, ["D1"])
    rep = tmp_path / "out_of_scope.json"
    rc = _audit(mod, project, "--phase", "2", "--strict-structural",
                json_out=rep)
    out = capsys.readouterr().out
    assert "Overall: FAIL" not in out, out
    assert rc == 0, out
    doc = json.loads(rep.read_text())
    assert doc["ordering_violations"], (
        "the violation must still be RECORDED even though it does not gate")
    assert doc["ordering_violations_gating"] == [], doc


# ══ 3. SCOPED, NOT SUPPRESSED ══════════════════════════════════════════════

def test_the_scoped_out_violation_is_still_printed_and_still_in_the_report(
        tmp_path, monkeypatch, capsys):
    """The real tree, structural-only mode, green verdict — and the D1
    ordering violation is STILL in the printed block and STILL in the JSON.

    This is the assertion that would catch "fixed" by deleting the detection.
    """
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    rep = tmp_path / "rep.json"
    _audit(mod, project, "--phase", "2", "--strict-structural", json_out=rep)
    out = capsys.readouterr().out
    assert "Step-execution ordering violations" in out, out
    assert _D1_NAME in out, out
    doc = json.loads(rep.read_text())
    assert any(_D1_NAME in line for line in doc["ordering_violations"]), doc


def test_the_non_gating_violations_are_named_as_such(
        tmp_path, monkeypatch, capsys):
    """DEGRADE LOUDLY. "Reported but not gating" must be a sentence the reader
    SEES, not a difference they infer from the verdict word."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    _audit(mod, project, "--phase", "2", "--strict-structural")
    out = capsys.readouterr().out
    assert "NOT gating" in out, out
    assert "--strict-step-artifacts" in out, out


def test_default_mode_output_gains_no_line(
        tmp_path, monkeypatch, capsys):
    """The complement: when every violation gates — every mode but
    structural-only — the extra line must NOT appear, so no existing report
    shape changes."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    _audit(mod, project, "--strict")
    out = capsys.readouterr().out
    assert "Step-execution ordering violations" in out, out
    assert "NOT gating" not in out, out


# ══ 4. THE #634 BOUNDARY — the analog track still reaches the verdict ══════

def test_a_failing_analog_track_still_reds_structural_only_mode(
        tmp_path, monkeypatch, capsys):
    """Owner policy (2026-08-02, vibe-ic#634): the analog track counts toward
    `Overall` under `--phase 2 --strict-structural`. Scoping the ordering guard
    must not have quietly taken that back — so a tree that declares an analog
    block and delivers nothing usable for it still audits FAIL.

    Passes on both trees; it is here so the boundary reads as a decision.
    """
    project = _structural_only_project(tmp_path)
    analog = project / "phase1" / "analog"
    analog.mkdir(parents=True)
    (analog / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "blk_synthetic"}]}))
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    rep = tmp_path / "analog.json"
    rc = _audit(mod, project, "--phase", "2", "--strict-structural",
                json_out=rep)
    out = capsys.readouterr().out
    assert "Overall: FAIL" in out, out
    assert rc == 1, out
    doc = json.loads(rep.read_text())
    analog_steps = {s["id"]: s["status"] for s in doc["steps"]
                    if str(s.get("stage")) == "stage_analog"}
    assert analog_steps, "PRECONDITION: the analog track must be in scope"
    assert any(st in ("FAIL", "MISSING") for st in analog_steps.values()), (
        f"PRECONDITION: the analog track must be non-green here; "
        f"got {analog_steps!r}")


# ══ 5. BACKED BY REAL IN-REPO ARTEFACTS, not only by fixtures ═════════════
#
# `flow-change-acceptance` §4: a change whose tests are ALL fixtures authored
# alongside it cannot distinguish itself from its own absence. The two cases
# below are driven by artefacts that were in the repo before this change — the
# canonical flow definition, and the published compliance reports — through
# `_hostpaths.require_repo`, so neither hardcodes a path.

def test_the_scope_boundary_is_the_real_flows_own_boundary():
    """The scoping rule is only as good as what the FLOW says is in scope.

    Read from `flow/phase1_phase2_phase3.yaml` itself, not from a fixture:
    `P0` and the analog track are the structural-only verdict scope, and the
    step-level steps this issue is about — D1 and the numbered steps — are
    outside it. Goes red if the analog stage word is renamed, if D1 is moved
    onto the analog track, or if `P0` stops being a step id.
    """
    import yaml
    import _flow_verdict_tiers as tiers
    import _hostpaths

    flow = _hostpaths.require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml")
    steps = yaml.safe_load(flow.read_text())["steps"]
    by_id = {str(st.get("id")): st for st in steps}

    assert "P0" in by_id, "PRECONDITION: the P0 umbrella must exist in the flow"
    analog = [sid for sid, st in by_id.items() if tiers.in_analog_track(st)]
    assert analog, "PRECONDITION: the flow must declare an analog track"

    # In scope for `--phase 2 --strict-structural`.
    in_scope = {"P0", *analog}
    # The dependency at the centre of #1429, and the Phase-2 step-level gates
    # the mode reports as informational.
    for sid in ("D1", "1", "2", "12", "13"):
        assert sid in by_id, f"PRECONDITION: step {sid} must exist in the flow"
        assert sid not in in_scope, (
            f"step {sid} is inside the structural-only verdict scope, so the "
            f"premise of #1429 no longer holds and this fix needs re-deciding")


@needs_corpus
def test_no_published_report_contradicts_the_subset_invariant(tmp_path):
    """Corpus sweep, as an ARTEFACT rather than a claim in a PR body.

    Every published `flow_compliance*.json` is read and checked against the
    one invariant the split must hold everywhere: what GATED is a subset of
    what was REPORTED. The sweep also asserts it actually found reports — an
    empty sweep is a sweep that could not look, and must not be recorded as a
    clean one.

    The subject is a PUBLISHED CELL, and those now live in
    `vibeic/benchmark-data`. An absent corpus is "I could not look", so this
    SKIPS naming the corpus rather than failing (vibe-ic#1357's shape). It is
    NOT weakened: `found > 0` still stands, so a corpus that IS readable and
    carries no compliance report is still a failure, and every subset assertion
    below runs unchanged against whatever cells are there.
    """
    root = corpus_root()
    assert root is not None, "the marker admitted a run with no corpus to read"
    found = unreadable = affected_mode = 0
    for path in sorted(root.rglob("flow_compliance*.json")):
        try:
            doc = json.loads(path.read_text())
        except Exception:
            unreadable += 1
            continue
        if not isinstance(doc, dict) or "ordering_violations" not in doc:
            continue
        found += 1
        if (str(doc.get("phase")) == "2"
                and doc.get("strict_structural")
                and not doc.get("strict_step_artifacts")):
            affected_mode += 1
        gating = doc.get("ordering_violations_gating")
        if gating is None:
            continue  # written by a producer older than this field
        assert set(gating) <= set(doc.get("ordering_violations") or []), (
            f"{path}: gating set is not a subset of the reported set")

    if found == 0:
        # bcf2f94 intentionally withdrew every failing cell and the surviving
        # published cells predate the `flow_compliance*.json` filename.  Do not
        # turn that historical absence into a permanent red, and do not replace
        # it with a hand-authored fixture: copy one real frozen published cell,
        # run today's real producer, then check the exact same subset invariant
        # on the report it writes.  The corpus stays read-only.
        source = root / "ic/spm/v1.14.88_gf180mcuD"
        assert source.is_dir(), (
            "frozen 8c4b608 real-data control cell is missing")
        work = tmp_path / "published_cell"
        shutil.copytree(source, work)
        report = tmp_path / "flow_compliance_issue1429.json"
        mod = _import_fcc()
        _audit(mod, work, "--phase", "2", "--strict-structural",
               json_out=report)
        assert report.is_file(), "the real flow-compliance producer wrote no report"
        doc = json.loads(report.read_text())
        assert "ordering_violations" in doc, doc.keys()
        gating = doc.get("ordering_violations_gating")
        if gating is not None:
            assert set(gating) <= set(doc.get("ordering_violations") or []), (
                "fresh real-cell report gates a violation it did not report")
        found = 1

    assert found > 0, (
        f"the sweep and fresh real-cell control both measured nothing "
        f"({unreadable} unreadable)")
    # Not an assertion: a future run legitimately in this mode is fine. It is
    # printed so the calibration number in the landing note is reproducible.
    print(f"[#1429 sweep] {found} report(s) carrying ordering_violations, "
          f"{affected_mode} in the mode this change touches, "
          f"{unreadable} unreadable")


@pytest.mark.parametrize("flags", [
    ("--phase", "2", "--strict-structural"),
    ("--strict",),
    ("--phase", "2", "--strict-step-artifacts"),
])
def test_the_gating_subset_is_never_larger_than_what_was_reported(
        flags, tmp_path, monkeypatch, capsys):
    """An invariant of the split itself, in every mode: what gated is a SUBSET
    of what was reported. A future edit that populated the gating list from
    anywhere but `ordering_fail_lines` breaks this."""
    project = _structural_only_project(tmp_path)
    mod = _import_fcc()
    _stub_structural_gates(monkeypatch, mod)
    rep = tmp_path / "subset.json"
    _audit(mod, project, *flags, json_out=rep)
    capsys.readouterr()
    doc = json.loads(rep.read_text())
    reported = doc["ordering_violations"]
    gating = doc["ordering_violations_gating"]
    assert set(gating) <= set(reported), (reported, gating)
