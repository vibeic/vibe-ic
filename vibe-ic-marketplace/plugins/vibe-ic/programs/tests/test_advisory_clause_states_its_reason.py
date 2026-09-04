"""An advisory gate must say WHY it is advisory — and the check must be
falsifiable in both directions, with a control that is green in both.

MEASURED on this tree at v1.13.61: 76 of the flow's 228 gate clauses sit in the
`advisory_program_exit_zero` slot, and 0 of the 76 state a reason. 57 declare
`ENFORCEMENT: advisory` — which says WHAT, not WHY, and is fully satisfied by a
gate somebody downgraded an hour ago — and 19 declare nothing at all.

EVERY TEST HERE CARRIES A CONTROL. The subject tree always holds TWO advisory
clauses: `control_gate`, which states a real reason and must be green in every
single arm, and `subject_gate`, which is the only thing a test mutates. A red
arm that also reddened the control would be a test of "did the tree survive",
not of the predicate. Nothing is added or removed between arms — same flow,
same clause count, same register — so the population the gate walks is
identical in both directions and only the ANSWER moves.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import advisory_clause_states_its_reason as G  # noqa: E402
import flow_gate_enforcement_audit as A  # noqa: E402

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

# The docstring census the gate publishes has exactly THESE THREE rows. Pinned
# as a SET and not only as a count (vibe-ic `population_pin_without_its_member
# _set`): `len(said) == 3` is invariant under one row leaving and another
# arriving in the same edit, and the dispatch below keys on these exact
# strings — so a renamed row used to fall through the `.get()` default and be
# compared against the WRONG measurement, silently. The set pin names a missing
# row and an extra row separately, and the dispatch is now total.
_ROW_ADVISORY = "declare `ENFORCEMENT: advisory` (says WHAT)"
_ROW_SILENT = "declare no enforcement intent at all"
_ROW_REASON = "state a REASON where the clause or the gate can show it"
_CENSUS_ROWS = {_ROW_ADVISORY, _ROW_SILENT, _ROW_REASON}

_CONTROL = '''#!/usr/bin/env python3
"""control_gate — green in every arm.

ADVISORY_REASON: what it reports is a disclosure about the corpus rather than a
defect in the design, so refusing a run over it would be a false refusal.
"""
'''

_STATED = '''#!/usr/bin/env python3
"""subject_gate.

ADVISORY_REASON: the metric it measures has no producer on any published run
yet, so blocking would stop every run over debt that is owned elsewhere.
"""
'''

_FLOW_SRC = """steps:
  - id: "1"
    gate:
      advisory_program_exit_zero:
        command: "control_gate . --json out.json"
  - id: "2"
    gate:
      advisory_program_exit_zero:
        command: "subject_gate . --json out.json"
"""


def _subject(subject_src: str = _STATED, *, flow: str = _FLOW_SRC,
             known=(), register: str = None, control: str = _CONTROL) -> Path:
    """A whole subject tree. `tmp_path` is NOT used: this plugin's container
    lane gives `tmp_path` a name containing a newline, which several tools in
    this tree cannot carry, so fixtures here use `mkdtemp`."""
    root = Path(tempfile.mkdtemp(prefix="advreason-"))
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plugin / "flow").mkdir(parents=True)
    programs = plugin / "programs"
    programs.mkdir(parents=True)
    (plugin / "flow" / "phase1_phase2_phase3.yaml").write_text(flow)
    (programs / "control_gate.py").write_text(control)
    (programs / "subject_gate.py").write_text(subject_src)
    if register is None:
        register = json.dumps({"known": sorted(known)}, indent=2) + "\n"
    if register != "":
        (programs / "advisory_reason_baseline.json").write_text(register)
    return root


def _run(root: Path):
    """Drive the program the way `repo_hygiene_gates.sh` drives it: as a
    SUBPROCESS with the subject root as argv, so the exit code under test is
    the one the dispatcher actually reads."""
    p = subprocess.run(
        [sys.executable, str(_PROGRAMS / "advisory_clause_states_its_reason.py"),
         str(root)], capture_output=True, text=True, timeout=180)
    return p.returncode, p.stdout + p.stderr


def _control_is_green(out: str) -> bool:
    """The control clause is never NAMED as an offender.

    It is legitimate for the word `control_gate` to appear in a census line, so
    this asserts on the FINDING lines specifically rather than on the whole
    output — a weaker check here would pass a gate that reddened everything.
    """
    for line in out.splitlines():
        if "control_gate" in line and any(
                v in line for v in ("NO_REASON", "EMPTY", "PLACEHOLDER",
                                    "RESTATES", "TOO_SHORT", "UNREAD",
                                    "ABSENT")):
            return False
    return True


# --------------------------------------------------------------- the census
def test_the_population_is_the_clause_keys_not_the_grep_count():
    """76 clauses, not the 87 lines that contain the token.

    `grep -c advisory_program_exit_zero` over the flow returns 87. Eleven of
    those lines are YAML COMMENTS that name the token while talking about it —
    one of them says `NOT advisory_program_exit_zero` — and counting a line
    that denies membership as a member is the same "prose is not a
    declaration" defect this file's subject is about. The gate reads the
    clause keys with the flow engine's own loader.
    """
    text = _FLOW.read_text()
    grep_lines = sum(1 for L in text.splitlines()
                     if "advisory_program_exit_zero" in L)
    clauses = [c for c in A.clauses_in_flow(_FLOW)
               if c["slot"] == "advisory_program_exit_zero"]
    assert len(clauses) < grep_lines, (
        "if these are equal the flow has stopped carrying comments about the "
        "token and this test no longer measures the difference it was written "
        "for — re-derive it rather than deleting it")


def test_the_census_the_gate_publishes_is_the_one_it_measures():
    """The gate's docstring prints a three-line census. It must be THIS tree's.

    NOT a hard pin on 76. Clauses are added and removed and that is ordinary;
    a test that reddens on an ordinary flow change is the false positive
    v1.13.59 records as costing the check. What is NOT ordinary is a published
    number that has quietly stopped being true — this repo's `at-head` failure
    mode — so the assertion is on AGREEMENT between the docstring and the
    measurement, and the repair is one edit in one place.
    """
    doc = (_PROGRAMS / "advisory_clause_states_its_reason.py").read_text()
    said = {k: int(v) for k, v in re.findall(
        r"^\s+(declare[^0-9]+?|state a REASON[^0-9]+?)\s+(\d+)\s*$",
        doc, re.M)}
    got_rows = set(k.strip() for k in said)
    missing = _CENSUS_ROWS - got_rows
    extra = got_rows - _CENSUS_ROWS
    assert got_rows == _CENSUS_ROWS, (
        f"this test compares the docstring's census rows to the measurement, "
        f"and the rows it read are not the ones it dispatches on. Rows the "
        f"docstring no longer states: {sorted(missing)}; rows it states that "
        f"nothing here measures: {sorted(extra)}. A reworded docstring would "
        f"otherwise make it pass by reading nothing, which is the vacuous "
        f"green it exists to prevent — and a row RENAMED (one out, one in) "
        f"keeps the count at 3 while changing the set.")
    population = int(re.search(r"MEASURED over all (\d+)", doc).group(1))
    rows = G.census(_FLOW, _PROGRAMS)
    assert len(rows) == population, (
        f"the gate's docstring says it measured {population} advisory "
        f"clauses; this tree has {len(rows)}. Re-state it — the number is "
        f"cited in the docstring and in the register's comment.")
    intents = [A.declared_intent(_PROGRAMS, r["gate"]) for r in rows]
    # The docstring also states the clause/program split, which is the fact a
    # bare population number hides. v1.13.63 wired one program six times.
    n_programs = int(re.search(r"(\d+) clauses in (\d+) distinct programs",
                               doc).group(2))
    assert n_programs == len({r["gate"] for r in rows}), (
        f"the docstring says {n_programs} distinct programs; measured "
        f"{len({r['gate'] for r in rows})}")
    measured_advisory = sum(1 for i in intents if i == "advisory")
    measured_silent = sum(1 for i in intents if i is None)
    stated = sum(1 for r in rows if r["verdict"] == G.OK)
    measured_by_row = {_ROW_ADVISORY: measured_advisory,
                       _ROW_SILENT: measured_silent,
                       _ROW_REASON: stated}
    for key, want in said.items():
        got = measured_by_row[key.strip()]
        assert got == want, f"docstring says {key.strip()!r} = {want}; measured {got}"


def test_every_advisory_clause_is_dispatchable():
    """All current clauses are under `steps:`, the section the engine reads.

    A clause the engine cannot reach is a different defect (v1.13.32) and would
    make "it is advisory" the wrong description of it.
    """
    adv = [c for c in A.clauses_in_flow(_FLOW)
           if c["slot"] == "advisory_program_exit_zero"]
    assert [c["gate"] for c in adv if not c["dispatchable"]] == []


# --------------------------------------------- falsification: REFUSED arms
@pytest.mark.parametrize("label,src,verdict", [
    ("nothing said at all",
     '"""subject_gate — says nothing about why."""\n', "NO_REASON"),
    ("the declaration has an empty value",
     '"""subject_gate\n\nADVISORY_REASON:\n"""\n', "EMPTY"),
    ("TBD", '"""s\n\nADVISORY_REASON: TBD\n"""\n', "PLACEHOLDER"),
    ("TODO", '"""s\n\nADVISORY_REASON: TODO\n"""\n', "PLACEHOLDER"),
    ("N/A", '"""s\n\nADVISORY_REASON: N/A\n"""\n', "PLACEHOLDER"),
    ("<PLACEHOLDER>",
     '"""s\n\nADVISORY_REASON: <PLACEHOLDER>\n"""\n', "PLACEHOLDER"),
    ("TBD with punctuation",
     '"""s\n\nADVISORY_REASON: [TBD].\n"""\n', "PLACEHOLDER"),
    ("two placeholders and nothing else",
     '"""s\n\nADVISORY_REASON: TODO / FIXME\n"""\n', "PLACEHOLDER"),
    ("restates the wiring",
     '"""s\n\nADVISORY_REASON: advisory only\n"""\n', "RESTATES_THE_WIRING"),
    ("non-blocking",
     '"""s\n\nADVISORY_REASON: it is non-blocking\n"""\n',
     "RESTATES_THE_WIRING"),
    ("see above", '"""s\n\nADVISORY_REASON: see above\n"""\n',
     "RESTATES_THE_WIRING"),
    ("under the floor", '"""s\n\nADVISORY_REASON: it is fine\n"""\n',
     "TOO_SHORT"),
    ("forty characters of padding",
     '"""s\n\nADVISORY_REASON: ' + "." * 44 + '\n"""\n', "TOO_SHORT"),
    ("long but almost no letters",
     '"""s\n\nADVISORY_REASON: 1234567890 1234567890 1234567890 ab cd ef\n"""\n',
     "TOO_SHORT"),
    # The gate's docstring claims these two reach the LENGTH floor rather than
    # the placeholder rule, because they carry no word at all. The claim is
    # executed here rather than asserted in prose.
    ("a bare question mark", '"""s\n\nADVISORY_REASON: ?\n"""\n', "TOO_SHORT"),
    ("a bare dash", '"""s\n\nADVISORY_REASON: -\n"""\n', "TOO_SHORT"),
])
def test_a_clause_with_no_real_reason_is_refused_and_named(label, src, verdict):
    rc, out = _run(_subject(src))
    assert rc == 1, f"{label}: expected a refusal, got rc {rc}\n{out}"
    assert "subject_gate" in out, f"{label}: refused without naming it\n{out}"
    assert verdict in out, f"{label}: expected verdict {verdict}\n{out}"
    assert _control_is_green(out), f"{label}: THE CONTROL WENT RED\n{out}"


@pytest.mark.parametrize("token", G.PLACEHOLDER_TOKENS)
def test_every_placeholder_token_is_actually_refused(token):
    """EXHAUSTIVE over the constant, not over a hand-written list beside it.

    A token added to `PLACEHOLDER_TOKENS` and never exercised is a token that
    might not work; a hand-copied list of "the placeholders we test" omits
    whatever the constant gains next.
    """
    src = f'"""s\n\nADVISORY_REASON: {token}\n"""\n'
    rc, out = _run(_subject(src))
    assert rc == 1, f"{token} was accepted as a reason\n{out}"
    assert "PLACEHOLDER" in out, f"{token} refused for the wrong reason\n{out}"
    assert _control_is_green(out), out


def test_a_prose_mention_of_the_token_is_not_a_declaration():
    """#886, inherited rather than re-derived.

    A docstring that discusses `ADVISORY_REASON:` mid-sentence has not declared
    one. The gate gets this from `flow_gate_enforcement_audit.declaration_re`,
    which anchors a declaration to the START of its line — the same rule that
    file already applies to `ENFORCEMENT:`, and it is the rule, not a copy of
    it, precisely so this property cannot hold in one place and not the other.
    """
    src = ('"""subject_gate\n\n'
           'The convention is that a gate writes `ADVISORY_REASON:` followed '
           'by a sentence long enough to clear any floor this checker might '
           'impose on it.\n"""\n')
    rc, out = _run(_subject(src))
    assert rc == 1 and "NO_REASON" in out and "subject_gate" in out, out
    assert _control_is_green(out), out


def test_the_gates_own_prose_declares_nothing():
    """The audit's #886 worst case was a file whose prose about the convention
    was read as a declaration ABOUT ITSELF, because the pattern was unanchored.

    The gate discusses `ADVISORY_REASON:` at length and must not declare one.
    Asserted BOTH ways so it cannot pass vacuously: the token must be present
    in the prose, and the declaration matcher must still find nothing.

    THIS TEST FILE AND `tools/ci/gate_fixtures/advisory_clauses_state_a_reason.py`
    ARE DELIBERATELY NOT SUBJECTS HERE. Their `ADVISORY_REASON:` lines are
    fixture INPUT -- synthetic gate sources the checker is pointed at -- and a
    declaration is exactly what those constants are for. Requiring a fixture
    not to contain the thing it is a fixture of would have been satisfied by
    weakening the fixture, which is the wrong direction.
    """
    path = _PROGRAMS / "advisory_clause_states_its_reason.py"
    text = path.read_text()
    assert G.REASON_TOKEN in text, (
        "the gate no longer mentions the token, so this test proves nothing")
    assert not G._REASON_RE.search(text), (
        f"{path.name} accidentally DECLARES an advisory reason")


def test_a_reason_past_the_window_is_unread_not_absent():
    """PRESENT AND UNREAD is a different finding from ABSENT.

    Measured in `flow_gate_enforcement_audit` 2026-08-22: two paragraphs of
    prose above a declaration moved it to byte 4371 and silently undid it. The
    author's repair is "move it up", not "write one", and printing the two the
    same way sends them to the wrong repair.
    """
    filler = "filler line that pushes the declaration down the file. " * 90
    src = ('"""subject_gate\n\n' + filler + '\n\nADVISORY_REASON: the metric '
           'has no producer on any published run yet, so blocking would stop '
           'every run.\n"""\n')
    rc, out = _run(_subject(src))
    assert rc == 1, out
    assert G.UNREAD in out, f"expected {G.UNREAD}, got:\n{out}"
    assert str(G.WINDOW) in out, "the finding must name the window it used"
    assert _control_is_green(out), out


# ------------------------------------------- falsification: ACCEPTED arms
def test_a_clause_that_states_a_reason_passes():
    rc, out = _run(_subject(_STATED))
    assert rc == 0, out
    assert "stating a reason: 2 of 2" in out, out


@pytest.mark.parametrize("label,reason", [
    ("v1.13.59's exact false positive",
     "the block_XXXa naming pattern cannot be resolved from the netlist alone"),
    # VERBATIM the example the gate's docstring gives as accepted. A worked
    # example in prose that nothing runs is a claim, not a specification.
    ("the docstring's own worked example",
     "the XXX corner has no model, so this can only report"),
    ("the word TODO inside a sentence",
     "it is on the TODO list to wire this blocking once a producer exists"),
    ("the word none inside a sentence",
     "none of the published runs produce the artefact this gate would read"),
    ("a sentence about a TBD upstream",
     "the upstream contract is still TBD, so a refusal here would be a guess"),
])
def test_a_placeholder_word_inside_a_real_sentence_is_accepted(label, reason):
    """v1.13.59 landed today because placeholder detection matched SUBSTRINGS,
    so the legal macro name `block_XXXa` reddened a correct document. The
    lesson recorded there is that a rule which reddens correct input is a rule
    that gets switched off — a false positive does not merely cost a review, it
    costs the check. Matching is on WORD BOUNDARIES and on the WHOLE value.

    THIS IS THE DIRECTION THAT CAN BLIND THE MATCHER, so the refusal arms above
    are parametrized over every placeholder token: a looser rule that also
    stopped catching a bare `TBD` would show the same green here.
    """
    src = f'"""subject_gate\n\nADVISORY_REASON: {reason}\n"""\n'
    rc, out = _run(_subject(src))
    assert rc == 0, f"{label}: a legitimate reason was refused\n{out}"


def test_the_reason_may_be_stated_on_the_clause_instead():
    """Channel 1. Per-CLAUSE, so a program wired advisory in one step and
    blocking in another can answer for each independently."""
    flow = _FLOW_SRC.replace(
        '        command: "subject_gate . --json out.json"\n',
        '        command: "subject_gate . --json out.json"\n'
        '        advisory_reason: "the metric it measures has no producer on '
        'any published run yet, so blocking would stop every run"\n')
    rc, out = _run(_subject('"""subject_gate — silent source."""\n', flow=flow))
    assert rc == 0, out
    assert "channel" not in out or "STATED" in out, out


def test_a_clause_level_placeholder_is_refused_too():
    """The clause channel is not a way around the substance rule."""
    flow = _FLOW_SRC.replace(
        '        command: "subject_gate . --json out.json"\n',
        '        command: "subject_gate . --json out.json"\n'
        '        advisory_reason: "TBD"\n')
    rc, out = _run(_subject('"""subject_gate."""\n', flow=flow))
    assert rc == 1 and "PLACEHOLDER" in out, out


# ------------------------------------------------------- the register
def test_a_recorded_clause_does_not_fail_but_is_disclosed():
    silent = '"""subject_gate — says nothing."""\n'
    rc, out = _run(_subject(silent, known=["subject_gate"]))
    assert rc == 0, out
    assert "DISCLOSURE" in out and "subject_gate" in out, (
        "recorded debt must still be PRINTED — a register that silences its "
        "entries is an amnesty\n" + out)


def test_a_new_offender_fails_even_when_the_register_is_non_empty():
    silent = '"""subject_gate — says nothing."""\n'
    rc, out = _run(_subject(silent, known=["some_other_gate"]))
    assert rc == 1 and "subject_gate" in out, out


def test_deleting_an_entry_brings_it_straight_back():
    """The register cannot be paid down by editing the file. The set is
    recomputed every run, so a deleted line returns as NEW and fails."""
    silent = '"""subject_gate — says nothing."""\n'
    assert _run(_subject(silent, known=["subject_gate"]))[0] == 0
    assert _run(_subject(silent, known=[]))[0] == 1


def test_the_register_can_never_gain_an_entry():
    """`shrunk()` is `previous & current`, a subset of `previous` for every
    possible input, so no argument to the recording path can add."""
    assert G._ratchet.shrunk(["a", "b"], ["b", "c"]) == ["b"]
    assert G._ratchet.shrunk([], ["x"]) == []


def test_write_baseline_is_refused_once_the_register_exists():
    """`--write-baseline` records whatever the run measured, ARRIVALS INCLUDED.
    On an existing register that is an amnesty, not a recording, and it is the
    remedy the audit next door had to stop advertising."""
    root = _subject('"""subject_gate — says nothing."""\n')
    p = subprocess.run(
        [sys.executable,
         str(_PROGRAMS / "advisory_clause_states_its_reason.py"), str(root),
         "--write-baseline"], capture_output=True, text=True, timeout=180)
    assert p.returncode == 1 and "amnesty" in (p.stdout + p.stderr)


# ------------------------------------------- rc 2: the question was not put
@pytest.mark.parametrize("label,mutate", [
    ("flow definition absent",
     lambda p: (p / "flow" / "phase1_phase2_phase3.yaml").unlink()),
    ("flow definition does not parse",
     lambda p: (p / "flow" / "phase1_phase2_phase3.yaml").write_text(
         "steps: [ unclosed\n")),
    ("register absent",
     lambda p: (p / "programs" / "advisory_reason_baseline.json").unlink()),
    ("register unreadable",
     lambda p: (p / "programs" / "advisory_reason_baseline.json").write_text(
         "{not json")),
    ("register states no measurement",
     lambda p: (p / "programs" / "advisory_reason_baseline.json").write_text(
         '{"known": null}')),
])
def test_the_question_could_not_be_put_is_rc_2(label, mutate):
    root = _subject()
    mutate(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
    rc, out = _run(root)
    assert rc == 2, f"{label}: expected rc 2, got {rc}\n{out}"
    assert "NOT CHECKED" in out, out


def test_an_empty_population_refuses_rather_than_passing():
    """A zero denominator is NOT OBSERVED, not PASS. This tree already names
    the rule (`gate_zero_denominator_refuses_check`): a sweep over nothing
    reports the same green as a sweep that found nothing wrong."""
    flow = ('steps:\n  - id: "1"\n    gate:\n'
            '      program_exit_zero: "control_gate ."\n')
    rc, out = _run(_subject(flow=flow))
    assert rc == 2 and "ZERO" in out, out


def test_an_explicitly_empty_register_is_a_measurement():
    """`known: []` is a MEASUREMENT and is accepted; a MISSING register is not.
    The difference is the whole reason the absent case is rc 2."""
    rc, out = _run(_subject(known=[]))
    assert rc == 0, out


# --------------------------------------------------- one premise, one place
def test_the_declaration_shape_is_spelt_once():
    """The gate reads `ADVISORY_REASON:` with the SAME builder
    `flow_gate_enforcement_audit` uses for `ENFORCEMENT:`.

    Two spellings of "what a declaration looks like" are two rules that drift,
    which is what this repo landed v1.13.46 and v1.13.39 to stop. This asserts
    the builder is what produced both, and that the `ENFORCEMENT` pattern is
    byte-for-byte the one that predated the refactor.
    """
    assert A._DECL_RE.pattern == A.declaration_re(
        "ENFORCEMENT", r"(blocking|advisory)\b").pattern
    frozen = (r"""^[ \t]*(?:\#[ \t]*)?(?:["']{1,3}[ \t]*)?"""
              r"""ENFORCEMENT:[ \t]*(blocking|advisory)\b""")
    assert A._DECL_RE.pattern == frozen, (
        "the ENFORCEMENT declaration shape changed; every gate's declared "
        "intent is read through it, so this is a re-decision and not a "
        "refactor")
    assert G._REASON_RE.pattern.startswith(
        r"""^[ \t]*(?:\#[ \t]*)?(?:["']{1,3}[ \t]*)?""")
    assert G.WINDOW is A.DECL_WINDOW_BYTES


def test_the_reason_floor_is_the_repos_own():
    """This tree already has a floor for a clause-level reason. A third,
    different number for the neighbouring question would be a third number to
    drift, so the raw floor is that one and this test fails if it moves —
    which forces the decision to be re-made rather than to drift."""
    import flow_condition_reachability_check as R
    assert G.MIN_REASON_CHARS == R.MIN_ABSENT_CONDITION_REASON == 40
    assert G.MIN_REASON_LETTERS < G.MIN_REASON_CHARS, (
        "the letters floor exists to catch padding, not to out-strict the "
        "repo's own bar")


# ------------------------------------------------- the gate is not its own subject
def test_this_gate_is_blocking_and_is_not_in_the_population_it_measures():
    """THE TRAP THIS CHECK WAS WRITTEN TO AVOID. A check that advisory clauses
    must justify themselves, itself wired as an unjustified advisory clause,
    would be its own subject and would prove nothing about any of the 76."""
    assert A.declared_intent(_PROGRAMS, "advisory_clause_states_its_reason") \
        == "blocking"
    adv = {c["gate"] for c in A.clauses_in_flow(_FLOW)
           if c["slot"] == "advisory_program_exit_zero"}
    assert "advisory_clause_states_its_reason" not in adv


def test_the_gate_is_wired_where_its_verdict_can_refuse():
    """A flow yaml clause cannot block on its own and a declaration is not a
    wiring. This one is declared in the BLOCKING repo-hygiene dispatcher with
    `run`, and the line is asserted here rather than assumed."""
    dispatcher = (_PROGRAMS.parents[3] / "tools" / "ci"
                  / "repo_hygiene_gates.sh")
    if not dispatcher.is_file():  # pragma: no cover - checkout shape guard
        pytest.skip(f"dispatcher not present at {dispatcher}")
    text = dispatcher.read_text()
    line = [L for L in text.splitlines()
            if "advisory_clause_states_its_reason.py" in L and
            not L.lstrip().startswith("#")]
    assert len(line) == 1, f"expected exactly one declaration, got {line}"
    assert re.match(r'^run\s+"', line[0]), (
        "declared with something other than blocking `run`: " + line[0])


def test_the_shipped_register_records_what_the_tree_measures():
    """The register on this tree must be exactly the offenders on this tree —
    no stale entry (a gate that has since stated a reason and would read as
    debt forever) and no missing one."""
    rows = G.census(_FLOW, _PROGRAMS)
    now = sorted({r["gate"] for r in rows if r["verdict"] in G._OFFENDING})
    recorded = G._load_register(_PROGRAMS / "advisory_reason_baseline.json")
    assert set(recorded) - set(now) == set(), (
        "STALE register entries — these gates no longer offend and the "
        "register must be tightened with --record-shrink: "
        f"{sorted(set(recorded) - set(now))}")
    assert set(now) - set(recorded) == set(), (
        "unrecorded offenders — the gate would exit 1: "
        f"{sorted(set(now) - set(recorded))}")
