#!/usr/bin/env python3
"""Rails a design STATES in a document table must reach L21.

The LEF-based producer (`l21_macro_supply_rail_synth`) removes the cause of the
empty-L21 route abort for a design whose rails ride on a hard-macro pin. It
cannot help two shapes that occur together on real mixed-signal cells:

  * the rails are stated in a DOC TABLE, not carried on any pin;
  * the macros are the design's OWN analog blocks, whose LEFs are generated at
    A8 in Phase 3 and do not exist when the Phase-1 producer runs.

Measured on such a cell: the LEF producer reported
`NOT_APPLICABLE, 0 hard macro(s) with PG pins across 0 LEF file(s)` while the
design's own L9 stated the rails in a two-row table under `## Supplies / levels`.
L21 stayed empty, every macro PG pin read `undeclared`, the pre-route gate failed
PnR, and the mixed-signal top had no digital half.

These tests pin the reader against document shapes, not against one project's
file. Written here because the round that authored the program shipped no test
with it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

from l21_doc_supply_rail_synth import derive  # noqa: E402

GATE = PROGRAMS / "l21_macro_supply_rail_declared_check.py"

_L9 = """\
# L9 Constraints

Some prose about the block.

## Supplies / levels

| Rail | Voltage | Note |
|---|---|---|
| VDDA | 1.8 V | analog supply |
| VDDD | 1.2 V | digital core |
| VSS  | 0 V   | common ground |

## Something else

| Parameter | Value |
|---|---|
| Temp | 27 C |
"""


def _project(tmp_path: Path, doc_text: str = _L9,
             doc_name: str = "L9_CONSTRAINTS.md") -> Path:
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True)
    (d / doc_name).write_text(doc_text)
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L21_POWER_INTENT.json").write_text(
        json.dumps({"doc_id": "L21", "power_domains": []}, indent=2))
    return tmp_path


def _names(rows):
    out = set()
    for r in rows or []:
        for k in ("name", "rail", "supply", "power_net"):
            v = r.get(k) if isinstance(r, dict) else None
            if isinstance(v, str) and v:
                out.add(v)
    return out


# ---------------------------------------------------------------------------
# What it must read
# ---------------------------------------------------------------------------
def test_a_stated_supply_table_yields_its_rails(tmp_path):
    got = derive(_project(tmp_path))
    names = _names(got.get("rails") or [])
    assert {"VDDA", "VDDD", "VSS"} <= names, got


def test_a_table_that_is_not_about_supplies_contributes_nothing(tmp_path):
    """The heading is the qualifier. A parameter table full of numbers must not
    become power intent just because it sits in the same document."""
    doc = """\
# L9

## Timing

| Parameter | Value |
|---|---|
| VDDA | 1.8 V |
| tsetup | 0.4 ns |
"""
    got = derive(_project(tmp_path, doc))
    names = _names(got.get("rails") or [])
    assert "tsetup" not in names


def test_no_supply_table_is_not_an_error(tmp_path):
    """A design that states its rails nowhere is the LEF producer's case, not a
    failure of this one. It must return cleanly with nothing derived."""
    got = derive(_project(tmp_path, "# L9\n\nNo tables here at all.\n"))
    assert not (got.get("rails"))


def test_a_table_with_no_stated_level_is_deliberately_not_read(tmp_path):
    """DELIBERATE, and this test exists to stop it being "fixed".

    A row contributes only when it yields BOTH an identifier and a voltage. My
    first instinct was that a rail without a level is still a rail and should be
    read — that would have undone a decision the program's author took from a
    measured false positive, so it is pinned here instead.

    Requiring a level is what keeps a SPEC table from becoming power intent: see
    the majority / same-column guards below.
    """
    doc = """\
# L9

## Supplies / levels

| Rail | Note |
|---|---|
| VDDA | analog |
| VSS  | ground |
"""
    assert not (derive(_project(tmp_path, doc)).get("rails")), (
        "a table stating no levels was read as power intent")


def test_a_spec_table_under_a_supply_sounding_heading_is_rejected(tmp_path):
    """THE guard, in the exact shape that was measured.

    The heading qualifier admits any heading containing "supplies". On a real
    mixed-signal cell that admitted a per-block SPEC table whose heading read
    "... (x1, supplies one modulator core)", and a spec named `Dropout` came out
    as a 0.6 V power rail with the 0.6 V scraped from a parenthetical in a NOTE
    column. A fabricated rail in the layer the PDN is built from is worse than
    declaring nothing.

    It is rejected structurally -- only 1 of 7 data rows contributes, below the
    majority floor -- not by blacklisting the word `Dropout`, so the rejection
    generalises to every spec table.
    """
    doc = """\
# L9

## Block B -- `ldo` : low-dropout regulator (x1, supplies one modulator core)

| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| Dropout | <= 0.5 | - | V | headroom (1.8 IOVDD - 1.2 CORE = 0.6 V available) |
| Iq | 50 | 30-80 | uA | quiescent |
| PSRR | 60 | - | dB | at 1 kHz |
| Load reg | 5 | - | mV/mA | |
| Line reg | 2 | - | mV/V | |
| Settling | 10 | - | us | |
| Area | 0.02 | - | mm2 | |
"""
    names = _names(derive(_project(tmp_path, doc)).get("rails") or [])
    assert "Dropout" not in names, "a spec became a power rail"
    assert not names, f"a spec table produced power intent: {names}"


# ---------------------------------------------------------------------------
# The property that matters: the gate it exists to satisfy
# ---------------------------------------------------------------------------
def test_applying_it_puts_the_rails_where_the_consumers_read_them(tmp_path):
    """L21 is read by `l21_macro_supply_rail_declared_check` and by
    `hardmacro_supply_intent`, both out of the layer's own fields. Deriving into
    a report nobody reads would satisfy this program and not the flow."""
    from l21_doc_supply_rail_synth import main as synth

    p = _project(tmp_path)
    rc = synth([str(p), "--apply"])
    assert rc in (0, 2), rc

    doc = json.loads((p / "phase1" / "generated_docs"
                      / "L21_POWER_INTENT.json").read_text())
    container = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    assert _names(container.get("power_domains") or []) >= {"VDDA", "VDDD", "VSS"}


def test_dry_run_leaves_the_design_document_untouched(tmp_path):
    """Editing a design document is opt-in, the same contract the LEF producer
    holds."""
    from l21_doc_supply_rail_synth import main as synth

    p = _project(tmp_path)
    layer = p / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    before = layer.read_bytes()
    assert synth([str(p)]) in (0, 2)
    assert layer.read_bytes() == before


def test_existing_declarations_are_preserved(tmp_path):
    """It ADDS what the document states and never rewrites what the design
    already declared."""
    from l21_doc_supply_rail_synth import main as synth

    p = _project(tmp_path)
    layer = p / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    layer.write_text(json.dumps({
        "doc_id": "L21",
        "power_domains": [{"name": "core", "power_net": "VDDD",
                           "ground_net": "VSS", "voltage_v": 1.2}]}, indent=2))
    synth([str(p), "--apply"])
    doc = json.loads(layer.read_text())
    container = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    core = [d for d in container["power_domains"] if d.get("name") == "core"]
    assert core and core[0]["voltage_v"] == 1.2
    assert core[0]["power_net"] == "VDDD"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
