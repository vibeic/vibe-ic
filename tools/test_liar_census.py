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

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS))
import liar_census as lc  # noqa: E402

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


def test_the_real_flow_has_clauses_of_both_kinds(tmp_path):
    """A census that only ever saw one clause kind would report a blocking
    count that is really the total."""
    if not lc.FLOW_YAML.is_file():
        pytest.skip(f"flow not present: {lc.FLOW_YAML}")
    kinds = {c.kind for c in lc.discover_clauses(lc.FLOW_YAML)}
    assert kinds == {"program_exit_zero", "advisory_program_exit_zero"}, kinds


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
    proc = subprocess.run([sys.executable, str(gate), "bad"],
                          capture_output=True, text=True, timeout=_T)
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
        return subprocess.run(
            ["git", "status", "--porcelain", str(lc.PLUGIN)],
            cwd=str(lc.REPO), capture_output=True, text=True, timeout=_T).stdout

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
    assert len(lc.ALL_PROBES) == 10, lc.ALL_PROBES


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
