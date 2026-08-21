"""v0.2.95 — #457 (two residuals of #451) + #466 (Bucket-A sub-item).

All three fixes live in programs/phase1_doc_one_shot_runner.py.

#457 residual 1 — the foundry deny-guard was polarity-BLIND. The old
    _FOUNDRY_CTX_RE only checked that a commercial-foundry name had a
    process / node / nm / pdk word within +/-60 chars, with no negation
    awareness, so a sentence like
        "fabbed at <foundry> but NOT as a process target; target is
         <open-pdk>"
    mis-extracted pdk_target=<commercial-foundry>. Fix adds a
    negation-distance deny PLUS a dual-evidence requirement (process
    word + numeric node) before trusting a commercial-foundry name, and
    iterates EVERY match so a negated/weak first mention does not poison
    a valid later one.

#457 residual 2 — on the L19 skeleton path the pdk_target evidence
    snippet (file + line) was OVERWRITTEN to {} because _write_l_doc
    unconditionally does `content["extraction_evidence"] = evidence`,
    and the snippet had been stuffed onto the skeleton's own
    extraction_evidence key instead of the `evidence` argument. Fix
    routes the pdk_target evidence through the evidence argument in the
    canonical {source: [{literal,label}]} schema shape with file + line.

#466 Bucket-A — the multiplicity parser only recognised English prose
    quantifiers + the `N×` order; a markdown table-header `×N` notation
    (`×6`, `(×1)`) was never parsed, AND a per-block `(×1)` was
    overwritten by a sibling row's `(×6)` because the count came from
    the shared blank-line paragraph instead of the block's OWN table row.
    Fix (a) recognises the sign-then-digit `×N` form, and (b) scopes the
    per-block count to the block's OWN row / line first.

Chip-AGNOSTIC: foundry vendor names appear ONLY in test fixtures (the
deny-list file tests/chip_deny_list.txt governs source detection), never
as plugin SOURCE detection literals. Block / IC names here are synthetic.
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


# ───────────────────────── #457 residual 1: foundry polarity ───────────────

def test_negated_foundry_acceptance_string(tmp_path):
    """The exact acceptance string: a negated foundry mention must NEVER
    yield the commercial name. The open-PDK token wins (or None)."""
    p = _inputs(
        tmp_path,
        "Prototype was fabbed at TSMC but not as a process target; "
        "the real target is sky130.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt == "sky130"           # open-pdk wins; commercial denied
    assert tgt != "tsmc"


def test_negated_foundry_no_open_pdk_returns_none(tmp_path):
    """Negated foundry mention with NO open-PDK token nearby → None
    (must never fall through to the commercial name)."""
    p = _inputs(
        tmp_path,
        "Earlier silicon was fabbed at TSMC but not as a 180nm process "
        "target.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt is None


def test_negation_before_foundry_token(tmp_path):
    """Negation sitting just BEFORE the foundry token (within the
    leading window) is also caught."""
    p = _inputs(tmp_path,
                "The chip is not a TSMC 28nm process at all.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt is None


def test_foundry_dual_evidence_required(tmp_path):
    """A bare `<foundry> process` with NO numeric node is too weak —
    dual-evidence guard rejects it."""
    p = _inputs(tmp_path, "Manufactured at the SMIC process site.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt is None


def test_negated_then_valid_foundry_later(tmp_path):
    """A negated first mention must not poison a later VALID one (we
    iterate every match)."""
    p = _inputs(
        tmp_path,
        "It is not a UMC node. It is fabricated in a TSMC 130nm "
        "process.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt == "tsmc"


# ── #457 residual 1 regression: prior CORRECT foundry behaviour intact ──────

def test_valid_foundry_context_still_extracted(tmp_path):
    """Corpus-sweep regression: a clean, non-negated foundry-context
    mention with a numeric node still extracts (was the #451 happy
    path)."""
    p = _inputs(tmp_path, "Fabricated in a TSMC 180nm process.\n")
    tgt, ev = P1._extract_pdk_target_from_inputs(p)
    assert tgt == "tsmc"
    assert "TSMC" in ev


def test_open_pdk_token_still_bare(tmp_path):
    p = _inputs(tmp_path, "Implemented on sky130A with the HD cells.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt == "sky130a"


def test_no_pdk_vocab_returns_none(tmp_path):
    p = _inputs(tmp_path, "# Adder\nA 32-bit ripple-carry adder.\n")
    tgt, _ = P1._extract_pdk_target_from_inputs(p)
    assert tgt is None


# ───────────────────── #457 residual 2: L19 evidence survives ──────────────

def test_l19_pdk_target_evidence_lands_with_file_and_line(tmp_path):
    """The fixed path: pdk_target evidence (file + line) must survive
    into L19.extraction_evidence (was overwritten to {})."""
    p = _inputs(
        tmp_path,
        "# Spec\nLine two\nImplemented on sky130A with the HD cells.\n")
    P1._emit_l19_to_l23_skeletons(p)
    l19 = json.loads(
        (P1._pl.generated_docs_dir(p) / "L19_CONSTRAINTS_PDK.json")
        .read_text())
    assert l19["fields"]["pdk_target"] == "sky130a"
    ev = l19.get("extraction_evidence")
    assert isinstance(ev, dict) and ev != {}
    # schema-valid shape: {source: [{literal, label}]}
    src_key, entries = next(iter(ev.items()))
    assert "spec.md" in src_key
    assert isinstance(entries, list) and entries
    entry0 = entries[0]
    assert isinstance(entry0, dict) and entry0.get("literal")
    # file + line provenance in the label
    assert "pdk_target" in entry0["label"]
    assert ":3" in entry0["label"]          # sky130A is on line 3


def test_l19_provenance_helper_returns_file_and_line(tmp_path):
    p = _inputs(tmp_path,
                "intro\nTarget process: IHP SG13G2 130nm SiGe.\n")
    tgt, snip, src, line = P1._extract_pdk_target_with_provenance(p)
    assert tgt == "sg13g2"
    assert "SG13G2" in snip
    assert src and "spec.md" in src
    assert line == 2


def test_l19_no_pdk_still_emits_without_evidence_key_crash(tmp_path):
    """Regression: when no pdk_target is found, the skeleton path still
    emits L19 cleanly (no pdk_target field, empty/absent evidence)."""
    p = _inputs(tmp_path, "# Adder\nA plain 8-bit counter, no PDK.\n")
    P1._emit_l19_to_l23_skeletons(p)
    l19_path = P1._pl.generated_docs_dir(p) / "L19_CONSTRAINTS_PDK.json"
    assert l19_path.exists()
    l19 = json.loads(l19_path.read_text())
    # no pdk_target → field absent or None; extraction_evidence is a dict
    assert l19.get("fields", {}).get("pdk_target") in (None, "")
    assert isinstance(l19.get("extraction_evidence"), dict)


# ───────────────────── #466 Bucket-A: ×N table-header notation ─────────────

def test_sign_then_digit_multiplicity_parsed():
    """The `×N` table-header form (sign before digit) is now parsed."""
    f = P1._v1_6_402_extract_block_multiplicity
    assert f("Block A (×6)") == 6
    assert f("Reference (×1) bandgap") == 1
    assert f("foo × 12 bar") == 12


def test_n_times_form_still_works_regression():
    """Corpus-sweep regression: the original `N×` order (digit before
    sign) still parses, and a dimension `2×6` is NOT misread as 6."""
    f = P1._v1_6_402_extract_block_multiplicity
    assert f("6× bandgap") == 6
    assert f("2× bandgap") == 2
    # dimension form: the N× tier matches the leading digit (2), the
    # ×N tier's lookbehind prevents reading the trailing 6.
    assert f("die size 2×6 mm") == 2


def test_word_and_copies_forms_unaffected_regression():
    """Prior prose-quantifier behaviour preserved."""
    f = P1._v1_6_402_extract_block_multiplicity
    assert f("six copies of an incremental modulator") == 6
    assert f("dual bandgap reference") == 2
    assert f("8-slot DSP array") == 8


# ── #466 Bucket-A: each block's count comes from its OWN table row ──────────

def test_own_entry_multiplicity_no_sibling_bleed():
    """A per-block `(×1)` table ROW must NOT inherit a sibling row's
    `(×6)` from the shared blank-line paragraph."""
    para = ("| Incremental delta-sigma modulator (×6) | ×6 | "
            "analog converters |\n"
            "| LDO regulator (×1) | ×1 | analog supply |")
    # paragraph-wide scan (the OLD behaviour) returns 6 for everyone:
    assert P1._v1_6_402_extract_block_multiplicity(para) == 6
    # own-entry scan: each row keeps its OWN count.
    ldo_pos = para.find("LDO")
    ds_pos = para.find("delta")
    assert P1._v466_block_multiplicity_own_entry(para, ldo_pos, para) == 1
    assert P1._v466_block_multiplicity_own_entry(para, ds_pos, para) == 6


def test_own_entry_table_row_without_count_no_bleed():
    """A table row with NO ×N must report None (not a sibling's count) —
    sibling-bleed across a table row break is forbidden."""
    para = ("| Modulator (×6) | analog converters |\n"
            "| Reference | analog bandgap, no count |")
    ref_pos = para.find("Reference")
    assert P1._v466_block_multiplicity_own_entry(para, ref_pos, para) is None


def test_own_entry_non_table_prose_falls_back_to_paragraph():
    """Non-table prose with no own-line quantifier may still use the
    paragraph (preserves the prose `six copies of` happy path)."""
    para = ("The block array is large.\n"
            "It bundles together many converters.")
    # paragraph has no quantifier at all → None
    pos = para.find("converters")
    assert P1._v466_block_multiplicity_own_entry(para, pos, para) is None
    # now give the paragraph a quantifier on a DIFFERENT prose line; the
    # block's own line carries NO quantifier of its own, so the fallback
    # to the wider paragraph applies (non-table prose only).
    para2 = ("six copies of an incremental modulator are present.\n"
             "They feed the digital core stage.")
    pos2 = para2.find("digital core")
    assert P1._v466_block_multiplicity_own_entry(para2, pos2, para2) == 6


# ── #466 Bucket-A: end-to-end through the L5 emitter ────────────────────────

_TABLE_DOC = """\
# Analog Blocks

| Block | Multiplicity | Notes |
| --- | --- | --- |
| Incremental delta-sigma modulator (×6) | ×6 | analog 1.2 V Vref converters |
| LDO regulator (×1) | ×1 | analog 1.8 V Vdd supply |
"""


def test_l5_emitter_per_block_table_header_counts(tmp_path):
    """End-to-end: each analog block in a markdown table gets its OWN
    `×N` count, not the first row's count."""
    res = P1.gen_l5_adi_spec(tmp_path, {"AnalogBlocks.md": _TABLE_DOC})
    j = json.loads(res.path.read_text())
    by = {b["type"]: b for b in j.get("analog_blocks", [])}
    assert by["delta_sigma"]["count"] == 6
    assert by["delta_sigma"]["multiplicity"] == 6
    assert by["ldo"]["count"] == 1
    assert by["ldo"]["multiplicity"] == 1


_PROSE_SUBQUAL_DOC = """\
# Analog

The chip contains six copies of an incremental delta-sigma modulator
(one of them is powered by an LDO regulator). Each runs at analog 1.2 V Vref.
"""


def test_l5_emitter_prose_subqualifier_preserved(tmp_path):
    """Corpus-sweep regression (#382): the prose `(one of them is …)`
    sub-qualifier form still yields head=6 / parenthetical=1."""
    res = P1.gen_l5_adi_spec(tmp_path, {"AnalogBlocks.md": _PROSE_SUBQUAL_DOC})
    j = json.loads(res.path.read_text())
    by = {b["type"]: b for b in j.get("analog_blocks", [])}
    assert by["delta_sigma"]["count"] == 6
    assert by["ldo"]["count"] == 1
