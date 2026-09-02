#!/usr/bin/env python3
"""The gate that EXECUTES the flow's declared on-pass commands.

WHAT THIS FILE HAS TO PROVE, AND WHY A SUBSTRING TEST WOULD NOT DO IT
=====================================================================
The subject exists because six reachability mutations of a declared clause left
`on_pass_review_answerable_check` at rc=0 PASS **and** the entire 14-file
on-pass pytest suite at 304 passed, while `stage_on_pass_review` returned rc=2
NOT CHECKED forever. Those mutations are the population this file measures
against, one test each, planted in a COPY of the shipped flow and never in the
tree. A test that asserted the gate's docstring mentions them would be the same
substring test that let them through.

THE CONTROL IS THE SHIPPED FLOW, and it is asserted first: the gate must be
green on the document that lands. A gate that refused everything would satisfy
every mutation test below and fail that one, which is why it is written first
and why the subject carries the same control internally as P7.
"""
from __future__ import annotations

import collections
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
PROGRAM = PROGRAMS / "on_pass_review_declared_command_runs_check.py"

#: The clause every mutation below edits, verbatim from the shipped flow.
#: Asserted present by `test_the_clause_this_file_mutates_is_in_the_flow`, so a
#: rename upstream reddens HERE rather than turning every mutation into a
#: silent no-op that passes.
#: The stage-3 clause, verbatim from the shipped flow. Its `--compliance` names
#: `reports/phase3/gates/stage3_compliance.json` — the report the clause BEFORE
#: it in the same `all_of` writes — and not `reports/flow_compliance.json`,
#: which the flow's `final_gate:` declares and NOTHING EXECUTES. Pinned as a
#: literal so a silent repoint of the verdict source shows up here as a red
#: `test_the_clause_this_file_mutates_is_in_the_flow` rather than as a mutation
#: battery quietly firing at a clause that no longer exists.
CLAUSE = ("stage_on_pass_review . --stage stage3 --json "
          "reports/phase3/gates/stage3_on_pass_review.json "
          "--compliance reports/phase3/gates/stage3_compliance.json")


def _run(flow: Path):
    r = subprocess.run([sys.executable, str(PROGRAM), ".", "--flow", str(flow)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def _text_mutant(tmp_path: Path, new_clause: str, name="flow.yaml") -> Path:
    t = FLOW.read_text(encoding="utf-8")
    assert CLAUSE in t
    p = tmp_path / name
    p.write_text(t.replace(CLAUSE, new_clause), encoding="utf-8")
    return p


def _doc_mutant(tmp_path: Path, mutate, name="flow.yaml") -> Path:
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    mutate(doc)
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                 encoding="utf-8")
    return p


def _stage3_block(doc):
    return next(s for s in doc["stages"]
                if s["id"] == "stage3")["on_pass_review"]


def _slot_command(val):
    """The command a gate slot carries, in BOTH shapes the engine runs.

    A slot holds either a bare command string or a mapping with `command:`.
    `d155935a7` (v1.13.85, 2026-08-31, "84 advisory clauses could not say why
    they were advisory") gave the stage-3 clause an `advisory_reason:`, which
    turned `advisory_program_exit_zero: "<command>"` into
    `advisory_program_exit_zero: {command:, advisory_reason:}`.

    THE SUBJECT ALREADY READ BOTH — `step_clauses` is `val.get("command") if
    isinstance(val, dict) else val`, and that commit changed only the yaml.
    This helper read the string shape ONLY, so from v1.13.85 it raised "no
    clause under `steps:` dispatches stage3" and the two mutation tests below
    were RED WITHOUT EVER PLANTING THEIR MUTANT: for two days the gate's P1
    and P2 clauses had no live test, while the failure looked like the gate.

    Read from the same predicate the subject uses, and pinned to it by
    `test_this_files_helper_sees_every_clause_the_subject_sees` so the next
    shape change reddens as a shape change and not as a phantom gate defect.
    """
    return val.get("command") if isinstance(val, dict) else val


def _dispatched_clause(doc, stage):
    """The mutable step clause dispatching `stage`'s review, and its slot key.

    Returns the `all_of` element (a mapping) and the slot key inside it, so a
    caller can pop the clause, move it to another slot, or rewrite it.
    """
    for st in doc["steps"]:
        for sub in ((st.get("gate") or {}).get("all_of") or []):
            if isinstance(sub, dict):
                for k, v in sub.items():
                    cmd = _slot_command(v)
                    if (isinstance(cmd, str)
                            and cmd.startswith("stage_on_pass_review")
                            and f"--stage {stage} " in cmd):
                        return sub, k
    raise AssertionError(
        f"no clause under `steps:` dispatches {stage}. Either the dispatch "
        f"was removed — which is the defect this file's subject exists to "
        f"refuse, and `test_the_shipped_flow_is_green` would be red too — or "
        f"the slot shape changed again and `_slot_command` no longer reads "
        f"it. Those are opposite repairs; check the control first.")


def _stage3_clause(doc):
    """The mutable step clause dispatching stage3's review, and its slot key."""
    return _dispatched_clause(doc, "stage3")


# ── the premise this file's mutations rest on ───────────────────────────────
def test_this_files_helper_sees_every_clause_the_subject_sees():
    """THE PREMISE, PINNED TO THE SUBJECT'S OWN READER.

    Every mutation below starts by LOCATING the clause it edits. A locator
    that finds nothing does not weaken a test — it deletes it, and leaves a
    red that reads as "the gate is broken" when the truth is "the mutant was
    never planted". MEASURED: from `d155935a7` (v1.13.85, 2026-08-31) to
    v1.16.28 this file's locator was string-only while the flow had moved to
    `{command:, advisory_reason:}`, and `test_an_undispatched_clause_is_refused`
    and `test_a_clause_wired_through_the_blocking_slot_is_refused` were red for
    two days without ever exercising P1 or P2.

    So the locator is not asserted against a shape typed here. It is asserted
    against `on_pass_review_declared_command_runs_check.step_clauses` — the
    subject's own structural walk of what `flow_compliance_check._evaluate_gate`
    executes. The next shape change reddens THIS test, by name, saying which
    stage went unreachable and in which direction.
    """
    sys.path.insert(0, str(PROGRAMS))
    import on_pass_review_declared_command_runs_check as SUBJECT

    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    clauses = SUBJECT.step_clauses(doc)
    assert clauses, ("the subject finds no dispatched on-pass clause at all; "
                     "the control test below would be red too")
    # EXACTLY ONCE PER STAGE, counted before the dict is built. Keying by
    # stage first would collapse a double dispatch into one entry and the
    # locator below would then agree with a population it never saw whole.
    counts = collections.Counter(c["stage"] for c in clauses)
    doubled = sorted(k for k, v in counts.items() if v != 1)
    assert not doubled, (
        f"these stage(s) are dispatched more than once under `steps:`: "
        f"{ {k: counts[k] for k in doubled} }. Two clauses for one stage means "
        "the mutation battery below edits one of them and the other keeps the "
        "flow green.")
    seen = {c["stage"]: (c["step"], c["slot"]) for c in clauses}
    for stage, (step, slot) in sorted(seen.items()):
        sub, key = _dispatched_clause(doc, stage)
        assert key == slot, (
            f"this file's locator puts {stage}'s clause in slot {key!r} and "
            f"the subject reads it from {slot!r}")
        assert _slot_command(sub[key]).startswith("stage_on_pass_review"), (
            f"{stage}: the located slot does not hold the declared command")


# ── the control, first ───────────────────────────────────────────────────────
def test_the_shipped_flow_is_green():
    """A gate that cannot pass the document that lands is stuck, not strict."""
    rc, out = _run(FLOW)
    assert rc == 0, f"the shipped flow must satisfy this gate:\n{out}"
    assert "[PASS]" in out


def test_the_clause_this_file_mutates_is_in_the_flow():
    assert CLAUSE in FLOW.read_text(encoding="utf-8"), (
        "the clause every mutation below edits is no longer in the shipped "
        "flow verbatim. Re-derive it; do NOT loosen the match — a mutation "
        "that edits nothing makes every test in this file pass for free.")


def test_it_reports_which_stage_and_which_tree_it_executed():
    """The evidence has to name its subject: a PASS that does not say what it
    ran is indistinguishable from a PASS that ran nothing."""
    rc, out = _run(FLOW)
    assert rc == 0, out
    for stage in ("stage_phase1", "stage1", "stage2", "stage_analog",
                  "stage3", "stage4"):
        assert stage in out, (stage, out)
    assert "reject_sgmii" in out and "accept_subservient" in out, out


# ── the six mutants both existing nets were blind to ─────────────────────────
@pytest.mark.parametrize("new_clause,expected", [
    (CLAUSE.replace("--stage stage3", "--stage stage2"), "P1 NOT DISPATCHED"),
    (CLAUSE.replace("--stage stage3", "--stage stage99"), "P1 NOT DISPATCHED"),
    (CLAUSE.replace("--stage stage3", "--stage stage5_manufacturing"),
     "P1 NOT DISPATCHED"),
    (CLAUSE.replace("stage_on_pass_review .", "stage_on_pass_review ./nope"),
     "CANNOT REFUSE"),
    (CLAUSE.replace("--json", "--emit-test /proc/nope/x --json"),
     "CANNOT REFUSE"),
    (CLAUSE.replace("--stage stage3", "--flow-def /dev/null --stage stage3"),
     "CANNOT REFUSE"),
])
def test_a_reachability_mutant_is_refused(tmp_path, new_clause, expected):
    """Each of these keeps `--compliance <the report final_gate writes>`, so
    each satisfies `on_pass_review_answerable_check` P1 and P2 — MEASURED at
    rc=0 PASS on all six — and each leaves the gate unable to answer."""
    assert new_clause != CLAUSE, "this parametrisation mutates nothing"
    rc, out = _run(_text_mutant(tmp_path, new_clause))
    assert rc == 1, f"the mutant must be REFUSED, got rc={rc}:\n{out}"
    assert expected in out, out
    assert "stage3" in out, "the finding must NAME the offending stage"


def test_the_flowdef_mutant_is_caught_because_the_injected_one_is_PREPENDED():
    """`--flow-def` is supplied to the child BEFORE the declared argv, never
    after, and this is the test that keeps it that way. argparse takes the
    LAST occurrence: appended, the gate's own `--flow-def` would OVERRIDE a
    smuggled one and the mutant would go green — the gate quietly repairing the
    defect it exists to find."""
    src = PROGRAM.read_text(encoding="utf-8")
    assert '"--flow-def", str(flow_path)] + argv[1:]' in src, (
        "the injected --flow-def is no longer prepended to the declared argv")


# ── the declaration checks ───────────────────────────────────────────────────
def test_an_undispatched_clause_is_refused(tmp_path):
    def mutate(doc):
        sub, key = _stage3_clause(doc)
        sub.pop(key)
    rc, out = _run(_doc_mutant(tmp_path, mutate))
    assert rc == 1, out
    assert "P1 NOT DISPATCHED" in out and "stage3" in out, out


def test_a_clause_wired_through_the_blocking_slot_is_refused(tmp_path):
    """`verdict: advisory` wired through `program_exit_zero` would make a
    rejection FAIL the step — turning "unverified" into "blocking"."""
    def mutate(doc):
        sub, key = _stage3_clause(doc)
        sub["program_exit_zero"] = sub.pop(key)
    rc, out = _run(_doc_mutant(tmp_path, mutate))
    assert rc == 1, out
    assert "P2 WRONG SLOT" in out, out


def test_a_lying_back_pointer_is_refused(tmp_path):
    def mutate(doc):
        _stage3_block(doc)["dispatched_by"] = "999"
    rc, out = _run(_doc_mutant(tmp_path, mutate))
    assert rc == 1, out
    assert "P3 BACK-POINTER IS WRONG" in out, out


def test_fires_on_is_read_here_and_therefore_means_something(tmp_path):
    """MEASURED on v1.13.54: set to "never", the review went on rejecting
    unchanged — nothing read the field. A field the engine does not read is
    worse than an absent one, because the flow author believes it."""
    def mutate(doc):
        _stage3_block(doc)["fires_on"] = "never"
    rc, out = _run(_doc_mutant(tmp_path, mutate))
    assert rc == 1, out
    assert "P4 fires_on IS NOT stage_pass" in out, out


def test_an_emit_dir_outside_the_run_is_refused(tmp_path):
    """MEASURED on v1.13.54: pointed at an absolute path, the review still
    returned rc=1 REJECT and wrote its regression outside the run tree, with an
    absolute path in the record's `test:`. A rejection whose evidence leaves
    the run is an unproven rejection wearing a proof."""
    def mutate(doc):
        _stage3_block(doc)["emit_test_dir"] = "/tmp/somewhere_else"
    rc, out = _run(_doc_mutant(tmp_path, mutate))
    assert rc == 1, out
    assert "P5 emit_test_dir ESCAPES THE RUN" in out, out


# ── nothing to check is a FAIL, never a pass ─────────────────────────────────
def test_a_flow_with_no_enabled_review_is_refused(tmp_path):
    def mutate(doc):
        for s in doc["stages"]:
            if isinstance(s.get("on_pass_review"), dict):
                s["on_pass_review"]["enabled"] = False
    rc, out = _run(_doc_mutant(tmp_path, mutate))
    assert rc == 1, f"an empty population must FAIL, got rc={rc}:\n{out}"
    assert "NOTHING TO CHECK" in out, out


def test_an_unreadable_flow_is_a_fail_and_never_a_pass(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("stages: [oh no: : :\n", encoding="utf-8")
    rc, out = _run(bad)
    assert rc == 1, out
    assert "[PASS]" not in out


def test_a_missing_flow_is_a_fail_and_never_a_pass(tmp_path):
    rc, out = _run(tmp_path / "nope.yaml")
    assert rc == 1
    assert "[PASS]" not in out


# ── the repair direction ─────────────────────────────────────────────────────
def test_the_same_flow_goes_green_once_the_mutant_is_removed(tmp_path):
    """Both arms on one tree: red planted, green restored. A gate that only
    ever refused would pass every test above and fail this one."""
    broken = _text_mutant(
        tmp_path, CLAUSE.replace("--stage stage3", "--stage stage99"),
        "broken.yaml")
    assert _run(broken)[0] == 1
    repaired = tmp_path / "repaired.yaml"
    repaired.write_text(FLOW.read_text(encoding="utf-8"), encoding="utf-8")
    rc, out = _run(repaired)
    assert rc == 0, f"restoring the clause must PASS, got rc={rc}:\n{out}"
