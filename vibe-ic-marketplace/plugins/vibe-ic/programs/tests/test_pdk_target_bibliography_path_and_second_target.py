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


class _PdkBoundaryReached(Exception):
    """Stop before unrelated layer generation after exercising the L19 producer."""


def _front_door_pdk(project, monkeypatch, pdk_args):
    import phase1_one_shot_runner as front


    def affected_boundary(project, **kwargs):
        p1._emit_l19_to_l23_skeletons(project)
        raise _PdkBoundaryReached

    monkeypatch.setattr(p1, "extract_text_pipeline", affected_boundary)
    monkeypatch.setattr(sys, "argv", ["phase1_one_shot_runner.py", str(project),
                                     "--route", "ic", "--mode", "docs",
                                     "--ic-name", "example", *pdk_args])
    try:
        return front.main()
    except _PdkBoundaryReached:
        return None


@pytest.mark.parametrize("flag", ["split", "equals"])
def test_explicit_run_pdk_reaches_phase2_from_normal_front_door(
        project, monkeypatch, flag):
    import librelane_contract as lc

    monkeypatch.setattr(p1, "_CLI_PDK", None)
    args = ["--pdk", "gf180mcuD"] if flag == "split" else ["--pdk=gf180mcuD"]
    _front_door_pdk(project, monkeypatch, args)
    selected, source = lc.phase2_pdk(project)
    assert selected == "gf180mcuD", (selected, source)
    assert "L19_CONSTRAINTS_PDK.json:fields.pdk_target" in source
    doc = json.loads((project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())
    assert doc["fields"]["pdk_target_alternates"] == ["sky130", "gf180mcu"]
    assert "input/docs/L1_product_metadata.md" in doc["extraction_evidence"]
    assert any(e["literal"] == "--pdk gf180mcuD"
               for e in doc["extraction_evidence"].get("command_line", []))
    assert not (project / "input/project.json").exists()


@pytest.mark.parametrize("args", [[], ["--pdk", "auto"]], ids=["omitted", "auto"])
def test_no_override_resets_previous_run_pdk_and_keeps_document_default(
        project, monkeypatch, args):
    import librelane_contract as lc

    monkeypatch.setattr(p1, "_CLI_PDK", "gf180mcuD")
    _front_door_pdk(project, monkeypatch, args)
    assert p1._CLI_PDK is None
    assert lc.phase2_pdk(project)[0] == "sky130"


@pytest.mark.parametrize("declared", ["sky130A", "gf180mcuA"])
def test_explicit_run_pdk_cannot_erase_conflicting_document_declaration(
        tmp_path, monkeypatch, declared, capsys):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text(f"| target PDK | {declared} |\n")
    monkeypatch.setattr(p1, "_CLI_PDK", None)
    rc = _front_door_pdk(tmp_path, monkeypatch, ["--pdk", "gf180mcuD"])
    assert rc == 2, rc
    assert "conflicts" in capsys.readouterr().err
    assert not (tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").exists()


def test_explicit_custom_distribution_without_prose_reaches_phase2(tmp_path, monkeypatch):
    import librelane_contract as lc

    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "spec.md").write_text("# Example integer core\nNo process named.\n")
    monkeypatch.setattr(p1, "_CLI_PDK", None)
    _front_door_pdk(tmp_path, monkeypatch, ["--pdk", "custom_kit_q7"])
    assert lc.phase2_pdk(tmp_path)[0] == "custom_kit_q7"


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
