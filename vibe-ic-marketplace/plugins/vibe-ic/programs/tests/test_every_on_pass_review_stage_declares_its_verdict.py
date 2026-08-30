#!/usr/bin/env python3
"""Every stage that wires the on-pass review must say whether it blocks —
including the stages not written yet.

WHAT THIS IS NOT. It is not a second copy of vibe-ic#1858. That PR paid the
debt `flow_gate_enforcement_audit` named on sight —

    [FAIL] refusing to GROW the baseline `undeclared_known`
           (116 -> 116, 1 NEW: undeclared::stage_on_pass_review)

— by giving `stage_on_pass_review` an `ENFORCEMENT: advisory` line the audit
can read, and MEASURED on a clean checkout of a23fe31a8 (v1.13.7) that closed
all nine reds it caused. Those nine are green and nothing here repairs them.
The declaration is re-measured below only as the premise the rest of this file
rests on: a guard that assumed it would go quiet if it were ever removed.

THE HOLE #1858 LEAVES OPEN, AND WHY NO EXISTING CHECK CAN SEE IT.
`flow_gate_enforcement_audit` populates by gate PROGRAM. Every stage's
`on_pass_review:` block names THE SAME program, so a stage added tomorrow adds
no row to the audit's population, moves neither of its registers, and fires
nothing. MEASURED: stage 1 wired this at v1.12.87, stage 2 at v1.13.2, stage 3
at v1.13.4 and the analog stage at v1.13.8 — four clauses, one gate, and the
audit's gate count never moved.

That matters because the ONE thing a stage has to decide for itself is
`verdict:` — whether this review's rejection blocks. It is the flow's call by
construction (the program's own docstring refuses to add a fourth mapping of
what the flow already declares), and before this file a stage could simply omit
it: the review ran anyway, emitted `verdict_policy: null`, and printed
`verdict policy: None` as though that were an answer. That is vibe-ic#886's
silence — "nothing said is not a decision" — arriving through the one door #886
is structurally unable to watch. The phase-1, mixed-signal, stage-4 and stage-5
blocks are queued behind those four.

SO THE REQUIREMENT IS MADE STRUCTURAL, IN TWO PLACES THAT FAIL AT DIFFERENT
TIMES:

  * RUN TIME — `stage_on_pass_review` returns rc 2 NOT CHECKED for a stage
    whose block omits `verdict:` or states one it does not recognise.
  * COMMIT TIME — the population below is DISCOVERED from the flow, never
    listed. A hand-kept list would be one stage short on exactly the day a new
    stage landed.

AND THE TWO HALVES OF ONE DECLARATION MUST AGREE. The program says
`ENFORCEMENT: advisory` about itself; each stage says `verdict:`. A stage
claiming `blocking` while nothing spawns the program inline is asserting a
wiring that does not exist — the audit's own `contradiction` class, reached
through the flow rather than through the docstring. This is not a prohibition
on blocking: wire the program where its rc can stop a step, re-declare it, and
both halves move together. It is a prohibition on moving one of them alone.

EVERY ASSERTION IS ON A RETURNED VALUE, AN EXIT CODE OR EMITTED JSON — never on
a string being present in a source file. A test that grepped for
`ENFORCEMENT: advisory` would pass on a file where the audit cannot see it (the
declaration must OPEN a line and sit in the first `DECL_WINDOW_BYTES`
characters), which is the #886 defect wearing a test's clothing.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_AUDIT = _PROGRAMS / "flow_gate_enforcement_audit.py"
_PROG = _PROGRAMS / "stage_on_pass_review.py"

_GATE = "stage_on_pass_review"

#: Fixtures of verbatim published-cell inputs; provenance in
#: `fixtures/stage1_on_pass_review/PROVENANCE.json`. `_ACCEPT` is the CONTROL
#: arm for the refusals below — without it they would also pass against a
#: program that had started refusing everything.
_ACCEPT = _TESTS / "fixtures" / "stage1_on_pass_review" / "accept_spm"
_REJECT = _TESTS / "fixtures" / "stage1_on_pass_review" / "reject_caravel"


def _mod(name: str, path: Path):
    """A private copy, so a sibling test's `sys.modules` entry cannot decide
    which version of the program this file measures."""
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path[:] = saved


def _audit_mod():
    return _mod("_fgea_on_pass", _AUDIT)


def _review_mod():
    return _mod("_sopr_guard", _PROG)


def _flow_copy(tmp_path: Path, mutate) -> Path:
    """The canonical flow with EVERY `on_pass_review:` block mutated.

    A COPY, so nothing here can depend on — or damage — the shipped file, and
    `mutate` receives the parsed stage so a test states the change it wants
    rather than a text substitution that could silently match nothing.
    """
    doc = copy.deepcopy(yaml.safe_load(_FLOW.read_text(encoding="utf-8")))
    for st in doc["stages"]:
        if isinstance(st, dict) and isinstance(st.get("on_pass_review"), dict):
            mutate(st)
    out = tmp_path / "flow.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return out


def _stage_ids_from_the_flow():
    """The stage ids carrying an `on_pass_review:` block, read from the YAML
    DIRECTLY and not through the program.

    Parametrisation happens at COLLECTION. Reading the population through the
    program under test would turn "the program lost its reader" into a
    collection ERROR — rc 2, "the question could not be put" — for every case
    in this file at once, which is not a result and reads as zero failures to
    anything scraping the run. Read from the flow, the cases still collect and
    each one FAILS on its own terms.
    """
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    return [str(st.get("id")) for st in (doc.get("stages") or [])
            if isinstance(st, dict)
            and isinstance(st.get("on_pass_review"), dict)]


def _stage_rows():
    return _review_mod().stages_declaring_review(_FLOW)


def test_the_program_exposes_the_flow_wide_reader():
    """The premise of the two parametrised guards below: the program is what
    decides which `verdict:` values count, so the guards ask IT rather than
    re-implementing the rule beside it."""
    mod = _review_mod()
    assert hasattr(mod, "stages_declaring_review"), (
        "stage_on_pass_review lost `stages_declaring_review`; the per-stage "
        "guards below can no longer ask the program what it accepts")
    assert set(mod.VERDICT_POLICIES) == {"advisory", "blocking"}
    assert {r["stage"] for r in mod.stages_declaring_review(_FLOW)} == \
        set(_stage_ids_from_the_flow())


# ═════════════════════════ the premise: #1858's declaration, re-measured here

def test_the_gate_still_declares_an_intent_the_audit_can_read():
    """RETURNED VALUE, not a grep. `declared_intent` is the exact function the
    audit uses to decide DECLARED vs UNDECLARED, so this cannot pass on a
    declaration the audit would not see — the wrong line prefix, or one pushed
    past `DECL_WINDOW_BYTES` by a paragraph added above it.

    vibe-ic#1858 landed this. It is re-measured because everything below is
    written against `advisory` being what the program says about itself."""
    mod = _audit_mod()
    assert mod.declared_intent(_PROGRAMS, _GATE) == "advisory", (
        f"{_GATE} must state where its verdict is consumed; the audit reads "
        f"`ENFORCEMENT:` opening a line in the first "
        f"{mod.DECL_WINDOW_BYTES} characters, or a lone `\"verdict_mode\"` "
        f"literal")


def test_the_program_constant_and_the_docstring_do_not_disagree():
    """One fact, one spelling. `DECLARED_ENFORCEMENT` is what the runtime
    refusal compares each stage against; the docstring is what the audit reads.
    A fact written in two places is a fact that will disagree, so the two are
    measured against each other rather than both against a literal typed
    here."""
    assert _review_mod().DECLARED_ENFORCEMENT == \
        _audit_mod().declared_intent(_PROGRAMS, _GATE)


def test_the_advisory_declaration_is_still_true_of_the_tree():
    """`advisory` is a CLAIM ABOUT THE TREE — "no runner spawns this inline" —
    and a declaration nobody re-measures is how five gates sat mis-declared
    until #1035. Measured through the audit's own wiring verdict, which is the
    thing the word describes."""
    mod = _audit_mod()
    rows = {r["gate"]: r for r in mod.audit(_FLOW, _PROGRAMS)["gates"]}
    assert rows[_GATE]["enforcement"] == "AUDIT_ONLY", (
        f"{_GATE} is now spawned inline somewhere; `ENFORCEMENT: advisory` "
        f"has become false and must be re-declared `blocking`")


def test_the_clause_is_in_the_slot_its_own_declared_verdict_names():
    """THE SLOT MUST AGREE WITH `verdict:`, and this test used to assert the
    opposite because the clause was never dispatched.

    It read `assert slots == ["program_exit_zero"]`, on the reasoning that an
    rc=1 "must stay in the slot that says so". That was free while the clause
    sat under `stages:` — a section `flow_compliance_check` never reads — so
    the slot name cost nothing and blocked nobody. Dispatched, it is not free:
    `program_exit_zero` FAILS the step on rc=1, which would turn every
    `verdict: advisory` block into a blocking one (#1253: wiring a gate that
    has never run turns "unverified" into "blocking", a different change), and
    would additionally read the program's rc=2 NOT CHECKED as VACUOUS_PASS.

    So the invariant is not a slot NAME, it is AGREEMENT: whatever each block
    declares, the clause must be wired through the slot that means it. Wiring
    it to block is then one edit to `verdict:` and one to the slot, together.
    Read from `clauses_in_flow` — the audit's own structural walk — so this is
    about what a dispatcher would see, not about the text of a YAML line."""
    mod = _audit_mod()
    want = {"advisory": "advisory_program_exit_zero",
            "blocking": "program_exit_zero"}
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    declared = {s["id"]: s["on_pass_review"].get("verdict")
                for s in doc["stages"]
                if isinstance(s.get("on_pass_review"), dict)
                and s["on_pass_review"].get("enabled", True) is not False}
    assert declared, "no enabled on_pass_review block to check"
    by_stage = {}
    for c in mod.clauses_in_flow(_FLOW):
        if c["gate"] != _GATE:
            continue
        toks = str(c["command"]).split()
        sid = toks[toks.index("--stage") + 1] if "--stage" in toks else None
        by_stage[sid] = c["slot"]
    for sid, verdict in declared.items():
        assert sid in by_stage, (
            f"{sid} declares `verdict: {verdict}` and no clause dispatches it")
        assert by_stage[sid] == want[verdict], (
            f"{sid} declares `verdict: {verdict}` and is wired through "
            f"{by_stage[sid]!r}, not {want[verdict]!r}. The slot is what "
            f"decides whether the verdict stops the step.")


# ═══════════════════ THE GAP: every stage that wires the review declares a
# ═══════════════════ verdict, and the population is discovered, never listed

def _row_for(mod, stage):
    """This stage's row, from the program's reader — and a real FAILURE, never
    a `StopIteration`, when the program stopped reporting the stage at all."""
    rows = [r for r in mod.stages_declaring_review(_FLOW)
            if r["stage"] == stage]
    assert rows, (
        f"the flow declares an `on_pass_review:` block on stage {stage!r} and "
        f"{_GATE}'s own reader does not report it")
    return rows[0]


def test_the_flow_still_declares_at_least_the_four_known_stages():
    """A parametrisation over an EMPTY population passes while measuring
    nothing. This is the floor that makes the per-stage guards below real, and
    it names the four that exist so a silent DELETION is a failure too."""
    ids = {r["stage"] for r in _stage_rows()}
    assert ids >= {"stage1", "stage2", "stage3", "stage_analog"}, (
        f"stage1 (v1.12.87), stage2 (v1.13.2), stage3 (v1.13.4) and "
        f"stage_analog (v1.13.8) each wired an `on_pass_review:` block; the "
        f"flow now declares one on {sorted(ids)}")


@pytest.mark.parametrize("stage", _stage_ids_from_the_flow())
def test_the_stage_declares_a_verdict_policy(stage):
    """THE GUARD THE NEXT STAGE TRIPS. Whether an on-pass rejection blocks is
    the flow's decision; a block that omits `verdict:` has not made it, and no
    existing check can notice — the enforcement audit populates by gate
    program, and every stage's clause names the same one."""
    mod = _review_mod()
    row = _row_for(mod, stage)
    assert row["declared_verdict"] is not None, (
        f"stage {stage!r} declares an `on_pass_review:` block whose "
        f"`verdict:` is {row['verdict']!r}, which is not one of "
        f"{list(mod.VERDICT_POLICIES)}. State whether this review's rejection "
        f"blocks; the review does not pick one on the flow's behalf.")


@pytest.mark.parametrize("stage", _stage_ids_from_the_flow())
def test_the_stage_verdict_agrees_with_the_programs_own_declaration(stage):
    """The two halves of one declaration. A stage claiming `blocking` while the
    program declares `advisory` and nothing spawns it inline asserts a wiring
    that does not exist — the audit's `contradiction` class, arriving through
    the flow instead of through the docstring.

    This is what makes "flip it to blocking" cost something. It is not a
    prohibition: wire the program where its rc can stop a step, re-declare it
    `blocking`, and both halves move together."""
    mod = _review_mod()
    row = _row_for(mod, stage)
    assert row["declared_verdict"] == mod.DECLARED_ENFORCEMENT, (
        f"stage {stage!r} declares `verdict: {row['declared_verdict']}` while "
        f"{_GATE} declares `ENFORCEMENT: {mod.DECLARED_ENFORCEMENT}` and no "
        f"runner spawns it inline")


# ═══════════════════════════════ the runtime refusal, on EXIT CODES, and its
# ═══════════════════════════════ control — BIDIRECTIONAL, or it proves nothing

def test_a_stage_that_omits_its_verdict_is_not_checked(tmp_path):
    """rc 2, from the real program, on a flow copy with `verdict:` deleted."""
    flow = _flow_copy(tmp_path, lambda st: st["on_pass_review"].pop("verdict"))
    out = tmp_path / "rec.json"
    cp = _pr.run([sys.executable, str(_PROG), str(_ACCEPT),
                  "--stage", "stage1", "--stage-verdict", "PASS",
                  "--flow-def", str(flow), "--json", str(out)],
                 capture_output=True, text=True)
    assert cp.returncode == 2, (
        f"rc={cp.returncode} — a stage that never said whether this review "
        f"blocks was reviewed anyway\n{cp.stdout[-2000:]}")
    rec = json.loads(out.read_text())
    assert rec["verdict"] == "NOT_CHECKED"
    assert "verdict" in rec["why"]


def test_a_stage_that_states_an_unrecognised_verdict_is_not_checked(tmp_path):
    """Said something; said nothing usable. The same fact as the omission —
    treating it as a near-miss worth guessing at is how a policy nobody chose
    becomes the default."""
    flow = _flow_copy(
        tmp_path,
        lambda st: st["on_pass_review"].update(verdict="informational"))
    cp = _pr.run([sys.executable, str(_PROG), str(_ACCEPT),
                  "--stage", "stage1", "--stage-verdict", "PASS",
                  "--flow-def", str(flow)],
                 capture_output=True, text=True)
    assert cp.returncode == 2, f"rc={cp.returncode}\n{cp.stdout[-2000:]}"
    assert "informational" in cp.stdout


def test_a_stage_claiming_blocking_while_the_program_says_advisory_refuses(
        tmp_path):
    """The disagreement arm. `blocking` is a legitimate answer — but only with
    an inline wiring and a re-declaration, and neither exists on this tree, so
    the review refuses rather than running under a policy the program
    contradicts."""
    flow = _flow_copy(
        tmp_path, lambda st: st["on_pass_review"].update(verdict="blocking"))
    cp = _pr.run([sys.executable, str(_PROG), str(_ACCEPT),
                  "--stage", "stage1", "--stage-verdict", "PASS",
                  "--flow-def", str(flow)],
                 capture_output=True, text=True)
    assert cp.returncode == 2, f"rc={cp.returncode}\n{cp.stdout[-2000:]}"
    assert "ENFORCEMENT: advisory" in cp.stdout


def test_the_control_the_shipped_declaration_still_reaches_a_verdict():
    """THE CONTROL, and the reason the three refusals above mean anything: the
    SAME fixture and the SAME stage, read through the SHIPPED flow, reach rc 0.
    A program that had started refusing every input would pass all three arms
    and fail this one."""
    cp = _pr.run([sys.executable, str(_PROG), str(_ACCEPT),
                  "--stage", "stage1", "--stage-verdict", "PASS",
                  "--flow-def", str(_FLOW)],
                 capture_output=True, text=True)
    assert cp.returncode == 0, f"rc={cp.returncode}\n{cp.stdout[-2000:]}"
    assert "ACCEPT" in cp.stdout


def test_a_rejection_still_writes_the_test_that_blocks(tmp_path):
    """`advisory` names the WIRING; it must not have softened the verdict.

    It also measures the claim the declaration rests on — that the blocker is
    the emitted test, one level down from the gate. rc 1 AND a test file on
    disk IN THE REVIEWED RUN'S OWN TREE — which is what this docstring always
    said and what the invocation did not do: it reviewed the shipped fixture
    and redirected the emit to `tmp_path`, so the proof landed outside the run
    it was proving something about. The engine refuses that now, so the run
    tree is a per-test COPY and the emit goes inside it — the same shape
    `test_stage_phase1_on_pass_review.tree()` has always used, and the reason
    the shipped fixture is still never written to."""
    run_dir = tmp_path / "run"
    shutil.copytree(_REJECT, run_dir)
    emit = run_dir / "reports" / "emitted"
    cp = _pr.run([sys.executable, str(_PROG), str(run_dir),
                  "--stage", "stage1", "--stage-verdict", "PASS",
                  "--flow-def", str(_FLOW), "--emit-test", str(emit)],
                 capture_output=True, text=True)
    assert cp.returncode == 1, (
        f"rc={cp.returncode} — the REJECT fixture stopped rejecting; "
        f"`ENFORCEMENT: advisory` describes the wiring and must not soften "
        f"the verdict\n{cp.stdout[-2000:]}")
    assert sorted(p.name for p in emit.glob("test_*.py")), (
        "a rejection emitted no test, so nothing blocks at all")


# ─────────────────────────────────────────────────────────────── the controls
#
# Without these, the declaration assertions above would also pass on an audit
# that had gone blind to this class entirely.

_SILENT = '''"""A gate that says nothing about where its verdict is enforced."""
'''
_DECLARING = '''"""A gate that says so.

ENFORCEMENT: advisory
"""
'''
_FLOW_DOC = textwrap.dedent("""\
    steps:
      - id: 1
        name: "synthetic"
        gate:
          all_of:
            - program_exit_zero: "{gate} . --json out.json"
    """)


def _synthetic(tmp_path: Path, name: str, body: str):
    progs = tmp_path / "programs"
    progs.mkdir(exist_ok=True)
    (progs / f"{name}.py").write_text(body)
    flow = tmp_path / f"{name}.yaml"
    flow.write_text(_FLOW_DOC.format(gate=name))
    return flow, progs


def test_the_control_an_undeclared_audit_only_gate_is_still_reported(tmp_path):
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path, "synthetic_silent_check", _SILENT)
    rep = mod.audit(flow, progs)
    assert [u["gate"] for u in rep["undeclared_audit_only"]] == [
        "synthetic_silent_check"]


def test_the_control_a_declaring_audit_only_gate_is_not_reported(tmp_path):
    mod = _audit_mod()
    flow, progs = _synthetic(tmp_path, "synthetic_declaring_check", _DECLARING)
    rep = mod.audit(flow, progs)
    assert rep["undeclared_audit_only"] == []
    assert rep["contradictions"] == []
    assert rep["gates"][0]["declared"] == "advisory"


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
