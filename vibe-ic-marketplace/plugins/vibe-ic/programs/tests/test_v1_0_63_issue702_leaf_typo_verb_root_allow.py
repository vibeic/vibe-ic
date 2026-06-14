"""v1.0.63 — #702 (MED, chip-AGNOSTIC): the leaf-typo aliaser must NOT treat a
bare verb-root module name (decode / encode-style) as a single-edit truncation
typo of its `-er`/`-or` agent-noun canonical term.

ROOT CAUSE: in `_closest_canonical`, a bare verb base (`decode`) that is the
legitimate morphological BASE of an agentive canonical term (`decoder`) is
edit-distance 1 from that term (append `r`) and was wrongly classified as a
truncation typo — emitting a spurious orphan `decoder` alias. The existing
guards covered inflected forms (-ed/-ing/-s), British -iser variants, and a
curated -er agent-noun denylist, but NOT the bare-verb-root case.

REPRODUCED: `detect_leaf_typo('prim_diff_decode')` returned `'prim_diff_decoder'`
— but `prim_diff_decode.sv` is a REAL licensed OpenTitan vendor module (lowRISC
Apache-2.0, differential-pair decoder), instantiated by `prim_alert_sender.sv`,
NOT a typo. The aliaser emitted a spurious `prim_diff_decoder.v` orphan.

FIX: a SUFFIX-GRAMMAR allow-check — when appending a trailing agentive suffix
(`r`/`er`/`or`) to the shorter token yields a canonical term verbatim, the
shorter token is the verb BASE (inflection, not a typo) → return None. Keyed on
the morphological grammar, NOT a word list, so ANY `X` / `X+r|er|or` pair is
excluded.

§4.05 NO-LEAK (load-bearing — this RELAXES the typo detector): a GENUINE
truncation typo that is NOT a verb→agent-noun morphological pair (`decodr` /
`decoer` missing/substituting a letter MID-word) MUST STILL be detected. The
allow-check fires ONLY for a PURE TRAILING APPEND (`token + suffix == term`).

chip-AGNOSTIC: only generic hardware-term roots are baked in; no chip literal.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import leaf_typo_alias_emit as L  # noqa: E402


# ── POSITIVE: bare verb root is exempt (was the spurious-alias bug) ──────

def test_prim_diff_decode_is_not_a_typo():
    # the exact #702 repro shape: the real OpenTitan vendor leaf
    # `prim_diff_decode` is a differential-pair decoder, NOT a truncation typo
    # of `prim_diff_decoder`. The detector must return None — no spurious alias.
    assert L.detect_leaf_typo("prim_diff_decode") is None


def test_bare_verb_roots_of_agent_nouns_do_not_fire():
    # a bare verb BASE that an -er/-or canonical agent noun derives from is
    # verb↔agent-noun INFLECTION, not a truncation typo. None may be aliased.
    for root in ("decode", "encode", "subtract", "increment", "decrement",
                 "multiplex", "demultiplex"):
        assert L.detect_leaf_typo(root) is None, f"verb root {root!r} false-fired"


def test_closest_canonical_verb_base_helper():
    # #702 round-2: the helper is keyed on an ENUMERATED silent-`e` verb
    # allow-list. The silent-`e` `+r` bases (the only ones at edit-distance 1
    # from their canonical, hence the only ones needing an exemption) ARE
    # recognised:
    assert L._is_verb_base_of_canonical("decode") is True   # +r -> decoder
    assert L._is_verb_base_of_canonical("encode") is True   # +r -> encoder
    assert L._is_verb_base_of_canonical("divide") is True   # +r -> divider
    # a `-er`/`-or` consonant root is NOT in the silent-`e` set — it is never
    # typo-flagged anyway (edit-distance >=2), so it needs no exemption and the
    # helper returns False (the exemption is reserved for the leak-prone 1-char
    # append class only):
    assert L._is_verb_base_of_canonical("subtract") is False  # dist 2 -> never flagged
    # _closest_canonical returns None for both the silent-`e` base (exempted)
    # AND the consonant root (distance >=2):
    assert L._closest_canonical("decode") is None
    assert L._closest_canonical("encode") is None
    assert L._closest_canonical("subtract") is None


def test_verb_root_inside_compound_does_not_fire():
    # the token-level path inside a `_`-compound must also exempt the verb root.
    assert L.detect_leaf_typo("prim_diff_decode") is None
    assert L.detect_leaf_typo("axi_stream_encode") is None
    assert L.detect_leaf_typo("rgb_color_decode") is None


def test_spurious_orphan_alias_not_emitted_for_verb_root(tmp_path):
    # end-to-end: a real verb-root leaf module must NOT cause an alias wrapper
    # to be written (the spurious orphan crediting #517 must not appear).
    rtl = tmp_path / "design.v"
    rtl.write_text(
        "module prim_diff_decode (\n"
        "    input clk_i,\n"
        "    input rst_ni,\n"
        "    input [1:0] diff_pi,\n"
        "    output level_o,\n"
        "    output rise_o,\n"
        "    output fall_o,\n"
        "    output event_o,\n"
        "    output sigint_o\n"
        ");\n"
        "    assign level_o = diff_pi[0];\n"
        "    assign rise_o = 1'b0;\n"
        "    assign fall_o = 1'b0;\n"
        "    assign event_o = 1'b0;\n"
        "    assign sigint_o = diff_pi[0] == diff_pi[1];\n"
        "endmodule\n")
    rc = L.main(["--rtl", str(rtl), "--leaf", "prim_diff_decode"])
    assert rc == 0
    # no spurious `prim_diff_decoder.v` orphan was written
    assert not (tmp_path / "prim_diff_decoder.v").exists()
    # only the original design.v exists
    assert sorted(p.name for p in tmp_path.glob("*.v")) == ["design.v"]


# ── §4.05 NO-LEAK: genuine truncation typos must STILL be flagged ────────

def test_genuine_truncation_typos_still_flagged():
    # these are REAL one-edit misspellings of the agent noun (a letter
    # missing / substituted MID-word) — NOT a verb→agent-noun morphological
    # pair. The allow-check must NOT exempt them; they stay typos.
    assert L.detect_leaf_typo("decodr") == "decoder"   # missing the `e`
    assert L.detect_leaf_typo("decoer") == "decoder"   # `d`->`e` substitution


def test_last_char_deletion_truncation_typos_still_flagged_NOLEAK():
    # §4.05 NO-LEAK (the v1.0.63 adversarial-review leak): a LAST-CHARACTER-
    # DELETION truncation of an `-er`/`-or` canonical agent noun (`counter`
    # minus `r` -> `counte`) ALSO satisfies the naive `t+"r"==canonical`
    # grammar, but it is a GENUINE misspelling — NOT a real silent-`e` verb —
    # and MUST stay flagged. The original #702 bare-`r` suffix grammar wrongly
    # exempted every one of these; the enumerated allow-list fix re-catches them.
    for typo, fix in (
        ("counte", "counter"), ("registe", "register"), ("arbite", "arbiter"),
        ("shifte", "shifter"), ("transmitte", "transmitter"),
        ("controlle", "controller"), ("incremente", "incrementer"),
        ("decremente", "decrementer"), ("multiplexe", "multiplexer"),
        ("subtracto", "subtractor"), ("accumulato", "accumulator"),
        ("comparato", "comparator"), ("modulato", "modulator"),
        ("rotato", "rotator"), ("saturato", "saturator"),
    ):
        assert L.detect_leaf_typo(typo) == fix, (
            f"#702 round-2 LEAK: truncation {typo!r} must alias to {fix!r}, "
            f"got {L.detect_leaf_typo(typo)!r}")
    # and the helper itself must NOT exempt any of these:
    assert L._is_verb_base_of_canonical("counte") is False
    assert L._is_verb_base_of_canonical("registe") is False


def test_classic_truncation_typos_unaffected_by_the_relax():
    # the pre-existing positive cases must keep firing after the relax.
    assert L.detect_leaf_typo("substractor") == "subtractor"
    assert L.detect_leaf_typo("multipler") == "multiplier"
    assert L.detect_leaf_typo("accumulater") == "accumulator"
    assert L.detect_leaf_typo("comparater") == "comparator"
    assert L.detect_leaf_typo("fast_multipler") == "fast_multiplier"
    assert L.detect_leaf_typo("pipelined_substractor") == "pipelined_subtractor"


def test_real_misspelled_leaf_still_aliased_end_to_end(tmp_path):
    # a genuinely-misspelled leaf must STILL auto-emit its canonical alias.
    rtl = tmp_path / "design.v"
    rtl.write_text(
        "module decodr (\n"
        "    input [3:0] in_,\n"
        "    output [15:0] out_\n"
        ");\n"
        "    assign out_ = 16'b1 << in_;\n"
        "endmodule\n")
    rc = L.main(["--rtl", str(rtl), "--leaf", "decodr"])
    assert rc == 0
    # the corrected canonical alias `decoder.v` IS written
    assert (tmp_path / "decoder.v").is_file()
    wtxt = (tmp_path / "decoder.v").read_text()
    assert "module decoder (" in wtxt
    assert "decodr u_decodr (" in wtxt


# ── existing guards must still hold after the relax ─────────────────────

def test_existing_inflection_guards_still_fire():
    # -ed / -ing / -s inflected real words still exempt (None).
    for w in ("shifted", "encoded", "decoded", "scheduled", "counters",
              "registers", "decoders", "encoders", "shifting", "counting"):
        assert L.detect_leaf_typo(w) is None, w


def test_existing_british_iser_guard_still_fires():
    for brit in ("normaliser", "serialiser", "deserialiser"):
        assert L.detect_leaf_typo(brit) is None, brit


def test_existing_agent_noun_denylist_still_fires():
    for word in ("resister", "diviner", "deceiver", "recorder", "reminder"):
        assert L.detect_leaf_typo(word) is None, word


def test_correct_canonical_agent_nouns_still_do_not_fire():
    # the agent nouns themselves (`decoder`, `encoder`) are correct spellings.
    for good in ("decoder", "encoder", "subtractor", "counter", "register"):
        assert L.detect_leaf_typo(good) is None, good
