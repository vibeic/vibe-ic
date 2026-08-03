#!/usr/bin/env python3
"""A citation is not a declaration, and a second declared target is still declared.

Two defects, measured together on one real design, because one caused the other
to matter:

  (1) `_extract_pdk_target_with_provenance`'s open-PDK tier returns the FIRST
      name-list match anywhere in the document. A document's first mention of a
      PDK name is very often a FILE PATH in a `sources:` bibliography, so Phase 1
      adopted `reference/data/<pdk-a>.tcl` — a citation of a tool config file —
      as the design's `pdk_target`, with `extraction_evidence` pointing at the
      path, while the design's own target row sat 7 lines further down.

  (2) That target row names TWO processes (`<A> primary; <B> secondary`) and
      `pdk_target` is one scalar, so only the first survived. `phase3`'s
      declared-vs-resolved guard then REFUSED an entire run on <B> — a process
      the design declares, in the same breath, on the same row — before any
      backend step executed.

Both halves are asserted here, and both are written so they FAIL against the
pre-fix code: a test that cannot fail against the code it is written for proves
nothing.

chip-AGNOSTIC: the fixture below names open PDKs (a public namespace the flow's
own registry already carries) and no chip, foundry SKU or design literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase1_doc_one_shot_runner as p1        # noqa: E402
import phase3_one_shot_runner as p3            # noqa: E402


# A document shaped like a real one: YAML front matter that CITES a tool
# config file by path, then a target table that DECLARES two processes.
_DOC = """\
---
layer: L1
sources:
  - reference/README.md
  - reference/data/sky130.tcl + openlane_common.tcl
---

# Product metadata

| field | value |
|---|---|
| target PDK | open-source(SKY130 primary;GF180MCU secondary) |
| Target clock period — SKY130 | **10 ns (100 MHz)** |
| Target clock period — GF180MCU | **20 ns (50 MHz)** |
"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L1_product_metadata.md").write_text(_DOC, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# (1) a bibliography path must not outrank the design's own target row
# ---------------------------------------------------------------------------

def test_declaration_row_outranks_a_bibliography_path(project: Path) -> None:
    """PRE-FIX this returns line 5 (the `sources:` path). Post-fix, line 12."""
    tok, snippet, src, line = p1._extract_pdk_target_with_provenance(project)
    assert tok == "sky130"
    assert line == 12, (
        f"pdk_target was read from line {line} ({snippet!r}); the design's own "
        f"target row is line 12 and the `sources:` path is line 5")
    assert ".tcl" not in (snippet or ""), (
        "the recorded evidence is a file path, i.e. a citation of a tool "
        "config file rather than a statement of intent")


def test_a_path_is_still_used_when_it_is_the_only_evidence(
        tmp_path: Path) -> None:
    """The repair is a RANKING, not a filter — no answer is lost.

    A document whose ONLY PDK evidence is a path must answer exactly as it did
    before, or the fix has traded one silent wrong value for a silent null.
    """
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "sources:\n  - reference/data/sky130.tcl\n", encoding="utf-8")
    tok, _snip, _src, line = p1._extract_pdk_target_with_provenance(tmp_path)
    assert tok == "sky130"
    assert line == 2


def test_path_classifier_does_not_eat_ordinary_identifiers() -> None:
    f = p1._match_is_inside_path_token
    assert f("- reference/data/sky130.tcl + x", 17, 23) is True
    assert f("map to sky130_fd_sc_hd cells", 7, 13) is False
    assert f("| PDK | open-source(SKY130 primary) |", 20, 26) is False


# ---------------------------------------------------------------------------
# (2) a co-declared second target is a declared target
# ---------------------------------------------------------------------------

def test_second_target_on_the_same_row_is_recorded(project: Path) -> None:
    tok, _snip, src, line = p1._extract_pdk_target_with_provenance(project)
    alts = p1._declared_pdk_alternates(project, src, line, tok)
    assert alts == ["sky130", "gf180mcu"], alts


def test_a_name_elsewhere_in_the_document_is_not_co_declared(
        tmp_path: Path) -> None:
    """Same-row scope. A MENTION must not become a DECLARATION."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "| target PDK | SKY130 |\n"
        "\n"
        "Prior art was demonstrated on GF180MCU by a third party.\n",
        encoding="utf-8")
    tok, _snip, src, line = p1._extract_pdk_target_with_provenance(tmp_path)
    assert p1._declared_pdk_alternates(tmp_path, src, line, tok) == []


def _write_l19(project: Path, target: str, alternates=None) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    fields = {"pdk_target": target}
    if alternates is not None:
        fields["pdk_target_alternates"] = alternates
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": fields}), encoding="utf-8")


def test_guard_admits_a_co_declared_second_target(tmp_path: Path) -> None:
    """PRE-FIX this REFUSES; the whole backend never runs."""
    _write_l19(tmp_path, "sky130", ["sky130", "gf180mcu"])
    assert p3.declared_pdk_target_guard(tmp_path, "gf180mcuD") is None


def test_guard_still_refuses_a_process_the_design_never_names(
        tmp_path: Path) -> None:
    _write_l19(tmp_path, "sky130", ["sky130", "gf180mcu"])
    msg = p3.declared_pdk_target_guard(tmp_path, "nangate45")
    assert msg and "REFUSED" in msg


def test_guard_unchanged_for_a_single_target_design(tmp_path: Path) -> None:
    """No `pdk_target_alternates` key at all — the pre-fix path, verbatim."""
    _write_l19(tmp_path, "sky130")
    assert p3.declared_pdk_target_guard(tmp_path, "sky130A") is None
    assert p3.declared_pdk_target_guard(tmp_path, "gf180mcuD") is not None


# ---------------------------------------------------------------------------
# revision tolerance: one-directional, on purpose
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("resolved,declared,expected", [
    ("gf180mcuD", {"gf180mcu"},  True),    # family named -> revision admitted
    ("sky130A",   {"sky130"},    True),
    ("sky130A",   {"sky130b"},   False),   # revision named -> NOT interchangeable
    ("gf180mcuA", {"gf180mcud"}, False),
    ("nangate45", {"sky130"},    False),
    ("asap7",     {"asap7"},     True),
])
def test_revision_tolerance(resolved, declared, expected) -> None:
    assert p3._declares_resolved_pdk(resolved, declared) is expected


# ---------------------------------------------------------------------------
# the timing contract must be resolved against the process being built
# ---------------------------------------------------------------------------

def test_pdk_keyed_clock_row_is_selected_by_the_run_pdk(project: Path) -> None:
    """The document answers this; the walker was flipping a coin.

    PRE-FIX there is no selector at all and the primary clock is whichever
    frequency row the prose walker reached first — right on the process listed
    first, wrong on every other.
    """
    a = p1._v1_9_65_pdk_scoped_clock_mhz(project, "sky130A")
    b = p1._v1_9_65_pdk_scoped_clock_mhz(project, "gf180mcuD")
    assert a is not None and a[0] == 100.0 and a[2] == 13
    assert b is not None and b[0] == 50.0 and b[2] == 14


def test_no_pdk_stated_changes_nothing(project: Path) -> None:
    assert p1._v1_9_65_pdk_scoped_clock_mhz(project, None) is None
    assert p1._v1_9_65_pdk_scoped_clock_mhz(project, "") is None


def test_a_process_the_document_does_not_key_changes_nothing(
        project: Path) -> None:
    assert p1._v1_9_65_pdk_scoped_clock_mhz(project, "nangate45") is None


def test_a_row_that_is_not_about_the_clock_is_not_a_clock_row(
        tmp_path: Path) -> None:
    """A time literal on a PDK row is not automatically a clock period."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(
        "| GF180MCU pad setup time | 3 ns |\n", encoding="utf-8")
    assert p1._v1_9_65_pdk_scoped_clock_mhz(tmp_path, "gf180mcuD") is None
