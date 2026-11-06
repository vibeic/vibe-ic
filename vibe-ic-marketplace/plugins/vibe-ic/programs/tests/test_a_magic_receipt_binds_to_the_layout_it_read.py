"""A receipt that cannot name the layout it read certifies nothing.

MEASURED on the real IC (SUB2AB2, spm x gf180mcuD on 0.3.67). The magic deck
RAN and found 0 violations — and its receipt read:

    passed               : False
    DRC_SIGNOFF_NO_LAYOUT_EVIDENCE
    layout_evidence_tier : none
    layout_evidence_witness: "recorded DRC report hash differs from current report"
    design_binding       : NOT_DETERMINED
    producers[0].deck    : null
    producers[0].top_cell: null
    categories_found     : ['spacing', 'width']   (+4 DRC_CATEGORY_PRESENT warnings)

on a run whose GDS was sitting at phase3/stage3/pnr all along. Four separate
defects, all mine, all in the receipt rather than in the check:

(1) THE REPORT WAS STILL BEING EDITED AFTER ITS PROVENANCE WAS TAKEN.
    `_docker_exec` records the sha256 of every declared OUTPUT at the moment
    the tool exits; the runner then APPENDED the deck's rule list. So
    `_recorded_layout_evidence` found the invocation, matched the tool, and
    refused on the digest — and with the invocation route gone the on-disk
    fallback had nothing to match either. The rule list is now written BY THE
    DECK, before magic exits, so the bytes whose digest was recorded are the
    bytes that ship.

(2) THE TRANSCRIPT NAMED NO DESIGN in any dialect `eda_report_audit` knows, so
    `design_binding` could not be decided. It now carries the runner's own
    `measured_design:` stamp — the dialect that exists for exactly this, "the
    runner asserting what it fed the tool" — and the sha256 of the layout it
    was handed.

(3) THE PRODUCER DECLARED NEITHER DECK NOR TOP CELL. A KLayout report database
    declares `<generator>` and `<top-cell>` and the classifier reads both; a
    Magic transcript declared neither. It now states `tech file:` and
    `top cell:`, taken from the TOOL (`tech filename`, and the cell it
    loaded), and the classifier reads them.

(4) FOUR CATEGORIES WERE LEFT UNDECIDABLE. The audit could not tell whether the
    deck HAS a density / antenna / via / enclosure rule. It does not — measured
    from the technology's own rule list, which the transcript now carries: of
    155 rule descriptions, 61 name a spacing rule, 26 a width rule, and ZERO
    name any of the other four.
"""
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402
import _signoff_drc_format as SDF  # noqa: E402
import eda_report_audit as A  # noqa: E402

#: The transcript the deck wrote on the real IC, as evidence and as a fixture.
#: Absent on a host that has not been handed it; the tests that need it skip
#: rather than assert on a file they cannot see.
_REAL = Path("/tmp/icsub2_sub2ab2_magic/drc_signoff_magic.rpt")
needs_real = pytest.mark.skipif(not _REAL.is_file(),
                                reason="the real-IC transcript is not on this host")

_STUBS = r"""
proc drc {args} {
  switch -- [lindex $args 0] {
    listall { return {{Rule A spacing} {{0 0 1 1}}} }
    list    { return 0 }
    default { return {} }
  }
}
proc gds {args} { return }
proc load {args} { return }
proc select {args} { return }
proc box {args} { return "0 0 10 10" }
proc tech {args} {
  switch -- [lindex $args 0] {
    name     { return TECHNAME }
    filename { return TECHFILE }
    version  { return 1.2.3 }
  }
  return {}
}
proc quit {args} { exit 0 }
"""

_TECH = ('tech\n format 32\nend\n\n'
         'drc\n'
         ' width  m1 23 "Metal1 width < 0.23um (M1.1)"\n'
         ' spacing m1 m1 23 touching_ok "Metal1 spacing < 0.23um (M1.2)"\n'
         ' edge4way m2 x 1 "s"\n'
         'end\n\n'
         'extract\n style "ngspice extraction style for this technology"\nend\n')




# ── (1) the report is FINAL when the tool exits ───────────────────────────







# ── (2) the transcript names its design and its layout ────────────────────



def test_without_the_stamp_the_design_is_undecidable():
    """THE NEGATIVE CONTROL, and it is the real artefact: the transcript the
    deck wrote on the real IC states no design at all, which is why that
    receipt read design_binding NOT_DETERMINED."""
    if not _REAL.is_file():
        pytest.skip("the real-IC transcript is not on this host")
    assert A._report_declared_designs(_REAL.read_text()) == set()






# ── (3) the producer declares its deck and its top cell ───────────────────

@needs_real
def test_the_real_transcript_now_classifies_with_a_deck_and_a_top_cell():
    p = SDF.classify_file(_REAL)
    assert p.kind == SDF.MAGIC
    assert p.is_signoff_deck is True
    assert p.top_cell == "chip_top", p.top_cell
    assert p.deck and p.deck.endswith(".tech"), p.deck


def test_a_magic_transcript_without_them_still_classifies_as_magic(tmp_path):
    """OVER-BREADTH CONTROL: a transcript from anywhere else is read exactly
    as it was before — the two fields are additions, not requirements."""
    q = tmp_path / "other.rpt"
    q.write_text("Magic 8.3\ndrc check\n[INFO] COUNT: 0\n")
    p = SDF.classify_file(q)
    assert p.kind == SDF.MAGIC
    assert p.is_signoff_deck is True
    assert p.deck is None and p.top_cell is None


def test_the_router_is_still_not_a_magic_producer(tmp_path):
    q = tmp_path / "r.rpt"
    q.write_text("top cell: chip_top\ntech file: /pdk/x.tech\n"
                 "[INFO DRT-0702] Post-route verification: 0 violation(s).\n")
    assert SDF.classify_file(q).kind != SDF.MAGIC


# ── (4) which classes the deck HAS, and which it genuinely has not ────────









# ── the two paths, end to end, through the real audit ─────────────────────







_GOOD = """# Tool: magic
# sign-off DRC, rule deck applied to a streamed layout
magic DRC: the rule deck of the loaded technology, applied to the streamed layout
tech name: T
tech file: /pdk/t.tech
tech version: 1.2.3
layout: /c/chip_top.gds
measured_design: chip_top
top cell: chip_top
layout sha256: %s
drc style requested: drc(full)
commands: drc check ; drc catchup ; drc listall why ; drc list count total

deck rules declared by /pdk/t.tech (drc section): 3
DECK_RULE: Metal1 spacing < 0.23um (M1.2)
DECK_RULE: Metal1 width < 0.23um (M1.1)
DECK_RULE: %s

rules with violations: 0
error tiles (drc list count total): 0
total violations: 0
COUNT: 0
""" % ("ab" * 32, "padding rule text so the report clears the stub floor " * 30)
