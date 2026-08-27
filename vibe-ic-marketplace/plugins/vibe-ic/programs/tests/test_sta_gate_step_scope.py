#!/usr/bin/env python3
"""STA gates discovered project-wide: another step's report carried — and
failed — a step it has nothing to do with.

THE DEFECT. `eda_report_audit` discovers reports with a project-wide `rglob`
that has no relationship to the step whose gate is asking, and STA mode globs
`*sta*.rpt` / `*timing*.rpt` / `*STA*.rpt` / `*timing*.log` — which matches
every STA artefact the whole flow ever writes. `--under` (the repeatable scope
flag `scoped_discovery` implements) was added for exactly this and wired for
DRC only: before this change all 10 `--under` occurrences in
`flow/phase1_phase2_phase3.yaml` were DRC clauses, and BOTH STA call sites
were project-wide.

MEASURED, on the published run `benchmark-data/ic/sha256/
clean_run_v1427_20260715`:

    step 10 (PRE-LAYOUT STA)   files_found=13   rc=1  STA_REAL_VIOLATION_FOUND
    step 23 (post-route STA)   files_found=13   rc=1  STA_REAL_VIOLATION_FOUND

Same thirteen files, so the two gates' summary documents come out
BYTE-IDENTICAL — and the violation both cite is sourced from
`phase3/stage3/sta/sta_mcorner_ocv.rpt` (setup -67.61 ns), from
`sta_mcorner_ocv_postrepair.rpt` (step 32's POST-repair artefact) and from
`reports/phase3/aging_sta.rpt`. Step 10's own declared report,
`phase3/stage3/sta/pre_pnr_timing.rpt`, is clean. A pre-layout gate was being
failed by a post-repair artefact.

THREE CALL SITES, not two. The two yaml clauses AND
`phase3_one_shot_runner._DECLARED_SIGNOFF_GATES`, whose `sta_signoff` entry
invokes the same wrapper inline and writes the SAME artefact step 23's yaml
clause writes (`reports/phase3/sta/post_route_summary.json`). Scoping only the
yaml would have been a no-op on every real run — the #755 shape. The scope is
therefore asserted in both places, and asserted to be the same string.

WHAT THE SCOPE MUST NOT BUY. `--under` narrows what a gate can see, so it is
also the perfect instrument for buying a green. Two guards below refuse that:
`test_a_violation_in_the_steps_own_report_still_fails_the_scoped_gate` (the
scope may not silence the step's own evidence) and
`test_step10_scope_is_not_wide_enough_to_reach_the_post_route_reports` (the
scope may not be widened back into a directory).

DIRECTION-1 GUARD (`test_d1_*`): unscoped discovery must keep working exactly
as before for callers that state no scope, so nothing outside these three
sites changes behaviour. That test holds on the pre-fix tree too.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_RUNNER_SRC = _PROGRAMS / "phase3_one_shot_runner.py"
_WRAPPER = _PROGRAMS / "sta_report_check.py"

sys.path.insert(0, str(_PROGRAMS))

# Padding to clear eda_report_audit.MIN_REPORT_BYTES["sta"] (1024 B).
_PAD = "# " + ("=" * 78 + "\n") * 20  # ~1.6 KB

_MET = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\n"
    "data arrival time: 2.34 ns\n"
    "data required time: 2.49 ns\n"
    "WNS = 0.15 ns\nTNS = 0.0 ns\n"
    "0.15   slack (MET)\n"
    "setup check: PASS\nhold check: PASS\n" + _PAD
)

_VIOLATED = (
    "OpenSTA 2.4.0 report_checks\n"
    "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
    "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
    "Path Type: max\n"
    "data arrival time: 9.90 ns\n"
    "data required time: 2.49 ns\n"
    "WNS = -7.41 ns\nTNS = -412.0 ns\n"
    "-7.41   slack (VIOLATED)\n"
    "setup check: FAIL\nhold check: PASS\n" + _PAD
)

_STEP10_REPORT = "phase3/stage3/sta/pre_pnr_timing.rpt"
_STEP23_REPORT = "phase3/stage3/sta/post_route_timing.rpt"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _flow_invocations(program: str):
    """Every `<program> ...` command string declared in the flow yaml."""
    return re.findall(rf'"({re.escape(program)} [^"]*)"',
                      _FLOW.read_text(errors="replace"))


def _unders(cmd: str):
    toks = cmd.split()
    return [toks[i + 1] for i, t in enumerate(toks)
            if t == "--under" and i + 1 < len(toks)]


def _run(project: Path, *extra, out="o.json"):
    """Invoke the wrapper the way the flow does, from inside the project."""
    cp = subprocess.run(
        [sys.executable, str(_WRAPPER), ".", "--mode", "sta", *extra,
         "--json", out],
        cwd=str(project), capture_output=True, text=True)
    doc = {}
    p = project / out
    if p.is_file():
        try:
            doc = json.loads(p.read_text())
        except ValueError:
            doc = {}
    return cp.returncode, doc


def _rules(doc):
    return sorted({f.get("rule") for f in (doc.get("findings") or [])})


@pytest.fixture()
def project(tmp_path):
    """A run whose PRE-LAYOUT report is clean and whose LATER-step reports are
    not — the shape measured on the published sha256 clean runs.

    `sta_mcorner_ocv_postrepair.rpt` is step 32's post-repair artefact and
    `aging_sta.rpt` is step 33's; neither belongs to step 10 or step 23.
    """
    p = tmp_path / "proj"
    (p / "phase3/stage3/sta").mkdir(parents=True)
    (p / "reports/phase3").mkdir(parents=True)
    (p / _STEP10_REPORT).write_text(_MET)
    (p / _STEP23_REPORT).write_text(_MET)
    (p / "phase3/stage3/sta/sta_mcorner_ocv.rpt").write_text(_VIOLATED)
    (p / "phase3/stage3/sta/sta_mcorner_ocv_postrepair.rpt").write_text(_VIOLATED)
    (p / "reports/phase3/aging_sta.rpt").write_text(_VIOLATED)
    return p


# ===========================================================================
# NEGATIVE CONTROL — these fail on the pre-fix tree
# ===========================================================================
def test_every_flow_sta_gate_is_step_scoped():
    """FAILS WITHOUT THE FIX: on the pre-fix tree neither STA clause carries
    `--under`, so both discover project-wide."""
    invocations = _flow_invocations("sta_report_check")
    assert len(invocations) == 2, (
        f"expected exactly 2 sta_report_check clauses in the flow, found "
        f"{len(invocations)}: {invocations} — a new call site must be scoped "
        f"in the same change that adds it")
    for cmd in invocations:
        assert _unders(cmd), (
            f"unscoped STA gate: {cmd!r}. `eda_report_audit` discovers "
            f"project-wide, so this clause reads every STA report in the run "
            f"— including other steps' — and both carries and fails on them.")


def test_each_sta_gate_scopes_to_the_report_its_own_step_declares():
    """The scope is only honest if it is the step's OWN declared artefact.
    Tie it to the `files_exist` clause in the same gate so it cannot drift to
    an unrelated path (and so a `--under` pointing at nothing is caught).

    AMENDED when step 10's scope gained `phase3/stage3/sta/per_corner`: the
    invariant was "exactly one --under", which read as the rule but was only
    the shape it happened to have. The rule is that the FIRST scope is the
    step's own declared report, backed by `files_exist`; the rule for any
    further scope is the sibling test below, which refuses anything that can
    reach another step's artefacts.
    """
    text = _FLOW.read_text(errors="replace")
    expected = {_STEP10_REPORT: "reports/phase3/sta/pre_pnr_summary.json",
                _STEP23_REPORT: "reports/phase3/sta/post_route_summary.json"}
    for cmd in _flow_invocations("sta_report_check"):
        toks = cmd.split()
        json_target = toks[toks.index("--json") + 1]
        unders = _unders(cmd)
        assert unders, f"{cmd!r}: unscoped"
        assert expected.get(unders[0]) == json_target, (
            f"{cmd!r}: --under {unders[0]!r} is not the report the step that "
            f"writes {json_target!r} declares")
        assert f'files_exist: ["{unders[0]}"]' in text, (
            f"--under {unders[0]!r} is not backed by a files_exist clause; a "
            f"scope naming an artefact the step does not declare is a scope "
            f"nobody is required to produce")


def test_the_runner_inline_sta_signoff_uses_step23_scope():
    """FAILS WITHOUT THE FIX. `_DECLARED_SIGNOFF_GATES` runs the same wrapper
    inline and writes the SAME json step 23's yaml clause writes, so an
    unscoped runner overwrites the scoped verdict on every real run. #755:
    fixing one call site is not fixing the class."""
    sys.path.insert(0, str(_PROGRAMS))
    import phase3_one_shot_runner as r  # noqa: WPS433

    entries = [g for g in r._DECLARED_SIGNOFF_GATES
               if g[1] == "sta_report_check.py"]
    assert len(entries) == 1, entries
    extra = list(entries[0][3])
    assert "--under" in extra, (
        "the runner's inline sta_signoff gate still discovers project-wide; "
        "it would overwrite step 23's scoped verdict with an unscoped one")
    runner_scope = extra[extra.index("--under") + 1]

    yaml_scopes = [s for cmd in _flow_invocations("sta_report_check")
                   for s in _unders(cmd)
                   if "post_route" in cmd]
    assert yaml_scopes == [runner_scope], (
        f"the runner scopes to {runner_scope!r} and step 23's yaml clause to "
        f"{yaml_scopes!r}; the two invocations write the same artefact and "
        f"must read the same one")


def test_the_two_sta_gates_no_longer_reach_one_verdict_over_one_file_set(
        project):
    """THE OBSERVED SYMPTOM, end-to-end: `pre_pnr_summary.json` and
    `post_route_summary.json` were byte-identical on a real run because both
    gates swept the same project-wide file set.

    FAILS WITHOUT THE FIX: unscoped, both commands see 5 files, both return 1
    (on the later steps' artefacts) and both summaries are identical.
    """
    cmds = _flow_invocations("sta_report_check")
    rcs, docs = [], []
    for cmd in cmds:
        toks = cmd.split()[1:]          # drop the program name
        toks[0] = "."                   # the project positional
        cp = subprocess.run([sys.executable, str(_WRAPPER), *toks],
                            cwd=str(project), capture_output=True, text=True)
        target = project / toks[toks.index("--json") + 1]
        rcs.append(cp.returncode)
        docs.append(json.loads(target.read_text()))

    assert rcs == [0, 0], (
        f"a step's own report is MET but its gate returned {rcs}: "
        f"{[_rules(d) for d in docs]} — the gate is still reading another "
        f"step's artefacts")
    assert docs[0] != docs[1], (
        "step 10's and step 23's summaries are identical documents; they are "
        "still being reached over the same file set")
    for d in docs:
        # This fixture writes no `per_corner/`, so step 10's second scope is
        # absent and each gate resolves exactly its own declared report.
        assert d["summary"]["files_found"] == 1, d["summary"]
    assert docs[0]["summary"]["scoped_under"][0] == _STEP10_REPORT
    assert docs[1]["summary"]["scoped_under"] == [_STEP23_REPORT]


def test_step10_scope_is_not_wide_enough_to_reach_the_post_route_reports(
        project):
    """A directory scope over `phase3/stage3/sta` would look like a fix and
    change nothing: every later-step STA artefact lives in that same
    directory, post-repair report included.

    AMENDED. The rule was spelled `u.endswith(".rpt")` — a syntactic stand-in
    that also forbids a subdirectory holding NOTHING but the declaring step's
    own artefacts. Step 10 is named "Pre-layout STA (multi-corner)" and its
    corner reports live in `phase3/stage3/sta/per_corner/`; the syntactic rule
    made the step structurally unable to declare the evidence it is named
    after. What the rule protects is stated directly instead, and then RUN:
    no scope may resolve any other step's STA report.
    """
    banned_dirs = {"phase3/stage3/sta", "phase3/stage3", "phase3", "."}
    for cmd in _flow_invocations("sta_report_check"):
        for u in _unders(cmd):
            assert u.rstrip("/") not in banned_dirs, (
                f"{cmd!r}: --under {u!r} is the shared STA directory. It "
                f"holds step 10's, step 23's AND step 32's post-repair reports, "
                f"so this restores exactly the cross-step contamination the "
                f"scope removes.")

    # EXECUTED, not asserted from the string. The fixture carries step 23's,
    # step 32's (post-repair) and step 33's (aging) artefacts; step 10's scope
    # must reach none of them even with a genuine per_corner/ present.
    pc = project / "phase3/stage3/sta/per_corner"
    pc.mkdir(parents=True, exist_ok=True)
    for corner in ("SS", "FF"):
        (pc / f"sta_{corner}.rpt").write_text(
            _MET + f"corner {corner}\nSTA_BASIS: PRE_LAYOUT_ESTIMATE\n")

    cmd = [c for c in _flow_invocations("sta_report_check")
           if "pre_pnr_summary.json" in c][0]
    toks = cmd.split()[1:]
    toks[0] = "."
    cp = subprocess.run([sys.executable, str(_WRAPPER), *toks],
                        cwd=str(project), capture_output=True, text=True)
    doc = json.loads((project / toks[toks.index("--json") + 1]).read_text())
    assert doc["summary"]["files_found"] == 3, doc["summary"]
    blob = json.dumps(doc)
    for foreign in ("post_route_timing.rpt", "sta_mcorner_ocv.rpt",
                    "sta_mcorner_ocv_postrepair.rpt", "aging_sta.rpt"):
        assert foreign not in blob, (
            f"step 10's scope reached {foreign!r}: {blob[:600]}")
    assert cp.returncode == 0, doc


# ===========================================================================
# ANTI-GREEN-BUY — the scope must not silence the step's own evidence
# ===========================================================================
def test_a_violation_in_the_steps_own_report_still_fails_the_scoped_gate(
        project):
    """`--under` narrows what a gate can see, which makes it the ideal
    instrument for buying a green. It must not silence the report the step
    itself declares."""
    (project / _STEP23_REPORT).write_text(_VIOLATED)
    rc, doc = _run(project, "--under", _STEP23_REPORT, out="s23.json")
    assert rc == 1, doc
    assert "STA_REAL_VIOLATION_FOUND" in _rules(doc), _rules(doc)


def test_a_scope_that_does_not_exist_is_not_a_pass(tmp_path):
    """A run with no step-10 report must not pass step 10 on some other
    step's. Scoped, the honest answer is rc 1 + SCOPE_NOT_FOUND — which is
    what the 11 corpus roots without a `pre_pnr_timing.rpt` now report."""
    p = tmp_path / "proj"
    (p / "reports/phase3").mkdir(parents=True)
    (p / "reports/phase3/sta_spef_based.rpt").write_text(_MET)
    rc_unscoped, doc_unscoped = _run(p, out="u.json")
    assert rc_unscoped == 0 and doc_unscoped["summary"]["files_found"] == 1, (
        "precondition: today this project passes an STA gate on a report no "
        "step-10 gate should be reading")
    rc, doc = _run(p, "--under", _STEP10_REPORT, out="s.json")
    assert rc == 1, doc
    assert "SCOPE_NOT_FOUND" in _rules(doc)
    assert "STA_REPORT_EXISTS" in _rules(doc)


def test_the_step_mirror_does_not_cost_the_gate_its_declared_report(project):
    """`steps/<n>_*/` holds symlinks to the declared artefacts, so the mirror
    needs no second `--under`.

    THIS TEST USED TO ASSERT `files_found == 2`, reasoning that "the count
    proves it is actually being read, not silently dropped". Since the alias
    dedup the mirror and its target are ONE physical file, so 2 would now mean
    the gate is summing one report's violations twice — the number stopped
    being a witness for anything the moment it stopped being reachable. It was
    never much of one either: 2 only ever proved that two PATHS survived
    discovery, and said nothing about whether either one's bytes were read.

    The concern it encoded — the declared report is genuinely read, not
    silently dropped — is exactly what a dedup can break, so it is pinned
    directly instead, three ways that are together strictly stronger than the
    old number:

      1. exactly ONE entry survives — the alias is collapsed, not summed;
      2. the verdict with the mirror present is IDENTICAL to the verdict
         without it — the mirror neither adds a count nor takes the report
         away. This is the order-independent form of "which alias won": both
         aliases are the same bytes, so the only two outcomes that are not
         identical-to-canonical-only are the double count (2 files) and the
         eviction (0 files, `STA_REPORT_EXISTS`);
      3. the verdict still MOVES with the declared artefact's content while
         the mirror is present — the only real proof the surviving path is
         being read. Had the dedup let the mirror claim the key and then
         dropped it, the rule would be `STA_REPORT_EXISTS`, not
         `STA_REAL_VIOLATION_FOUND`.
    """
    rc_solo, doc_solo = _run(project, "--under", _STEP10_REPORT, out="solo.json")

    mirror = project / "steps/10_pre_layout_sta_multi_corner"
    mirror.mkdir(parents=True)
    (mirror / "pre_pnr_timing.rpt").symlink_to(project / _STEP10_REPORT)

    rc, doc = _run(project, "--under", _STEP10_REPORT, out="m.json")
    assert rc == 0, _rules(doc)
    assert doc["summary"]["files_found"] == 1, (
        f"the mirror and its target are one physical file; discovering both "
        f"sums every per-file quantity twice (got {doc['summary']})")
    assert doc["summary"] == doc_solo["summary"] and rc == rc_solo, (
        f"publishing the step mirror changed the gate's verdict: "
        f"{doc_solo['summary']} -> {doc['summary']}")

    (project / _STEP10_REPORT).write_text(_VIOLATED)
    rc_v, doc_v = _run(project, "--under", _STEP10_REPORT, out="mv.json")
    assert doc_v["summary"]["files_found"] == 1, doc_v["summary"]
    assert rc_v == 1 and "STA_REAL_VIOLATION_FOUND" in _rules(doc_v), (
        f"the declared report's own violation did not reach the gate with the "
        f"mirror present — the report is not being read: {_rules(doc_v)}")


def test_the_scope_is_matched_on_the_resolved_target_not_the_literal_path():
    """`_in_scope` resolves before comparing. Once aliases of one file
    collapse, the `steps/` mirror shape can no longer witness that: admitting
    the mirror and dropping it both leave exactly one entry carrying exactly
    the same bytes, so the two are indistinguishable in the verdict (measured
    — a literal-prefix `_in_scope` returns the identical document there).

    The shape where it IS observable is the one that motivated the resolve in
    the first place: the DECLARED artefact is itself a published symlink over
    the tool's raw output, whose own basename matches no discovery pattern. A
    literal-prefix comparison then puts every glob-matching path outside a
    scope naming the file they all are::

        _in_scope resolves     rc=0  files_found=1
        literal prefix         rc=1  files_found=0  [STA_REPORT_EXISTS]

    i.e. the step's own report, present and clean, read as absent.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "proj"
        (p / "phase3/stage3/sta").mkdir(parents=True)
        # the tool's raw stdout: matches none of the STA discovery patterns
        (p / "phase3/stage3/sta/opensta_pre_pnr.out").write_text(_MET)
        # the flow publishes the DECLARED artefact as a symlink over it …
        (p / _STEP10_REPORT).symlink_to("opensta_pre_pnr.out")
        # … and the step mirror publishes it a third time
        mirror = p / "steps/10_pre_layout_sta_multi_corner"
        mirror.mkdir(parents=True)
        (mirror / "pre_pnr_timing.rpt").symlink_to(p / _STEP10_REPORT)

        assert sorted(q.name for q in p.rglob("*timing*.rpt")) == [
            "pre_pnr_timing.rpt", "pre_pnr_timing.rpt"], (
            "fixture precondition: the raw output must not be glob-matched, "
            "so every candidate reaches the scope only by resolving")

        rc, doc = _run(p, "--under", _STEP10_REPORT, out="r.json")
        assert rc == 0, _rules(doc)
        assert doc["summary"]["files_found"] == 1, doc["summary"]
        assert "STA_REPORT_EXISTS" not in _rules(doc), _rules(doc)


# ===========================================================================
# DIRECTION-1 — behaviour that must NOT change (holds pre-fix too)
# ===========================================================================
def test_d1_unscoped_discovery_is_unchanged(project):
    """Every caller that states no scope keeps project-wide discovery, so the
    only behaviour this change moves is at the three sites it scopes."""
    rc, doc = _run(project, out="d1.json")
    assert rc == 1
    assert doc["summary"]["files_found"] == 5, doc["summary"]
    assert "scoped_under" not in doc["summary"]
    assert "STA_REAL_VIOLATION_FOUND" in _rules(doc)


def test_d1_the_flow_still_declares_a_real_mode_at_both_sites():
    import eda_report_audit  # noqa: WPS433
    for cmd in _flow_invocations("sta_report_check"):
        toks = cmd.split()
        assert toks[toks.index("--mode") + 1] in eda_report_audit.MODE_MAP, cmd


def test_d1_the_declared_json_targets_are_unchanged():
    """The scope must not move where the verdict is written — those paths are
    both steps' `required_outputs`."""
    targets = {cmd.split()[cmd.split().index("--json") + 1]
               for cmd in _flow_invocations("sta_report_check")}
    assert targets == {"reports/phase3/sta/pre_pnr_summary.json",
                       "reports/phase3/sta/post_route_summary.json"}
    assert '"reports/phase3/sta/post_route_summary.json"' in \
        _RUNNER_SRC.read_text(errors="replace")
