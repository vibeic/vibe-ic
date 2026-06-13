"""v0.2.96 — ORGANIC-20260606 #466 R2 (REOPENED, field-agent counter-evidence).

The earlier #466 fix landed the ×N notation parser + own-entry anchoring
(covered by test_v0_2_95_issue457_466_phase1.py). The field agent's
counter-evidence proved two halves were STILL broken end-to-end through
`gen_l5_adi_spec` on real-shaped inputs:

  1. Hallucinated product-name block STILL emitted. When L5 explicitly
     enumerates the analog block TYPES (a count statement like "two
     analog block types" OR Block A / Block B headers), a candidate
     whose spec==null AND whose only evidence is an L1 product-name
     keyword match (a converter acronym embedded in the SKU) is a
     hallucination. The spurious-block guard had only landed in skill
     prose, never in the deterministic runner. REQUIRED: an emitter-side
     PROGRAM guard, applied ONLY when L5 has an explicit enumeration.
     When L5 has NO enumeration the ambiguous case is owned by the skill
     prose (block kept) — preserved behaviour.

  2. The ldo-class count regression root cause is keyword ANCHORING, not
     the multiplicity parser. `re.search(pat, text)` returned the FIRST
     match anywhere; for `ldo` (pattern includes `\\bregulator\\b`) that
     first hit was often a PROSE line inside a sibling block's spec table
     ("(one copy from the LDO)") instead of the block's own header line
     ("… Block B … (×1)"), and seen_classes then blocked re-matching the
     correct header. REQUIRED: anchoring PREFERS Block HEADER lines
     (markdown heading mentioning "Block" / table HEADER row) over a
     prose hit; prose match is fallback only.

Chip-AGNOSTIC: every IC / block / product name here is synthetic. The
anchoring + enumeration cues are pure structural vocabulary; no
chip-class / vendor / SKU literal participates in plugin SOURCE
detection (verified separately by source_chip_agnostic_check.py).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase1_doc_one_shot_runner as P1  # noqa: E402


def _inputs(tmp_path, text, fname="spec.md"):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True)
    (d / fname).write_text(text)
    return tmp_path


# Field-shaped fixture: L5 explicitly enumerates ("two analog block
# types") with Block A (×6 converter-class delta-sigma) + Block B (×1
# regulator-class), and the L1 product name (H1) contains a converter
# acronym ("ADC") as a standalone word so the `adc` analog keyword
# fires on the SKU and nowhere else.
_FIELD_DOC = """\
# ADC-9000 Mixed-Signal Front-End

The device integrates two analog block types.

## Block A — Incremental delta-sigma modulator (×6)

| Spec | Target | Range | Unit |
| --- | --- | --- | --- |
| ENOB | 16 | 14-18 | bits |

analog 1.2 V Vref converters.

## Block B — On-chip regulator (×1)

| Spec | Target | Range | Unit |
| --- | --- | --- | --- |
| Dropout | 200 | 100-300 | mV |

analog 1.8 V Vdd supply. (one copy from the LDO)
"""


# ─────────────────── helper-level unit coverage ───────────────────

def test_best_class_match_prefers_block_header_line():
    """ANCHORING fix: when a class keyword appears FIRST in a sibling
    block's prose line and LATER in its own Block HEADER line, the
    chosen match is the header line (not the first prose hit)."""
    text = (
        "## Block A — delta-sigma modulator (×6)\n"
        "analog converters. (one copy from the LDO regulator)\n\n"
        "## Block B — On-chip regulator (×1)\n"
        "analog 1.8 V Vdd supply.\n"
    )
    m = P1._v466_best_class_match(text, P1._ANALOG_KEYWORDS["ldo"])
    assert m is not None
    ls, le = P1._v466_line_bounds(text, m.start())
    chosen_line = text[ls:le]
    assert "Block B" in chosen_line
    assert "one copy from the LDO" not in chosen_line


def test_best_class_match_falls_back_to_first_when_no_header():
    """When NO match sits on a Block header line, fall back to the first
    match (legacy single-search behaviour preserved)."""
    text = (
        "Some prose mentions an LDO regulator here.\n"
        "Later prose says regulator again.\n"
    )
    m = P1._v466_best_class_match(text, P1._ANALOG_KEYWORDS["ldo"])
    assert m is not None
    # first match is the earliest position
    first = next(__import__("re").finditer(
        P1._ANALOG_KEYWORDS["ldo"], text, __import__("re").IGNORECASE))
    assert m.start() == first.start()


def test_block_header_line_recognises_heading_and_table_header():
    assert P1._v466_line_is_block_header("## Block B — regulator (×1)")
    assert P1._v466_line_is_block_header(
        "| Block | Multiplicity | Notes |")
    # prose pipe-row (a spec table body row) is NOT a header
    assert not P1._v466_line_is_block_header(
        "| Dropout | 200 | 100-300 | mV |")
    # plain prose is not a header
    assert not P1._v466_line_is_block_header(
        "analog 1.8 V Vdd supply. (one copy from the LDO)")


def test_l5_enumerates_block_types_count_statement():
    assert P1._v466_l5_enumerates_block_types(
        {"a.md": "The device integrates two analog block types."})
    assert P1._v466_l5_enumerates_block_types(
        {"a.md": "There are 3 analog blocks on this die."})


def test_l5_enumerates_block_types_block_ab_headers():
    doc = ("## Block A — modulator\n\n## Block B — regulator\n")
    assert P1._v466_l5_enumerates_block_types({"a.md": doc})


def test_l5_no_enumeration_returns_false():
    doc = ("# Front-End\n\nThe chip has an LDO regulator and a "
           "delta-sigma modulator.\n")
    assert not P1._v466_l5_enumerates_block_types({"a.md": doc})


def test_evidence_is_product_name_only_true_when_sku_embedded():
    text = ("# ADC-9000 Mixed-Signal Front-End\n\n"
            "analog 1.2 V Vref front end.\n")
    assert P1._v466_evidence_is_product_name_only(
        text, "ADC", "ADC-9000 Mixed-Signal Front-End")


def test_evidence_is_product_name_only_false_when_standalone_mention():
    """If the literal also appears as a free-standing block mention
    (outside the product-name token), it is grounded by more than the
    SKU → NOT product-name-only."""
    text = ("# ADC-9000 Front-End\n\n"
            "The on-chip ADC runs at analog 1.2 V Vref.\n")
    assert not P1._v466_evidence_is_product_name_only(
        text, "ADC", "ADC-9000 Front-End")


def test_evidence_is_product_name_only_false_when_not_in_name():
    text = "The chip has an LDO regulator.\n"
    assert not P1._v466_evidence_is_product_name_only(
        text, "regulator", "ADC-9000 Front-End")


# ─────────────────── end-to-end acceptance ───────────────────

def test_field_case_exactly_two_blocks_no_hallucination(tmp_path):
    """ACCEPTANCE: L5 enumerates 'two analog block types' + Block A (×6
    converter) + Block B (×1 regulator) + L1 product name contains a
    converter acronym → EXACTLY 2 blocks, regulator-class multiplicity
    ×1 (own header), no product-name-only hallucinated block in the
    consumed list."""
    p = _inputs(tmp_path, _FIELD_DOC)
    res = P1.gen_l5_adi_spec(p, {"spec.md": _FIELD_DOC})
    j = json.loads(res.path.read_text())
    blocks = j["analog_blocks"]
    types = sorted(b["type"] for b in blocks)
    assert types == ["delta_sigma", "ldo"], types
    assert len(blocks) == 2
    # the product-name-only hallucination ('adc') is not in the list
    assert "adc" not in types
    # regulator-class multiplicity reads its OWN header ×1, not the
    # sibling's ×6
    ldo = [b for b in blocks if b["type"] == "ldo"][0]
    assert ldo["count"] == 1
    assert ldo["multiplicity"] == 1
    # converter-class keeps its own ×6
    ds = [b for b in blocks if b["type"] == "delta_sigma"][0]
    assert ds["count"] == 6


def test_field_case_spurious_block_surfaced_and_excluded(tmp_path):
    """The dropped product-name block is surfaced as spurious:true for
    audit but EXCLUDED from the sizing-consuming block list
    (analog_block_list.json) and from analog_blocks."""
    p = _inputs(tmp_path, _FIELD_DOC)
    res = P1.gen_l5_adi_spec(p, {"spec.md": _FIELD_DOC})
    j = json.loads(res.path.read_text())
    spurious = j.get("spurious_analog_blocks", [])
    assert any(b.get("type") == "adc" and b.get("spurious") is True
               for b in spurious)
    # excluded from analog_blocks
    assert all(b["type"] != "adc" for b in j["analog_blocks"])
    # excluded from the canonical sizing block list
    blp = P1._pl.analog_dir(p) / "analog_block_list.json"
    bl = json.loads(blp.read_text())["blocks"]
    assert all(b["type"] != "adc" for b in bl)
    assert sorted(b["type"] for b in bl) == ["delta_sigma", "ldo"]


def test_no_internal_bookkeeping_fields_leak(tmp_path):
    """The private #466 bookkeeping keys must never reach the serialised
    L5 doc (analog_blocks OR spurious_analog_blocks)."""
    p = _inputs(tmp_path, _FIELD_DOC)
    res = P1.gen_l5_adi_spec(p, {"spec.md": _FIELD_DOC})
    j = json.loads(res.path.read_text())
    for b in j["analog_blocks"] + j.get("spurious_analog_blocks", []):
        assert "_v466_kw_literal" not in b
        assert "_v466_src_fname" not in b


# ─────────────────── regression: skill-prose (no-enum) case ──────────

_NO_ENUM_DOC = """\
# ADC-9000 Mixed-Signal Front-End

The device front-end runs at analog 1.2 V Vref.

## Block A — Incremental delta-sigma modulator (×6)

analog 1.2 V Vref converters.
"""


def test_no_enumeration_keeps_name_matched_block(tmp_path):
    """REGRESSION: with NO L5 enumeration the product-name-matched block
    is KEPT (skill prose owns the ambiguous case, not dropped by the
    deterministic guard)."""
    p = _inputs(tmp_path, _NO_ENUM_DOC)
    res = P1.gen_l5_adi_spec(p, {"spec.md": _NO_ENUM_DOC})
    j = json.loads(res.path.read_text())
    types = sorted(b["type"] for b in j["analog_blocks"])
    # the name-matched 'adc' block survives
    assert "adc" in types
    # nothing was dropped as spurious
    assert "spurious_analog_blocks" not in j
    for b in j["analog_blocks"]:
        assert b.get("spurious") is not True


# ─────────────────── regression: prior-correct behaviour ────────────

_TABLE_DOC = """\
# Analog Blocks

| Block | Multiplicity | Notes |
| --- | --- | --- |
| Incremental delta-sigma modulator (×6) | ×6 | analog 1.2 V Vref converters |
| LDO regulator (×1) | ×1 | analog 1.8 V Vdd supply |
"""


def test_prior_table_header_counts_still_per_block(tmp_path):
    """REGRESSION (#466 R1): each block in a markdown table still gets
    its OWN ×N count — the anchoring rewrite must not regress this."""
    p = _inputs(tmp_path, _TABLE_DOC)
    res = P1.gen_l5_adi_spec(p, {"spec.md": _TABLE_DOC})
    j = json.loads(res.path.read_text())
    by = {b["type"]: b for b in j["analog_blocks"]}
    assert by["delta_sigma"]["count"] == 6
    assert by["ldo"]["count"] == 1


_PROSE_SUBQUAL_DOC = """\
# Analog

The chip contains six copies of an incremental delta-sigma modulator
(one of them is powered by an LDO regulator). Each runs at analog 1.2 V Vref.
"""


def test_prior_prose_subqualifier_preserved(tmp_path):
    """REGRESSION (#382): prose `(one of them is …)` sub-qualifier still
    yields head=6 / parenthetical=1. The header-preferring anchoring +
    spurious guard must not perturb this (no enumeration here)."""
    p = _inputs(tmp_path, _PROSE_SUBQUAL_DOC)
    res = P1.gen_l5_adi_spec(p, {"spec.md": _PROSE_SUBQUAL_DOC})
    j = json.loads(res.path.read_text())
    by = {b["type"]: b for b in j["analog_blocks"]}
    assert by["delta_sigma"]["count"] == 6
    assert by["ldo"]["count"] == 1


def test_pure_digital_no_analog_unaffected(tmp_path):
    """REGRESSION: a pure-digital doc with no analog vocabulary still
    yields no analog blocks; the new guard never fabricates / surfaces
    anything."""
    doc = ("# SHA-CORE\n\nA pure digital hashing core. No analog "
           "content whatsoever.\n")
    p = _inputs(tmp_path, doc)
    res = P1.gen_l5_adi_spec(p, {"spec.md": doc})
    j = json.loads(res.path.read_text())
    assert j["analog_blocks"] == []
    assert j["analog_blocks_detected"] is False
    assert j["no_analog"] is True
    assert "spurious_analog_blocks" not in j
