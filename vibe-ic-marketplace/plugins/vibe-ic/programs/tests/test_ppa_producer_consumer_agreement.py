#!/usr/bin/env python3
"""The producers and the canonical consumer must agree about the shape of a
record. This file is what makes them, and it is a CENSUS rather than a list of
examples on purpose.

WHAT WENT WRONG, MEASURED 2026-08-21 ON A REAL RUN TREE
======================================================
Fourteen lanes built the PPA layer in parallel from one frozen interface, and
the seams were exactly where two authors read `docs/PPA_INTERFACES.md` and came
away with different readings:

* every one of the three shipped record producers wrote an envelope
  `_ppa/metrics.records_from_document` refused -- so the canonical extraction
  CLI indexed ZERO records from every extractor the repository ships (F-4);
* `_ppa/area.py` declared the unit of `area.proxy.cell_count` as `"cells"`
  while `_ppa/metrics.py` demanded `"count"`, and six records per run were
  refused by their own sibling module (F-5).

Both were single-line disagreements that no test could see, because every test
exercised ONE side. The tests below walk the whole registry and the whole
envelope namespace instead, so a NEW metric or a NEW envelope is covered the
day it is added rather than the day somebody writes a test for it.

    positive   every declared unit agrees; every registered envelope reads
    negative   a deliberately contradicting unit is caught by these same checks
    vacuous    a record with no unit at all is refused, never assumed
    mutation   revert either fix and a named test here goes red

chip-AGNOSTIC: registries, envelopes and synthetic records. No design, PDK,
vendor or part literal appears here or can affect a verdict.
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from _ppa import area as A                       # noqa: E402
from _ppa import backends as BK                  # noqa: E402
from _ppa import metrics as M                    # noqa: E402
from _ppa import power as P                      # noqa: E402
from _ppa import timing as T                     # noqa: E402
from _ppa.backends import openroad as ORB        # noqa: E402
from _ppa.backends import orfs as ORFS           # noqa: E402

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PPA = PROGRAMS / "_ppa"

SCOPE = {"stage": "synthesis"}
SOURCE = {"path": "stat.txt", "tool": "yosys"}


# ─────────────────────────── 1. the unit / name rule ────────────────────────

def test_every_area_metric_builds_a_record_its_own_consumer_ACCEPTS():
    """THE F-5 GUARD, and it is general over the registry rather than over the
    three names that happened to be wrong.

    `_ppa/area.py` owns the unit of every area metric and `_ppa/metrics.py`
    validates it. Any metric either module gains is covered here the day it is
    added: build the record the producer would build, and hand it to the
    consumer that has to accept it.
    """
    assert A.AREA_METRICS, "the registry is empty; this test would be vacuous"
    bad = {}
    for name in sorted(A.AREA_METRICS):
        rec = A.area_record(name, A.MEASURED, value=1.0, scope=SCOPE,
                            source=SOURCE)
        problems = M.validate(rec)
        if problems:
            bad[name] = (rec.get("unit"), problems)
    assert not bad, (
        "these area metrics build records the canonical index refuses:\n"
        + "\n".join(f"  {n}: unit={u!r} -> {[c for c, _ in p]}"
                    for n, (u, p) in sorted(bad.items())))


@pytest.mark.parametrize("table,label", [
    ({m: u for m, u, _ in ORB._JSON_MAP.values()}, "openroad._JSON_MAP"),
    ({m: u for m, u in ORFS.NUMERIC_METRICS.values()}, "orfs.NUMERIC_METRICS"),
    ({n: s.unit for n, s in A.AREA_METRICS.items()}, "area.AREA_METRICS"),
])
def test_no_declared_unit_contradicts_its_metric_name(table, label):
    """Every static metric->unit table in the tree, against the one rule.

    `unit_suffix_of` is the only cross-check in the system positioned to catch
    an order-of-magnitude unit error, because every consumer downstream trusts
    `unit`.
    """
    assert table, f"{label} is empty; this parametrisation would be vacuous"
    clashes = {name: (declared, M.unit_suffix_of(name))
               for name, declared in table.items()
               if M.unit_suffix_of(name) is not None
               and M.unit_suffix_of(name).lower() != str(declared).lower()}
    assert not clashes, (
        f"{label} declares units its own metric names contradict:\n"
        + "\n".join(f"  {n}: table says {d!r}, the name claims {c!r}"
                    for n, (d, c) in sorted(clashes.items())))


def test_the_unit_rule_is_ENFORCED_and_not_merely_declared():
    """The negative arm. If `unit_suffix_of` stopped firing, the census above
    would pass over a tree where every unit was wrong."""
    rec = A.area_record("area.proxy.cell_count", A.MEASURED, value=287.0,
                        scope=SCOPE, source=SOURCE)
    rec["unit"] = "cells"                       # the pre-v1.11.33 declaration
    codes = [c for c, _ in M.validate(rec)]
    assert "UNIT_CONTRADICTS_NAME" in codes, codes


def test_vacuous_a_record_with_NO_unit_is_refused_never_assumed():
    """The name is a cross-check on a declared unit, not a substitute for one:
    a consumer that inferred `count` from `_count` would accept a record whose
    producer never established a unit at all."""
    rec = A.area_record("area.proxy.cell_count", A.MEASURED, value=287.0,
                        scope=SCOPE, source=SOURCE)
    for missing in ({}, {"unit": ""}, {"unit": None}):
        probe = dict(rec)
        probe.pop("unit", None)
        probe.update(missing)
        codes = [c for c, _ in M.validate(probe)]
        assert "NO_UNIT" in codes, (missing, codes)


# ──────────────────── 2. the envelope census (F-4) ──────────────────────────

#: Every `vibeic.ppa.*` document schema in `_ppa/`, classified. A carrier holds
#: canonical metric records and MUST be in `M.RECORD_CARRIERS`; a non-carrier
#: holds something else and must not be. The point of listing the non-carriers
#: is that a new envelope cannot be added without a decision being recorded
#: here -- an omission fails the census instead of silently costing a producer
#: every record it emits, which is what happened to all three of them.
NON_CARRIERS = {
    "vibeic.ppa.metric.v1":                 "one record, not a set of them",
    "vibeic.ppa.contract.v1":               "a measurement contract",
    "vibeic.ppa.contract_declaration.v1":   "the input to building one",
    "vibeic.ppa.identity.v1":               "one of the five identities",
    "vibeic.ppa.run_manifest.v1":           "artefact hashes for a run",
    "vibeic.ppa.evidence_manifest.v1":      "which artefacts back which claim",
    "vibeic.ppa.feasibility.v1":            "an adjudication, not a reading",
    "vibeic.ppa.area_verdict.v1":           "an adjudication over records: it "
                                            "holds comparisons and a verdict, "
                                            "not the records themselves",
    "vibeic.ppa.comparison.v1":             "a head-to-head, v1",
    "vibeic.ppa.comparison.v2":             "a head-to-head, v2",
    "vibeic.ppa.pareto_frontier.v1":        "a frontier over records",
    "vibeic.ppa.search_manifest.v1":        "the candidate lifecycle",
    "vibeic.ppa.closure_run.v1":            "a controller run",
    "vibeic.ppa.actuator_registry.v1":      "what a controller may move",
    # The agent control plane (`_ppa/agent_policy.py`, `_ppa/agent_router.py`,
    # `_ppa/agent_context.py`). None of these five carry a reading: the context
    # is deliberately evidence REFERENCES and hashes with no file content at
    # all, and the other four are a permission set, a situation, a diagnosis
    # and a proposal. Declared rather than left out, because "not classified"
    # and "classified as not a carrier" are the two states this guard exists to
    # keep apart.
    "vibeic.ppa.agent_policy.v1":           "what an agent is allowed to do",
    "vibeic.ppa.situation.v1":              "the question put to the router",
    "vibeic.ppa.diagnosis.v1":              "the router's answer, not a reading",
    "vibeic.ppa.agent_handoff.v1":          "an explicit waive to an agent",
    "vibeic.ppa.agent_proposal.v1":         "what an agent proposes doing",
    "vibeic.ppa.agent_context.v1":          "evidence REFERENCES and hashes; "
                                            "it carries no file content at "
                                            "all, by construction",
}

_SCHEMA_RE = re.compile(r'"(vibeic\.ppa\.[a-z_0-9]+\.v\d+)"')


def _declared_schemas():
    found = set()
    for path in sorted(PPA.rglob("*.py")):
        found |= set(_SCHEMA_RE.findall(path.read_text(encoding="utf-8")))
    return found


def test_every_ppa_envelope_is_classified_carrier_or_not():
    """THE F-4 GUARD. A new producer envelope must be registered as a record
    carrier or declared a non-carrier -- never left to be discovered by a run
    that indexes zero records and calls it a clean extraction."""
    declared = _declared_schemas()
    assert len(declared) > 10, f"the scan found only {declared}; it is broken"
    unclassified = declared - set(M.RECORD_CARRIERS) - set(NON_CARRIERS)
    assert not unclassified, (
        "these `vibeic.ppa.*` envelopes are neither registered in "
        "`_ppa/metrics.RECORD_CARRIERS` nor declared a non-carrier here:\n  "
        + "\n  ".join(sorted(unclassified))
        + "\nIf it carries metric records, register it -- otherwise every "
          "record it holds is refused UNRECOGNISED_DOCUMENT.")
    assert not (set(M.RECORD_CARRIERS) & set(NON_CARRIERS))


def test_every_registered_carrier_actually_reads():
    """A registration that names the wrong key is worse than none: it turns
    UNRECOGNISED_DOCUMENT into NO_RECORDS and the producer still loses."""
    rec = M.measured("area.die_um2", 12000.0, "um^2", SCOPE, SOURCE)
    for schema, key in sorted(M.RECORD_CARRIERS.items()):
        doc = {"schema": schema, key: [rec]}
        assert M.records_from_document(doc) == [rec], schema
        with pytest.raises(M.MetricError) as exc:
            M.records_from_document({"schema": schema})
        assert exc.value.code == "NO_RECORDS", schema


def test_the_three_shipped_producers_write_documents_the_consumer_READS():
    """The exact defect, end to end: build each producer's real envelope and
    hand it to the canonical consumer.

    The record CONTENT is not asserted here -- these are envelope shapes, and
    the domain lanes own what goes in them.
    """
    rec = M.measured("area.die_um2", 12000.0, "um^2", SCOPE, SOURCE)
    envelopes = {
        "openroad": {"schema": "vibeic.ppa.backend_records.v1",
                     "records": [rec]},
        "timing":   {"schema": "vibeic.ppa.timing_rows.v1", "rows": [rec]},
        "power":    {"schema": "vibeic.ppa.power.v1", "metrics": [rec]},
    }
    for who, doc in sorted(envelopes.items()):
        assert M.records_from_document(doc) == [rec], who


def test_those_envelope_names_are_the_ones_the_producers_REALLY_write():
    """The census above is only worth anything if the strings match the
    producers. Read them from the modules, not from this file."""
    assert ORB.ParseOutcome().document()["schema"] in M.RECORD_CARRIERS
    assert T._document(pathlib.Path("."), [], [])["schema"] in M.RECORD_CARRIERS
    assert P.SCHEMA_POWER in M.RECORD_CARRIERS


def test_vacuous_an_unregistered_envelope_is_REFUSED_not_read_as_empty():
    """Rule 9 at the document level, and the reason the registry is closed."""
    with pytest.raises(M.MetricError) as exc:
        M.records_from_document({"schema": "vibeic.ppa.not_a_thing.v1",
                                 "records": []})
    assert exc.value.code == "UNRECOGNISED_DOCUMENT"


# ──────────────────── 3. the backend driver census (F-2) ────────────────────

def test_every_backend_is_drivable_or_says_WHY_NOT():
    """THE F-2 GUARD. `--backend TOOL` refused for every tool including the
    five that exist, with one blanket sentence. A backend must now either be
    drivable from a path or state its own reason, so the refusal a caller reads
    names the actual obstacle."""
    assert BK.BACKENDS
    silent = []
    for tool in BK.BACKENDS:
        try:
            BK.driver_for(tool)
        except BK.BackendNotDrivable as exc:
            if not exc.reason or len(exc.reason) < 40:
                silent.append(tool)
    assert not silent, (
        f"these backends refuse to be driven without saying why: {silent}")
    assert BK.drivable(), (
        "not one backend can be driven from a path, which is the F-2 defect")


def test_a_backend_that_needs_an_option_DECLARES_it():
    """yosys prints two statistics blocks in one transcript and they are two
    stages of one run. A driver that defaulted the stage would compare a
    pre-techmap count against a mapped one."""
    assert "stage" in BK.requirements("yosys")
    with pytest.raises(ValueError) as exc:
        BK.driver_for("yosys")(PROGRAMS / "_ppa" / "backends" / "yosys.py")
    assert "stage" in str(exc.value)
