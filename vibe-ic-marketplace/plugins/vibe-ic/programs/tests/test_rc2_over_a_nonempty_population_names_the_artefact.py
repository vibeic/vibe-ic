#!/usr/bin/env python3
"""rc 2 over a population that is NOT EMPTY must NAME what is missing.

WHY THIS FILE EXISTS
====================
`test_issue1241_ppa_gates_are_aimed_at_a_population_that_exists.py` closed the
first half of this hole: a gate wired at a directory that had moved reported
NOT_CHECKED in zero seconds forever, and nothing could see it. That file asserts
every PPA record gate has a subject.

This one is the second half, and the two are different failures. A gate can have
a subject, open it, read every document in it -- and still exit 2 saying nothing
a reader can act on. MEASURED on the tree this file landed against, before the
fixes that ship with it:

    PPA head-to-head records (end-to-end campaign)
        2 records read, rc 2, and the output was TWO BYTE-IDENTICAL blocks:

            [UNDETERMINED] ppa_head_to_head_check: SCOPE_SENTINEL
              arm '...''s `timing_wns_ns` scope declares ['rc_corner'] with no value.

        Nothing said which document either block was about, or even that they
        were two documents rather than one reported twice. `format_report`'s
        PASS branch printed `report['record']`; its refusal branch printed the
        CODE alone, over a field that was populated and sitting right there.

    PPA promotion feasibility (cross-layer campaign)
        21 candidate sets adjudicated, rc 2, and the refusal read in full:

            [CANNOT CHECK] at least one candidate was not adjudicated;
                           this run makes no claim about it

        No candidate, no axis, no artefact. The naming was never missing -- the
        adjudicator carries it through `AxisResult.coverage` as a `reason`
        lifted VERBATIM from the metric row plus the `sources` path that row
        cites, and writes it into the `--json` report. The hygiene wiring passes
        no `--json`, so on the one channel a reader sees, it was dropped.

"rc 2 with no named missing input" is the failure mode this whole layer exists
to end, and until this file nothing tested for it. An unearned rc 0 is loudly
forbidden here; an unactionable rc 2 was not forbidden at all, and it is the
cheaper way to the same place -- a row nobody can do anything about is a row
that gets skipped, and a skipped row is a green one at the next reading.

THE RULE, IN TWO CLAUSES, BOTH COUNTABLE
========================================
When a gate exits 2 and the population it printed is greater than zero:

  1. SUBJECT NAMED. It names, by a path that exists, at least as many distinct
     subjects as the roll-up says it could not decide. Two undecided records
     must produce two named records. The candidate paths are enumerated with
     the CHECKER'S OWN corpus walk, so this cannot drift from what the gate
     actually opened.

  2. ABSENT INPUT NAMED. For each subject named, somewhere in the output --
     either stream -- there is a REFERENT for what is absent: a backticked
     field or metric name, an artefact path other than the subject itself, or a
     command-line flag the reader could supply. A SCREAMING_CASE code is not a
     referent; `FEAS_NOT_MEASURED` names a verdict, not a thing to go and get.

WHAT THIS FILE DOES NOT ASSERT, and the omission is the point. Not that any gate
passes. Not that any rc 2 should become rc 0. An rc 2 that is CORRECT stays rc 2
here forever and this file is satisfied -- it only ever asks that the refusal be
actionable. Converting one of these rows to green by editing a record would be
caught by nothing in this file, because that is not what it is for.

chip-AGNOSTIC: no design, PDK, vendor or node literal. The synthetic arm invents
its own corpus; the live arm reads whatever the wiring names.
"""
import copy
import importlib.util
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
WIRING = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

sys.path.insert(0, str(PROGRAMS))

RC_UNDETERMINED = 2

#: The corpus gates this rule covers, and how each one enumerates its OWN
#: subjects. Two shapes ship today: a checker with its own walk function, and a
#: checker that hands a SELECTION PREDICATE to the shared `_ppa_corpus.collect`
#: seam. Both are the checker's own code, which is what keeps this test honest —
#: a subject the gate never opened is not one it has to name, and a subject it
#: did open cannot be excused by a stale list here.
CORPUS_GATES = {
    "ppa_head_to_head_check.py": ("walk", "corpus_records"),
    "ppa_feasibility_check.py": ("predicate", "is_candidate_set"),
    "ppa_contract_check.py": ("predicate", "is_contract"),
    "ppa_problem_integrity_check.py": ("predicate", "is_contract"),
}

#: `12 record(s),` / `21 set(s),` / `61 contract(s),` — the denominator every
#: corpus roll-up prints. Anchored on the plural marker rather than on a per-gate
#: word list so a gate that starts counting `bundle(s)` is still measured.
_POPULATION = re.compile(r"(\d+)\s+[a-z_]+\(s\),")
_UNDECIDED = re.compile(r"(\d+)\s+(?:undetermined|refused)\b")

#: A REFERENT: something a reader could go and get, or go and look at.
_BACKTICKED_FIELD = re.compile(r"`([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)`")
_ARTEFACT_PATH = re.compile(
    r"[A-Za-z0-9_.\-/]*/[A-Za-z0-9_.\-]+\."
    r"(?:json|rpt|log|txt|v|sv|def|lef|lib|spef|sdc|gds|yaml|yml)\b")
_CLI_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]{2,}")

#: NOT a referent. A verdict code names what the gate concluded, never what is
#: absent, and a refusal built only from these is the shape this file refuses.
_CODE = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")

#: A line where the gate is SPEAKING A REFUSAL, as opposed to echoing its own
#: invocation or printing a roll-up. A flag only counts as a referent here: every
#: corpus gate prints `--corpus <dir>` in its own header line, and counting that
#: would let a gate satisfy this whole file by naming the argument it was called
#: with. MEASURED — the first draft of this rule did exactly that, and negative
#: control B passed against a program with all of its naming removed.
_REFUSAL_MARKER = re.compile(r"\[(?:CANNOT CHECK|UNDETERMINED|REFUSE|FAIL)\]")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _subjects(checker: str, corpus: Path):
    """The documents `checker` would open under `corpus`, by its own reckoning."""
    kind, name = CORPUS_GATES[checker]
    mod = _load(f"_subj_{Path(checker).stem}", checker)
    if kind == "walk":
        return list(getattr(mod, name)(corpus))
    import _ppa_corpus as corpus_seam
    return [path for path, _ in corpus_seam.collect(
        corpus, getattr(mod, name)).records]


def _run(checker: str, argv) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS / checker), *[str(a) for a in argv]],
        capture_output=True, text=True, timeout=600, cwd=str(PROGRAMS))


def _counts(text: str):
    """(population, undecided) as the gate itself printed them."""
    pop = [int(m) for m in _POPULATION.findall(text)]
    und = sum(int(m) for m in _UNDECIDED.findall(text))
    return (max(pop) if pop else 0), und


def _subject_lines(streams, subjects):
    """Group every output line under the subject it is about.

    A line naming a subject opens that subject's group and every line after it,
    IN THE SAME STREAM, belongs to it until another subject is named. Streams
    are grouped separately and then merged per subject, because a gate keeps its
    refusal on stderr and its detail on stdout deliberately -- the reader sees
    both, so the rule reads both.
    """
    groups = {s: [] for s in subjects}
    for stream in streams:
        current = None
        for line in stream.splitlines():
            named = [s for s in subjects if s in line]
            if named:
                current = max(named, key=len)
            if current is not None:
                groups[current].append(line)
    return groups


def _referents(lines, subject: str):
    """Referents in `lines`, excluding the subject itself and every code."""
    found = []
    for line in lines:
        body = _CODE.sub(" ", line.replace(subject, " "))
        found += [f"`{m}`" for m in _BACKTICKED_FIELD.findall(body)]
        found += _ARTEFACT_PATH.findall(body)
        if _REFUSAL_MARKER.search(line):
            found += _CLI_FLAG.findall(body)
    return sorted(set(found))


def assert_rc2_names_the_missing_artefact(proc, subjects, label):
    """THE RULE. Returns quietly for any rc but 2, and for an empty population.

    `subjects` are the paths the checker's OWN corpus walk found, so a gate is
    only ever asked to name documents it actually opened.
    """
    if proc.returncode != RC_UNDETERMINED:
        return
    text = proc.stdout + "\n" + proc.stderr
    population, undecided = _counts(text)
    if population == 0:
        return                      # the empty-corpus case; a different rule
    wanted = max(undecided, 1)
    named = sorted({str(s) for s in subjects if str(s) in text})
    assert len(named) >= wanted, (
        f"{label}: rc 2 over a population of {population} with {undecided} "
        f"undecided, and the output names {len(named)} of them. A refusal whose "
        f"SUBJECT is unnamed cannot be acted on.\n"
        f"named: {named}\n--- output ---\n{text}")
    unreferenced = []
    for subject, lines in _subject_lines(
            [proc.stdout, proc.stderr], named).items():
        if not _referents(lines, subject):
            unreferenced.append(subject)
    assert unreferenced == [], (
        f"{label}: rc 2 and these subjects are named but nothing says what is "
        f"ABSENT from them -- no field, no artefact, no flag, only verdict "
        f"codes. 'rc 2' with no named missing input is the failure mode this "
        f"layer exists to end.\n  " + "\n  ".join(unreferenced) +
        f"\n--- output ---\n{text}")


# ===========================================================================
# The SYNTHETIC arm. It owns its corpus, so the rule is enforced on a host that
# carries no campaign data at all -- which is every host that installs the
# plugin without this repository's `ppa-*/` trees.
# ===========================================================================
_H2H = _load("_h2h_rc2", "ppa_head_to_head_check.py")

_DESIGN = {"spec_sha256": "a" * 64, "pdk": "PDK_UNDER_TEST",
           "clock_target_ns": 10.0, "corners": ["c_slow", "c_typ"]}
_TIMING_SCOPE = {"stage": "post_route_extracted", "mode": "functional",
                 "process": "PROC_SLOW", "voltage_v": 1.62,
                 "temperature_c": 125.0, "rc_corner": "max",
                 "check": "setup", "clock": "clk"}


def _metric(value, unit, scope):
    return {"status": "MEASURED", "value": value, "unit": unit,
            "scope": copy.deepcopy(scope)}


def _arm(role, tuned, area, wns, power):
    from _ppa import benchmark as B
    return {
        "flow": f"{role}-flow", "role": role,
        "design": dict(_DESIGN),
        "contract": {"sha256": "b" * 64},
        "measurement_basis": "signed_off_gds",
        "config_source": "declared for this fixture",
        "tuned_by_this_project": tuned,
        "ppa": {"area_um2": _metric(area, "um^2",
                                    {"stage": "post_route_extracted"}),
                "timing_wns_ns": _metric(wns, "ns", _TIMING_SCOPE),
                "power_mw": _metric(power, "mW",
                                    {"stage": "post_route_extracted",
                                     "mode": "functional",
                                     "process": "PROC_SLOW",
                                     "voltage_v": 1.62,
                                     "temperature_c": 125.0,
                                     "activity_basis": "vectorless"})},
        "feasibility": {"checks": {n: {"violations": 0, "source": f"<{n}>"}
                                   for n in B.FEASIBILITY_FLOOR}},
        "tuning": {"supported": False},
    }


def _undecidable_record():
    """A record the gate can READ and cannot DECIDE: the null-corner sentinel.

    `null` is not an unknown-corner marker -- two of them compare EQUAL, so two
    numbers taken under conditions nobody recorded would read as taken under the
    same ones. The gate refuses that, correctly, and this fixture exists to make
    it refuse in a way a reader can act on.
    """
    doc = {"schema": "vibeic.ppa.comparison.v2",
           "arms": [_arm("subject", True, 1000.0, -0.10, 5.0),
                    _arm("baseline", False, 1200.0, -0.30, 6.0)]}
    for a in doc["arms"]:
        a["ppa"]["timing_wns_ns"]["scope"]["rc_corner"] = None
    return doc


@pytest.fixture
def h2h_corpus(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "one").mkdir(parents=True)
    (corpus / "two").mkdir(parents=True)
    for sub in ("one", "two"):
        (corpus / sub / "cmp.json").write_text(
            json.dumps(_undecidable_record()), encoding="utf-8")
    return corpus


def test_the_fixture_corpus_really_is_two_records_and_really_is_rc_2(h2h_corpus):
    """The paired half. Without it every assertion below is satisfied by a
    corpus the gate never opened, or by a gate that never refused."""
    assert len(_H2H.corpus_records(h2h_corpus)) == 2
    proc = _run("ppa_head_to_head_check.py", ["--corpus", h2h_corpus])
    assert proc.returncode == RC_UNDETERMINED, proc.stdout + proc.stderr
    population, undecided = _counts(proc.stdout + proc.stderr)
    assert (population, undecided) == (2, 2)


def test_a_refusal_over_two_records_names_both_of_them(h2h_corpus):
    """RED before this branch: `format_report` printed the code and dropped
    `report['record']` on the refusal branch, so two different documents
    produced two byte-identical blocks."""
    proc = _run("ppa_head_to_head_check.py", ["--corpus", h2h_corpus])
    assert_rc2_names_the_missing_artefact(
        proc, _H2H.corpus_records(h2h_corpus), "synthetic h2h corpus")


def test_the_two_blocks_are_not_byte_identical(h2h_corpus):
    """The sharpest statement of the defect: two subjects, one message.

    A count is not enough on its own -- a gate could name one record twice and
    satisfy a length check. Two records must produce two DIFFERENT refusals.
    """
    proc = _run("ppa_head_to_head_check.py", ["--corpus", h2h_corpus])
    # Blocks are cut at the marker and closed at the `[CANNOT CHECK]` line, NOT
    # by splitting the stream: the trailing roll-up would otherwise land inside
    # the last block and make two identical refusals compare unequal. That is
    # exactly how this assertion first passed against the broken program, so the
    # framing is part of the test.
    blocks, current = [], None
    for line in proc.stdout.splitlines():
        if line.startswith("[UNDETERMINED]"):
            current = [line]
            blocks.append(current)
        elif current is not None:
            current.append(line)
            if "[CANNOT CHECK]" in line:
                current = None
    assert len(blocks) == 2, proc.stdout
    assert blocks[0] != blocks[1], (
        "two different records produced byte-identical refusals; nothing in "
        "this output says which document either was about:\n" + proc.stdout)


def test_an_internal_error_is_rc_2_and_names_the_record_not_rc_1(tmp_path):
    """A CRASH MUST NOT BE PUBLISHED AS A FINDING ABOUT SILICON.

    MEASURED before this branch: an arm whose `design` is written as a bare
    digest STRING instead of a mapping raises out of `check_same_problem`, the
    traceback escaped `evaluate`, and the interpreter exited 1 -- which in this
    contract means "these two runs did not solve the same problem", a verdict
    nothing reached. In corpus mode ONE such document decides the whole row.

    2 and not 3: the invocation was correct. A corpus of fifty records where one
    is badly shaped is not a bad invocation, and 3 would let that one document
    decide a row about the other forty-nine.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    doc = _undecidable_record()
    doc["arms"][0]["design"] = "sha256:" + "a" * 64
    (corpus / "malformed.json").write_text(json.dumps(doc), encoding="utf-8")
    proc = _run("ppa_head_to_head_check.py", ["--corpus", corpus])
    assert proc.returncode == RC_UNDETERMINED, (
        f"an internal error exited {proc.returncode}; 1 is reserved for a "
        f"finding about the comparison\n{proc.stdout}{proc.stderr}")
    assert "INTERNAL_ERROR" in proc.stdout, proc.stdout
    assert_rc2_names_the_missing_artefact(
        proc, _H2H.corpus_records(corpus), "malformed record")


# ===========================================================================
# The feasibility arm, synthetic, on the same rule.
# ===========================================================================
def _candidates_doc():
    """One candidate whose EM axis was run and reached no verdict.

    This is the shape that matters and it is not a missing file: the tool ran,
    the artefact exists, the record names it, and the row is NOT_MEASURED with
    the reason stated. A gate that renders that as `FEAS_NOT_MEASURED` and
    stops has thrown away the only sentence a reader could act on.
    """
    view = {"stage": "post_route"}
    return {
        "schema": "vibeic.ppa.candidates.v1",
        "required_views_by_axis": {"em": [dict(view)]},
        "required_views": [dict(view)],
        "limits": {"reliability.em.worst_ratio": {"max": 1.0}},
        "allow_waivers": False,
        "candidates": [{
            "candidate_id": "cand_under_test",
            "metrics": [{
                "schema": "vibeic.ppa.metric.v1",
                "metric": "reliability.em.worst_ratio",
                "status": "NOT_MEASURED",
                "unit": "ratio",
                "scope": dict(view),
                "reason": ("the current-density screen reached no verdict, so "
                           "no segment was screened and no ratio exists"),
                "source": {"path": "reports/current_density_screen.json",
                           "sha256": "sha256:" + "0" * 64,
                           "tool": "TOOL_UNDER_TEST"},
            }],
            "waivers": [],
        }],
    }


@pytest.fixture
def feas_corpus(tmp_path):
    corpus = tmp_path / "candidates"
    (corpus / "trial").mkdir(parents=True)
    (corpus / "trial" / "candidates.json").write_text(
        json.dumps(_candidates_doc()), encoding="utf-8")
    return corpus


def test_the_feasibility_fixture_really_is_one_set_and_really_is_rc_2(feas_corpus):
    """The paired half again."""
    assert len(_subjects("ppa_feasibility_check.py", feas_corpus)) == 1
    proc = _run("ppa_feasibility_check.py", ["--corpus", feas_corpus])
    assert proc.returncode == RC_UNDETERMINED, proc.stdout + proc.stderr


def test_a_feasibility_refusal_names_the_metric_and_the_cited_artefact(feas_corpus):
    """RED before this branch: the refusal read 'at least one candidate was not
    adjudicated; this run makes no claim about it' and named nothing."""
    proc = _run("ppa_feasibility_check.py", ["--corpus", feas_corpus])
    assert_rc2_names_the_missing_artefact(
        proc, _subjects("ppa_feasibility_check.py", feas_corpus),
        "synthetic candidate set")
    text = proc.stdout + proc.stderr
    assert "reliability.em.worst_ratio" in text, text
    assert "reports/current_density_screen.json" in text, (
        "the record CITES the artefact it read and the refusal did not repeat "
        "it, so a reader is told a measurement is absent and not where the "
        "absence is:\n" + text)


def test_a_verdict_code_alone_is_not_a_referent():
    """The rule's own teeth, tested directly.

    Without this, `_referents` could be satisfied by the codes every refusal
    already carries, and the whole file would pass over the exact output it was
    written to refuse.
    """
    codes_only = ["[CANNOT CHECK] /c/x.json: UNDETERMINED  "
                  "em:FEAS_NOT_MEASURED,em:FEAS_INCOMPLETE_VIEW_SET"]
    assert _referents(codes_only, "/c/x.json") == []
    # NOR IS THE GATE'S OWN INVOCATION. Every corpus gate echoes `--corpus DIR`
    # in its header and roll-up; counting that would let any gate satisfy this
    # file by repeating the argument it was called with, and it did — negative
    # control B passed against a program whose naming had been fully removed.
    echo = ["ppa_feasibility_check --corpus /c: 1 set(s), 1 undetermined -> rc=2"]
    assert _referents(echo, "/c/x.json") == []
    # The SAME flag on a line that is a refusal IS a referent: there the gate is
    # telling the reader what to supply, which is the thing this file is for.
    told = ["[CANNOT CHECK] no route was established; pass --project to decide"]
    assert _referents(told, "/c/x.json") == ["--project"]
    with_referent = codes_only + [
        "  em: MISSING `reliability.em.worst_ratio` -- cited artefact: "
        "reports/screen.json"]
    assert _referents(with_referent, "/c/x.json") == [
        "`reliability.em.worst_ratio`", "reports/screen.json"]


# ===========================================================================
# The LIVE arm — the wired gates, over whatever corpora this repository holds.
# ===========================================================================
def _logical_lines(text: str):
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def _wired_corpus_invocations():
    """(checker, corpus-path) for every in-tree `--corpus` gate in the wiring.

    Rows aimed at the published corpus in the other repository are skipped by
    the same rule the sibling guard uses: they are ALLOWED to find nothing here,
    and a gate that found nothing is not the subject of this file.
    """
    if not WIRING.is_file():                        # pragma: no cover
        pytest.skip(f"wiring not present at {WIRING}")
    out = []
    for line in _logical_lines(WIRING.read_text(encoding="utf-8")):
        if line.lstrip().startswith("#") or "$PG/ppa_" not in line:
            continue
        for checker in CORPUS_GATES:
            if f"$PG/{checker}" not in line or "--corpus" not in line:
                continue
            argv = shlex.split(line, comments=True)
            raw = argv[argv.index("--corpus") + 1]
            path = Path(raw.replace("$ROOT", str(REPO))
                        .replace("${ROOT}", str(REPO)))
            if "benchmark-data" in path.parts or not path.is_dir():
                continue
            out.append((checker, path))
    return out


def test_the_live_arm_has_something_to_measure():
    """A live arm that resolved to nothing would pass every case below in
    silence, which is the shape of test this repository has shipped before."""
    wired = _wired_corpus_invocations()
    if not wired:
        pytest.skip("no in-tree PPA corpus gate is wired in this checkout")
    assert len(wired) >= 2, wired


@pytest.mark.parametrize(
    "checker,corpus",
    _wired_corpus_invocations() or [pytest.param(
        None, None, marks=pytest.mark.skip(reason="no in-tree corpus wired"))],
    ids=lambda v: Path(str(v)).name if v else "none")
def test_every_wired_corpus_gate_that_refuses_names_what_is_missing(
        checker, corpus):
    """THE ONE THIS FILE IS FOR, on the real wiring.

    Silent for a gate that PASSES or FAILS -- both of those reached a verdict.
    It speaks only when a gate stood in front of a population it had opened and
    said it could not look.
    """
    subjects = _subjects(checker, corpus)
    proc = _run(checker, ["--corpus", corpus])
    assert_rc2_names_the_missing_artefact(
        proc, subjects, f"{checker} --corpus {corpus.name}")


# ===========================================================================
# THE EXACT-PATH ROWS. Two wired gates refuse over a NON-EMPTY population
# through `--coverage` / `--candidates`, not a corpus, so the corpus arm above
# never reached them and the rule went unenforced on a third of the family.
# ===========================================================================
def _bundle(rows):
    return [{"schema": "vibeic.ppa.metric.v1", "metric": m, "status": "MEASURED",
             "unit": "u", "value": v, "scope": {"stage": "post_route"},
             "source": {"path": src, "sha256": "sha256:" + h * 64,
                        "tool": "TOOL_UNDER_TEST"}}
            for m, v, src, h in rows]


def test_a_coverage_refusal_names_the_bundle_it_read(tmp_path):
    """RED before this branch: the refusal said "the bundle" and never which.

    An rc 2 that names no document is indistinguishable from the same sentence
    over a file that is not there, and only one of those is fixed by looking
    somewhere else.
    """
    b = tmp_path / "records_flat.json"
    b.write_text(json.dumps(_bundle([("area.die.um2", 1.0, "r/a.log", "a")])),
                 encoding="utf-8")
    proc = _run("ppa_measurement_check.py", ["--coverage", b])
    assert proc.returncode == RC_UNDETERMINED, proc.stdout + proc.stderr
    text = proc.stdout + proc.stderr
    assert str(b) in text, (
        "the coverage refusal does not name the bundle it opened:\n" + text)
    assert "`expected`" in text, (
        "the coverage refusal does not name the artefact it needs:\n" + text)
    assert_rc2_names_the_missing_artefact(proc, [b], "coverage bundle")


def test_a_frontier_refusal_names_the_document_and_BOTH_missing_artefacts(tmp_path):
    """RED before this branch: one sentence, no document, no key, no flag.

    Both artefacts must be named, not just the objectives list: with only the
    objectives this gate would recompute a frontier and check it against its own
    recomputation, so naming one of the two would send a reader to manufacture
    exactly the pass the gate exists to refuse.
    """
    c = tmp_path / "candidates.json"
    c.write_text(json.dumps({
        "schema": "vibeic.ppa.candidates.v1",
        "required_views_by_axis": {"em": [{"stage": "post_route"}]},
        "required_views": [{"stage": "post_route"}], "limits": {},
        "allow_waivers": False,
        "candidates": [{"candidate_id": "c1", "metrics": _bundle(
            [("area.die.um2", 1.0, "r/a.log", "a")]), "waivers": []}]}),
        encoding="utf-8")
    proc = _run("ppa_pareto_check.py", ["--candidates", c])
    assert proc.returncode == RC_UNDETERMINED, proc.stdout + proc.stderr
    text = proc.stdout + proc.stderr
    assert str(c) in text, text
    assert "`objectives`" in text, text
    assert "--frontier" in text, (
        "only ONE of the two missing artefacts is named; a reader told to "
        "declare objectives and not told a published frontier is also required "
        "will build the self-marking pass this gate refuses:\n" + text)
    assert_rc2_names_the_missing_artefact(proc, [c], "frontier candidates")


def test_a_refused_record_is_rc_1_even_when_the_denominator_is_absent(tmp_path):
    """AN rc 2 WAS HIDING AN rc 1, and this is the one that matters most here.

    `run_coverage` states its own severity rule -- "An invalid record is a
    finding about the record set and outranks a coverage gap" -- and the rule
    could never fire when no denominator was declared, because `_expected_from`
    raised before the report carrying `record_refusals` was ever built.

    The two questions are INDEPENDENT. A record that is invalid is invalid
    whatever the denominator says. Answering "I could not check coverage" while
    silent about a conflicting record is the more dangerous direction of this
    lane's defect: an unearned PASS at least looks like a claim, an unearned
    NOT_CHECKED looks like diligence.

    MEASURED on the wired row: 148 rows, 54 refused -- 44 SCOPE_SENTINEL,
    8 SAME_ARTEFACT_TWO_VALUES, 2 CONFLICTING_RECORD -- reported as NOT_CHECKED
    and naming none of them.
    """
    b = tmp_path / "records_flat.json"
    # One metric, one scope, TWO different measured values from TWO artefacts.
    b.write_text(json.dumps(_bundle([
        ("route.wirelength.um", 16511.0, "r/pnr.log", "a"),
        ("route.wirelength.um", 16522.0, "r/pnr.metrics.json", "b")])),
        encoding="utf-8")
    proc = _run("ppa_measurement_check.py", ["--coverage", b])
    text = proc.stdout + proc.stderr
    assert "Traceback" not in text, (
        "a traceback escaped; rc 1 is reserved for a finding and a crash must "
        "never publish itself as one:\n" + text)
    assert proc.returncode == 1, (
        f"a conflicting record is a finding about the record set and this "
        f"returned {proc.returncode}\n{text}")
    assert "CONFLICTING_RECORD" in text, text
    # ...and the undecidable half is still SAID, not swallowed by the finding.
    assert "NO_EXPECTATION_SET" in text, (
        "the coverage question is still undecidable and the run must say so; "
        "an rc 1 about the records is not an answer about coverage:\n" + text)


def test_the_paired_half_a_clean_bundle_with_no_denominator_is_still_rc_2(tmp_path):
    """Without this, the test above is satisfied by a gate that returns 1 always.

    A bundle whose records are all VALID and which still declares no denominator
    has nothing to report as a finding, so it must stay rc 2 -- the STILL-CANNOT
    verdict this row has carried all along, and which this branch does not touch.
    """
    b = tmp_path / "records_flat.json"
    b.write_text(json.dumps(_bundle([("area.die.um2", 1.0, "r/a.log", "a")])),
                 encoding="utf-8")
    proc = _run("ppa_measurement_check.py", ["--coverage", b])
    assert proc.returncode == RC_UNDETERMINED, (
        "a clean bundle with no declared denominator must stay NOT CHECKED; "
        "turning it into a finding would be inventing one\n"
        + proc.stdout + proc.stderr)


def _wired_ppa_invocations():
    """Every PPA gate line in the wiring, as the argv the dispatcher will run.

    Not just the `--corpus` ones: the point below is about the ARGUMENTS, so a
    row is only measured if it is reproduced whole.
    """
    if not WIRING.is_file():                        # pragma: no cover
        pytest.skip(f"wiring not present at {WIRING}")
    rows = []
    for line in _logical_lines(WIRING.read_text(encoding="utf-8")):
        if line.lstrip().startswith("#") or "$PG/ppa_" not in line:
            continue
        argv = shlex.split(line, comments=True)
        try:
            start = next(i for i, a in enumerate(argv) if a.startswith("$PG/"))
        except StopIteration:                       # pragma: no cover
            continue
        checker = argv[start].split("/")[-1]
        rest = [a.replace("$ROOT", str(REPO)).replace("${ROOT}", str(REPO))
                for a in argv[start + 1:]]
        rows.append((checker, rest))
    return rows


@pytest.mark.parametrize(
    "checker,rest", _wired_ppa_invocations() or [pytest.param(
        None, None, marks=pytest.mark.skip(reason="no wiring in this checkout"))],
    ids=lambda v: (v if isinstance(v, str) else "|".join(
        a for a in (v or []) if a.startswith("--")) or "-"))
def test_no_wired_ppa_gate_is_a_bad_invocation(checker, rest):
    """rc 3 IS A GATE THAT DECIDED NOTHING, and it is quieter than rc 2.

    An rc 2 at least says "I could not look" and the roll-up renders it
    NOT_CHECKED. rc 3 says the CALLER got the arguments wrong -- and nothing in
    the roll-up distinguishes it, so a row whose flags have gone stale reads as a
    row that ran.

    RED ON THE TREE THIS BRANCH STARTED FROM, both `PPA arms solved one problem`
    rows. `--corpus` mode of `ppa_problem_integrity_check` was rewritten to group
    contracts by problem identity and pair inside each group -- which needs no
    baseline -- and its refusal of `--baseline` beside `--corpus` is deliberate
    and argued in the program. The wiring still passed both, so both rows had
    stopped examining any pair at all:

        [ppa_problem_integrity_check] REFUSE (bad invocation): --baseline/
        --candidate and --corpus were both given. ... Give exactly one. rc=3.

    This is the same family as everything else in this file -- a gate that is
    declared, wired, counted in the roll-up, and reaches no verdict -- arriving
    through the argument list instead of through the output.
    """
    proc = _run(checker, rest)
    assert proc.returncode != 3, (
        f"{checker} {' '.join(rest)}\nis wired with arguments its own program "
        f"refuses as a bad invocation, so this row decides nothing and the "
        f"roll-up cannot tell it from one that ran:\n"
        f"{proc.stdout}{proc.stderr}")


def test_a_gate_that_refuses_still_refuses(monkeypatch):
    """The direction this file must NEVER be satisfiable in.

    Every assertion above is about WORDING, and a wording rule is one lazy
    repair away from being met by deleting the refusal. So the two gates this
    branch changed are pinned at rc 2 over an input they cannot decide: if a
    later change makes either of them report a pass, this goes red before the
    naming rules are ever consulted.
    """
    for checker, flag in (("ppa_head_to_head_check.py", "--corpus"),
                          ("ppa_feasibility_check.py", "--corpus")):
        proc = _run(checker, [flag, str(PROGRAMS / "__no_such_corpus__")])
        assert proc.returncode == RC_UNDETERMINED, (
            f"{checker} over an absent corpus returned {proc.returncode}; "
            f"only 2 is honest here\n{proc.stdout}{proc.stderr}")
