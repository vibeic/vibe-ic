"""vibe-ic#693 — the repo-process family: what was really unwired, and what
the audits that exist to notice could not see.

#693 measured 130 programs referenced from no executable location and named 29
of them as gates. Four of the 29 are the repo-process family. Measured against
origin/main 1f3d8d067 with the repo's OWN wiring oracle
(`checker_execution_wiring_audit.runners`):

    landing_worktree_is_clean_check   TOOLS, TEST   <- FALSE POSITIVE
    benchmark_triage_absorption_audit SKILL, TEST
    organic_issue_body_lint           SKILL, TEST
    gitignore_scratch_guard           TEST only     <- the real orphan

`landing_worktree_is_clean_check` is invoked TWICE from
`tools/gatekeeper-land.sh`. #693's location set enumerates `tools/ci/` and not
`tools/`, which is why it was listed. The other three are correctly classified
by #693's own definition, which addresses the SKILL case explicitly.

This file locks the four facts that make that record true, so the classification
cannot silently drift back.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))

import checker_execution_wiring_audit as W  # noqa: E402
import gate_host_independence_check as H  # noqa: E402


def _repo_root() -> Path:
    cp = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                        capture_output=True, text=True,
                        cwd=str(Path(__file__).resolve().parent))
    if cp.returncode != 0:
        pytest.skip("not in a git repo")
    return Path(cp.stdout.strip())


# ── 1. the population glob that could not contain its own finding ──────────
def test_the_checker_population_covers_checker_shaped_names():
    """`gitignore_scratch_guard.py` was a wired-to-nothing gate that this audit
    reported PASS over, because `_guard.py` is neither `_check.py` nor
    `_audit.py`. A denominator that excludes the finding by naming alone is the
    defect the audit exists to find, one level up."""
    pop = set(W.checker_population(_PROGRAMS))
    assert "gitignore_scratch_guard.py" in pop
    assert "organic_issue_body_lint.py" in pop
    assert "benchmark_triage_absorption_audit.py" in pop
    # AND THE WIDENING STAYED CHECKER-SHAPED. Asserted against the NAME GLOB,
    # which is the half this clause is about, and not against the population as
    # a whole — the two are different questions and reading one for the other
    # made this assertion wrong on 2026-08-20.
    #
    # `checker_population` is `glob(_CHECKER_SUFFIXES)` UNION the programs the
    # flow DECLARES as gate clauses, and its own docstring states the rule the
    # union exists for: "A gate is in this population because the flow runs it,
    # not because somebody named it `*_check.py`." Step 15.5ic and step 37.5ic,
    # declared at 0a7699737, put `pad_assignment_gen` and `tapeout_docs_gen`
    # into `program_exit_zero:` clauses. Both are therefore programs the flow
    # runs as gates, both must be wired, and both belong in this denominator —
    # arriving by DECLARATION, which is the union's whole purpose, and not by
    # name. MEASURED here: each is `in glob=False, in flow-declared=True`.
    #
    # The blanket form of this assertion said the opposite and would have to be
    # satisfied by narrowing the flow union — that is, by dropping two real gate
    # programs out of the wiring audit's denominator to protect a sentence about
    # filenames. So the predicate is corrected to the population it was always
    # arguing about, and it can still go red: adding `*_gen.py` or `*_synth.py`
    # to `_CHECKER_SUFFIXES` fails the first assertion, and a generator that is
    # neither name-shaped nor flow-declared fails the second.
    by_name = {q.name for suf in W._CHECKER_SUFFIXES for q in _PROGRAMS.glob(suf)}
    assert not [p for p in by_name if p.endswith(("_synth.py", "_gen.py"))], (
        "the checker NAME GLOB now matches generators; the widening was "
        "supposed to stay checker-shaped")
    flow_declared = {n for n in W.flow_declared_gate_programs(
        _PLUGIN / "flow" / "phase1_phase2_phase3.yaml")
        if (_PROGRAMS / n).is_file()}
    strays = [p for p in pop if p.endswith(("_synth.py", "_gen.py"))
              and p not in flow_declared]
    assert not strays, (
        f"generator(s) in the checker population that the flow does not "
        f"declare as a gate: {strays}")


def test_the_orphan_now_has_a_real_runner_and_the_false_positive_always_had_one():
    root = _repo_root()
    hay = W._tokenise(W._haystacks(_PLUGIN, root))

    def runners(name):
        return W.runners(name[:-3], hay, str(_PROGRAMS / name))

    assert "TOOLS" in runners("landing_worktree_is_clean_check.py"), \
        "#693 listed this as unwired; it is invoked from tools/gatekeeper-land.sh"
    r = runners("gitignore_scratch_guard.py")
    assert r - {"TEST"}, "the one real orphan is still wired to nothing"
    assert "TOOLS" in r


# ── 2. the SKILL-only disclosure register ──────────────────────────────────
def test_skill_only_register_is_loadable_and_describes_skill_only_checkers():
    """`_UNROUTED_INVENTORY` is an exact-equality ratchet over unrouted SKIP
    PATHS and `checker_execution_wiring_baseline.json` FAILs on any entry that
    has a runner, so neither can hold a checker that is reachable only from a
    skill document. This register can, and every entry must still BE one."""
    root = _repo_root()
    reasons = W.skill_only_register(_PROGRAMS / W._SKILL_ONLY_NAME)
    assert reasons, "the register must not be empty while entries are claimed"
    rep = W.audit(_PLUGIN, root)
    skill_only = set(rep["skill_only"])
    for name, why in reasons.items():
        assert (_PROGRAMS / name).is_file(), f"{name} does not exist"
        assert name in skill_only, (
            f"{name} is recorded as SKILL-only but its runners are not "
            f"SKILL-only any more — the register is describing a state that "
            f"no longer exists")
        assert len(why) >= 200, (
            f"{name}: a register entry is a DISCLOSURE, not a bare listing — "
            f"it must say what the checker asserts, what was measured, and "
            f"what would make it wireable")


def test_the_two_inventoried_gates_are_named_with_their_measured_reason():
    reasons = W.skill_only_register(_PROGRAMS / W._SKILL_ONLY_NAME)
    assert "organic_issue_body_lint.py" in reasons
    assert "benchmark_triage_absorption_audit.py" in reasons
    # the numbers that decide the outcome have to be IN the reason, not in a
    # PR body that nobody reads again
    assert "59" in reasons["organic_issue_body_lint.py"]
    assert "55 of 60" in reasons["organic_issue_body_lint.py"]
    assert "156" in reasons["benchmark_triage_absorption_audit.py"]


# ── 3. a written exclusion that excludes nothing ───────────────────────────
def test_an_exclude_directive_that_is_not_adjacent_is_reported():
    """The adjacency rule is fail-safe for the GATE (drift means the gate is
    probed again) and was silent for the READER. Measured on origin/main:
    three directives written, two effective."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        s = Path(td) / "gates.sh"
        s.write_text(
            '# host-independence: EXCLUDE — adjacent, effective\n'
            'run "a" "$ROOT" python3 a.py\n'
            '\n'
            '# host-independence: EXCLUDE — detached by a blank line\n'
            '\n'
            'run "b" "$ROOT" python3 b.py\n')
        inert = H.inert_exclusions(s)
        assert len(inert) == 1, inert
        assert "detached" in inert[0][1]
        gates = {g.label: g.excluded for g in H.corpus_gates(s)}
        assert gates["a"] is not None
        assert gates["b"] is None, "the fixture must reproduce the drift"


def test_the_real_ci_script_has_no_inert_exclusion():
    root = _repo_root()
    script = root / "tools" / "ci" / "repo_hygiene_gates.sh"
    assert H.inert_exclusions(script) == []
    written = sum(1 for ln in script.read_text().splitlines()
                  if "host-independence: EXCLUDE" in ln)
    effective = sum(1 for g in H.corpus_gates(script) if g.excluded)
    assert written == effective, (
        f"{written} EXCLUDE directive(s) written, {effective} in effect")


# ── 4. the A-H rubric letter is not a convergence verdict ──────────────────
def _real_triage_records():
    root = _repo_root()
    p = (root / "benchmark-data" / "evaluation" / "cvdp" /
         "run_v1239_converge" / "triage_records.json")
    if not p.is_file():
        pytest.skip("the one published triage_records.json is not present")
    return json.loads(p.read_text())


def test_a_rubric_letter_never_shadows_a_real_verdict(tmp_path):
    """The § 4/§ 6.4 rubric writes A-H into `category`; § 4.2 writes the
    convergence verdict. The one real input carries both, and was audited
    correctly only because `verdict` came first in the alias tuple. A producer
    that put the verdict in any OTHER alias got 121 of 121 records accused."""
    import benchmark_triage_absorption_audit as A
    doc = _real_triage_records()
    for r in doc["records"]:
        r["outcome"] = r.pop("verdict")
    rep = A.audit_records(doc["records"])
    assert rep["n_violations"] == 0, rep["violations"][:2]


def test_only_a_rubric_letter_is_named_as_such_not_as_an_unknown_verdict():
    """Still a violation — a record with no § 4.2 verdict is under-specified —
    but the message must not invite the author to add "H" to the vocabulary."""
    import benchmark_triage_absorption_audit as A
    doc = _real_triage_records()
    for r in doc["records"]:
        r.pop("verdict")
    rep = A.audit_records(doc["records"])
    rules = {v["rule"] for v in rep["violations"]}
    assert rules == {"rubric_letter_not_a_verdict"}, rules


def test_the_published_absorption_audit_is_still_reproduced(tmp_path):
    """The one real run this gate has ever judged must be byte-stable across
    the fix: a change to a verdict extractor that moves a published number is a
    different kind of change entirely."""
    import benchmark_triage_absorption_audit as A
    root = _repo_root()
    d = root / "benchmark-data" / "evaluation" / "cvdp" / "run_v1239_converge"
    if not (d / "absorption_audit.json").is_file():
        pytest.skip("no published absorption_audit.json")
    published = json.loads((d / "absorption_audit.json").read_text())
    doc = _real_triage_records()
    now = A.audit_records(doc["records"])
    for k in ("verdict", "n_records", "n_violations", "n_absorbed", "n_exempt"):
        assert now[k] == published[k], k


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
