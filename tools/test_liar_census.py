"""A detector that has never fired is indistinguishable from no detector.

`liar_census` is an instrument, and an instrument that reports CLEAN over a
corpus is making the strongest claim in this repo. The load-bearing tests here
are therefore not the ones where it reports clean — they are the ones where a
gate is PLANTED to lie and the census has to catch it, one planted shape per
probe it implements.

The census is also the first thing in this campaign whose own FALSE POSITIVES
are a hazard: the discount list is what future sweeps trust, so
`test_the_discount_is_structural_not_a_name_list` pins that the forgiveness is
derived from the flow YAML and would follow a gate that was renamed.

Every planted gate here is a real file executed by a real subprocess through
the real `_run`, for the reason `test_corpus_write_guard.py` gives: a fixture
copy of the logic would drift from the code that actually runs.
"""
from __future__ import annotations

import ast
import collections
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS))
import liar_census as lc  # noqa: E402

for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

_T = 55

#: See `test_the_mutation_never_writes_inside_the_checkout`.
_MUTATION_BOUND_S = 45


def _programs(tmp_path: Path, **gates: str) -> Path:
    """A throwaway `programs/` dir holding one real, runnable file per gate."""
    d = tmp_path / "programs"
    d.mkdir(exist_ok=True)
    for name, body in gates.items():
        (d / f"{name}.py").write_text(textwrap.dedent(body))
    return d


def _flow(tmp_path: Path, yaml_text: str) -> Path:
    f = tmp_path / "flow.yaml"
    f.write_text(textwrap.dedent(yaml_text))
    return f


@pytest.fixture()
def census(tmp_path, monkeypatch):
    """Point the census at a planted `programs/` tree instead of the repo's."""
    def _run(flow: Path, programs: Path, *extra: str):
        monkeypatch.setattr(lc, "PROGRAMS", programs)
        rc = lc.main(["--flow", str(flow), *extra])
        return rc
    return _run


# --------------------------------------------------------------------------
# THE CONTROLS. One planted liar per probe. If any of these stops failing, the
# census has stopped looking on that axis and would still print a confident 0.
# --------------------------------------------------------------------------

_UNGUARDED_STEP = """
    steps:
      - id: 99
        name: planted
        gate:
          all_of:
            - program_exit_zero: "{prog} ."
    """


def test_it_fires_on_a_gate_that_passes_over_an_empty_tree(census, tmp_path, capsys):
    progs = _programs(tmp_path, silent_pass="""
        import sys
        print("[PASS] silent_pass: all good")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="silent_pass")),
                progs, "--probes", "empty")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "LIAR" in out and "empty tree" in out, out
    assert "1   (1 of them BLOCKING)" in out, out


def test_it_fires_on_prose_that_contradicts_the_exit_code(census, tmp_path, capsys):
    """The #1017 shape: the gate's own line says it did not look."""
    progs = _programs(tmp_path, refuses_but_passes="""
        import sys
        print("INCOMPLETE: nothing was compared against anything")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="refuses_but_passes")),
                progs, "--probes", "prose")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "prose_vs_exit" in out and "INCOMPLETE" in out, out


def test_it_fires_on_a_pass_over_a_zero_population(census, tmp_path, capsys):
    progs = _programs(tmp_path, zero_pop="""
        import sys
        print("[PASS] compared 0 cells across 0 reports")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="zero_pop")),
                progs, "--probes", "zero")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "zero_denominator" in out, out


def test_it_fires_when_the_written_artefact_is_READ_BY_another_gate(census, tmp_path, capsys):
    """#1029: the auditor produces the artefact a later auditor reads.

    The severity turns on the CONSUMER, so the planted tree carries one: a
    second program that names the path the first one writes.
    """
    progs = _programs(
        tmp_path,
        writes_evidence="""
        import pathlib, sys
        p = pathlib.Path("reports/planted_evidence.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
        print("[FAIL] writes_evidence")
        sys.exit(1)
        """,
        reads_evidence="""
        # names reports/planted_evidence.json, so the write above is a chain
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="writes_evidence")),
                progs, "--probes", "writes")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "READ BY reads_evidence" in out, out


def test_a_self_report_nobody_reads_is_SUSPECT_not_a_liar(census, tmp_path, capsys):
    """The other half of the same probe: a gate emitting its own report is the
    normal shape. Scoring it LIAR would drown the real chains in noise."""
    progs = _programs(tmp_path, writes_own_report="""
        import pathlib, sys
        p = pathlib.Path("reports/nobody_reads_this.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
        print("[FAIL] writes_own_report")
        sys.exit(1)
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="writes_own_report")),
                progs, "--probes", "writes")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "SUSPECT" in out and "undisclosed self-report" in out, out


# --------------------------------------------------------------------------
# The census's OWN false positives. This is the half that decides whether a
# future sweep can be trusted, because the discount is what it trusts.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("guard_yaml,expect", [
    ("""
    steps:
      - id: 99
        condition:
          files_exist: ["never/there.json"]
        gate:
          all_of:
            - program_exit_zero: "silent_pass ."
    """, "[condition]"),
    ("""
    steps:
      - id: 99
        gate:
          all_of:
            - files_exist: ["never/there.json"]
            - program_exit_zero: "silent_pass ."
    """, "[sibling]"),
    ("""
    steps:
      - id: 99
        required_outputs: ["never/there.json"]
        gate:
          all_of:
            - program_exit_zero: "silent_pass ."
    """, "[required_outputs]"),
])
def test_each_declared_guard_declines_the_empty_tree_question(
        census, tmp_path, capsys, guard_yaml, expect):
    """All three guard forms, each proved separately.

    Same gate, same rc 0, same empty tree — only the flow STRUCTURE differs, and
    only the structure decides. That is the property that makes this a rule and
    not a name list.
    """
    progs = _programs(tmp_path, silent_pass="""
        import sys
        print("[PASS] silent_pass: all good")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, guard_yaml), progs, "--probes", "empty")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "GUARDED" in out, out
    # and the forgiveness is PRINTED with the structure that earned it
    assert "DECLINED" in out, out
    assert expect in out, out


def test_the_discount_is_structural_not_a_name_list(census, tmp_path, capsys):
    """Rename the gate and the verdict must not move.

    An allowlist of gate names rots the moment a gate is renamed, and rots
    SILENTLY — it is itself a check that lies. Two runs, two different program
    names, identical flow shape, identical verdict.
    """
    seen = set()
    for name in ("silent_pass", "renamed_yesterday"):
        progs = _programs(tmp_path, **{name: """
            import sys
            print("[PASS] all good")
            sys.exit(0)
            """})
        rc = census(_flow(tmp_path, f"""
        steps:
          - id: 99
            required_outputs: ["never/there.json"]
            gate:
              all_of:
                - program_exit_zero: "{name} ."
        """), progs, "--probes", "empty")
        out = capsys.readouterr().out
        seen.add((rc, "GUARDED" in out))
    assert seen == {(0, True)}, seen


def test_a_guard_does_NOT_forgive_the_prose_or_the_zero(census, tmp_path, capsys):
    """The guard answers "is the empty tree load-bearing", nothing else.

    #1017's real evidence was 92 POPULATED published runs, so a rule that let an
    existence guard silence `prose_vs_exit` would have discounted the defect the
    census exists to find. Measured directly against that: the pre-#1018 gates
    are still LIAR under all three guard forms.
    """
    progs = _programs(tmp_path, guarded_but_lying="""
        import sys
        print("INCOMPLETE: electromigration was NOT screened")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 99
        required_outputs: ["never/there.json"]
        condition:
          files_exist: ["never/there.json"]
        gate:
          all_of:
            - files_exist: ["never/there.json"]
            - program_exit_zero: "guarded_but_lying ."
    """), progs, "--probes", "empty,prose")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "prose_vs_exit" in out, out
    assert "GUARDED" in out, out          # the empty-tree half still declined


# --------------------------------------------------------------------------
# Degrade loudly (flow-change-acceptance §6): a census over nothing is not a
# census, and must never be reported as a clean one.
# --------------------------------------------------------------------------

def test_a_flow_with_no_clauses_REFUSES_rather_than_passing(tmp_path, capsys):
    rc = lc.main(["--flow", str(_flow(tmp_path, "steps: []\n"))])
    out = capsys.readouterr().out
    assert rc == 2, out
    assert "REFUSE" in out, out


def test_an_unrunnable_program_is_NA_and_never_clean(census, tmp_path, capsys):
    """A gate whose file is missing has not been measured. Silently scoring it
    CLEAN is how a census reports 0 over a population it never reached."""
    progs = _programs(tmp_path)          # deliberately empty
    census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="not_a_file")),
           progs, "--probes", "empty")
    out = capsys.readouterr().out
    assert "LIAR        0" in out, out
    assert "SUSPECT     0" in out, out


# --------------------------------------------------------------------------
# Driven by the REAL flow, not only by planted fixtures
# (flow-change-acceptance §4).
# --------------------------------------------------------------------------

def test_it_discovers_the_real_flow_by_STRUCTURE(tmp_path):
    """vibe-ic#1012: a substring test over the raw YAML counted a program named
    in a COMMENT as wired. Discovery must parse, not grep — so a clause spelled
    inside a comment must not be discovered."""
    if not lc.FLOW_YAML.is_file():
        pytest.skip(f"flow not present: {lc.FLOW_YAML}")
    real = lc.discover_clauses(lc.FLOW_YAML)
    assert len(real) > 100, len(real)
    assert all(c.program and " " not in c.program for c in real)

    commented = _flow(tmp_path, """
    steps:
      - id: 99
        # - program_exit_zero: "commented_out_gate ."
        gate:
          all_of:
            - program_exit_zero: "real_gate ."
    """)
    names = {c.program for c in lc.discover_clauses(commented)}
    assert names == {"real_gate"}, names


def test_the_real_flow_has_both_blocking_and_advisory_clauses(tmp_path):
    """A census that only ever saw one enforcement tier would report a blocking
    count that is really the total.

    This test USED TO ASSERT `kinds == {program_exit_zero,
    advisory_program_exit_zero}` — it PINNED the narrow population as correct,
    so the 28 `optional_program_exit_zero` clauses were not merely missed, they
    were held out by a green test. A test that pins a denominator has to be
    reasoned about as a denominator; the kind set now lives in
    `test_all_three_clause_kinds_are_swept`, which asserts against
    `lc.CLAUSE_KINDS` rather than against a hand-typed pair.
    """
    if not lc.FLOW_YAML.is_file():
        pytest.skip(f"flow not present: {lc.FLOW_YAML}")
    clauses = lc.discover_clauses(lc.FLOW_YAML)
    assert any(c.blocking for c in clauses)
    assert any(not c.blocking for c in clauses)

# --------------------------------------------------------------------------
# THE CONSOLIDATION GUARD (#1220)
#
# Three PRs grew this file at once and every one of them collided with another
# on a NAME rather than on a behaviour. The dangerous half is that git does not
# mark that class of collision: two top-level bindings of one name, added in
# different regions by different branches, merge with NO conflict marker, and
# the second silently shadows the first. Measured while consolidating #1220:
#
#   `clean`        main bound it to a COUNT (by subtraction), #1108 to the LIST
#                  of clean reports. Both survived a text merge; the surviving
#                  print then formatted a list with `:>4`.
#   `budget`       main's corpus-mutation COUNT (an int, #1065) vs #1108's
#                  wall-clock `Budget` object. Both survived; the ruler/cycle
#                  probes then indexed a `Budget`.
#   `_run_traced`  main's sitecustomize tracer (#1065) vs #1071's shim tracer,
#                  DIFFERENT SIGNATURES, defined 379 lines apart. Merging #1071
#                  onto main produced both, no conflict marker, and every
#                  shape-12 call site raised TypeError at runtime.
#
# A reviewer resolving marked hunks correctly still ships all three. So the
# check is not "did you resolve the conflicts" but "is any name in this file
# bound twice at module level" -- which is mechanical, and which is the only
# one of the three that a machine can see.
# --------------------------------------------------------------------------
def test_no_top_level_name_in_the_census_is_BOUND_TWICE():
    tree = ast.parse(Path(lc.__file__).read_text(encoding="utf-8"))
    where = collections.defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            where[node.name].append(node.lineno)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    where[tgt.id].append(node.lineno)
    twice = {n: ls for n, ls in where.items() if len(ls) > 1}
    assert not twice, (
        "shadowed top-level binding(s) in %s -- the LAST one wins and the "
        "earlier one is dead code that still reads as live:\n%s"
        % (lc.__file__,
           "\n".join(f"    {n} bound at lines {ls}" for n, ls in sorted(twice.items()))))


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))


# --------------------------------------------------------------------------
# THE CENSUS'S OWN REPAIRS (#1051 follow-up). Every one of these was a way the
# INSTRUMENT lied, found while adjudicating its output by hand. Each gets a
# control, because a probe repaired once and never pinned regresses silently.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    "VACUOUS_PASS: l_doc_todo_stub_count_check — scanned=0",
    "SKIP_NO_ANALOG_DIR: nothing to do",
    "SKIPPED_CONDITION: step condition unmet",
    "SKIP_MISSING_ORACLE: no oracle for this cell",
])
def test_the_refusal_pattern_sees_SCREAMING_SNAKE_verdict_tokens(line):
    """`\\b` does not match between `VACUOUS` and `_`, so the pattern was blind
    to this repo's OWN canonical refusal tokens — `VACUOUS_PASS` appears 139
    times in `programs/`. A refusal detector that cannot see the standard
    refusal token is the census's version of the defect it hunts."""
    assert lc._REFUSAL_LEAD.match(line), line


@pytest.mark.parametrize("line,is_empty_population", [
    ("[PASS] compared 0 librar(ies) across 0 log(s)", True),   # #1002's evidence
    ("INCOMPLETE: … 0 segment", True),                          # #1017's evidence
    ("[PASS] 504 cells screened, 0 violations", False),         # a NUMERATOR
    ("VACUOUS_PASS: … scanned=0 docs_with_todo=0", False),      # also a numerator
])
def test_the_zero_pattern_tells_a_denominator_from_a_numerator(line, is_empty_population):
    """`\\w*` let `doc` swallow `s_with_todo`, so a violation COUNT of zero read
    as an empty POPULATION — and on a clean project that zero is the correct
    answer. Both real historical denominators must still match."""
    assert bool(lc._ZERO_POP.search(line)) is is_empty_population, line


def test_a_refusal_the_CONSUMER_reads_is_disclosed_not_laundered(census, tmp_path, capsys):
    """rc 0 beside a refusal is only laundering if nothing reads the refusal.

    `flow_compliance_check` promotes a step to VACUOUS_PASS when it sees a
    `VACUOUS_PASS:` line, on the PASSING path, rc-independently. 11 of 17
    clauses this probe accused were using that channel correctly, 8 of them
    BLOCKING.
    """
    progs = _programs(tmp_path, discloses_properly="""
        import sys
        print("VACUOUS_PASS: discloses_properly examined nothing (reason: no input)")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="discloses_properly")),
                progs, "--probes", "prose")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "GUARDED" in out and "VACUOUS_PASS" in out, out


def test_free_prose_no_consumer_reads_is_STILL_a_liar(census, tmp_path, capsys):
    """The other side of the same rule, and the one that keeps #1017 caught:
    `INCOMPLETE:` and `skipped:` are not the sentinel and reach nobody."""
    for body in ("INCOMPLETE: nothing was compared", "skipped: no L7 document"):
        progs = _programs(tmp_path, free_prose=f"""
            import sys
            print({body!r})
            sys.exit(0)
            """)
        rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="free_prose")),
                    progs, "--probes", "prose")
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "no consumer reads" in out, out


def test_a_producer_whose_consumer_is_in_the_SAME_step_is_declined(census, tmp_path, capsys):
    """The flow's own M1 adjudication, as a rule: "PRODUCER, advisory on
    purpose: producing is not a verdict … the BLOCKING verdict stays with
    mixed_signal_merge_check, which reads what this writes."

    Same write, same consumer — only the STEP membership differs between this
    test and the cross-step one above, and only that decides.
    """
    progs = _programs(
        tmp_path,
        producer="""
        import pathlib, sys
        p = pathlib.Path("reports/planted_evidence.json")
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text("{}")
        print("[FAIL] producer"); sys.exit(1)
        """,
        checker_same_step="""
        # names reports/planted_evidence.json
        """)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 99
        gate:
          all_of:
            - advisory_program_exit_zero: "producer ."
            - program_exit_zero: "checker_same_step ."
    """), progs, "--probes", "writes")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "GUARDED" in out, out
    assert "OWN gate" in out, out


@pytest.mark.parametrize("body,verdict", [
    # rooted at a __file__-derived constant: reaches the CHECKOUT, every run
    ("""
     import pathlib, sys
     HERE = pathlib.Path(__file__).resolve().parent
     CORPUS = HERE / "fixtures"
     def pick():
         return next(CORPUS.rglob("*.spef"), None)
     print("[PASS] picked", pick()); sys.exit(0)
     """, "LIAR"),
    # rooted at what the caller handed it: cannot reach the checkout
    ("""
     import pathlib, sys
     def pick(project):
         return next(pathlib.Path(project).rglob("*.spef"), None)
     print("[PASS] picked", pick(sys.argv[1])); sys.exit(0)
     """, "CLEAN"),
])
def test_the_selector_probe_asks_where_the_walk_is_ROOTED(census, tmp_path, capsys,
                                                          body, verdict):
    """Same walk, same glob, same absence of the word `fixtures` — only the ROOT
    differs, and only the root decides.

    The old rule asked whether the file happened to mention `tests/` or
    `fixtures/` anywhere, which forgave the dangerous case whenever the file
    said the word and accused the safe case whenever it did not. Measured on
    the real flow, it produced 30 accusations and zero true positives.

    This test is why a probe that now reports zero can be believed: the first
    parameter is a known positive it still catches.
    """
    progs = _programs(tmp_path, selector=body)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="selector")),
                progs, "--probes", "selector")
    out = capsys.readouterr().out
    if verdict == "LIAR":
        assert rc == 1, out
        assert "__file__-derived" in out, out
    else:
        assert rc == 0, out
        assert "LIAR        0" in out, out


# ==========================================================================
# SHAPES 4 & 5 -- the mutation probes.
#
# These two are the only probes here that cannot be answered by looking. The
# question is not about the gate's text or about one run of it; it is "does
# anything in this repo notice when this gate stops deciding", and the only
# way to establish that is to stop it deciding and watch.
#
# So the controls below are not optional decoration. A mutation probe that
# has never been shown to FIRE is worth less than no probe at all, because it
# reports a confident CLEAN over every gate it silently failed to measure.
# ==========================================================================

#: A planted gate with a real verdict: rc 1 on the input it should refuse,
#: rc 0 otherwise, and prose either way. The prose is what the two suites
#: below differ on, and it is the whole experiment.
_PLANTED_GATE = """
    import sys
    def main(argv=None):
        args = argv if argv is not None else sys.argv[1:]
        if args and args[0] == "bad":
            print("[FAIL] planted: found the defect")
            return 1
        print("[PASS] planted: nothing to report")
        return 0
    if __name__ == "__main__":
        sys.exit(main())
    """

_DRIVER_HEAD = """
    import pathlib, subprocess, sys
    GATE = pathlib.Path(__file__).resolve().parents[1] / "planted.py"
    def _run(arg):
        return subprocess.run([sys.executable, str(GATE), arg],
                              capture_output=True, text=True)
    """

#: Observes the VERDICT in both directions. Nothing here can survive either
#: mutation.
_CONTROLLED = _DRIVER_HEAD + """
    def test_it_refuses_the_bad_input():
        assert _run("bad").returncode == 1
    def test_it_accepts_the_good_input():
        assert _run("good").returncode == 0
    """

#: Observes only what the gate SAYS. Every assertion here is satisfied by a
#: gate whose exit code has been replaced by a constant, in either direction --
#: which is the #1017 shape one layer down: the prose is measured and the
#: number the flow acts on is not.
_PROSE_ONLY = _DRIVER_HEAD + """
    def test_it_says_fail_on_the_bad_input():
        assert "[FAIL]" in _run("bad").stdout
    def test_it_says_pass_on_the_good_input():
        assert "[PASS]" in _run("good").stdout
    """


def _plant(tmp_path, gate: str = _PLANTED_GATE, **suites: str) -> Path:
    """A `programs/` tree with one gate and the test files that name it."""
    progs = _programs(tmp_path, planted=gate)
    tests = progs / "tests"
    tests.mkdir(exist_ok=True)
    for name, body in suites.items():
        (tests / f"test_{name}.py").write_text(textwrap.dedent(body))
    return progs


@pytest.fixture(autouse=True)
def _no_mutation_bleed():
    """Each planted tree is measured on its own.

    The caches are keyed by the programs tree for this reason, and this asserts
    the keying rather than trusting it: a cache that answered the second planted
    gate with the first one's result would make every test after the first one
    pass without measuring anything.
    """
    lc._MUTATION_CACHE.clear()
    lc._SCRATCH_ROOTS.clear()
    yield
    lc._MUTATION_CACHE.clear()
    lc._SCRATCH_ROOTS.clear()


def test_shape4_fires_when_neutering_the_verdict_kills_nothing(census, tmp_path, capsys):
    """THE PLANTED LIAR FOR SHAPE 4. Its suite drives the CLI, asserts on real
    output, and never once looks at the number the flow reads."""
    progs = _plant(tmp_path, prose=_PROSE_ONLY)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedpass")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "NO NEGATIVE CONTROL" in out, out
    assert "always says yes" in out, out


def test_shape5_fires_when_forcing_a_refusal_kills_nothing(census, tmp_path, capsys):
    """THE PLANTED LIAR FOR SHAPE 5. The same suite, the other direction: nothing
    in it pins that the gate can ever say yes."""
    progs = _plant(tmp_path, prose=_PROSE_ONLY)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedfail")
    out = capsys.readouterr().out
    assert "NO POSITIVE CONTROL" in out, out
    assert "a BAN" in out, out
    # SUSPECT, not LIAR: a gate that can only say no does not launder a PASS.
    assert rc == 0, out
    assert "SUSPECT     1" in out, out


def test_both_shapes_read_clean_on_a_gate_that_has_both_controls(census, tmp_path, capsys):
    """THE GREEN ARM. Same gate, same probes, a suite that observes the verdict.

    Without this the two tests above are satisfied by a probe that always fires.
    """
    progs = _plant(tmp_path, control=_CONTROLLED)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedpass,forcedfail")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out, out
    assert "SUSPECT     0" in out, out


def test_the_mutation_replaces_the_verdict_and_keeps_every_side_effect(tmp_path):
    """WHAT SEPARATES THIS FROM THE SHIPPED PROBE, asserted rather than claimed.

    `gate_cli_mutation_probe` injects `return 0` as the entry point's FIRST
    statement, so the gate returns before it writes its report or prints a line,
    and every test asserting on the gate's OUTPUT dies -- including the ones
    that never constrained the exit code. That over-reports protection.

    Here the original expression is still evaluated and only its VALUE is
    replaced, so `_PROSE_ONLY` above stays green and the finding survives. This
    pins the difference at the source level, where it is decidable.
    """
    src = textwrap.dedent(_PLANTED_GATE)
    forced, sites = lc.force_verdict(src, 0)
    assert sites >= 2, "nothing was forced, so the probe would measure nothing"
    gate = tmp_path / "planted.py"
    gate.write_text(forced)
    proc = _pr.run([sys.executable, str(gate), "bad"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, "the verdict was not forced"
    assert "[FAIL] planted: found the defect" in proc.stdout, (
        "the gate stopped doing its work, so this is a lobotomy rather than a "
        "verdict mutation, and every output assertion would die for the wrong "
        "reason: %r" % proc.stdout)


def test_a_test_that_was_already_red_is_not_mistaken_for_protection(census, tmp_path,
                                                                    capsys):
    """THE BASELINE ARM, which is the other half of what this adds.

    `gate_cli_mutation_probe` scores `CAUGHT if returncode != 0` over a single
    run. Here the selection contains a module that fails before anything is
    mutated -- the state main was measurably in while this was written, 49
    failures across a 184-file selection -- so pytest exits non-zero on every
    arm and an exit-code rule reports this unprotected gate as protected.

    Compared as node-ID SETS, the already-red module cancels and the finding
    stands.
    """
    # NAMES the program, because that is what puts a file in the selection --
    # the same rule the shipped probe selects by. A red module the selector
    # never reaches would prove nothing about the selector's arithmetic.
    # NAMES the program, because that is what puts a file in the selection --
    # the same rule the shipped probe selects by. It must also COLLECT: a
    # module that fails to import aborts the whole pytest session, which is a
    # different fault with a different verdict (BASELINE_DEAD), and pinning
    # this one on it would prove nothing about the arithmetic.
    progs = _plant(tmp_path, prose=_PROSE_ONLY,
                   alreadyred=_DRIVER_HEAD + """
    def test_it_is_red_for_a_reason_that_has_nothing_to_do_with_the_verdict():
        assert GATE.is_file() and False, "red before anything was mutated"
    """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedpass")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "NO NEGATIVE CONTROL" in out, out


def test_a_selection_with_nothing_green_is_declined_not_cleared(census, tmp_path,
                                                               capsys):
    """The fail-safe class. If nothing in the selection passes unmutated, the
    mutation had nothing to kill, and "no test noticed" is an accusation the
    measurement cannot support. It is DECLINED, and printed -- never folded
    into CLEAN, which is how a coverage hole becomes a clean bill of health."""
    progs = _plant(tmp_path, allred=_DRIVER_HEAD + """
    def test_the_only_module_that_names_it_is_red_before_anything_is_mutated():
        assert GATE.is_file() and False, "red before anything was mutated"
    """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedpass")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "NOT MEASURED" in out, out
    assert "BASELINE_DEAD" in out, out
    assert "CLEAN       0" in out, out


def test_a_gate_no_test_names_is_declined_not_cleared(census, tmp_path, capsys):
    """An unprotected gate and an untested one are different facts, and this
    probe can only establish the second. It says which."""
    progs = _plant(tmp_path)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedpass,forcedfail")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "NOT MEASURED (NO_TEST)" in out, out
    assert "CLEAN       0" in out, out


def test_a_program_with_no_verdict_is_declined_not_cleared(census, tmp_path, capsys):
    """Nothing reaches the exit status, so there is no verdict to force. That is
    a finding of a different shape and it is named rather than scored."""
    progs = _plant(tmp_path, gate="""
        print("[PASS] planted: I have no main and no exit")
        """, control=_CONTROLLED)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedpass")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "NOT MEASURED (NO_VERDICT)" in out, out


def test_an_advisory_clause_is_suspect_where_a_blocking_one_is_a_liar(census, tmp_path,
                                                                     capsys):
    """Severity follows the FLOW's own declaration, read from the yaml. An
    advisory clause's exit code is recorded rather than acted on, so the same
    measurement is a weaker claim about it."""
    progs = _plant(tmp_path, prose=_PROSE_ONLY)
    rc = census(_flow(tmp_path, """
        steps:
          - id: 99
            name: planted
            gate:
              all_of:
                - advisory_program_exit_zero: "planted ."
        """), progs, "--probes", "forcedpass")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "NO NEGATIVE CONTROL" in out, out
    assert "SUSPECT     1" in out, out


def test_the_mutation_never_writes_inside_the_checkout(tmp_path):
    """Asserted on `git status` across a REAL run of the real probe, following
    `test_the_default_run_never_touches_the_shipped_programs_tree`.

    Two shipped gates were once found carrying an injected `return 0` beside a
    `.probe-orig` sidecar, left by runs that were SIGKILLed between the write
    and the restore. A neutered gate exits 0 and the flow reads PASS, so the
    damage is quiet and green. This probe mutates a disposable copy for that
    reason, and the flag that would let it do otherwise does not exist.
    """
    def dirt():
        return _pr.run(
            ["git", "status", "--porcelain", str(lc.PLUGIN)],
            cwd=str(lc.REPO), capture_output=True, text=True).stdout

    before = dirt()
    # 45 s, not 300: the harness that now runs this file bounds the SESSION at
    # 180 s with `--timeout-method=thread`, which takes the whole process down
    # rather than failing the test. An inner bound at or above the harness bound
    # can never fire — `ci_harness_timeout_ceiling_check` exists for exactly
    # this, and it cannot see this call site because the bound is positional.
    # A TIMEOUT here does not weaken the assertion: it is on `git status`, and a
    # probe that gave up still must not have written into the checkout.
    lc.mutation_run("neutered_gate_tree_check", _MUTATION_BOUND_S, lc.Budget(0))
    assert dirt() == before, (
        "the mutation reached the checkout:\n%s" % dirt())


_TWO_CLAUSE_STEPS = """
    steps:
      - id: 98
        name: first
        gate:
          all_of:
            - program_exit_zero: "planted ."
      - id: 99
        name: second
        gate:
          all_of:
            - program_exit_zero: "planted2 ."
    """


def test_a_spent_budget_is_named_as_a_DROP_never_folded_into_clean(census, tmp_path,
                                                                   capsys):
    """A bounded sweep that does not name its own coverage hole reads as
    "covered everything". `--mutation-budget` is the only thing here that can
    silently stop measuring, so the branch that stops has its own verdict and
    its own line in the report -- and this fires it, because a decline path
    nobody has ever exercised is indistinguishable from one that does not work.
    """
    progs = _plant(tmp_path, control=_CONTROLLED)
    (progs / "planted2.py").write_text(textwrap.dedent(_PLANTED_GATE))
    (progs / "tests" / "test_planted2.py").write_text(textwrap.dedent("""
        import pathlib, subprocess, sys
        GATE = pathlib.Path(__file__).resolve().parents[1] / "planted2.py"
        def test_it_refuses_the_bad_input():
            assert subprocess.run([sys.executable, str(GATE), "bad"]).returncode == 1
        """))
    rc = census(_flow(tmp_path, _TWO_CLAUSE_STEPS), progs,
                "--probes", "forcedpass", "--mutation-budget", "0.001")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "NOT MEASURED (BUDGET_SPENT)" in out, out
    assert "DROPPED rather than cleared" in out, out


def test_two_gates_measured_concurrently_get_their_own_trees(census, tmp_path, capsys):
    """`--mutation-jobs` gives each worker its own copy of the plugin.

    Two workers mutating one tree would each be measuring the other's mutation.
    Asserted on the verdicts rather than on the copies: the planted pair is one
    controlled gate and one uncontrolled one, and if the trees were shared the
    answers would blur into each other.
    """
    progs = _plant(tmp_path, control=_CONTROLLED)
    (progs / "planted2.py").write_text(textwrap.dedent(_PLANTED_GATE))
    (progs / "tests" / "test_planted2_prose.py").write_text(textwrap.dedent("""
        import pathlib, subprocess, sys
        GATE = pathlib.Path(__file__).resolve().parents[1] / "planted2.py"
        def test_it_says_fail_on_the_bad_input():
            out = subprocess.run([sys.executable, str(GATE), "bad"],
                                 capture_output=True, text=True).stdout
            assert "[FAIL]" in out
        """))
    rc = census(_flow(tmp_path, _TWO_CLAUSE_STEPS), progs,
                "--probes", "forcedpass", "--mutation-jobs", "2")
    out = capsys.readouterr().out
    assert rc == 1, out
    # exactly one of the two is the finding; the controlled one stays clean
    assert "LIAR        1" in out, out
    assert "CLEAN       1" in out, out
    assert "planted2" in out, out


def test_every_decline_state_has_a_printed_explanation():
    """A state with no entry in `_UNMEASURED` raises KeyError while FORMATTING
    the report — after the expensive part has run, destroying a whole sweep's
    results at the last step.

    Pinned here rather than papered over with a `.get()` default, because the
    failure this prevents is an author adding a decline reason and forgetting to
    say what it means. A default would let that ship as an unexplained N/A,
    which is a coverage hole that reads as a considered decision.
    """
    import re
    src = (_TOOLS / "liar_census.py").read_text()
    constructed = set(re.findall(r'MutationRun\(\s*program,\s*"([A-Z_]+)"', src))
    constructed |= set(re.findall(r'run\.state\s*=\s*"([A-Z_]+)"', src))
    assert "MEASURED" in constructed, (
        "the pattern no longer finds the states this file constructs, so this "
        "test is watching nothing: %s" % sorted(constructed))
    unexplained = constructed - set(lc._UNMEASURED) - {"MEASURED"}
    assert not unexplained, (
        "these MutationRun states would raise KeyError when the report is "
        "formatted: %s" % sorted(unexplained))


def test_the_DEFAULT_probe_set_runs_all_of_them_together(census, tmp_path, capsys):
    """The shipped default is all seven probes, and until this existed every
    test drove a hand-picked subset -- so the combination a user actually runs
    was the one combination nothing exercised.

    Asserts the two mutation probes reach their verdict ALONGSIDE the five that
    came before, because the mutation pass is pre-warmed before the per-clause
    loop and an ordering fault there would show up only here.
    """
    progs = _plant(tmp_path, prose=_PROSE_ONLY)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")), progs)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "NO NEGATIVE CONTROL" in out, out          # P6 reached its verdict
    assert "NO POSITIVE CONTROL" in out, out          # P7 reached its verdict
    # and the run really was the seven-probe one, not a subset that happened to
    # include the two: the header names what ran.
    assert "probes: " + ",".join(lc.ALL_PROBES) in out, out
    # 7 -> 10 at the #1063 merge: main added `blocks`/`depth`/`spelling` while
    # this branch added the two mutation probes. The pin is on the DEFAULT set
    # being the WHOLE set -- the number is derived from that, not chosen -- so
    # it moves whenever a probe is added and is meant to.
    # 10 -> 12 at this consolidation: `ruler`/`cycle` were already on main and
    # `forcedpass`/`forcedfail` arrive with it. The pin is on the DEFAULT set
    # being the WHOLE set -- the number is derived from that, not chosen -- so
    # it moves whenever a probe is added and is meant to.
    assert len(lc.ALL_PROBES) == 13, lc.ALL_PROBES


def test_an_arm_whose_session_DIES_is_declined_not_reported_as_a_finding(
        census, tmp_path, capsys):
    """THE FALSE ACCUSATION THIS PROBE ACTUALLY MADE, reproduced deterministically.

    `--timeout-method=thread` does not fail a test when the inner bound is hit;
    it takes the whole pytest PROCESS down. A killed session prints no `FAILED`
    lines, so the arm's failure set comes back EMPTY -- and empty-minus-baseline
    is an empty difference, which is exactly the shape of the finding. "No test
    died" and "no test ran" produced identical output.

    Measured for real: under an 8-worker sweep `drc_report_check`'s forced-1 arm
    died and was reported as having no positive control; reproduced on an idle
    machine it killed 25 tests. It was caught only by reproducing every finding
    by hand.

    Simulated here without depending on load: the planted suite kills its own
    session with `os._exit` when it sees the forced-verdict rewrite in the gate's
    source, so the mutant arm dies every time and the baseline arm never does.
    """
    progs = _plant(tmp_path, control=_CONTROLLED, killer=_DRIVER_HEAD + """
    import os
    def test_the_session_dies_only_when_the_gate_has_been_mutated():
        # `(expr, 0)[1]` is the rewrite; the baseline arm is unparsed too, so
        # this cannot fire on formatting alone.
        if ", 0)[1]" in GATE.read_text() or ", 1)[1]" in GATE.read_text():
            os._exit(1)
        assert True
    """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="planted")),
                progs, "--probes", "forcedpass,forcedfail")
    out = capsys.readouterr().out
    assert "NOT MEASURED (ARM_DIED)" in out, out
    assert "NO NEGATIVE CONTROL" not in out, (
        "a dead session was reported as a gate with no control:\n" + out)
    assert "NO POSITIVE CONTROL" not in out, out
    assert rc == 0, out


@pytest.mark.parametrize("summary,completed", [
    ("1 passed in 0.05s", True),
    ("1 failed, 155 passed in 30.42s", True),
    # >= 60 s: pytest appends a human-readable duration, and a pattern anchored
    # at `s$` matches none of these. Written that way, this guard called every
    # arm over a minute DEAD -- 8 of the first 42 programs of a sweep, climbing.
    ("1 passed in 62.07s (0:01:02)", True),
    ("2 failed, 3 passed, 1 warning in 3601.10s (1:00:01)", True),
    ("no tests ran in 0.01s", True),
    # what a session killed by `--timeout-method=thread` actually leaves behind
    ("..F\n+++ Timeout +++\nStack of MainThread (0x7f0):\n  File \"x.py\"", False),
    ("", False),
])
def test_the_completion_pattern_knows_every_shape_of_pytest_summary(summary, completed):
    """Which sessions count as measurements, pinned on literal pytest output.

    This is the whole difference between a finding and a coverage hole, and it
    has been wrong in BOTH directions inside one afternoon: absent, it read a
    killed session as a gate with no control; anchored at `s$`, it read every
    session over a minute as killed.
    """
    assert bool(lc._PYTEST_DONE.search(summary + "\n")) is completed, summary
# --------------------------------------------------------------------------
# SHAPE 7 -- "runs, produces a verdict, and is wired where it can never
# block". The controls that matter here are the ones where the GATE IS
# IDENTICAL and only the flow's wiring moves, because the whole claim of this
# probe is that no amount of looking at the gate can answer the question.
# --------------------------------------------------------------------------

_READS_BUT_DOES_NOT_BLOCK_ON = """
    steps:
      - id: 7
        name: producer
        gate:
          all_of:
            - program_exit_zero: "upstream ."
      - id: 8
        name: consumer
        required_inputs:
          - from: 7
            path: "out/thing.json"
        blocks_on: {edges}
        gate:
          all_of:
            - program_exit_zero: "downstream ."
    """


@pytest.fixture()
def _two_gates(tmp_path):
    return _programs(tmp_path, upstream="""
        import sys
        print("[PASS] upstream"); sys.exit(0)
        """, downstream="""
        import sys
        print("[PASS] downstream"); sys.exit(0)
        """)


def test_it_fires_when_a_step_reads_a_producer_it_does_not_block_on(
        census, tmp_path, capsys, _two_gates):
    """The #923 / step-1-vs-D1 shape, as a rule instead of a collision.

    Step 8 says in the flow's own grammar that it READS step 7's output. With
    no ordering edge to 7, `flow_step_execution_coverage_check`'s guard — the
    only consumer that can contradict a step which passed its own gate — never
    walks from 8 to 7, so a FAILED 7 leaves 8's PASS standing.
    """
    rc = census(_flow(tmp_path, _READS_BUT_DOES_NOT_BLOCK_ON.format(edges="[]")),
                _two_gates, "--probes", "blocks")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "never_blocks" in out and "uncontradictable" in out, out
    # attributed to the CONSUMER's clause, not to the producer's
    assert "downstream" in out, out


def test_declaring_the_edge_is_the_whole_difference(census, tmp_path, capsys,
                                                    _two_gates):
    """Same two gates, same programs, same verdicts, same everything — one
    YAML list changes and the finding goes away. That is what makes this a
    property of the WIRING and not of the gate, which is the entire claim."""
    rc = census(_flow(tmp_path, _READS_BUT_DOES_NOT_BLOCK_ON.format(edges="[7]")),
                _two_gates, "--probes", "blocks")

# P6 (ruler_blind) and P9 (self_upstream). Both need a POPULATED tree, so both
# get a planted corpus root as well as a planted gate. The mutation is the same
# one the real probe makes -- truncate to zero bytes -- and the guards are
# exercised one at a time so a guard that silently swallowed everything would
# leave the FIRES tests red rather than pass unnoticed.
# --------------------------------------------------------------------------

_CORPUS_STEP = """
    steps:
      - id: 77
        name: planted
        required_outputs:
          - out/evidence.json
        gate:
          all_of:
{clauses}
    """


def _corpus(tmp_path: Path, files: dict) -> Path:
    """A tree shaped like a published run root: one dir named by the first
    segment of a declared output, so `discover_corpus_roots` finds it the same
    structural way it finds a real one."""
    root = tmp_path / "corpus" / "run1"
    for rel, text in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    return tmp_path / "corpus"


@pytest.fixture()
def consumer_says(monkeypatch):
    """Pin what the AUTHORITY (`flow_compliance_check`) answers.

    The real consumer takes ~6s and knows nothing about a planted flow, so
    these tests fix its answer and assert on the DECISION the census makes
    given that answer. The consumer's real behaviour on a real root is
    measured in the PR body, not simulated here -- the two are different
    claims and neither substitutes for the other.
    """
    def _set(*statuses: str):
        seq = list(statuses)
        def _fake(project, tmp, timeout):
            return {"77": seq.pop(0) if len(seq) > 1 else seq[0]}
        monkeypatch.setattr(lc, "_flow_step_status", _fake)
    return _set


def _clauses(*cmds: str) -> str:
    return "\n".join(f"            - program_exit_zero: \"{c}\"" for c in cmds)


_BLIND = """
    import json, sys
    json.load(open("out/evidence.json")) if open("out/evidence.json").read().strip() else None
    print("[PASS] evidence considered")
    sys.exit(0)
    """


def test_ruler_blind_fires_when_emptying_a_declared_artefact_moves_nothing(
        census, tmp_path, capsys, consumer_says):
    """The shape: it DECLARES the artefact, it OPENS the artefact, and the
    artefact's content decides nothing."""
    consumer_says("PASS")
    progs = _programs(tmp_path, blind=_BLIND)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("blind ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "ruler_blind" in out and "out/evidence.json" in out, out
    assert "nothing anywhere in the flow reacted" in out, out


def test_ruler_blind_reads_CLEAN_on_a_gate_that_does_measure_the_content(
        census, tmp_path, capsys, consumer_says):
    """The other arm. Same declaration, same read, same corpus -- the only
    difference is that this gate's verdict depends on what it found."""
    consumer_says("PASS")
    progs = _programs(tmp_path, measures="""
        import json, sys
        try:
            doc = json.load(open("out/evidence.json"))
        except Exception:
            print("FAIL: evidence unreadable"); sys.exit(1)
        print("[PASS] %d violation(s)" % doc["violations"]); sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("measures ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out, out


def test_a_transitive_edge_counts_because_the_guard_walks_transitively(
        census, tmp_path, capsys):
    """The guard's ancestry walk is transitive, so demanding a DIRECT edge
    would accuse every correctly-ordered chain of more than two steps. 9 blocks
    on 8 blocks on 7, and 9 reads 7: correctly ordered, and CLEAN."""
    progs = _programs(tmp_path, g="""
        import sys
        print("[PASS] g"); sys.exit(0)
        """)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 7
        name: a
        gate:
          all_of:
            - program_exit_zero: "g ."
      - id: 8
        name: b
        blocks_on: [7]
        gate:
          all_of:
            - program_exit_zero: "g ."
      - id: 9
        name: c
        blocks_on: [8]
        required_inputs:
          - from: 7
        gate:
          all_of:
            - program_exit_zero: "g ."
    """), progs, "--probes", "blocks")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out, out


def test_an_input_from_OUTSIDE_the_flow_is_declined_not_accused(
        census, tmp_path, capsys):
    """The fail-safe class, and it is the majority of the population: a step
    whose input comes from the user's documents or the PDK declares
    `from: external`. No `blocks_on` edge can point at a step that does not
    exist, so demanding one would accuse every genuine entry point.

    Decided by asking whether the `from` value is a step id THIS FLOW declares
    — the same test `flow_dependency_graph_check` uses for a dangling
    reference — so a flow that spells its outside world `upstream_of_us`
    instead of `external` is treated identically. A word list with one word in
    it is still a word list.
    """
    progs = _programs(tmp_path, g="""
        import sys
        print("[PASS] g"); sys.exit(0)
        """)
    for outside in ("external", "the_customer", "upstream_of_us"):
        rc = census(_flow(tmp_path, f"""
        steps:
          - id: 9
            name: entry
            blocks_on: []
            required_inputs:
              - from: {outside}
            gate:
              all_of:
                - program_exit_zero: "g ."
        """), progs, "--probes", "blocks")
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "GUARDED" in out and "outside the" in out, (outside, out)
        assert "DECLINED" in out, out


def test_an_advisory_slot_that_DECLARES_blocking_is_a_liar(census, tmp_path,
                                                           capsys, monkeypatch):
    """The other consumer: the SLOT.

    `flow_compliance_check._evaluate_gate` answers `advisory_program_exit_zero`
    with an unconditional `return True`, so a clause there cannot fail its step
    whatever it prints. That is not a lie — the slot is the disclosure. It
    becomes one when the gate's own docstring opens a line with
    `ENFORCEMENT: blocking`, because then a reader is being told the verdict
    blocks while the wiring guarantees it cannot.

    MEASURED on the real flow: zero clauses are in that state. This is the
    control that makes the zero mean something, and it is a CONSTRUCTED
    positive — no historical instance of this exact pairing was found in the
    repo's history, only its mirror image (nine gates wired BLOCKING while
    declaring advisory, which is the safe direction).
    """
    progs = _programs(tmp_path, says_it_blocks='''
        """A gate.

        ENFORCEMENT: blocking
        """
        import sys
        print("[PASS] says_it_blocks"); sys.exit(0)
        ''')
    monkeypatch.setattr(lc, "PROGRAMS", progs)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 9
        name: mis-slotted
        gate:
          all_of:
            - advisory_program_exit_zero: "says_it_blocks ."
    """), progs, "--probes", "blocks")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "ENFORCEMENT: blocking" in out, out


def test_the_same_gate_declaring_advisory_is_NOT_a_liar(census, tmp_path,
                                                        capsys, monkeypatch):
    """The paired direction. Identical wiring, identical exit code — only the
    word in the docstring differs, and only that decides."""
    progs = _programs(tmp_path, says_it_advises='''
        """A gate.

        ENFORCEMENT: advisory
        """
        import sys
        print("[PASS] says_it_advises"); sys.exit(0)
        ''')
    monkeypatch.setattr(lc, "PROGRAMS", progs)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 9
        name: honestly-advisory
        gate:
          all_of:
            - advisory_program_exit_zero: "says_it_advises ."
    """), progs, "--probes", "blocks")
    out = capsys.readouterr().out
    assert rc == 0, out


def test_a_MENTION_of_the_enforcement_token_is_not_a_declaration(tmp_path,
                                                                 monkeypatch):
    """#886's lesson, re-pinned here because this probe now depends on it: an
    unanchored pattern read "gates that say ENFORCEMENT: blocking in prose" as
    a declaration, and several gates that say in prose they carry NO
    declaration were each read as carrying one."""
    progs = _programs(tmp_path, chatty='''
        """A gate that talks about the ENFORCEMENT: blocking convention
        without adopting it."""
        ''', declares='''
        """A gate.

        ENFORCEMENT: blocking
        """
        ''')
    monkeypatch.setattr(lc, "PROGRAMS", progs)
    assert lc._declared_enforcement("chatty") is None
    assert lc._declared_enforcement("declares") == "blocking"


# --------------------------------------------------------------------------
# SHAPE 11 -- "spell the same directory differently and the answer changes".
# Two probes, because the family has two mechanisms and one of them is
# invisible to the other: a fixed-depth walk agrees across every SPELLING of
# a directory and still reaches nothing when the caller types a different
# DEPTH of the same corpus.
# --------------------------------------------------------------------------

def test_the_depth_probe_fires_on_the_real_pre_1025_source(tmp_path,
                                                           monkeypatch, capsys):
    """The historical positive, restored in place.

    `step_internal_fail_bubble_up_check` searched `corpus.glob("*/clean_run_*")`
    until #1025. Same tree, same commit, same question:

        --corpus benchmark-data      ->  0 tree(s), VACUOUS_PASS, rc 2
        --corpus benchmark-data/ic   -> 13 tree(s), 5 unacknowledged FAILs

    This test reconstructs the DEFECT rather than quoting the source, so it
    keeps meaning if that file is renamed or deleted; the two-arm calibration
    against the real blob (`git show 05451599^:…`) is recorded in the PR.
    """
    progs = _programs(tmp_path, pre_1025="""
        import pathlib, sys
        def _published_run_trees(corpus):
            return sorted(p for p in corpus.glob("*/clean_run_*") if p.is_dir())
        print("[PASS]", len(_published_run_trees(pathlib.Path(sys.argv[1]))), "trees")
        sys.exit(0)
        """)
    monkeypatch.setattr(lc, "PROGRAMS", progs)
    rc = lc.main(["--flow", str(_flow(tmp_path, _UNGUARDED_STEP.format(prog="pre_1025"))),
                  "--probes", "depth"])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "BARE caller-supplied" in out, out


def test_the_depth_probe_reads_clean_on_the_repaired_source(tmp_path,
                                                            monkeypatch, capsys):
    """`rglob` makes the two invocations agree by construction rather than by
    the caller remembering the right depth. Same function, same pattern NAME,
    same population intent."""
    progs = _programs(tmp_path, post_1025="""
        import pathlib, sys
        def _published_run_trees(corpus):
            return sorted(p for p in corpus.rglob("clean_run_*") if p.is_dir())
        print("[PASS]", len(_published_run_trees(pathlib.Path(sys.argv[1]))), "trees")
        sys.exit(0)
        """)
    monkeypatch.setattr(lc, "PROGRAMS", progs)
    rc = lc.main(["--flow", str(_flow(tmp_path, _UNGUARDED_STEP.format(prog="post_1025"))),
                  "--probes", "depth"])
    out = capsys.readouterr().out
    assert rc == 0, out


def test_a_fixed_depth_walk_under_a_CONSTRUCTED_anchor_is_not_accused(
        census, tmp_path, capsys):
    """The false-positive class, and it is every leading-wildcard glob in the
    real population: `analog_dir = _pl.analog_dir(project)` then
    `analog_dir.glob("*/spec.json")`.

    The depth there is measured from an anchor the PROGRAM builds, so it means
    the same thing however the project was spelled — and the flow declares that
    same shape itself (`phase3/analog/*/spec.json` is a `required_outputs`
    entry). Same glob, same pattern, same wildcard: only the root differs.
    """
    progs = _programs(tmp_path, anchored="""
        import pathlib, sys
        def blocks(project):
            analog_dir = pathlib.Path(project) / "phase3" / "analog"
            return sorted(analog_dir.glob("*/spec.json"))
        print("[PASS]", len(blocks(sys.argv[1])), "blocks")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="anchored")),
                progs, "--probes", "depth")
    out = capsys.readouterr().out
    assert rc == 0, out
    # the census prints detail only for LIAR/SUSPECT, so the REASON for the
    # discount is read off the probe itself — a forgiveness has to be auditable
    # even when it is silent in the summary.
    result = lc.probe_depth_pinned_walk(
        lc.Clause(step="99", kind="program_exit_zero", cmd="anchored .",
                  program="anchored"))
    assert result.verdict == lc.CLEAN, result
    assert "CONSTRUCTS" in result.detail, result


def test_an_ANCHORED_pattern_is_not_a_fixed_depth_walk(census, tmp_path, capsys):
    """`reports/*.json` names its directory, so its depth is a fact about the
    layout. Only a LEADING wildcard component — "some directory whose name I do
    not know, exactly one level down" — is the caller-depth shape."""
    progs = _programs(tmp_path, anchored_pattern="""
        import pathlib, sys
        p = pathlib.Path(sys.argv[1])
        print("[PASS]", len(list(p.glob("reports/*.json"))), "reports")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="anchored_pattern")),
                progs, "--probes", "depth")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "no fixed-depth walk" in out or "LIAR        0" in out, out


@pytest.mark.parametrize("name,body", [
    # rc turns on a trailing slash: `str(path).endswith("/")` and friends
    ("verdict", """
     import pathlib, sys
     raw = sys.argv[1]
     if raw.endswith("/") or raw.startswith("/"):
         print("[PASS] nothing to do here"); sys.exit(0)
     print("[FAIL] found a problem"); sys.exit(1)
     """),
    # rc agrees everywhere and the gate says PASS every time -- only the
    # POPULATION moves. The quieter half, and the one that ships: the walk is
    # RESOLVED and the root it is compared against is not, so the filter keeps
    # everything under an absolute spelling and nothing under `.`
    ("population", """
     import pathlib, sys
     root = pathlib.Path(sys.argv[1])
     found = [p for p in root.rglob("*.json") if p.resolve().parent.parent == root]
     print("[PASS] screened", len(found), "reports")
     sys.exit(0)
     """),
])
def test_the_spelling_probe_fires_when_the_same_directory_answers_differently(
        census, tmp_path, capsys, name, body):
    """CONSTRUCTED, and said plainly: no historical instance of a pure SPELLING
    divergence was found in this repo's history — #1025, the landed member of
    this family, is a DEPTH defect, which is why it has its own probe. Measured
    over all 136 clauses this one reports zero, and these two fixtures are the
    reason that zero can be believed rather than assumed.

    Both arms of the comparison name the SAME directory and the cwd never
    moves, so nothing but the gate's own path handling can make them differ.
    """
    progs = _programs(tmp_path, spells=body)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 9
        name: planted
        required_outputs: ["reports/thing.json"]
        gate:
          all_of:
            - program_exit_zero: "spells ."
    """), progs, "--probes", "spelling")
    out = capsys.readouterr().out
    assert rc == 1, (name, out)
    assert "spelled" in out and "cwd unmoved" in out, out


def test_a_gate_that_merely_ECHOES_its_argument_is_not_a_liar(census, tmp_path,
                                                              capsys):
    """The false-positive class this probe would otherwise have: almost every
    gate prints the path it was handed, and six spellings print six different
    strings. Quoting your argument back is not disagreeing with yourself, so
    the spelling is normalised out of the comparison before it is made."""
    progs = _programs(tmp_path, echoes="""
        import pathlib, sys
        p = pathlib.Path(sys.argv[1])
        print(f"[PASS] scanned {p} — {len(list(p.rglob('*.json')))} reports")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 9
        name: planted
        required_outputs: ["reports/thing.json"]
        gate:
          all_of:
            - program_exit_zero: "echoes ."
    """), progs, "--probes", "spelling")
    out = capsys.readouterr().out
    assert rc == 0, out


def test_a_clause_with_no_project_path_is_NA_and_the_bound_is_PRINTED(
        census, tmp_path, capsys):
    """`spec_review_lint --strict input/docs/*.md …` takes a glob list, never a
    project path, so there is nothing to spell differently. Ten of the 136
    clauses are like that.

    They must be N/A and the count must reach the reader: a probe that quietly
    drops part of its population reports a confident number about a sweep it
    never ran — #1054's finding about the selector probe, which returned a
    zero over a tree it had never scanned.
    """
    progs = _programs(tmp_path, no_path="""
        import sys
        print("[PASS] no_path"); sys.exit(0)
        """)
    rc = census(_flow(tmp_path, """
    steps:
      - id: 9
        name: planted
        gate:
          all_of:
            - program_exit_zero: "no_path --strict input/docs/*.md"
    """), progs, "--probes", "spelling")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "COVERAGE" in out and "did NOT measure" in out, out
    assert "path_spelling" in out, out


def test_bounding_the_spelling_probe_PRINTS_what_it_dropped(census, tmp_path,
                                                            capsys):
    """The probe is the most expensive thing in this file, so it can be
    bounded. Silent truncation reads as "covered everything" when it did not,
    so the spellings NOT tried are named."""
    progs = _programs(tmp_path, g="""
        import sys
        print("[PASS] g"); sys.exit(0)
        """)
    census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="g")), progs,
           "--probes", "spelling", "--spelling-variants", "1")
    out = capsys.readouterr().out
    assert "BOUNDED to 1 of" in out, out
    assert "through_a_symlink" in out, out


# --------------------------------------------------------------------------
# The census's own arithmetic.
# --------------------------------------------------------------------------

def test_an_unmeasured_clause_is_NOT_counted_CLEAN(census, tmp_path, capsys):
    """CLEAN used to be "everything that is not LIAR/SUSPECT/GUARDED", which
    folded the clauses no probe could measure into the clean count. Running the
    spelling probe alone printed `CLEAN 136` over 126 measurements.

    A census reporting a population it never reached is the shape this file
    exists to find, so it may not do it itself.
    """
    progs = _programs(tmp_path, no_path="""
        import sys
        print("[PASS] no_path"); sys.exit(0)
        """)
    census(_flow(tmp_path, """
    steps:
      - id: 9
        name: planted
        gate:
          all_of:
            - program_exit_zero: "no_path --strict input/docs/*.md"
    """), progs, "--probes", "spelling")
    out = capsys.readouterr().out
    assert "CLEAN       0" in out, out
    assert "N/A         1" in out, out

def test_ruler_blind_is_declined_when_the_gate_REWROTE_what_was_emptied(
        census, tmp_path, capsys, consumer_says):
    """Producer, not ruler. A gate that regenerates the artefact will always
    survive its deletion, and that says nothing about whether it measures it."""
    consumer_says("PASS")
    progs = _programs(tmp_path, producer="""
        import pathlib, sys
        pathlib.Path("out/evidence.json").read_text()
        pathlib.Path("out/evidence.json").write_text('{"violations": 0}')
        print("[PASS] regenerated"); sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("producer ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "REWROTE that file" in out, out


def test_ruler_blind_is_declined_when_a_SIBLING_conjunct_objects(
        census, tmp_path, capsys, consumer_says):
    """The measured version of #1051's `[sibling]` guard.

    The gate list is an `all_of`, so a conjunct that turns red on the same
    mutation makes the whole conjunction fail and this clause's rc 0 cannot
    wave anything through. #1051 could only read this off a DECLARED
    `files_exist` sibling; here the sibling is RUN, which also catches one that
    objects on substance.
    """
    consumer_says("PASS")
    progs = _programs(tmp_path, blind=_BLIND, strict="""
        import json, sys
        try:
            doc = json.load(open("out/evidence.json"))
        except Exception:
            doc = {}
        if "violations" not in doc:
            print("FAIL: evidence carries no measurement"); sys.exit(1)
        sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(
        clauses=_clauses("blind .", "strict ."))),
        progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "turns red on the same mutation" in out, out
    assert "strict" in out, out


def test_ruler_blind_is_declined_when_the_CONSUMER_moves_the_step_verdict(
        census, tmp_path, capsys, consumer_says):
    """The census's own first false positive, pinned.

    On `benchmark-data/ic/spm/v1.10.18_sky130A`, emptying
    `reports/phase3/ir_drop.json` leaves BOTH of step 24's gate clauses at rc 0
    -- and the flow still moves the step PASS-VOIDED -> FAIL, because
    `flow_compliance_check` owns an EVIDENCE_MISSING (#433) tier that reads
    emptiness directly. A gate-only probe scored that clause LIAR. Asking the
    consumer is what makes it a GUARDED.
    """
    consumer_says("PASS", "FAIL")   # pristine map, then the mutated map
    progs = _programs(tmp_path, blind=_BLIND)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("blind ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "PASS -> FAIL" in out, out
    assert "measured — just not here" in out, out


def test_ruler_blind_declines_a_step_whose_gate_is_NOT_WHAT_DECIDES(
        census, tmp_path, capsys, consumer_says):
    """Where the gate's rc is not the thing the step turns on, a blind ruler
    certifies nothing.

    `SKIPPED-CONDITION` is #1051's `[condition]` guard arriving from the
    consumer instead of from the YAML — same rule, read off the thing that
    actually decides.
    """
    consumer_says("SKIPPED-CONDITION")
    progs = _programs(tmp_path, blind=_BLIND)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("blind ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "not what the step turns on" in out, out


def test_ruler_blind_is_CAPPED_at_suspect_when_the_step_is_red_anyway(
        census, tmp_path, capsys, consumer_says):
    """Blindness measured, consequence unproven — and the two are said apart.

    The gate IS blind: the artefact went to zero bytes and nothing moved. But
    the step is FAIL on this root for some other reason, so the flow is not
    waving this particular emptiness through here. Promoting that to LIAR would
    be claiming a consequence the run did not measure.
    """
    consumer_says("FAIL")
    progs = _programs(tmp_path, blind=_BLIND)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("blind ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "SUSPECT" in out and "capped at SUSPECT" in out, out
    assert "LIAR        0" in out, out


def test_ruler_blind_only_mutates_what_the_STEP_DECLARES(
        census, tmp_path, capsys, consumer_says):
    """Reading a file is not enough; the flow has to have declared it.

    Without this the probe would accuse `l7_debug_access_grounding_check` of
    lying because emptying `L11_OTP_CONTENT.json` -- which it reads for context
    and which step D1 declares for a DIFFERENT clause -- does not move it.
    """
    consumer_says("PASS")
    progs = _programs(tmp_path, side="""
        import sys
        open("side/notes.txt").read()
        print("[PASS] read something undeclared"); sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/evidence.json": "{}", "side/notes.txt": "hello"})
    report = tmp_path / "census.json"
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("side ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus),
                "--json", str(report))
    out = capsys.readouterr().out
    assert rc == 0, out
    # N/A is not printed anywhere -- and an N/A that reads as CLEAN in the
    # summary is exactly the confident zero this file is about, so the
    # assertion goes to the machine-readable record rather than the text.
    probe = json.loads(report.read_text())["reports"][0]["probes"][0]
    assert probe["verdict"] == "N/A", probe
    assert "no declared artefact to empty" in probe["detail"], probe


# ------------------------------- P9: the gate as its own upstream ----------

_SELF_UPSTREAM = """
    import json, pathlib, sys
    prior = pathlib.Path("out/verdict.json")
    inherited = prior.read_text().strip() if prior.exists() else ""
    if not inherited:
        print("FAIL: nothing to stand on"); sys.exit(1)
    prior.write_text(json.dumps({"verdict": "PASS"}))
    print("[PASS] carried forward"); sys.exit(0)
    """

_CYCLE_STEP = """
    steps:
      - id: 77
        name: planted
        required_outputs:
          - out/verdict.json
        gate:
          all_of:
            - program_exit_zero: "{prog} ."
    """


# SHAPE 12 — "it measures a proxy, not the property"
#
# The controls here are the load-bearing part twice over. Measured on the real
# flow, `pass_without_reading` + `content_blind_pass` fire on ONE clause of 136,
# and a probe that reports 1/136 is one bad rule away from reporting 0/136 and
# being believed. So every tier and every guard has a planted known positive
# AND a planted known negative that differ in exactly one respect.
#
# CALIBRATION HONESTY: these are CONSTRUCTED fixtures, not restored history.
# The search for a real historical positive INSIDE the clause population was
# run and is reported in the PR: the two nearest real defects
# (`transition_coverage_check` / `path_delay_coverage_check`, #219 "an absent or
# hollow ATPG result must never read as a pass") both spawn a child process, so
# the probe declines to score them in either arm; and `e170de81`
# ("deliverable_verdict_consistency_check never read the completion audit it
# cited") is a program the flow declares no clause for. The one real in-tree
# positive the sweep did find, `vacuous_testbench_check`, is pinned separately
# in `test_the_real_sweep_still_finds_its_one_real_positive`.
# --------------------------------------------------------------------------



def test_self_upstream_fires_when_the_gate_reads_the_report_it_WROTE(
        census, tmp_path, capsys):
    """The literal shape: it opens its own report BEFORE writing it, and what
    it found there is what carried the verdict."""
    progs = _programs(tmp_path, carries=_SELF_UPSTREAM)
    corpus = _corpus(tmp_path, {"out/verdict.json": '{"verdict": "PASS"}'})
    rc = census(_flow(tmp_path, _CYCLE_STEP.format(prog="carries")),
                progs, "--probes", "cycle", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "reads its OWN report before writing it" in out, out
    assert "rc 0 -> 1" in out, out


def test_self_upstream_is_declined_when_the_read_is_a_READ_BACK(
        census, tmp_path, capsys):
    """Order is the whole discriminator.

    Same file, same two operations, opposite sequence: writing first and
    reading back is a value THIS run produced. A set-based view of the same
    trace cannot tell these two apart, which is why the tracer keeps order.
    """
    progs = _programs(tmp_path, readback="""
        import json, pathlib, sys
        p = pathlib.Path("out/verdict.json")
        p.write_text(json.dumps({"verdict": "PASS"}))
        assert json.loads(p.read_text())["verdict"] == "PASS"
        print("[PASS] wrote then verified"); sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/verdict.json": '{"verdict": "PASS"}'})
    rc = census(_flow(tmp_path, _CYCLE_STEP.format(prog="readback")),
                progs, "--probes", "cycle", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "only AFTER writing it" in out, out


def test_self_upstream_is_SUSPECT_when_the_cycle_is_not_load_bearing(
        census, tmp_path, capsys):
    """A cycle it does not lean on is reported, not promoted.

    The trace can only show that the artefact was opened. Whether the verdict
    RESTS on it is a separate question and it is answered by mutation, not by
    inference -- so this gate, which opens its own prior report and ignores it,
    is SUSPECT and says exactly why.
    """
    progs = _programs(tmp_path, ignores="""
        import json, pathlib, sys
        p = pathlib.Path("out/verdict.json")
        if p.exists():
            p.read_text()
        p.write_text(json.dumps({"verdict": "PASS"}))
        print("[PASS] did not care"); sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/verdict.json": '{"verdict": "PASS"}'})
    rc = census(_flow(tmp_path, _CYCLE_STEP.format(prog="ignores")),
                progs, "--probes", "cycle", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "not load-bearing on this root" in out, out
    assert "SUSPECT" in out, out


def test_self_upstream_is_SUSPECT_not_LIAR_when_the_gate_CRASHES(
        census, tmp_path, capsys):
    """A traceback is a robustness defect, not proof of laundering.

    Scoring it LIAR would be the census inferring a verdict from an exit code
    it did not understand -- which is the family it exists to find.
    """
    progs = _programs(tmp_path, crashes="""
        import json, pathlib, sys
        p = pathlib.Path("out/verdict.json")
        doc = json.loads(p.read_text())        # blows up on an empty file
        p.write_text(json.dumps(doc))
        print("[PASS]"); sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/verdict.json": '{"verdict": "PASS"}'})
    rc = census(_flow(tmp_path, _CYCLE_STEP.format(prog="crashes")),
                progs, "--probes", "cycle", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "CRASHES when that artefact is emptied" in out, out


# ------------------------------- the instrument's own failure modes --------



def test_a_tracer_that_did_not_load_scores_NA_and_NEVER_clean(
        census, tmp_path, capsys, monkeypatch):
    """`sitecustomize` loses to any earlier one on PYTHONPATH, and loses
    SILENTLY. A census that scored the resulting empty trace CLEAN would print
    a confident zero over a population it never observed -- so the tracer
    stamps a liveness marker and its absence is N/A, out loud.

    Simulated by handing the census a tracer dir with no tracer in it, which is
    exactly what a shadowed `sitecustomize` produces.
    """
    monkeypatch.setattr(lc, "make_tracer", lambda where: (where.mkdir(parents=True,
                        exist_ok=True) or where))
    progs = _programs(tmp_path, carries=_SELF_UPSTREAM)
    corpus = _corpus(tmp_path, {"out/verdict.json": '{"verdict": "PASS"}'})
    rc = census(_flow(tmp_path, _CYCLE_STEP.format(prog="carries")),
                progs, "--probes", "cycle", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out, out
    assert "tracer failed to load" in out, out
    assert "UNDERSTATES" in out, out


def test_a_corpus_that_reaches_NOTHING_says_so_instead_of_reporting_clean(
        census, tmp_path, capsys):
    """vibe-ic#1025's shape, in the census's own instrument: a corpus sweep
    that reached nothing unless the caller typed the right path depth. Reaching
    nothing and printing CLEAN is the confident zero this whole file exists to
    prevent."""
    progs = _programs(tmp_path, blind=_BLIND)
    empty = tmp_path / "no_such_corpus"
    empty.mkdir()
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("blind ."))),
                progs, "--probes", "ruler", "--corpus", str(empty))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "NO POPULATED CORPUS ROOT" in out, out
    assert "establishes NOTHING" in out, out


def test_the_corpus_root_is_found_by_STRUCTURE_not_by_a_path_list(tmp_path):
    """The root is recognised because one of its children is named by the first
    segment of a pattern the FLOW declares. Rename the layout in the flow and
    the discovery follows it; a hardcoded `benchmark-data/ic/...` list would
    not, and would rot in silence."""
    cl = lc.Clause(step="77", kind="program_exit_zero", cmd="x .", program="x",
                   step_outputs=["weird_layout/evidence.json"])
    corpus = tmp_path / "c"
    (corpus / "run1" / "weird_layout").mkdir(parents=True)
    (corpus / "run1" / "weird_layout" / "evidence.json").write_text("{}")
    (corpus / "decoy" / "unrelated").mkdir(parents=True)
    found = lc.discover_corpus_roots(corpus, [cl], limit=4)
    assert [p.name for p, _ in found] == ["run1"], found


def test_the_mutation_must_be_HOLLOW_and_not_merely_truncated(
        census, tmp_path, capsys, consumer_says):
    """The probe's own calibration failure, pinned so it cannot come back.

    This gate is blind to content and red on garbage: it parses the artefact
    and passes on ANY valid JSON. Truncating to zero bytes makes it exit 1 --
    the parser dies -- which reads exactly like a gate that measures what it
    reads. Only a mutation that stays VALID and carries NO CONTENT separates
    the two.

    That is not hypothetical. The first version of P6 truncated and nothing
    else, and calibrating it against the pre-#219 `transition_coverage_check`
    ("an absent or HOLLOW at-speed ATPG result must never read as a pass")
    returned CLEAN on the broken arm and CLEAN on the repaired one. A probe
    whose mutation kills every gate distinguishes none of them.
    """
    consumer_says("PASS")
    progs = _programs(tmp_path, parses_only="""
        import json, sys
        try:
            json.load(open("out/evidence.json"))
        except Exception:
            print("FAIL: evidence unreadable"); sys.exit(1)
        print("[PASS] it was JSON, so it must be fine"); sys.exit(0)
        """)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(_flow(tmp_path, _CORPUS_STEP.format(clauses=_clauses("parses_only ."))),
                progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "hollowed to {}" in out, out


def test_the_mutation_is_derived_from_the_ARTEFACT_not_from_a_schema():
    """`_mutations` reads the shape off the file, so it stays chip-AGNOSTIC and
    does not rot when a report gains a key."""
    d = Path(__file__).resolve().parent
    obj, arr, txt, empty = (d / "_m1.json", d / "_m2.json", d / "_m3.rpt", d / "_m4.json")
    try:
        obj.write_text('{"a": 1}')
        arr.write_text('[1, 2]')
        txt.write_text("not json at all")
        empty.write_text("{}")
        assert [p for _l, p in lc._mutations(obj)] == ["{}", ""]
        assert [p for _l, p in lc._mutations(arr)] == ["[]", ""]
        assert [p for _l, p in lc._mutations(txt)] == [""]
        # an ALREADY hollow container has no hollow mutation to make
        assert [p for _l, p in lc._mutations(empty)] == [""]
    finally:
        for f in (obj, arr, txt, empty):
            f.unlink(missing_ok=True)


def test_an_OR_alternative_whose_sibling_still_carries_content_is_declined(
        census, tmp_path, capsys, consumer_says):
    """`a OR b` means the step must deliver ONE of them.

    Hollowing `b` while `a` still carries the measurement removes nothing the
    flow asked for. Found by hand-adjudicating this probe's own step-9 finding,
    which sits on `phase2/stage2/synth/area.rpt OR .../stats.json` — that one
    survives because `area.rpt` is absent on the root, and it is only because
    the two cases are now distinguishable that it can be said to.
    """
    consumer_says("PASS")
    progs = _programs(tmp_path, blind="""
        import sys
        open("out/evidence.json").read()
        print("[PASS]"); sys.exit(0)
        """)
    flow = _flow(tmp_path, """
        steps:
          - id: 77
            name: planted
            required_outputs:
              - out/area.rpt OR out/evidence.json
            gate:
              all_of:
                - program_exit_zero: "blind ."
        """)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}',
                                "out/area.rpt": "area = 1234"})
    rc = census(flow, progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "ALTERNATIVE" in out and "out/area.rpt still carries content" in out, out


def test_an_OR_alternative_that_is_the_ONLY_satisfier_still_fires(
        census, tmp_path, capsys, consumer_says):
    """The other arm, and the one that keeps the step-9 finding standing: same
    declaration, same gate — the alternative simply is not there."""
    consumer_says("PASS")
    progs = _programs(tmp_path, blind="""
        import sys
        open("out/evidence.json").read()
        print("[PASS]"); sys.exit(0)
        """)
    flow = _flow(tmp_path, """
        steps:
          - id: 77
            name: planted
            required_outputs:
              - out/area.rpt OR out/evidence.json
            gate:
              all_of:
                - program_exit_zero: "blind ."
        """)
    corpus = _corpus(tmp_path, {"out/evidence.json": '{"violations": 7}'})
    rc = census(flow, progs, "--probes", "ruler", "--corpus", str(corpus))
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "ruler_blind" in out, out




























# --------------------------------------------------------------------------
# THE DENOMINATOR
#
# Every number this census ever published silently meant "of the ones I could
# see". These tests pin the two halves of the repair: the population is now
# WHOLE, and the disclosure that says so survives it being whole — because the
# next clause shape somebody invents must not drop out in silence the way
# `optional_program_exit_zero` did for the entire campaign.
# --------------------------------------------------------------------------

def test_all_three_clause_kinds_are_swept(tmp_path):
    kinds = {c.kind for c in lc.discover_clauses(lc.FLOW_YAML)}
    assert kinds == set(lc.CLAUSE_KINDS), kinds


def test_the_mapping_spelling_is_swept_as_well_as_the_string(tmp_path):
    """Three clauses were declared `{command: …}` instead of as a bare string
    and fell through `isinstance(val, str)` — one of them BLOCKING."""
    progs = {c.program for c in lc.discover_clauses(lc.FLOW_YAML)}
    assert "clock_plan_check" in progs                    # program_exit_zero, mapping
    assert "yosys_tiecell_recipe_order_check" in progs    # advisory, mapping
    assert "l10_tb_conformance_check" in progs            # optional, mapping


def test_nothing_the_flow_declares_is_left_unswept(tmp_path):
    pop = lc.population_report(lc.FLOW_YAML)
    assert pop["unswept"] == [], pop["unswept"]
    # 168 -> 169 -> 170 as the flow gained a clause. The PIN is
    # `swept == declared`; the literal is only there so a flow that silently
    # SHRINKS is caught too, and it is meant to move whenever the flow does.
    #
    # 169 -> 170 at 74b6abbe35 ("feat(lvs): read magic's extraction feedback
    # channel and gate it at zero, before netgen"), which added exactly ONE
    # clause -- `program_exit_zero: magic_illegal_overlap_check`. MEASURED over
    # the flow YAML at each commit: 772c31dcb4 (the commit that last moved this
    # literal) 169, 74b6abbe35^ 169, 74b6abbe35 170, HEAD 170, with the added
    # clause set exactly {('program_exit_zero', 'magic_illegal_overlap_check')}
    # and nothing removed. The literal did not move with it, so the calibration
    # instrument's own control has been red on main ever since.
    # 170 -> 175 at int/tonight. MEASURED with `liar_census.population_report`
    # over BOTH trees rather than inferred: origin/main declared=170 swept=170
    # (so the literal was CURRENT on main, not stale as the paragraph above
    # records for an earlier round), int/tonight declared=175 swept=175. The
    # five added clauses are the gates of the five half-steps the chip/IP split
    # introduced -- 0.5ic submission_template_check, 15.5ic pad_ring_check,
    # 26.5ic die_finishing_check, 37.5ip digital_hardmacro_check, 37.5ic
    # tapeout_readiness_check -- one `program_exit_zero` each, and nothing was
    # removed. The PIN `swept == declared` never broke; only the shrink-detector
    # literal needed to follow the flow, which is what it is for.
    # 175 -> 178. MEASURED the same way, over the flow YAML blob at each commit
    # with `liar_census.population_report`, and the CLAUSE SET diffed rather than
    # the count compared: 03f7b945d7 (the commit that last moved this literal)
    # declared=175 swept=175, 46db018669 (origin/main) declared=178 swept=178.
    # The three added clauses, attributed to the commits that added them, are
    #   69ce9260d  program_exit_zero: tapeout_docs_gen --project . --out-dir
    #                                 reports/phase3/docs
    #   00d9dc261  program_exit_zero: general_precheck . --json
    #                                 reports/phase3/general_precheck.json
    #   00d9dc261  program_exit_zero: tapeout_declaration_check . --json
    #                                 reports/phase1/tapeout_declaration.json
    # and the REMOVED set is empty, so this is a grow and not a churn. `by_kind`
    # moves 110 -> 113 `program_exit_zero` with `advisory` 37 and `optional` 28
    # unchanged, and `unswept`/`unrecognised` stay empty on both trees.
    #
    # THIRD TIME THIS LITERAL HAS LAGGED THE FLOW (169->170, 170->175, 175->178).
    # A hand-maintained number that must be remembered by an author who is
    # editing a different file is prose wearing an assertion, and this file
    # cannot fix that alone: making the detector derive its floor from the
    # PREVIOUS flow blob would catch every shrink with nothing to remember, but
    # it would also leave a DELIBERATE shrink no way to be authorised. That is a
    # call for the flow's owner, so it is written down here rather than taken.
    # 178 -> 180 -> 179, and the middle step is not mine. RE-DERIVED the way
    # the block above derives its own: `discover_clauses` over the flow yaml at
    # `03f7b945d` (the commit that last moved this literal), at `053eecd27`
    # (main) and on this branch, CLAUSE SETS diffed rather than counts compared.
    #
    #   pin @03f7b945d  175      main @053eecd27  180      branch  179
    #
    # FIVE clauses arrived since the literal was last moved and NONE of them
    # moved it, which is the FOURTH time this file records that happening:
    #   + 0.5ic    program_exit_zero           tapeout_declaration_check
    #   + 37.5ic   program_exit_zero           tapeout_docs_gen
    #   + 37.5self program_exit_zero           general_precheck    (retired below)
    #   + 9        program_exit_zero           area_total_vs_budget_check   (ppa-loop)
    #   + 36       optional_program_exit_zero  ppa_head_to_head_check       (ppa-h2h)
    # and the REMOVED set against the pin is empty. The last two landed after
    # this literal was last touched and are the reason main itself measures 180
    # against a literal of 178 — main is RED here right now, and that is not
    # this change's doing.
    #
    # THIS CHANGE retires step `37.5self` and folds the general precheck into
    # `37.5ic` as a second ARM, so 37.5ic's gate names ONE program that runs
    # both ladders:
    #   + 37.5ic   program_exit_zero  tapeout_precheck
    #   - 37.5ic   program_exit_zero  tapeout_readiness_check
    #   - 37.5self program_exit_zero  general_precheck
    # 180 + 1 - 2 = 179. `by_kind` moves 114 -> 113 `program_exit_zero` with
    # `advisory` 37 and `optional` 29 unchanged; `unswept`/`unrecognised` stay
    # empty on both trees.
    #
    # 181 -> 182, FOURTH TIME THIS LITERAL HAS LAGGED THE FLOW. RE-DERIVED the
    # way every block above derives its own: `discover_clauses` over the flow YAML
    # blob at 100af53b4 (the commit that last moved this literal) and at HEAD, with
    # the CLAUSE SETS diffed on the identity the census uses -- (step, kind, cmd) --
    # rather than the counts compared. MEASURED:
    #
    #   100af53b4   declared=181 swept=181 unswept=0 unrecognised=0
    #   HEAD        declared=182 swept=182 unswept=0 unrecognised=0
    #
    #   ADDED   1   step 2  program_exit_zero
    #                       slot_pad_budget_check . --json reports/phase2/gates/slot_pad_budget.json
    #   REMOVED 0
    #
    # So it is a GROW and not a churn, and the PIN `swept == declared` never broke:
    # 182 == 182 on this tree, `unswept` and `unrecognised` both empty. Only the
    # shrink-detector literal needed to follow the flow, which is what it is for.
    #
    # THE ADDED CLAUSE IS NOT INCIDENTAL. `slot_pad_budget_check` is one of the
    # three checkers `checker execution wiring` reported as run by nothing but
    # their own tests. Wiring it into the flow is what turned that gate green --
    # and it is the same edit that grew this count. One repair, two rows.
    #
    # A FIRST DIFF OF MINE SAID "CHURN, DO NOT MOVE IT", AND IT WAS WRONG: the key
    # fell through to the dataclass repr, which carries fields the census does not
    # identify a clause by, so 14 unchanged clauses showed as added AND removed.
    # Recorded because the false verdict was the safe-looking one, and a diff key
    # that reports churn over identical commands would have blocked a legitimate
    # follow for as long as anyone believed it.
    # A SHRINK IS EXACTLY WHAT THIS LITERAL EXISTS FOR, and the block above
    # states the open question as "a DELIBERATE shrink has no way to be
    # authorised". This is one, and the authorisation is written here:
    # TWO GATES STOPPED BEING FLOW CLAUSES WITHOUT STOPPING BEING RUN. Both are
    # now ARMS that `tapeout_precheck` dispatches, and the venue that proves
    # they are still reached is `flow_gate_enforcement_audit`'s FOURTH venue —
    # a transitive dispatch closure seeded only by the flow definition, added
    # in this same change. Before it, that audit reported both of them
    # `ORPHANED`, i.e. "reachable from nothing at all", which was false.
    #
    # 179 -> 181, AND THE 179 NEVER MATCHED A TREE. RE-DERIVED with
    # `population_delta` -- added in this change, and added BECAUSE of what the
    # re-derivation found -- over the flow blob at each commit, CLAUSE SETS
    # diffed rather than counts compared:
    #
    #   053eecd27 (the base the block above measured)   180
    #   7fcbc7397 ppa(phase4): step 13 ... second relation
    #   867de4289^ (the parent 867de4289 LANDED ON)     181
    #   867de4289 (the commit that last moved this literal, set it to 179)  180
    #   790224904 flow(chip path): a pad ring and a seal ring too
    #   HEAD                                            181
    #
    # THE BLOCK ABOVE IS ARITHMETICALLY RIGHT AND WAS MEASURED AGAINST A BASE
    # THAT MOVED. `180 + 1 - 2 = 179` is exact against `053eecd27`, which is
    # where that branch started. `7fcbc7397` landed one clause while the branch
    # was open, so the parent it actually merged onto measured 181, and the
    # landed tree was `181 + 1 - 2 = 180` against a literal of 179. IT WAS RED
    # ON ARRIVAL -- not lagging, wrong on the day -- and `790224904` then added
    #   + 15.5ic  program_exit_zero  pad_assignment_gen . --json
    #                                reports/phase3/pad_assignment.json
    # which is the whole of the delta from `867de4289` to HEAD. The REMOVED set
    # against that commit is EMPTY, so this is a GROW and no shrink is being
    # authorised here. `by_kind` moves 114 -> 115 `program_exit_zero` with
    # `advisory` 37 and `optional` 29 unchanged; `unswept` and `unrecognised`
    # are empty on both trees, so the SWEEP was never what was broken -- the
    # census reads every clause the flow declares and this literal is the only
    # thing in this test that was ever wrong.
    #
    # FIFTH ROUND, AND THE FIRST ONE THE PROSE ITSELF LOST. Four rounds above
    # record the literal LAGGING; this one records the derivation being CORRECT
    # AGAINST THE WRONG TREE, which no amount of care in a comment block can
    # prevent, because the fact it depends on -- what the parent measures at the
    # moment of landing -- is not knowable when the comment is written. So the
    # protocol every one of those rounds describes in prose ("MEASURED ... the
    # CLAUSE SET diffed rather than the count compared") is now a function,
    # `liar_census.population_delta`, with its own controls below. It reports
    # `added` and `removed` SEPARATELY, so a GROW, a SHRINK and a CHURN are
    # three different answers rather than one number that cannot tell them
    # apart. It still decides nothing: the open question the block above states
    # -- how a DELIBERATE shrink is authorised -- is still the flow owner's to
    # answer, and is deliberately NOT answered here. What is fixed is that the
    # next author can MEASURE the delta against the tree they are landing on
    # instead of reconstructing it by hand from a base that may have moved.
    # 181 -> 182, AND IT IS THE "BASE THAT MOVED" SHAPE AGAIN -- the exact
    # failure the commit that last set this literal was named for
    # (100af53b47, "the shrink pin was measured against a base that moved, not
    # a sweep that missed"). RE-DERIVED the way every block above derives its
    # own: `population_report` over the flow YAML BLOB at each commit, CLAUSE
    # SETS diffed rather than counts compared.
    #
    #   pin @100af53b47   declared=181 swept=181
    #   main @a4caccefea  declared=182 swept=182
    #   HEAD              declared=182 swept=182
    #
    # ONE clause arrived and NOTHING was removed, so this is a grow and not a
    # churn:
    #   + step 2   program_exit_zero   slot_pad_budget_check
    # attributed to 34466e7262 ("flow(#1347): the pad-budget gate answers
    # before the build, not after it").
    #
    # WHY THE LITERAL LAGGED, MEASURED RATHER THAN GUESSED: the pin commit and
    # the adding commit are on PARALLEL branches -- neither is an ancestor of
    # the other, both landed on main, both dated 2026-08-21. So the literal was
    # CURRENT against the tree its author measured and stale against the trunk
    # the moment the other branch landed. That is the FIFTH time this file
    # records the literal lagging, and the second time it lagged for this
    # reason specifically; the open question stated two blocks above -- a
    # hand-maintained number an author must remember while editing a different
    # file -- is unchanged and is still the flow owner's call.
    #
    # `by_kind` moves 115 -> 116 `program_exit_zero` with `advisory` 37 and
    # `optional` 29 unchanged; `unswept` and `unrecognised` are empty on all
    # three trees.
    #
    # 182 -> 217, A GROW OF 35 WITH NOTHING REMOVED. RE-DERIVED the way every
    # block above derives its own, but with `population_delta` -- the function
    # the block above installed for exactly this -- over the flow YAML BLOB at
    # each commit, CLAUSE SETS diffed rather than counts compared:
    #
    #   pin @fe27b28b7 (main)  declared=182 swept=182 unswept=0 unrecognised=0
    #   HEAD                   declared=217 swept=217 unswept=0 unrecognised=0
    #   population_delta       before=182 after=217 added=35 removed=0
    #                          shrank=False
    #
    # THE SWEEP WAS NEVER WHAT WAS BROKEN, and this is the first round where
    # that had to be CHECKED rather than assumed. The change under this literal
    # wires 86 previously-orphaned programs back into the flow, so "the census
    # newly sees 35 things it did not see before" is also the shape a MISSED
    # SWEEP would have -- a declaration the parser cannot read is counted in
    # `declared` and absent from `swept`. It is not that: `swept == declared`
    # holds on BOTH trees, and `unswept` and `unrecognised` are empty on both,
    # so every one of the 35 is parsed, swept and probed. NARROWING the census
    # to make this literal true again would be the exact failure this test
    # exists to catch, and is not what moved.
    #
    # The REMOVED set is EMPTY, so this authorises no shrink and the open
    # question two blocks above -- how a DELIBERATE shrink is authorised --
    # stays open and stays the flow owner's.
    #
    # `by_kind` moves `advisory_program_exit_zero` 37 -> 72 with
    # `program_exit_zero` 116 and `optional_program_exit_zero` 29 UNCHANGED --
    # the whole delta is advisory -- and `non_program` stays
    # `{json_field_true: 1}`.
    #
    # WHAT DID NOT MOVE, measured because "the instrument changed" is the other
    # way a population jumps and a comment cannot tell the two apart: over
    # `fe27b28b7..HEAD`, `tools/liar_census.py` and this file carry ZERO
    # changed lines. The only file in that diff the census reads is the flow
    # YAML itself, +718/-1. The census did not start counting differently; the
    # flow got bigger.
    # 217 -> 221, FIFTH TIME THIS LITERAL HAS LAGGED THE FLOW. RE-DERIVED the way
    # every block above derives its own: `population_report` over the flow YAML blob
    # at 57cf2814c (the commit that last moved this literal) and at HEAD, with the
    # CLAUSE SETS diffed on the identity the census uses -- (step, kind, cmd) --
    # rather than the counts compared. MEASURED:
    #
    #   57cf2814c   declared=217 swept=217 unswept=0 unrecognised=0
    #   HEAD        declared=221 swept=221 unswept=0 unrecognised=0
    #   ADDED 14    REMOVED 10        217 + 14 - 10 = 221
    #
    # `by_kind` moves advisory_program_exit_zero 72 -> 76 with program_exit_zero
    # 116 and optional_program_exit_zero 29 BOTH UNCHANGED, which is the shape that
    # says no blocking gate was added or lost in the move.
    #
    # TEN REMOVED AND NOT ONE RETIREMENT. Nine of the ten are the same clause with
    # its command string EDITED, and `(step, kind, cmd)` cannot see that:
    #   * six `provenance_check` clauses gained ` --require-measured` -- a
    #     TIGHTENING, at steps 9, 21, 22, 31 (x2) and 37;
    #   * two clauses at steps 4 and 6 follow `coverage_actual.json` ->
    #     `coverage_verilator.json`;
    #   * step 32's `eco_loop_audit` is `postroute_timing_repair_audit` since
    #     c4fba40c4 renamed it.
    # The tenth, step 31's `perc_corpus_sweep .`, gained ` --report ...` and its
    # bare form is still declared elsewhere, so it never reached `unaccounted`.
    # Each of the nine is named against its live successor, and ASSERTED to still
    # be live, by `_REHOMED` below -- prose here, a control that runs there.
    assert pop["swept"] == pop["declared"] == 221, pop
    assert pop["unrecognised"] == {}, pop["unrecognised"]


# --------------------------------------------------------------------------
# THE SHRINK PIN'S OWN PROTOCOL, EXECUTABLE
#
# The literal above is moved by hand, and the block that authorises each move
# derives it by DIFFING CLAUSE SETS between two flow blobs -- because a count
# cannot tell a grow from a churn, and "which clause left" is the only answer
# worth having. That derivation was prose for five rounds and on the fifth it
# failed exactly as prose fails: computed against a base that moved, never
# re-run, landed red. `population_delta` is that protocol as a function. These
# controls pin that it can DECIDE the three directions apart -- if it answered
# the same way for a grow, a shrink and a churn it would be a vacuous green and
# strictly worse than the hand-diff it replaces.
# --------------------------------------------------------------------------

def _delta_flow(where: Path, yaml_text: str) -> Path:
    """`_flow` writes a fixed filename, so two blobs need two directories."""
    where.mkdir(parents=True, exist_ok=True)
    return _flow(where, yaml_text)


_DELTA_BEFORE = """
    steps:
      - id: 9
        name: planted
        gate:
          all_of:
            - program_exit_zero: "alpha ."
            - program_exit_zero: "beta ."
    """

_DELTA_GROW = """
    steps:
      - id: 9
        name: planted
        gate:
          all_of:
            - program_exit_zero: "alpha ."
            - program_exit_zero: "beta ."
            - program_exit_zero: "gamma ."
    """

_DELTA_SHRINK = """
    steps:
      - id: 9
        name: planted
        gate:
          all_of:
            - program_exit_zero: "alpha ."
    """

_DELTA_CHURN = """
    steps:
      - id: 9
        name: planted
        gate:
          all_of:
            - program_exit_zero: "alpha ."
            - program_exit_zero: "gamma ."
    """


def test_a_grow_is_named_clause_by_clause(tmp_path):
    """The direction the literal has moved in four of its five rounds."""
    d = lc.population_delta(_delta_flow(tmp_path / "a", _DELTA_BEFORE),
                            _delta_flow(tmp_path / "b", _DELTA_GROW))
    assert d["before"] == 2 and d["after"] == 3, d
    assert [c["cmd"] for c in d["added"]] == ["gamma ."], d["added"]
    assert d["removed"] == [], d["removed"]
    assert d["shrank"] is False, d


def test_a_shrink_NAMES_the_clause_that_left(tmp_path):
    """The direction the literal exists for. `shrank` is not enough on its own
    -- a reader asked to authorise a removal needs to be told WHAT was removed,
    which is the question a count can never answer."""
    d = lc.population_delta(_delta_flow(tmp_path / "a", _DELTA_BEFORE),
                            _delta_flow(tmp_path / "b", _DELTA_SHRINK))
    assert d["before"] == 2 and d["after"] == 1, d
    assert [c["cmd"] for c in d["removed"]] == ["beta ."], d["removed"]
    assert d["added"] == [], d["added"]
    assert d["shrank"] is True, d


def test_a_CHURN_is_not_invisible_the_way_it_is_to_a_count(tmp_path):
    """THE REASON THIS IS NOT THE LITERAL. `before == after == 2`, so the pin
    above would be green in both directions and report nothing at all, while a
    BLOCKING clause has silently left the flow and a different one has taken its
    slot. Every round's comment block says it diffed the SETS rather than
    comparing the counts; this is what that sentence is protecting against."""
    d = lc.population_delta(_delta_flow(tmp_path / "a", _DELTA_BEFORE),
                            _delta_flow(tmp_path / "b", _DELTA_CHURN))
    assert d["before"] == d["after"] == 2, d
    assert [c["cmd"] for c in d["added"]] == ["gamma ."], d["added"]
    assert [c["cmd"] for c in d["removed"]] == ["beta ."], d["removed"]
    assert d["shrank"] is True, d


def test_the_identity_keeps_the_cmd_and_not_just_the_program(tmp_path):
    """An identity projected onto `(step, kind, program)` folds two clauses that
    differ only in their arguments into one, so removing either reports NO
    CHANGE: a blocking clause leaves the flow and the instrument says nothing.

    TWO HALVES, AND NEITHER NAMES A STEP. The behaviour is pinned on planted
    blobs, which cannot rot. The flow is then asked whether it actually CONTAINS
    such a pair -- DERIVED by grouping, never a typed `("31", ...) == 2`, which
    would be a third hand-maintained coupling to the flow in the same file whose
    whole subject is that hand-maintained couplings rot. Today exactly one group
    qualifies; if the flow ever has none, `cmd` stops being load-bearing HERE
    without becoming wrong, so that half DISCLOSES and skips rather than
    reddening on a change that broke nothing."""
    kept = _delta_flow(tmp_path / "a", """
        steps:
          - id: 99
            name: planted
            gate:
              all_of:
                - program_exit_zero: "planted_check . --output one.rpt"
                - program_exit_zero: "planted_check . --output two.rpt"
        """)
    one_left = _delta_flow(tmp_path / "b", """
        steps:
          - id: 99
            name: planted
            gate:
              all_of:
                - program_exit_zero: "planted_check . --output one.rpt"
        """)
    d = lc.population_delta(kept, one_left)
    assert d["before"] == 2 and d["after"] == 1, d
    assert [c["cmd"] for c in d["removed"]] == [
        "planted_check . --output two.rpt"], d["removed"]
    assert d["shrank"] is True, d

    # ... and the real flow, derived. The claim worth making is not "a group
    # exists" -- restating the filter that built the group would be a tautology
    # -- it is that the WEAKER identity LOSES CLAUSES on this flow: fold the
    # arguments away and the population shrinks, which is precisely the silent
    # removal `population_delta` must never report as no change.
    clauses = lc.discover_clauses(lc.FLOW_YAML)
    keeping_cmd = {(c.step, c.kind, c.cmd) for c in clauses}
    folding_cmd = {(c.step, c.kind, c.program) for c in clauses}
    if len(keeping_cmd) == len(folding_cmd):
        pytest.skip("no clause group in the flow shares (step, kind, program) "
                    "with differing arguments today, so this flow cannot tell "
                    "the two identities apart -- pinned on the fixture above")
    assert len(keeping_cmd) > len(folding_cmd), (
        len(keeping_cmd), len(folding_cmd))
    assert len(keeping_cmd) == len(clauses), (
        "every clause is distinct under the identity population_delta uses",
        len(keeping_cmd), len(clauses))


def test_two_clauses_that_are_IDENTICAL_are_two_and_not_one(tmp_path):
    """Why the comparison is a MULTISET and not a set.

    HONESTY NOTE, because the first version of this control was vacuous: the
    flow as it stands declares NO two clauses with the same `(step, kind, cmd)`
    -- 181 clauses, 181 distinct triples -- so nothing in the real flow can tell
    a set from a multiset today, and a control that only looked at the real flow
    would pass against either and pin nothing. It is pinned HERE, on a planted
    duplicate, because the shape is one line of copy-paste away in a 6300-line
    YAML: declare a clause twice, delete one copy, and a set-based diff reports
    the flow unchanged while the gate's redundancy is gone."""
    twice = _delta_flow(tmp_path / "a", """
        steps:
          - id: 9
            name: planted
            gate:
              all_of:
                - program_exit_zero: "alpha ."
                - program_exit_zero: "alpha ."
        """)
    once = _delta_flow(tmp_path / "b", """
        steps:
          - id: 9
            name: planted
            gate:
              all_of:
                - program_exit_zero: "alpha ."
        """)
    d = lc.population_delta(twice, once)
    assert d["before"] == 2 and d["after"] == 1, d
    assert [c["cmd"] for c in d["removed"]] == ["alpha ."], d["removed"]
    assert d["shrank"] is True, d


#: The commit whose flow blob this shrink-detector measures against, and what
#: that blob declares. BOTH move together or the assertion below is comparing a
#: count to a different tree's population -- which is the exact failure the
#: "base that moved" blocks above record, five times.
# PIN MOVED e265f228be -> d760471ed (v1.12.40), AND IT AUTHORISES A TEN-CLAUSE
# CHURN. `d760471ed` is not chosen for being recent: it is the OLDEST commit
# whose flow blob has `population_delta(pin, HEAD)["removed"] == []`, MEASURED by
# walking all 17 commits that touched the flow YAML since the old pin and
# reporting `removed_vs_HEAD` for each (14, 16, 17, 11, 13, 16, 16, 14, 13, 10,
# 8, 8, 7, 7, 6, 0, 0). Taking the newest instead would blind the detector to
# every commit in between for nothing; taking anything older leaves a removal in
# the window that this change has not authorised.
#
# WHAT THE MOVE AUTHORISES is set out clause by clause beside the census literal
# above, and NONE of it is a retirement -- every removed command has a live
# successor. The half of that authorisation which RUNS is `_REHOMED`, below.
_SHRINK_PIN = "d760471ed"
_SHRINK_PIN_DECLARED = 220

#: The pin this one replaced, kept because the control below is anchored to it
#: permanently: it is the only tree in this repository's history that can
#: demonstrate a RE-HOMING, and a control that loses its stimulus stops being a
#: control without stopping being green.
_REHOME_PIN = "867de4289"
_REHOME_CMD_PREFIX = "crosslayer_rewrite_equivalence_check ."

#: Removed command -> the live command that succeeds it, for every clause that
#: has left the flow since `_REHOME_PIN` by having its command string EDITED.
#:
#: WHY A TABLE AND NOT A WIDER MATCH. `population_delta` identifies a clause by
#: `(step, kind, cmd)`, and the control below reads a removal whose cmd is not
#: declared today as a RETIREMENT. That is the right default -- it is how a gate
#: being switched off is caught -- but a command string legitimately changes
#: when a flag is added, a path is renamed, or a program is renamed, and the
#: exact-string test cannot tell that from a deletion. Relaxing the match to a
#: prefix or a program name would make the deletion invisible too, which is
#: making the check pass by deleting what it checks. So the distinction is made
#: HERE, one named row at a time, and every row is ASSERTED -- a successor that
#: stops being live reddens this control instead of quietly excusing a removal.
#:
#: THIS PIN IS PERMANENT, so this table only ever grows; that is the cost of the
#: control keeping its stimulus, and it is paid one line per authored edit.
_REHOMED = {
    # NO ROW FOR THE 1.6x CLAUSE, and that is the point of the shape. vibe-ic#1779
    # folded step `1.6x` into step `2` and the gate moved BYTE FOR BYTE, so its
    # command is still in `live` under its own spelling and the exact-string test
    # accounts for it with nothing written here. This table is only ever for the
    # narrower case the exact-string test cannot see: the command itself changed.
    # d760471ed: six provenance gates gained ` --require-measured`. A
    # TIGHTENING -- the clause is strictly harder to satisfy than before, so
    # reading it as a retirement had the sign backwards.
    "provenance_check . --output phase2/stage2/synth/netlist.v "
    "--tool yosys,yosys-abc":
    "provenance_check . --output phase2/stage2/synth/netlist.v "
    "--tool yosys,yosys-abc --require-measured",
    "provenance_check . --output phase3/stage3/pnr/routed.def --tool openroad":
    "provenance_check . --output phase3/stage3/pnr/routed.def "
    "--tool openroad --require-measured",
    "provenance_check . --output phase3/stage3/extracted/*.spef "
    "--tool magic,openroad":
    "provenance_check . --output phase3/stage3/extracted/*.spef "
    "--tool magic,openroad --require-measured",
    "provenance_check . --output reports/phase3/drc_signoff.rpt "
    "--tool klayout,magic,svrfdrc":
    "provenance_check . --output reports/phase3/drc_signoff.rpt "
    "--tool klayout,magic,svrfdrc --require-measured",
    "provenance_check . --output reports/phase3/lvs.rpt "
    "--tool netgen,magic,klayout":
    "provenance_check . --output reports/phase3/lvs.rpt "
    "--tool netgen,magic,klayout --require-measured",
    "provenance_check . --output=phase3/stage4/gds/*.gds "
    "--tool=klayout,magic,openroad":
    "provenance_check . --output=phase3/stage4/gds/*.gds "
    "--tool=klayout,magic,openroad --require-measured",
    # The coverage artefact was renamed to name its producer, so the two
    # clauses that read it followed it.
    "verilator_coverage_measure check --coverage-json "
    "reports/phase2/coverage/coverage_actual.json":
    "verilator_coverage_measure check --coverage-json "
    "reports/phase2/coverage/coverage_verilator.json",
    "fpga_verification_audit --report reports/fpga_verification_report.md "
    "--summary phase2/stage1/sim/work/summary.txt --coverage "
    "reports/phase2/coverage/coverage_actual.json --out "
    "reports/phase2/gates/fpga_verification_audit.json":
    "fpga_verification_audit --report reports/fpga_verification_report.md "
    "--summary phase2/stage1/sim/work/summary.txt --coverage "
    "reports/phase2/coverage/coverage_verilator.json --out "
    "reports/phase2/gates/fpga_verification_audit.json",
    # c4fba40c4 reserved "ECO" for physical changes; step 32 regenerates RTL,
    # so its audit is `postroute_timing_repair_audit` now. Same clause, same
    # step, same kind (`optional_program_exit_zero`), renamed program.
    "eco_loop_audit . --json reports/phase2/gates/eco_audit.json":
    "postroute_timing_repair_audit . --json "
    "reports/phase2/gates/postroute_timing_repair_audit.json",
}


def test_the_flow_has_NOT_shrunk_since_the_literal_was_last_moved(tmp_path):
    """The pin above is a count and this is its other half: that the move was a
    GROW and not a churn. Measured against the flow blob at the commit that last
    moved the literal, read out of git rather than copied into this file -- a
    fixture copy would rot into the prose the delta function exists to replace.
    SKIPS rather than lies where the history is not available (a shallow clone,
    an exported tarball).

    PIN MOVED 867de4289 -> e265f228be (2026-08-24), AND IT IS A DELIBERATE
    SHRINK BEING AUTHORISED -- the third time this file has had to do that, and
    the first where the clause did not stop being a flow clause at all.

    MEASURED with `population_delta` over the two blobs, clause SETS diffed on
    the identity the census uses, not counts compared:

        867de4289   declared=180
        e265f228be  declared=182
        ADDED   3   15.5ic program_exit_zero pad_assignment_gen ...
                    2      program_exit_zero slot_pad_budget_check ...
                    2      program_exit_zero crosslayer_rewrite_equivalence_check ...
        REMOVED 1   1.6x   program_exit_zero crosslayer_rewrite_equivalence_check ...

    THE AUTHORISATION, and it is the weakest shrink this file has ever had to
    authorise: the removed clause and one of the added clauses are the SAME
    COMMAND. vibe-ic#1779 folded step `1.6x` into step `2`; the gate moved with
    it, byte for byte. A clause's identity here is `(step, kind, cmd)`, so a
    step RENUMBER reads as a removal plus an addition even though nothing was
    retired and nothing stopped running.

    That is not a defect in `population_delta` -- widening the identity to
    ignore the step would blind it to a gate silently moving to a step that
    never runs, which is a real way to switch a gate off. It is a shape the
    identity cannot distinguish on its own, so the distinction is made HERE, by
    a control that runs rather than by this paragraph:
    `test_the_1_6x_clause_was_REHOMED_and_not_retired` below pins the old
    commit permanently and asserts the removed command is still declared
    somewhere in the live flow. Delete that control and this authorisation
    becomes prose again."""
    # BOUNDED AT `_T` like every other subprocess this file starts. The harness
    # note beside this gate records that the 180 s session bound is gone and
    # that these inner bounds are now the ONLY one, so an unbounded `git` here
    # would be a hang with nothing above it to cut -- and `git` in this repo
    # contends with a large worktree set, so "it is only a `git show`" is the
    # reasoning, not the measurement. A timeout is the same class of answer as
    # a non-zero rc -- the history could not be read -- so it SKIPS too, and
    # says which of the two happened rather than reporting one as the other.
    try:
        blob = subprocess.run(
            ["git", "show", _SHRINK_PIN + ":vibe-ic-marketplace/plugins/vibe-ic/"
             "flow/phase1_phase2_phase3.yaml"],
            cwd=Path(lc.__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=_T)
    except subprocess.TimeoutExpired:
        pytest.skip(f"`git show` did not answer within {_T}s — the flow blob at "
                    f"{_SHRINK_PIN} could not be read, so nothing is claimed here")
    if blob.returncode != 0:
        pytest.skip(f"flow blob at {_SHRINK_PIN} is not in this checkout's history")
    pinned = tmp_path / "pinned.yaml"
    pinned.write_text(blob.stdout)

    d = lc.population_delta(pinned, lc.FLOW_YAML)
    assert d["removed"] == [], d["removed"]
    assert d["shrank"] is False, d
    # A FIXED COMMIT's blob, so this number is history and cannot rot. The
    # previous pin (867de4289) measured 180 -- not the 179 its own commit set
    # the literal to, which was the red this control would have named on the
    # day and is recorded in the block above rather than smoothed over.
    assert d["before"] == _SHRINK_PIN_DECLARED, d
    # DERIVED, NEVER TYPED. Writing `== 181` here would put a SECOND literal in
    # this file that a flow author has to remember, which is the disease this
    # whole change is treating -- the next grow would redden two controls
    # instead of one and this one would teach nothing the pin had not already
    # said. Cross-checking the two instruments against the SAME tree is the
    # assertion actually worth making, and it survives every grow.
    assert d["after"] == lc.population_report(lc.FLOW_YAML)["declared"], d



def test_the_1_6x_clause_was_REHOMED_and_not_retired(tmp_path):
    """The half of the shrink authorisation above that RUNS.

    `population_delta` identifies a clause by `(step, kind, cmd)`, so folding
    step `1.6x` into step `2` (vibe-ic#1779) reads as one removal and one
    addition of the SAME command. The paragraph above says that is a re-homing;
    this asserts it, against the tree where the removal is still visible.

    PINNED AT THE OLD COMMIT ON PURPOSE. Anchoring this to `_SHRINK_PIN` would
    make it vacuous the moment the pin moved -- the removal it exists to
    examine would no longer be in the delta, `removed` would be empty, and the
    assertion would pass over nothing. `_REHOME_PIN` is the only tree that can
    still supply the stimulus, so it is fixed there and the vacuity is checked
    rather than assumed.

    WHAT WOULD MAKE THIS RED, and each is a real defect rather than a rename:
      * the gate is deleted from the flow entirely -> `still_declared` empty;
      * the gate is moved to a step whose gate clause spells the command
        differently -> the removed cmd matches nothing;
      * some OTHER clause is removed between the pin and HEAD and never
        re-homed -> it appears in `unaccounted`.
    """
    try:
        blob = subprocess.run(
            ["git", "show", _REHOME_PIN + ":vibe-ic-marketplace/plugins/vibe-ic/"
             "flow/phase1_phase2_phase3.yaml"],
            cwd=Path(lc.__file__).resolve().parent.parent,
            capture_output=True, text=True, timeout=_T)
    except subprocess.TimeoutExpired:
        pytest.skip(f"`git show` did not answer within {_T}s — the flow blob at "
                    f"{_REHOME_PIN} could not be read, so nothing is claimed here")
    if blob.returncode != 0:
        pytest.skip(f"flow blob at {_REHOME_PIN} is not in this checkout's history")
    pinned = tmp_path / "rehome.yaml"
    pinned.write_text(blob.stdout)

    d = lc.population_delta(pinned, lc.FLOW_YAML)

    # NOT VACUOUS: this pin must still show the removal, or this test is
    # asserting a property of an empty list.
    assert d["removed"], (
        f"no clause is removed between {_REHOME_PIN} and HEAD, so this control "
        "has lost its stimulus — the re-homing it exists to prove can no longer "
        "be observed from here"
    )

    live = {c.cmd for c in lc.discover_clauses(lc.FLOW_YAML)}

    # THE AUTHORISATION TABLE IS CHECKED BEFORE IT IS SPENT. A row whose
    # successor has itself left the flow would otherwise go on excusing a
    # removal forever, which is how an authorisation rots into prose.
    dead = {was: now for was, now in _REHOMED.items() if now not in live}
    assert not dead, (
        "these `_REHOMED` rows name a successor that no step declares today, so "
        "they are excusing a removal on the strength of a command that is itself "
        f"gone — each needs re-deriving, not re-dating: {dead}"
    )

    unaccounted = [c for c in d["removed"]
                   if c["cmd"] not in live and c["cmd"] not in _REHOMED]
    assert not unaccounted, (
        "these clauses left the flow between the pin and HEAD and their command "
        "is declared by no step today and no `_REHOMED` row names a successor "
        "for them — that is a RETIREMENT, not a re-homing, and it needs its own "
        f"authorisation: {[c['cmd'] for c in unaccounted]}"
    )

    # and the specific one the authorisation names, so a future re-homing of
    # something else cannot quietly stand in for this one.
    named = [c for c in d["removed"] if c["cmd"].startswith(_REHOME_CMD_PREFIX)]
    assert named, (
        f"{_REHOME_CMD_PREFIX!r} is not among the clauses removed since "
        f"{_REHOME_PIN}; the authorisation above describes a delta this tree "
        "no longer has"
    )
    assert [c["step"] for c in named] == ["1.6x"], named

def test_an_optional_clause_is_BLOCKING_not_advisory(tmp_path):
    """Its optionality is entirely in WHETHER IT RUNS. Once
    `condition_files_exist` resolves, `flow_compliance_check` fails the gate on
    a non-zero exit exactly as the mandatory slot does. Reading it as advisory
    would have understated every finding among the 28 of them."""
    opt = [c for c in lc.discover_clauses(lc.FLOW_YAML)
           if c.kind == "optional_program_exit_zero"]
    assert opt and all(c.blocking for c in opt), len(opt)


def test_condition_files_exist_becomes_a_structural_empty_tree_guard(tmp_path):
    """Same structural fact as a step-level `condition`, one level down: the
    consumer returns before dispatch when none resolve, so on an empty tree the
    program never runs and its exit code is never read."""
    opt = [c for c in lc.discover_clauses(lc.FLOW_YAML)
           if c.kind == "optional_program_exit_zero"]
    assert all(any("[condition_files_exist]" in g for g in c.guards) for c in opt)


def test_an_UNRECOGNISED_clause_shape_is_named_not_dropped(tmp_path):
    """The requirement that survives the repair. A shape this file has never
    seen must appear in the coverage block, not vanish from the denominator."""
    flow = _flow(tmp_path, """
        steps:
          - id: 99
            gate:
              all_of:
                - program_exit_zero: "seen ."
                - program_exit_when_the_moon_is_full: "invented ."
        """)
    pop = lc.population_report(flow)
    assert pop["swept"] == 1, pop
    assert pop["unrecognised"] == {"program_exit_when_the_moon_is_full": 1}, pop
    block = lc._coverage_block(pop, 1, False)
    assert "UNRECOGNISED SHAPE" in block, block
    assert "program_exit_when_the_moon_is_full" in block, block


def test_the_coverage_line_is_printed_even_when_coverage_is_TOTAL(census, tmp_path, capsys):
    """Printing it only when there is a gap makes the gap's ABSENCE the thing
    nobody can audit."""
    flow = _flow(tmp_path, _UNGUARDED_STEP.format(prog="g"))
    progs = _programs(tmp_path, g="import sys\nprint('[PASS]')\nsys.exit(1)\n")
    census(flow, progs, "--probes", "empty")
    out = capsys.readouterr().out
    assert "COVERAGE — swept 1 of 1 program clause(s)" in out, out
    assert "NOT SWEPT" not in out, out


def test_a_clause_kind_that_runs_no_program_is_OUT_OF_SUBJECT_not_swept(tmp_path):
    """`json_field_true` is a gate clause. Every probe here runs a program, so
    none can address it — which is a statement the census has to make, not a
    silence."""
    pop = lc.population_report(lc.FLOW_YAML)
    assert pop["non_program"] == {"json_field_true": 1}, pop["non_program"]
    assert "OUT OF SUBJECT" in lc._coverage_block(pop, pop["swept"], False)


def test_the_tracer_records_reads_and_writes_IN_ORDER(tmp_path):
    """The unit the two probes rest on. If this stops working every
    trace-derived verdict silently becomes N/A -- which is the point of the
    liveness marker, tested next."""
    tracer = lc.make_tracer(tmp_path / "tracer")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "in.txt").write_text("x")
    prog = tmp_path / "programs" / "seq.py"
    prog.parent.mkdir(exist_ok=True)
    prog.write_text("import pathlib\n"
                    "pathlib.Path('in.txt').read_text()\n"
                    "pathlib.Path('made.txt').write_text('y')\n"
                    "pathlib.Path('made.txt').read_text()\n")
    lc.PROGRAMS = prog.parent
    rc, _out, events = lc._run_traced("seq", proj, tracer, _T)
    assert rc == 0
    assert events is not None
    assert ("r", "in.txt") in events
    assert events.index(("w", "made.txt")) < events.index(("r", "made.txt"))
    tr = lc.Traced(rc=rc, out="", events=events)
    assert tr.reads_before_writing("in.txt") is True
    assert tr.reads_before_writing("made.txt") is False


# --------------------------------------------------------------------------
# P10: the PRODUCER emitted nothing, and the checker read the absence as
# consent (vibe-ic#1115, from the LibreLane 3.0.8 study; re-implementing #1236).
#
# The control that matters most is the one proving this is not a rename of
# `empty_tree`: the fixture here is a step whose declared artefacts EXIST and
# are ZERO BYTES, which is precisely the state `empty_tree`'s guards DECLINE.
# --------------------------------------------------------------------------

#: A gate that exhibits the SHAPE, which needs more than "passes on an empty
#: file": it must be able to tell that the artefact is MISSING and say so, and
#: then FAIL to tell when the same artefact is present-but-hollow. A gate that
#: is silent both ways never read the input at all, and the probe declines it —
#: see `test_a_gate_that_never_read_the_seeded_paths_is_DECLINED`.
_READS_A_METRIC = """
    import pathlib, sys
    p = pathlib.Path("reports/measurement.json")
    if not p.exists():
        print("VACUOUS_PASS: the measurement was never produced")
        sys.exit(0)
    body = p.read_text()
    if not body.strip():
        # it EXISTS, so the producer "ran" -> nothing to check -> PASS. THE DEFECT.
        print("[PASS] no violations found"); sys.exit(0)
    print("[FAIL] violations"); sys.exit(1)
    """

_STEP_WITH_A_DECLARED_INPUT = """
    steps:
      - id: 99
        name: planted
        required_outputs: ["reports/measurement.json"]
        gate:
          all_of:
            - program_exit_zero: "{prog} ."
    """

#: The same step with a SECOND program-dispatching clause beside it. It is the
#: `optional_program_exit_zero` MAPPING form on purpose: `discover_clauses`
#: collects only the string form, so this sibling is invisible to the census's
#: own clause list and visible only to `_dispatching_clause_counts` — which is
#: the undercount that decides whether the JSON channel can be unanimous.
_STEP_WITH_A_SIBLING_DISPATCHER = """
    steps:
      - id: 99
        name: planted
        required_outputs: ["reports/measurement.json"]
        gate:
          all_of:
            - program_exit_zero: "{prog} . --json reports/x.json"
            - optional_program_exit_zero:
                command: "sibling . --json reports/sib.json"
                condition_files_exist: ["reports/measurement.json"]
    """

_STEP_WITH_A_SOLE_DISPATCHER = """
    steps:
      - id: 99
        name: planted
        required_outputs: ["reports/measurement.json"]
        gate:
          all_of:
            - program_exit_zero: "{prog} . --json reports/x.json"
    """

#: Discloses ONLY into its own `--json` report. Nothing on stdout matches the
#: one channel `check_step` promotes on, and with the input ABSENT it objects —
#: so the fixture provably reached it.
_JSON_ONLY = """
    import json, pathlib, sys
    p = pathlib.Path("reports/measurement.json")
    if not p.exists():
        print("INCOMPLETE: the measurement was never produced"); sys.exit(2)
    rep = pathlib.Path("reports/x.json")
    rep.parent.mkdir(parents=True, exist_ok=True)
    if not p.read_text().strip():
        rep.write_text(json.dumps({"gate": "d", "verdict": "NOT_APPLICABLE",
                                   "reason": "the producer emitted nothing"}))
        print("[PASS] nothing to check")      # no sentinel the consumer matches
        sys.exit(0)
    rep.write_text(json.dumps({"gate": "d", "verdict": "PASS"}))
    sys.exit(0)
    """


def test_it_fires_when_a_gate_passes_over_an_EMPTY_declared_input(census, tmp_path,
                                                                  capsys):
    """LibreLane's `return {}` shape: the producer ran, emitted nothing, and the
    checker found nothing to check and passed."""
    progs = _programs(tmp_path, reads_a_metric=_READS_A_METRIC)
    rc = census(_flow(tmp_path, _STEP_WITH_A_DECLARED_INPUT.format(prog="reads_a_metric")),
                progs, "--probes", "emitted")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "producer_emitted_nothing" in out, out
    assert "PRESENT BUT EMPTY" in out, out
    assert "1   (1 of them BLOCKING)" in out, out


def test_a_gate_that_OBJECTS_to_an_empty_input_is_clean(census, tmp_path, capsys):
    """The paired direction, and the issue's own rule: an absent input is
    'not measured', and not-measured may resolve to rc 1 or rc 2 — just never 0."""
    progs = _programs(tmp_path, refuses_empty="""
        import pathlib, sys
        p = pathlib.Path("reports/measurement.json")
        if not (p.exists() and p.read_text().strip()):
            print("INCOMPLETE: the measurement was never produced"); sys.exit(2)
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _STEP_WITH_A_DECLARED_INPUT.format(prog="refuses_empty")),
                progs, "--probes", "emitted")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out, out
    assert "CLEAN       1" in out, out


def test_rc0_WITH_the_stdout_sentinel_is_guarded_not_a_liar(census, tmp_path,
                                                            capsys):
    """The disclosure channel is not this file's opinion: it is
    `flow_compliance_check`'s rc-independent `VACUOUS_PASS:` sentinel, read
    through the same predicate `prose_vs_exit` uses. A gate may exit 0 and still
    be honest, and the flow records VACUOUS_PASS rather than PASS."""
    progs = _programs(tmp_path, discloses="""
        import pathlib, sys
        p = pathlib.Path("reports/measurement.json")
        if not (p.exists() and p.read_text().strip()):
            print("VACUOUS_PASS: the measurement was never produced — nothing examined")
            sys.exit(0)
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _STEP_WITH_A_DECLARED_INPUT.format(prog="discloses")),
                progs, "--probes", "emitted")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "GUARDED" in out, out
    assert "PROMOTES the step to VACUOUS_PASS" in out, out


def test_a_JSON_ONLY_disclosure_is_STILL_a_finding(census, tmp_path, capsys):
    """THE HEADLINE OF #1236, restated against what main's consumer does TODAY.

    `flow_compliance_check` reads the gate's own `--json` report and records
    `__JSON_VACUOUS_HINT__` — so this gate is NOT silent and is not a LIAR. But
    `check_step` tiers the step on that bucket only when the count is unanimous
    (`len(all_vacuous_cmds) >= len(ran_hints)`). This step has a second
    dispatching clause, so short of unanimity the step KEEPS ITS BARE PASS and
    the disclosure surfaces as a `PARTIALLY-VACUOUS` reason — which names the
    hole rather than closing it. SUSPECT is that third position: neither the
    amnesty a stdout-only probe would grant, nor the LIAR a channel-blind one
    would call it.
    """
    progs = _programs(tmp_path, json_only=_JSON_ONLY, sibling="""
        import sys
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path,
                      _STEP_WITH_A_SIBLING_DISPATCHER.format(prog="json_only")),
                progs, "--probes", "emitted")
    out = capsys.readouterr().out
    assert rc == 0, out                      # SUSPECT is not a LIAR
    assert "SUSPECT     1" in out, out
    assert "LIAR        0" in out, out
    assert "__JSON_VACUOUS_HINT__" in out, out
    assert "STILL RECORDS PASS" in out, out


def test_the_SAME_gate_is_GUARDED_when_it_is_the_STEPS_ONLY_dispatcher(
        census, tmp_path, capsys):
    """The discount that makes the finding above structural rather than a
    blanket suspicion of the JSON channel.

    Byte-identical gate, one clause removed from the step. With a single
    program-dispatching clause the consumer's unanimity test is satisfied by
    construction, the step IS tiered VACUOUS_PASS on the JSON channel alone, and
    accusing it would be this census's own version of the defect it hunts.
    Derived from the flow's structure, never from a gate name.
    """
    progs = _programs(tmp_path, json_only=_JSON_ONLY)
    rc = census(_flow(tmp_path,
                      _STEP_WITH_A_SOLE_DISPATCHER.format(prog="json_only")),
                progs, "--probes", "emitted")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "SUSPECT     0" in out, out
    assert "GUARDED" in out, out
    assert "ONLY program-dispatching clause" in out, out


def test_a_gate_that_never_read_the_seeded_paths_is_DECLINED(census, tmp_path,
                                                             capsys):
    """The fail-safe class, and the reason the probe pays for a second
    subprocess.

    A step's declared outputs are the STEP's, not each clause's, so a clause may
    read a subset of them or none. This gate ignores them entirely: it answers
    the same way whether they are EMPTY or ABSENT. The fixture starved it of
    nothing, so the probe declines instead of inventing a starvation it never
    caused — the class #1051 already had to learn for `empty_tree`.
    """
    progs = _programs(tmp_path, ignores_the_input="""
        import sys
        print("[PASS] forbidden marker not present"); sys.exit(0)
        """)
    rc = census(_flow(tmp_path,
                      _STEP_WITH_A_DECLARED_INPUT.format(prog="ignores_the_input")),
                progs, "--probes", "emitted")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out, out
    assert "starved it of nothing" in out, out


def test_this_shape_is_INVISIBLE_to_the_empty_tree_probe(census, tmp_path, capsys):
    """The load-bearing control: without it, this probe could be a rename.

    The SAME planted gate, the SAME flow, run under `empty` and under `emitted`.
    `empty_tree` DECLINES — the step declares `required_outputs`, so on an empty
    tree it is MISSING before its gate is read, and that discount is correct.
    `emitted` fires, because there the step RAN and only its content is missing.
    """
    flow = _flow(tmp_path, _STEP_WITH_A_DECLARED_INPUT.format(prog="reads_a_metric"))

    progs = _programs(tmp_path, reads_a_metric=_READS_A_METRIC)
    rc_empty = census(flow, progs, "--probes", "empty")
    out_empty = capsys.readouterr().out

    progs = _programs(tmp_path, reads_a_metric=_READS_A_METRIC)
    rc_emitted = census(flow, progs, "--probes", "emitted")
    out_emitted = capsys.readouterr().out

    assert rc_empty == 0, out_empty
    assert "GUARDED" in out_empty, out_empty          # declined, correctly
    assert rc_emitted == 1, out_emitted               # and still caught here
    assert "producer_emitted_nothing" in out_emitted, out_emitted


def test_a_clause_whose_step_declares_no_input_is_NA_not_clean(census, tmp_path,
                                                               capsys):
    """No declared input means no producer whose silence could be read as
    consent. That is N/A — a question this probe cannot ask — and N/A must not
    be folded into the clean count."""
    progs = _programs(tmp_path, no_inputs="""
        import sys
        print("[PASS] no_inputs"); sys.exit(0)
        """)
    census(_flow(tmp_path, _UNGUARDED_STEP.format(prog="no_inputs")),
           progs, "--probes", "emitted")
    out = capsys.readouterr().out
    assert "CLEAN       0" in out, out
    assert "N/A         1" in out, out


def test_an_empty_JSON_OBJECT_is_not_the_same_as_zero_bytes(tmp_path):
    """`_materialise` writes `{}` into a `.json`; this probe writes nothing.

    An empty JSON OBJECT is a producer that emitted a DOCUMENT — a gate that
    reads it and says "0 findings" is answering correctly. Zero bytes is a
    producer that emitted nothing. Seeding the wrong one would make this probe
    accuse every gate that correctly reports an empty result set.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    lc._materialise(["reports/m.json"], a)
    lc._materialise_empty(["reports/m.json"], b)
    assert (a / "reports/m.json").read_text().strip() == "{}"
    assert (b / "reports/m.json").read_text() == ""


def test_an_ALREADY_POPULATED_declared_path_is_truncated_not_skipped(tmp_path):
    """The fixture must be what it claims. A path the skeleton already wrote
    would otherwise leave the probe measuring a tree it did not build, and
    reporting CLEAN because the gate found real content."""
    root = tmp_path / "r"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "m.json").write_text('{"violations": 7}')
    made = lc._materialise_empty(["reports/m.json"], root)
    assert made == 1
    assert (root / "reports" / "m.json").read_text() == ""


def test_the_dispatcher_count_is_the_CONSUMERS_denominator(tmp_path):
    """It counts the two slots that append `__RAN_HINT__` and only those.

    `optional_program_exit_zero` IS in the consumer's denominator and is a
    mapping the census's own clause walk never collects, so counting siblings
    from that walk would UNDERCOUNT — the direction that hands out amnesties.
    `advisory_program_exit_zero` appends no RAN marker and must NOT be counted,
    or a step with one advisory sibling would look non-unanimous when it is not.
    """
    import yaml
    doc = yaml.safe_load(textwrap.dedent("""
        steps:
          - id: 7
            name: planted
            gate:
              all_of:
                - program_exit_zero: "a ."
                - optional_program_exit_zero:
                    command: "b ."
                    condition_files_exist: ["x"]
                - advisory_program_exit_zero: "c ."
                - files_exist: ["y"]
          - id: 8
            name: other
            gate:
              all_of:
                - program_exit_zero: "d ."
        """))
    counts = lc._dispatching_clause_counts(doc)
    assert counts["7"] == 2, counts
    assert counts["8"] == 1, counts


def test_the_dispatcher_count_reaches_the_real_flow(tmp_path):
    """The instrument must be measuring the shipped flow, not only fixtures.

    If this ever returns 0 for every step, `probe_producer_emitted_nothing`
    silently loses its structural discount and starts reporting the sole-clause
    steps as SUSPECT — a change in findings with no change in the flow.
    """
    clauses = lc.discover_clauses(lc.FLOW_YAML)
    assert clauses, "no clauses discovered in the shipped flow"
    assert any(c.step_dispatchers > 0 for c in clauses), (
        "every clause in the shipped flow reports 0 dispatching siblings — the "
        "count is no longer reaching the YAML")
    for c in clauses:
        if not c.blocking:
            # An `advisory_program_exit_zero` clause is not in the consumer's
            # denominator, so a step carrying ONLY advisory clauses counts 0 —
            # measured on step 35 (`dfm_screen_check`), and correct.
            continue
        assert c.step_dispatchers >= 1, (
            f"step {c.step} carries BLOCKING clause {c.program} yet counts "
            f"{c.step_dispatchers} dispatching clause(s) — a blocking clause is "
            f"in the denominator by definition")


def test_an_ABSENT_control_arm_that_TIMED_OUT_is_NA_not_a_liar(monkeypatch,
                                                               tmp_path):
    """An empty result is not a zero, in the direction that costs a false
    accusation.

    The probe's differential needs BOTH arms. If the ABSENT run times out or
    cannot be spawned it told us it was unable to look, never that the gate
    behaves differently — and `(rc_bare, channel_bare) != (rc, channel)` would
    then be satisfied by the timeout itself, promoting an undetermined control
    into a BLOCKING LIAR. Scored N/A instead, which this file's own rule keeps
    out of the clean count.
    """
    cl = lc.Clause(step="99", kind="program_exit_zero", cmd="g .", program="g",
                   step_outputs=["reports/m.json"], step_dispatchers=2)
    calls = []

    def fake_run(cmd, project, timeout=60):
        calls.append(project)
        return (0, "[PASS] nothing to check") if len(calls) == 1 else (124, "<TIMEOUT>")

    monkeypatch.setattr(lc, "_run", fake_run)
    monkeypatch.setattr(lc, "disclosure_channel",
                        lambda *a, **k: lc._CH_NONE)
    sandbox = tmp_path / "sb"
    sandbox.mkdir()
    res = lc.probe_producer_emitted_nothing(cl, sandbox)
    assert res.verdict == lc.NA, res
    assert "control arm did not run" in res.detail, res.detail
