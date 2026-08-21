"""Phase-1 identity must not be decided by an INCIDENTAL mention.

Defect reproduced on a real campaign run: an accessory-authentication
part — no memory interface of any kind — had Phase 1 stamp its
``ic_name`` as the canonical DDR3 SDRAM name, in 14 L docs, with no
uncertainty signal. The opcode extraction was unaffected, so nothing
downstream crashed; the record was simply, confidently wrong, and every
later step that keys on ``ic_name`` / IC class was steered by it.

Cause: the protocol detectors test term membership with a bare ``in``
substring test, which has no left word boundary. Three things then
compound:

  * ``"DDR" in blob`` is satisfied by the word **ADDRESS**;
  * ``"JEDEC" in blob`` is satisfied by the ESD / packaging /
    moisture-sensitivity boilerplate present in essentially every
    datasheet and PDK guide, whatever the part does;
  * ``"DDR3" in blob`` is satisfied by ONE comparison sentence.

With a 48-document input set, all three are near-certain to co-occur in
some document, so the weakest identity branch fires on a part that has
nothing to do with memory.

These tests pin the PUBLIC detector contract ``is_ddr(blob)`` — the
same importable predicate ``test_ddr4_protocol_detect.py`` uses for the
sibling generation — on both sides: the defect must not fire, and a
genuine DDR3 spec must still be detected. A detector that cannot still
return True is an alarm that cannot ring, which is the more expensive
failure of the two.

chip-AGNOSTIC: every blob below is synthetic prose. No benchmark, part,
or vendor identity is referenced.
"""
from ddr_protocol_synth import is_ddr
from _incidental_mention import AnchoredBlob, subject_term


# --------------------------------------------------------------- defect
def test_address_bus_plus_jedec_boilerplate_is_not_a_memory_part():
    """The reproduction: an unrelated part misclassified as DDR3.

    Address bus + JEDEC ESD citation + a single comparative DDR3
    mention. Nothing here is a memory interface.
    """
    blob = (
        '{"part_class":"accessory authentication controller",'
        '"bus":"single-wire ID bus","ADDRESS":"8-bit register ADDRESS bus",'
        '"esd":"ESD rating per JEDEC JS-001-2017 and JESD22-A114",'
        '"note":"Unlike DDR3 memory devices, this part exposes no '
        'external memory interface."}'
    )
    assert is_ddr(blob) is False


def test_single_generation_citation_does_not_decide_identity():
    """One reference-list row must not overwrite a design's identity."""
    blob = (
        "Serial authentication coprocessor. Register ADDRESS map below. "
        "Qualification per JEDEC standards. "
        "References: [7] JESD79-3C, DDR3 SDRAM Specification."
    )
    assert is_ddr(blob) is False


def test_sibling_generation_name_is_not_matched_as_infix():
    """``DDR`` must not be read out of LPDDR5 / GDDR6 / LPDDR4.

    Previously these needed hand-maintained sibling-mutex denylists,
    each added reactively after an observed false positive. Left-anchor
    makes it structural.
    """
    for foreign in ("LPDDR4", "LPDDR5", "GDDR6"):
        blob = f"{foreign} controller front-end. ADDRESS decode. JEDEC qualified."
        assert is_ddr(blob) is False, foreign


# ------------------------------------------------------- must still fire
def test_genuine_ddr3_spec_is_still_detected():
    """The alarm must still ring — no false-clean.

    A real DDR3 SDRAM specification names its own generation
    throughout, which is exactly the subject-density signal that
    separates it from a passing citation.
    """
    blob = (
        "DDR3 SDRAM Standard, JEDEC Standard No. JESD79-3C. "
        "DDR3 SDRAM device organised as 8 banks. "
        "DDR3 mode registers MR0, MR1, MR2. "
        "Bank ACTIVATE and PRECHARGE commands; tRCD, tRP, tRAS. "
        "DDR interface signalling; DDR3 x8 configuration; DDR3 burst length 8."
    )
    assert is_ddr(blob) is True


def test_ddr3_detected_via_structural_command_cluster():
    """The structural branch is untouched by the anchoring change."""
    blob = (
        "Synchronous DRAM. ACTIVATE opens a row, PRECHARGE closes it. "
        "Timing parameters tRCD and tRP govern the row cycle."
    )
    assert is_ddr(blob) is True


def test_empty_and_none_are_safe():
    assert is_ddr("") is False
    assert is_ddr(None) is False  # type: ignore[arg-type]


# ------------------------------------------------- anchoring rule itself
def test_left_anchor_rejects_infix_and_keeps_prefix():
    """Left-anchored, deliberately not ``\\b...\\b``.

    Infix matches are the entire observed false-positive class; prefix
    continuation carries real signal (``DDR`` inside ``DDR3``) and must
    survive.
    """
    assert "DDR" not in AnchoredBlob("The ADDRESS bus is 16 bits")
    assert "CLE" not in AnchoredBlob("NAND gate delay per CYCLE is 3 ns")
    assert "ALE" not in AnchoredBlob("full-SCALE input range")
    assert "MR0" not in AnchoredBlob("timer register TIMR0 reload")
    # prefix continuation preserved
    assert "DDR" in AnchoredBlob("DDR3 SDRAM")
    assert "MR0" in AnchoredBlob("write MR0 to set burst length")


def test_case_folding_stays_anchored():
    assert "ddr" not in AnchoredBlob("The ADDRESS bus").lower()
    assert "ddr" in AnchoredBlob("DDR3 SDRAM").lower()


def test_subject_term_separates_subject_from_citation():
    citation = "See DDR3 for comparison."
    subject = "DDR3 device. DDR3 banks. DDR3 mode register. DDR3 timing."
    assert subject_term(citation, "DDR3") is False
    assert subject_term(subject, "DDR3") is True
