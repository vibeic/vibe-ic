"""ORGANIC-20260803 — a MENTION must not outrank a DECLARATION.

`_extract_pdk_target_with_provenance` reads three sources. Two of them
recognise a NAME off a closed list (open PDKs, six commercial foundries); the
third reads a labelled DECLARATION (`^<label>: <value>`). Before this change the
name-list tiers ran first, so a design's own labelled declaration could never
outrank a bare mention, and the open-PDK tier carried no polarity guard at all
while the commercial tier carried two.

Both tests below are CONTROL PAIRS: the two documents in each pair differ only
in which vendor family the mentioned name belongs to. Chip-, PDK- and
vendor-AGNOSTIC: the commercial value used here is a placeholder that appears on
no name list in the module.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from phase1_doc_one_shot_runner import (          # noqa: E402
    _extract_pdk_target_with_provenance,
)

DECLARED = "acmefoundry-xy7 180nm"


def _project(tmp_path, body):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "L1.md").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_negated_open_pdk_mention_does_not_beat_the_declaration(tmp_path):
    """The half of the control pair that used to fail."""
    p = _project(tmp_path, (
        "# L1\n\n"
        "This block is NOT targeted at sky130.\n\n"
        "**PDK target**: %s\n" % DECLARED))
    tok, _snip, rel, line = _extract_pdk_target_with_provenance(p)
    assert tok == DECLARED, (
        "a sentence saying the design does NOT use a process was adopted as "
        "the process it targets: %r" % tok)
    assert rel.endswith("L1.md") and line == 5


def test_a_negated_commercial_mention_already_did_not(tmp_path):
    """The half of the control pair that already held — it must keep holding."""
    p = _project(tmp_path, (
        "# L1\n\n"
        "This block is NOT fabricated at a tsmc 180nm process.\n\n"
        "**PDK target**: %s\n" % DECLARED))
    tok, _snip, _rel, _line = _extract_pdk_target_with_provenance(p)
    assert tok == DECLARED


def test_a_third_partys_chip_is_not_this_designs_target(tmp_path):
    """The shape actually measured on a design being moved off an open process:
    a benchmark-comparison sentence naming somebody else's chip sits ABOVE the
    design's own declaration, and the extractor adopted the sentence."""
    p = _project(tmp_path, (
        "# L1\n\n"
        "| Benchmark comparison | a competitor's 48-hour demo chip "
        "(nangate45, 1.46M cells, 100 MHz) |\n\n"
        "**PDK target**: %s\n" % DECLARED))
    tok, _snip, _rel, line = _extract_pdk_target_with_provenance(p)
    assert tok == DECLARED, (
        "the target was read off a sentence about a different chip: %r" % tok)
    assert line == 5


def test_a_declaration_that_names_only_a_node_still_refuses(tmp_path):
    """The promotion must not let a node-only line become a target: with the
    node removed the value names nothing, so the tier refuses and the
    name-list tiers answer exactly as they did before."""
    p = _project(tmp_path, (
        "# L1\n\n"
        "**Process**: 180nm\n\n"
        "The target process is sky130.\n"))
    tok, _snip, _rel, _line = _extract_pdk_target_with_provenance(p)
    assert tok == "sky130"


def test_a_labelled_open_pdk_declaration_is_unchanged(tmp_path):
    """A design that declares its open PDK with a label carries no numeric node
    in the value, so the label tier still returns nothing and the open-PDK tier
    answers — byte-identical to pre-change behaviour."""
    p = _project(tmp_path, "# L1\n\n**PDK**: sky130A\n")
    tok, _snip, _rel, _line = _extract_pdk_target_with_provenance(p)
    assert tok == "sky130a"


def test_an_unnegated_open_pdk_mention_still_wins_with_no_declaration(tmp_path):
    """No declaration present -> the open-PDK tier is still the answer."""
    p = _project(tmp_path, "# L1\n\nThe target process is gf180mcuD.\n")
    tok, _snip, _rel, _line = _extract_pdk_target_with_provenance(p)
    assert tok == "gf180mcud"
