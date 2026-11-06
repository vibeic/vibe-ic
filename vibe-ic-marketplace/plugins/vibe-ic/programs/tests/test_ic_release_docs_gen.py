"""tests/test_ic_release_docs_gen.py — step 37.5ic's PRODUCT-document producer.

WHAT IS BEING DEFENDED HERE, AND WHY IT IS NOT "THE DOCUMENTS ARE GENERATED"
===========================================================================
Step 37.5ic already had a document generator before this one. ``tapeout_docs_gen``
writes the sign-off HTML and refuses to write anything for a run that is not
clean — and every one of the 17 properties it decides is read from ONE artefact,
``phase3/final/metrics.json``, which is a set of NUMBERS ABOUT a layout and not
the layout.

That is the gap this producer closes, and the fixture below makes the gap
provable rather than asserted: ``METRICS_CLEAN`` carries all 17 properties CLEAN
in EVERY case in this file. So when a case plants a hollow GDS and the producer
refuses, the refusal cannot be the metrics half firing — the metrics half is
green by construction, and the only thing that changed is the bytes of an
artefact nothing had ever opened.

    A generator that writes a beautiful datasheet for a design with no geometry
    in its GDS is worse than no generator, because it launders an empty result
    into a document somebody signs.

Every case therefore:

  * asserts an EXACT exit code. rc 2 is "the question could not be put", rc 143
    is KILLED and rc 199 is a stall kill; none of them is a result, and a test
    that accepted ``!= 0`` would accept all three;
  * breaks exactly ONE artefact, so a future weakening of any single predicate
    turns exactly one test;
  * asserts NO DOCUMENT WAS WRITTEN, because the refusal that matters is the
    absence of the file — a document that says NOT RELEASABLE is a status line
    wearing a document's clothes, and it still gets copied and quoted;
  * REPAIRS the same defect and asserts rc 0. A producer that only ever refuses
    is a producer that will be switched off.
"""

from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


FLOW_YAML = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"

#: rc values `flow_compliance_check` scores in a PASS tier: 0 PASS,
#: 2 VACUOUS_PASS, 3 PASS_WITH_WAIVERS.











# ═════════════════════ the clean run, and what it produces ═════════════════




















# ═══════ the refusals — one artefact class each, metrics CLEAN throughout ═══
#: (case id, the rule the refusal must name, how to plant it)












# ═══════════════════════════ the vacuous tier ══════════════════════════════








# ═════════════════ the flow declares what this producer writes ═════════════






def test_the_existing_signoff_generator_is_not_replaced():
    """EXTEND, DO NOT REPLACE. `tapeout_docs_gen` stays exactly where it is."""
    text = FLOW_YAML.read_text(encoding="utf-8")
    start = text.index("  - id: 37.5ic")
    block = text[start:text.index("  - id: 38", start)]
    assert "- tapeout_docs_gen" in block
    assert 'program_exit_zero: "tapeout_docs_gen --project . ' in block
    assert '"reports/phase3/docs/SIGNOFF_*.html"' in block
    assert '"reports/phase3/docs/BRIEF_*.html"' in block


# ═══════════════════════════════ NDA ═══════════════════════════════════════
#: Substrings that must appear in NOTHING this producer emits. Narrow on
#: purpose: this is a leak census, not a prose critic. The open PDKs this flow
#: targets are NOT on it and must never be added.
