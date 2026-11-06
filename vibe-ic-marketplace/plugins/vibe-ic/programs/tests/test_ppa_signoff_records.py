#!/usr/bin/env python3
"""The producer for the physical / reliability / equivalence feasibility axes.

Positive, NEGATIVE and VACUOUS for every axis. Weighted towards the negatives on
purpose: this program's failure mode is not "it computes the wrong number", it
is "it writes a zero for something nobody measured", and a suite of only
positive fixtures is a gate that is always green.

The DRC tests are driven by the SHIPPED fixture tree
(`fixtures/ppa/drc/zero_three_ways/`) rather than by numbers written here, so
that the discriminator this program implements is demonstrably the one the
fixture states and not an eleventh near-miss of it.
"""
import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import metrics as M      # noqa: E402

ZERO_THREE_WAYS = _PROGRAMS / "tests" / "fixtures" / "ppa" / "drc" / "zero_three_ways"


# --------------------------------------------------------------------------
# a run tree
# --------------------------------------------------------------------------
def _write(root: pathlib.Path, rel: str, doc) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n")


def clean_run(tmp_path, **overrides):
    """A run whose every sign-off artefact says the design closed."""
    root = tmp_path / "run"
    return root


def by_metric(records, name):
    return [r for r in records if r["metric"] == name]


def one(records, name):
    hits = by_metric(records, name)
    assert len(hits) == 1, f"{name}: expected 1 record, got {len(hits)}"
    return hits[0]


# --------------------------------------------------------------------------
# POSITIVE
# --------------------------------------------------------------------------












# --------------------------------------------------------------------------
# NEGATIVE -- DRC, driven by the shipped three-way fixture
# --------------------------------------------------------------------------
def _fixture_cases():
    doc = json.loads((ZERO_THREE_WAYS / "expected.json").read_text())
    return {c["dir"]: c for c in doc["cases"]}






def test_two_byte_identical_reports_get_opposite_answers(tmp_path):
    """`ran_and_found_none/drc.xml` and `ran_on_empty_layout/drc.xml` are the
    same 702 bytes. If this program decided from the report alone it could not
    tell them apart, so this asserts it does not."""
    cases = _fixture_cases()
    a = (ZERO_THREE_WAYS / "ran_and_found_none" / "drc.xml").read_bytes()
    b = (ZERO_THREE_WAYS / "ran_on_empty_layout" / "drc.xml").read_bytes()
    assert a == b, "the fixture's premise no longer holds"






# --------------------------------------------------------------------------
# NEGATIVE -- the other axes
# --------------------------------------------------------------------------




















# --------------------------------------------------------------------------
# VACUOUS
# --------------------------------------------------------------------------




# --------------------------------------------------------------------------
# THE CLI -- rc 0 / 2 / 3, and never rc 1
# --------------------------------------------------------------------------


def test_cli_rc0_on_a_run_that_measured_something(tmp_path):
    doc = json.loads((tmp_path / "out.json").read_text())
    assert doc["census"]["measured"] >= 6


def test_cli_rc2_and_a_marker_when_it_read_nothing(tmp_path):
    """A producer that reports success when it read nothing is the vacuous pass
    this repository has shipped before."""
    empty = tmp_path / "empty"
    empty.mkdir()
    # ...and the artefact it wrote is honest too, not just the exit code.
    doc = json.loads((tmp_path / "out.json").read_text())
    assert doc["census"]["measured"] == 0

    # EVERY row is present and NOT_MEASURED -- §2: "a report prints the literal
    # NOT_MEASURED row; it does not omit it". An omitted row and a met row look
    # the same to anything that scans a table for violations and finds none.
    #
    # The denominator is `SOURCES` PLUS the design-for-ECO rows, which come
    # from a second reader (`ppa_eco_spare_records.py` owns the spare plan;
    # this program owns only where the flow writes it). It is asserted as a
    # SET of metric names and not as a count: a count goes red when a row is
    # legitimately added and stays green when one is swapped for another.
    names = [r["metric"] for r in doc["records"]]
    assert len(names) == len(set(names)), f"a metric is emitted twice: {names}"
    eco = [n for n in names if n.startswith("design_for_eco.")]
    assert eco, (
        "the bundle carries no design-for-ECO row at all. The eco_readiness "
        "axis proves from these names, and an axis nothing produces evidence "
        "for reads UNDETERMINED on every run however good the design is -- "
        "which is the defect this whole program exists to have fixed.")
    assert all(r["status"] != "MEASURED" and "value" not in r
               for r in doc["records"]), (
        "an empty tree produced a MEASURED row. Nothing was read, and a "
        "number here would be one nobody measured.")






# --------------------------------------------------------------------------
# the whole point: the gate can now adjudicate a closed run
# --------------------------------------------------------------------------
