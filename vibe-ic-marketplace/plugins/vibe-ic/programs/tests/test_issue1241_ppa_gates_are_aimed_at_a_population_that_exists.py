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
import re
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
    # Wired by "PPA ablation records (within-project)". A record gate like the
    # rest: it selects on the DECLARED schema through the shared seam, so the
    # population counter below reaches it by its own predicate.
    "ppa_ablation_check.py": ("--record", "--corpus"),
}

#: A path under here is the published corpus in the other repository. Finding
#: nothing is its correct behaviour on this host.
EXTERNAL = "benchmark-data"


def _logical_lines(text: str):
    """The wiring file continues gate invocations with a trailing backslash."""
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def _wiring_text() -> str:
    """The wiring file, or a SKIP that names what could not be read.

    `programs/tests/` ships with the plugin and `tools/ci/` does not, so on an
    installed plugin this file has no subject. `_invocations` guarded that from
    the start; `test_no_ppa_exemption_still_claims_that_no_record_has_been_filed`
    read WIRING directly and did not, so THREE of four reads were guarded and the
    fourth raised FileNotFoundError. MEASURED by moving the wiring file aside and
    running this file's whole family: 1 failed, 44 passed, 9 skipped — the one
    failure being that traceback, about nothing to do with exemptions.

    A guard that ERRORS because its subject is absent is
    blocking-because-unreadable, which is the state this family exists to keep
    apart from a finding.
    """
    if not WIRING.is_file():
        pytest.skip(f"{WIRING} is not in this checkout — the plugin's tests ship "
                    "without tools/ci/, so this guard has no subject here. "
                    "NOT a pass and NOT a finding.")
    return WIRING.read_text(encoding="utf-8")










#: How to count a population, per checker. Each uses the checker's OWN corpus
#: walk, so this cannot drift from what the gate will actually find.










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
    guilty = [line for line in _logical_lines(_wiring_text())
              if line.lstrip().startswith("uncheckable_until")
              and "no run in this repository has filed one yet" in line]
    assert guilty == [], (
        "a PPA exemption still declares that no record has been filed here:\n  "
        + "\n  ".join(g[:160] for g in guilty))


#: A wired `ppa_*` gate this family deliberately does not cover, with the reason.
#: It must stay a DECLARATION rather than a silence: the test below forces a new
#: wired ppa gate to be either covered or named here.
#:
#: THE BAR FOR A ROW HERE, and it is not "this gate has no corpus". It is that
#: the defect this file was written about — a gate whose subject moved away,
#: reporting NOT_CHECKED forever while nothing noticed — is STRUCTURALLY
#: unreachable for it. The six covered gates are all wired
#: `run_tolerating_uncheckable`, which renders rc 2 as a non-fatal NOT_CHECKED;
#: that tolerance is what let them sit dead for two months, and it is what makes
#: the population count the only signal they still have a subject. A gate wired
#: with a plain `run` has rc 2 BLOCKING (`_gate_dispatch.sh`: `run` is
#: `_dispatch 0 0`), so the day its input goes missing it goes red and stops the
#: suite. It cannot go quiet, so a population counter would be measuring a
#: failure mode it does not have.
NOT_A_RECORD_GATE: dict = {
    "ppa_page_claim_check.py":
        "Its subject is a PUBLISHED DOCUMENT — `ppa-e2e/report/winner/report.md` "
        "and the `claims.json` emitted beside it — not a corpus of filed PPA "
        "records, so there is no record population to count. Wired with a plain "
        "`run`, so rc 2 (page or claims unreadable) BLOCKS rather than becoming a "
        "quiet NOT_CHECKED. MEASURED: 35 sentence(s), 139 claim(s), 9 banned "
        "form(s) enforced, rc 0.",
    "ppa_closure_run.py":
        "Wired in `--verify-registry` mode, where the subject is the actuator "
        "REGISTRY — a permission table at `$PLUGIN/config/ppa_actuator_registry."
        "yaml` — not records any run filed. Two reasons it cannot be covered "
        "here: the population is authorisations rather than documents, and "
        "`_resolve` substitutes `$ROOT` only, so a `$PLUGIN`-rooted input is not "
        "addressable by this family's resolver at all. Wired with a plain `run`, "
        "so rc 2 BLOCKS. MEASURED: 6 actuators (1 EXECUTABLE), 9 domains "
        "(2 EXECUTABLE), 1 controller, every EXECUTABLE claim resolves, rc 0.",
}
