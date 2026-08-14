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

_SEEDED_STEP = """
    steps:
      - id: 99
        name: planted
        required_outputs:
          - evidence/report.json
        gate:
          all_of:
            - program_exit_zero: "{prog} ."
    """


def test_it_fires_on_a_gate_that_passes_having_touched_nothing(census, tmp_path, capsys):
    """The purest form: the verdict is a function of argv."""
    progs = _programs(tmp_path, decides_on_argv="""
        import sys
        print("[PASS] decides_on_argv: 1/1 conformant")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _SEEDED_STEP.format(prog="decides_on_argv")),
                progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "never opened, stat'd or listed ANY path" in out, out


def test_existence_standing_in_for_substance_is_SUSPECT_never_LIAR(census, tmp_path, capsys):
    """The `gds_size_check` tier — and the reason it is deliberately the weaker
    verdict is stated in the probe: a gate whose declared property IS presence
    measures exactly this, and no structure separates the two."""
    progs = _programs(tmp_path, exists_is_enough="""
        import pathlib, sys
        p = pathlib.Path("evidence/report.json")
        if p.exists() and p.stat().st_size > 4:
            print("[PASS] exists_is_enough: evidence present")
            sys.exit(0)
        sys.exit(1)
        """)
    rc = census(_flow(tmp_path, _SEEDED_STEP.format(prog="exists_is_enough")),
                progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert rc == 0, out                       # SUSPECT does not set the exit code
    assert "LIAR        0" in out, out
    assert "SUSPECT     1" in out, out
    assert "existence stood in for substance" in out, out
    # and the mutation arm CONFIRMS it rather than the probe merely asserting it
    assert "CONFIRMED by mutation" in out, out


def test_a_gate_that_actually_reads_its_subject_is_CLEAN(census, tmp_path, capsys):
    """The negative control for the tier above: same file, same PASS, one
    difference — it opens it."""
    progs = _programs(tmp_path, reads_it="""
        import json, pathlib, sys
        d = json.loads(pathlib.Path("evidence/report.json").read_text())
        print("[PASS] reads_it: n=%s" % d.get("n"))
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _SEEDED_STEP.format(prog="reads_it")),
                progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out and "SUSPECT     0" in out, out


def test_the_mutation_arm_is_NOT_scored_where_the_gate_read_the_file(census, tmp_path, capsys):
    """The false positive this probe HAD, and the reason P7 is gated on P6.

    `l_doc_todo_stub_count_check` reads every L-doc, counts `TODO`, and passes
    on both arms because neither arm contains a TODO. Its verdict is perfectly
    content-sensitive; a byte-scramble at equal length simply handed it a second
    COMPLIANT input. Scoring "the verdict did not move" as a finding there is
    the probe committing shape 12 on its way to reporting it.
    """
    progs = _programs(tmp_path, counts_a_token="""
        import pathlib, sys
        t = pathlib.Path("evidence/report.json").read_text(errors="replace")
        print("[PASS] counts_a_token: todo=%d" % t.count("TODO"))
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _SEEDED_STEP.format(prog="counts_a_token")),
                progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out and "SUSPECT     0" in out, out


def test_a_gate_asserting_an_artefact_is_ABSENT_is_declined(census, tmp_path, capsys):
    """The fail-safe class, and it is the same one #1051's `empty_tree` probe
    had. `analog_a0_skip_forbidden_check` is the live instance."""
    progs = _programs(tmp_path, forbidden_absent="""
        import pathlib, sys
        if pathlib.Path("A0_skip_decision.json").exists():
            print("FAIL: forbidden artefact present"); sys.exit(1)
        print("[PASS] forbidden_absent: not present")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _SEEDED_STEP.format(prog="forbidden_absent")),
                progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out and "SUSPECT     0" in out, out
    assert "its subject may BE the absence" in out, out


def test_a_child_process_is_DROPPED_and_never_accused(census, tmp_path, capsys):
    """The audit hook does not follow children. A gate whose reading happens in
    `klayout` looks exactly like a gate that read nothing, and accusing it would
    be the census publishing its own blindness as a finding."""
    progs = _programs(tmp_path, delegates="""
        import subprocess, sys
        subprocess.run([sys.executable, "-c", "pass"])
        print("[PASS] delegates: child said so")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _SEEDED_STEP.format(prog="delegates")),
                progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out and "SUSPECT     0" in out, out
    assert "spawned a child process" in out, out


def test_a_disclosed_VACUOUS_PASS_is_declined_here_too(census, tmp_path, capsys):
    """#1054's rule, applied to the new probes rather than re-derived: a gate
    that prints `VACUOUS_PASS:` is not certifying the project, and the flow does
    not record it as a PASS."""
    progs = _programs(tmp_path, discloses="""
        import sys
        print("VACUOUS_PASS: discloses — nothing was examined")
        sys.exit(0)
        """)
    rc = census(_flow(tmp_path, _SEEDED_STEP.format(prog="discloses")),
                progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "LIAR        0" in out and "SUSPECT     0" in out, out
    assert "records VACUOUS_PASS rather than PASS" in out, out


def test_every_unscored_shape12_result_is_PRINTED_with_its_reason(census, tmp_path, capsys):
    """Bounded coverage that does not say what it skipped reads as coverage it
    never had."""
    progs = _programs(tmp_path, refuses="""
        import sys
        print("cannot decide"); sys.exit(1)
        """)
    census(_flow(tmp_path, _SEEDED_STEP.format(prog="refuses")), progs, "--probes", "proxy")
    out = capsys.readouterr().out
    assert "DROPPED" in out, out
    assert "does not PASS on the seeded tree" in out, out


def test_the_OR_alternatives_are_each_seeded_as_a_path(tmp_path):
    """` OR ` is the flow's ANY-OF separator inside one `required_outputs`
    entry. Before it was split, the census wrote ONE file whose NAME was the
    whole `A OR B OR C` string and then reported what a gate did with that."""
    cl = lc.Clause(step="9", kind="program_exit_zero", cmd="g .", program="g",
                   step_outputs=["a/x.log OR b/y.xml"])
    got = lc.seed_declared_tree(tmp_path / "p", cl)
    assert got == ["a/x.log", "b/y.xml"], got


def test_a_glob_output_is_materialised_not_silently_skipped(tmp_path):
    """Every one of step 37's declared outputs is a glob. Skipping them would
    drop the whole step and report the gap as coverage."""
    cl = lc.Clause(step="37", kind="program_exit_zero", cmd="g .", program="g",
                   step_outputs=["phase3/stage4/gds/*.gds"])
    got = lc.seed_declared_tree(tmp_path / "p", cl)
    assert got == ["phase3/stage4/gds/liar_census_seed.gds"], got


def test_the_subject_is_the_clause_ARGUMENT_not_the_step_report(tmp_path):
    """The probe's own shape-12 trap. `required_outputs` is frequently the
    gate's OWN REPORT while its subject is the positional argument beside it;
    seeding the report and calling it the subject would measure whether the gate
    reads its own output."""
    cl = lc.Clause(step="2", kind="program_exit_zero",
                   cmd="rtl_hygiene_lint phase2/stage1/rtl/*.sv --json reports/x.json",
                   program="rtl_hygiene_lint",
                   step_outputs=["reports/x.json", "reports/other.json"])
    subjects, outputs = lc.clause_subject_paths(cl)
    assert outputs == ["reports/x.json"], outputs
    assert "phase2/stage1/rtl/*.sv" in subjects, subjects
    assert "reports/x.json" not in subjects, subjects
    assert "reports/other.json" in subjects, subjects


def test_the_trace_shim_self_tests_every_channel_before_it_is_trusted(tmp_path):
    """`pathlib` binds `os.stat` at import on some CPython versions, so a LOOK
    can be invisible — which would UPGRADE a "looked but did not read" finding
    into "touched nothing at all", silently, on some hosts. The shim proves each
    channel against a scratch directory first and names any that is dark."""
    import json as _json
    prog = tmp_path / "p.py"
    prog.write_text("import pathlib, sys\n"
                    "pathlib.Path('seen.txt').exists()\n"
                    "pathlib.Path('read.txt').read_text()\n"
                    "sys.exit(0)\n")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "seen.txt").write_text("x")
    (proj / "read.txt").write_text("y")
    tr = tmp_path / "t.json"
    rc = subprocess.run([sys.executable, str(lc.TRACE_SHIM), str(prog), str(tr)],
                        cwd=str(proj), capture_output=True, text=True, timeout=_T).returncode
    assert rc == 0
    payload = _json.loads(tr.read_text())
    assert payload["instrumentation"] == "COMPLETE", payload["instrumentation"]
    assert payload["touched"]["seen.txt"] == ["look"], payload["touched"]
    assert "read" in payload["touched"]["read.txt"], payload["touched"]


def test_the_real_sweep_still_finds_its_one_real_positive(capsys):
    """The one REAL in-population positive the shape-12 probes found, pinned.

    `vacuous_testbench_check` — the gate whose entire subject is a testbench
    that "prints a PASS and never drives the design" — returns rc 0 over a sim
    tree that carries a `results.xml` and NO testbench source, having read none
    of it. Reproduced by hand, independently of the census:

        verdict: NOT_APPLICABLE, reason: "no testbench discovered", rc 0

    The step-4 sibling `files_exist` asserts the sim RESULT, never a testbench
    SOURCE, so nothing else in that `all_of` asks the question either.
    """
    rc = lc.main(["--probes", "proxy", "--only", "vacuous_testbench_check"])
    out = capsys.readouterr().out
    assert rc == 0, out                      # advisory tier: SUSPECT, not LIAR
    assert "SUSPECT     1" in out, out
    assert "vacuous_testbench_check" in out, out
    assert "existence stood in for substance" in out, out




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
    assert pop["swept"] == pop["declared"] == 167, pop
    assert pop["unrecognised"] == {}, pop["unrecognised"]


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
