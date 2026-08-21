#!/usr/bin/env python3
"""Every PPA record gate must be aimed at a population that EXISTS and is NOT EMPTY.

WHY THIS FILE EXISTS
====================
v1.10.56 moved `benchmark-data/` to its own repository. vibe-ic#1710 found four
hygiene gates aimed at what it held and re-aimed them. The SIX PPA record gates
were aimed at the same tree and were NOT in that sweep, so they went on pointing
at `benchmark-data/ppa/*` for the next two months:

    PPA head-to-head records    rc 2  no corpus at <ROOT>/benchmark-data
    PPA measurement contract    rc 2  <ROOT>/benchmark-data/ppa/contract.json: absent
    PPA measurement coverage    rc 2  INPUT_ABSENT: no such bundle: .../coverage.json
    PPA promotion feasibility   rc 2  candidates not found: .../candidates.json
    PPA frontier recomputes     rc 2  candidates not found: .../candidates.json
    PPA arms solved one problem rc 2  baseline .../baseline_contract.json: absent

Each was carried by `uncheckable_until 2026-11-30`, and four of those exemptions
declared "no run in this repository has filed one yet" while 17 head-to-head
records, 82 contracts, 21 candidate sets and 80 published contract pairs sat
committed in `ppa-e2e/` and `ppa-crosslayer/`. Six gates, zero seconds each, zero
items examined, and a date three months out.

NOTHING WOULD HAVE NOTICED. `run_tolerating_uncheckable` renders rc 2 as
NOT_CHECKED, which is exactly what these gates SHOULD report when they cannot
look — so the roll-up was correct and useless at the same time. The only signal
that a gate has stopped having a subject is the one this file supplies: its
declared input, resolved, is a thing that exists and holds something.

WHAT THIS DOES NOT ASSERT. Not the verdict. A gate here may PASS, FAIL or be
UNDETERMINED over its population and this file is indifferent — `h2h_F` is
refused today and that is a finding, not a wiring defect. The only claim is that
each gate has a subject to reach a verdict ABOUT.

THE ONE EXEMPT SHAPE, and it is declared rather than inferred: a row aimed at
`benchmark-data/` is aimed at the published corpus in the OTHER repository,
reachable only when `$VIBE_IC_BENCHMARK_DATA` points at a clone. Those rows are
allowed to find nothing here. What is NOT allowed is for that to be the ONLY way
a checker is invoked — which is the state v1.10.56 left behind and which
`test_every_ppa_checker_is_aimed_somewhere_that_exists` is the guard against.
"""
import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
WIRING = REPO / "tools" / "ci" / "repo_hygiene_gates.sh"

sys.path.insert(0, str(PROGRAMS))

#: The six gates vibe-ic#1241 is about, and the flag each reads its subject from.
#: A checker added to this family without a row here is invisible to this guard,
#: which is why the last test asserts the family is complete against the wiring.
PPA_RECORD_CHECKERS = {
    "ppa_head_to_head_check.py": ("--corpus",),
    "ppa_contract_check.py": ("--corpus", "--contract"),
    "ppa_measurement_check.py": ("--coverage",),
    "ppa_feasibility_check.py": ("--candidates", "--corpus"),
    "ppa_pareto_check.py": ("--candidates", "--frontier"),
    "ppa_problem_integrity_check.py": ("--baseline", "--candidate", "--corpus"),
}

#: A path under here is the published corpus in the other repository. Finding
#: nothing is its correct behaviour on this host.
EXTERNAL = "benchmark-data"


def _logical_lines(text: str):
    """The wiring file continues gate invocations with a trailing backslash."""
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def _invocations():
    """(checker, {flag: raw-argument}) for every PPA record gate in the wiring."""
    if not WIRING.is_file():                       # pragma: no cover
        pytest.skip(f"wiring not present at {WIRING}")
    out = []
    for line in _logical_lines(WIRING.read_text(encoding="utf-8")):
        stripped = line.lstrip()
        if stripped.startswith("#") or "$PG/ppa_" not in line:
            continue
        for checker, flags in PPA_RECORD_CHECKERS.items():
            if f"$PG/{checker}" not in line:
                continue
            try:
                argv = shlex.split(line, comments=True)
            except ValueError:                     # pragma: no cover
                argv = line.split()
            args = {}
            for flag in flags:
                if flag in argv:
                    idx = argv.index(flag)
                    if idx + 1 < len(argv):
                        args[flag] = argv[idx + 1]
            out.append((checker, args))
    return out


def _resolve(raw: str) -> Path:
    """`$ROOT` is the subject root the wiring `cd`s into; here that is the repo."""
    return Path(raw.replace("$ROOT", str(REPO)).replace("${ROOT}", str(REPO)))


def _is_external(path: Path) -> bool:
    return EXTERNAL in path.parts


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, PROGRAMS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


#: How to count a population, per checker. Each uses the checker's OWN corpus
#: walk, so this cannot drift from what the gate will actually find.
def _population(checker: str, flag: str, path: Path) -> int:
    if flag != "--corpus":
        return 1 if path.is_file() else 0
    if checker == "ppa_head_to_head_check.py":
        return len(_load("_hh", checker).corpus_records(path))
    if checker == "ppa_contract_check.py":
        return len(_load("_cc", checker).corpus_contracts(path))
    if checker == "ppa_feasibility_check.py":
        return len(_load("_fc", checker).corpus_candidate_sets(path))
    if checker == "ppa_problem_integrity_check.py":
        # A PAIR needs the baseline too, and the baseline is the OTHER flag on
        # the same invocation — so the count here is of candidates available to
        # pair with, which is what an empty corpus would make zero.
        mod = _load("_pi", checker)
        return len(mod.corpus_candidates(path, path / "__no_such_baseline__"))
    raise AssertionError(f"no population counter for {checker} --corpus")


def test_the_wiring_still_invokes_every_ppa_record_gate():
    """The guard is worthless if the gates were simply deleted."""
    found = {c for c, _ in _invocations()}
    assert found == set(PPA_RECORD_CHECKERS), (
        f"wiring invokes {sorted(found)}; this family is "
        f"{sorted(PPA_RECORD_CHECKERS)}")


def test_every_declared_input_that_is_not_the_external_corpus_exists():
    """RED IN v1.10.56, on the day `benchmark-data/` left this repository."""
    missing = []
    for checker, args in _invocations():
        for flag, raw in args.items():
            path = _resolve(raw)
            if _is_external(path):
                continue
            if not path.exists():
                missing.append(f"{checker} {flag} {raw} -> {path} does not exist")
    assert missing == [], (
        "a PPA gate names an input that is not there, so it can only ever "
        "report 'I could not look':\n  " + "\n  ".join(missing))


def test_every_in_tree_corpus_holds_at_least_one_document():
    """A directory that exists and holds nothing is the OTHER way a gate stops
    having a subject, and it prints the same zero."""
    empty = []
    for checker, args in _invocations():
        for flag, raw in args.items():
            path = _resolve(raw)
            if _is_external(path) or not path.exists():
                continue
            n = _population(checker, flag, path)
            if n == 0:
                empty.append(f"{checker} {flag} {raw} -> 0 document(s)")
    assert empty == [], (
        "a PPA gate is aimed at an EMPTY population; it will report a zero it "
        "did not measure:\n  " + "\n  ".join(empty))


@pytest.mark.parametrize("checker", sorted(PPA_RECORD_CHECKERS))
def test_every_ppa_checker_is_aimed_somewhere_that_exists(checker):
    """THE ONE THIS FILE IS FOR.

    A checker invoked ONLY against `benchmark-data/` is a checker that decides
    nothing on any host that does not carry a clone — which is every host in CI
    today. That is the state v1.10.56 left and that no exemption expiry, no
    roll-up and no other test could see.
    """
    aims = [(flag, _resolve(raw))
            for c, args in _invocations() if c == checker
            for flag, raw in args.items()]
    assert aims, f"{checker} is invoked with none of {PPA_RECORD_CHECKERS[checker]}"
    live = [(f, p) for f, p in aims if not _is_external(p) and p.exists()]
    assert live, (
        f"{checker} is aimed ONLY at the published corpus in the other "
        f"repository ({[str(p) for _, p in aims]}). On a host without a clone "
        f"it examines nothing, forever, and reports NOT_CHECKED while doing it.")


def test_no_ppa_exemption_still_claims_that_no_record_has_been_filed():
    """The sentence that let six gates sit dead for two months.

    Four of the six exemptions read "no run in this repository has filed one
    yet". Measured on the day that wording was reviewed, this tree held 17
    head-to-head records, 82 contracts, 21 candidate sets and 80 published
    contract pairs. The gates were not waiting for a record; they were pointed
    at a directory that had moved. An exemption may say a gate cannot look — it
    may not say there is nothing to look at when there is.
    """
    # DECLARATION LINES ONLY. A comment may quote the old wording — the one in
    # this wiring file does, to record what it was corrected from — and a test
    # that could not tell a quotation from a live declaration would force the
    # history to be deleted to stay green.
    guilty = [line for line in _logical_lines(WIRING.read_text(encoding="utf-8"))
              if line.lstrip().startswith("uncheckable_until")
              and "no run in this repository has filed one yet" in line]
    assert guilty == [], (
        "a PPA exemption still declares that no record has been filed here:\n  "
        + "\n  ".join(g[:160] for g in guilty))
