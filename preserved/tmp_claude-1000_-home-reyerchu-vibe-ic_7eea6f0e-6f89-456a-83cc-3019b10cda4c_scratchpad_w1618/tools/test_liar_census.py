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

import json
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
