"""A supply-rail NAME is not an electrical specification.

``_electrical_mention`` is the one definition of "this text mentions an
electrical quantity", shared by the L1 emitter and by
``l1_electrical_specs_typed_depth_check`` so the two can never drift.  It
counted the five supply-rail names (VDD / VDDA / VSS / VSSA / VDDIO) as
mentions on their own.  A rail name is the ordinary identifier of a net and a
pin: it appears in the connectivity / floorplan section of every digital design
that has never stated an electrical specification.

MEASURED consequence (edge_llm_accel x nangate45, stock v1.9.65).  One line of
one floorplan document --

    | 電源 | `VDD` / `VSS`(NangateOpenCellLibrary 標準) |

-- naming the two rails of a standard-cell library made the L1 emitter publish

    "electrical_specs": [],
    "no_electrical_specs_in_input": false,
    "electrical_specs_unextracted_mentions":
        [{"evidence": "input/docs/L9_constraints_floorplan.md:44",
          "literal": "VDD"}]

i.e. "the input HAS electrical specs and I did not type them" about a document
that states none.  ``phase1_structured_field_substance_check`` then counted the
empty list as template scaffolding, 2 of 6 audited fields = 33.3% > its 30%
threshold, FAIL -> phase2 final_audit FAIL -> the whole run halted at phase2.

THE RULE: a rail name counts only when its own line is CORROBORATED by a
quantity, a Min./Typ./Max. header, or a unit standing alone in its own table
cell -- exactly the corroboration discipline this module already applies to a
lone Min./Typ./Max. marker.  A rail with a value is a specification; a rail
alone is a net name.

chip-AGNOSTIC: the vocabulary is the standard supply-rail and SI-unit set.  No
vendor, SKU, design or document literal participates.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import _electrical_mention as E  # noqa: E402


# ── the defect ────────────────────────────────────────────────────────────

def test_a_bare_rail_pair_in_a_floorplan_table_is_not_a_spec():
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix."""
    line = "| 電源 | `VDD` / `VSS`(NangateOpenCellLibrary 標準) |"
    assert not E.has_electrical_mention(line), (
        "a floorplan row naming the supply rails was read as an "
        "electrical-spec mention")


def test_a_bare_rail_in_a_connectivity_row_is_not_a_spec():
    """NEGATIVE CONTROL — fails pre-fix, passes post-fix.

    A digit on the line is deliberately NOT a corroborator: admitting any
    number would re-open the same false-positive door from the other side.
    """
    assert not E.has_electrical_mention("| Power | `VDD` / `VSS` | metal1 |")
    assert not E.has_electrical_mention("  | VSSA | analog ground | pad ring |")


def test_prose_about_a_rail_is_STILL_a_mention():
    """SCOPE LIMIT — the narrowing is to TABLE ROWS, and only to those.

    Prose that names a rail is making a statement about it; v1.7.80 (#514)
    already fixed "VDD must be stable before the reset is released" as an
    electrical mention and this change must not take that back.  Asserted
    here so a future widening of the rule has to break a test that says so.
    """
    assert E.has_electrical_mention(
        "VDD must be stable before the reset is released")
    assert E.has_electrical_mention("Connect VSS to the ground plane.")


# ── what must keep working (these pass BOTH before and after) ─────────────

def test_the_canonical_supply_row_still_counts():
    """The unit sits in its OWN column here, which the quantity rule
    deliberately does not match — so the rail must be corroborated by the
    standalone unit cell, or the fix would lose the commonest spec shape."""
    assert E.has_electrical_mention(
        "| VDD | 1.62 | 1.80 | 1.98 | V | core supply |")
    assert E.has_electrical_mention("| VDDIO | 1.71 | 1.80 | 1.89 | V |")


def test_a_rail_with_an_inline_value_still_counts():
    assert E.has_electrical_mention("VDD 1.8 V")
    assert E.has_electrical_mention("1.8 V supply on VDD")


def test_a_rail_in_a_min_typ_max_header_still_counts():
    assert E.has_electrical_mention("| VDD | Min. | Typ. | Max. |")


def test_parameter_symbols_are_unchanged():
    """A parameter symbol has no use outside an electrical specification, so
    naming it IS mentioning one.  Only the RAIL class was narrowed."""
    for line in ("IDDQ leakage measured at wafer sort",
                 "VOH minimum",
                 "VTH shift after burn-in",
                 "VREF ladder",
                 "IDD budget"):
        assert E.has_electrical_mention(line), line


def test_the_pre_existing_false_positive_guards_still_hold():
    """The boundary rules this module was written for must be untouched."""
    for line in ("The Volume of the buffer",
                 "sv2v and sha256.v",
                 "the village clock",
                 "max. bandwidth"):
        assert not E.has_electrical_mention(line), line


def test_scan_reports_line_numbers_for_a_real_spec_table():
    doc = ("# Electrical\n"
           "\n"
           "| Symbol | Min | Typ | Max | Unit |\n"
           "| VDD | 1.62 | 1.80 | 1.98 | V |\n")
    hits = E.scan_electrical_mentions(doc)
    assert [ln for ln, _ in hits] == [4], hits
