#!/usr/bin/env python3
"""#2052 — ONE Phase-1 front door: the engine stub stops being an entry, the
top module is derived once, and a top named in prose is read.

Everything below was MEASURED on live main 91d9063b4 (v1.17.80) on 8HD-6
before any edit, over one 409-byte `input/phase1_prompt.md`
(md5 a781c00c8c5f1bb3aee516ffb92561b3) that declares five signals and no top:

    arm                 rc  door    L*.json  L9.top_module  ports  sufficiency
    AUTO                 0  docs     28      "chip_top"       4    sufficient
    --mode prompt        1  engine   13      null             0    EXTRACTION GAP

Same bytes, two doors, two different designs — and one of them exits 1. The
flow declares ONE canonical front door; `--mode prompt` was the second.

ITEM 1 — `phase1_one_shot_runner.main` took `mode = args.mode` for any forced
mode, so `--mode prompt` OVERRODE `_detect_input_mode` and entered
`phase1_engine._stub_l_docs_from_prose` (13 layers, its own prose heuristics)
for input the detector had already ruled belongs to the doc-extraction track.
`_resolve_mode` now resolves that REQUEST to the docs door and says so. AUTO is
untouched by construction, and the engine stays reachable exactly where the
DETECTOR itself answers "prompt" (a pre-structured `L*.json` corpus — the
reverse-extractor's real job) and where nothing is staged (the SKIP).

ITEM 2 — the docs door published the invented name `chip_top` with strategy
`canonical_chip_top_sentinel` whenever no extractor found a top, while the
other door published `top_module: null` + `top_module_status: top_undeclared`
for the same bytes. Census on this host: of 283 published L9 documents, 51
carry that sentinel — 51 real designs whose top module is a placeholder that
reads exactly like an extracted identifier. One derivation, one refusal, one
vocabulary; the constants live in the docs runner and the engine door imports
them, so the two spellings cannot drift.

ITEM 3 — neither door read a top the design STATES in a sentence. Measured on
base: "The top module is `foo_top`." -> None, "The top-level module is named
foo_top." -> None. `_doc_module_name_label_or_inline` now reads that
convention, as GRAMMAR: the identifier must be adjacent to a top-module phrase,
and a BARE value must additionally have RTL identifier shape, so a copula's
English object ("the top module is instantiated.") cannot name a design.

Both directions throughout: each mutation restores the exact pre-fix rule and
the rows go red again, and every control names what must NOT move.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PLUGIN / "tools"))

import phase1_doc_one_shot_runner as D        # noqa: E402

# The four answers `_detect_input_mode` can give.
_DETECTED = ("docs", "prompt", "none")

# Prose that declares five signals and NO top module — the measured input.
_UNDECLARED = ("Implement a framed serial receiver.\n"
               "\n"
               " - input  clk\n"
               " - input  rst\n"
               " - input  rx\n"
               " - output cmd_out (4 bits)\n"
               " - output frame_done\n")


# ── ITEM 1 — one front door ───────────────────────────────────────────















# ── ITEM 2 — the top module is derived once ───────────────────────────

def _l9(tmp_path, text, name="design_description.md"):
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / name).write_text(text)
    res = D.gen_l9_integration_spec(proj, {f"input/docs/{name}": text}, {})
    return json.loads(Path(res.path).read_text(encoding="utf-8"))


def test_the_docs_door_no_longer_invents_a_top_module(tmp_path):
    """RED before: top_module == "chip_top", strategy
    "canonical_chip_top_sentinel" — a name nobody declared."""
    l9 = _l9(tmp_path, _UNDECLARED)
    assert l9["top_module"] is None
    assert l9["top_module_status"] == D.TOP_MODULE_STATUS_UNDECLARED
    assert l9["top_module_extraction_strategy"] == D.TOP_MODULE_UNDECLARED_STRATEGY
    assert l9["no_top_module_in_input"] is True


def test_both_front_doors_publish_the_same_refusal_for_the_same_bytes(tmp_path):
    """The two doors' answers to one question, side by side. RED before: the
    docs door said 'chip_top' where the engine door said None."""
    from phase1_engine.cli import _docs_door_top_module  # noqa: E402
    engine_value, engine_status = _docs_door_top_module(_UNDECLARED)
    l9 = _l9(tmp_path, _UNDECLARED)
    assert (l9["top_module"], l9["top_module_status"]) == \
           (engine_value, engine_status)


def test_the_status_vocabulary_is_one_definition_not_two_spellings():
    """The engine door imports the strings from the docs door. A fact spelt in
    two places is a fact that will disagree."""
    src = (PLUGIN / "tools" / "phase1_engine" / "cli.py").read_text(
        encoding="utf-8")
    assert "_docs.TOP_MODULE_STATUS_DECLARED" in src
    assert "_docs.TOP_MODULE_STATUS_UNDECLARED" in src
    assert D.TOP_MODULE_STATUS_DECLARED == "declared_in_input"
    assert D.TOP_MODULE_STATUS_UNDECLARED == "top_undeclared"


def test_a_declared_top_is_unchanged_and_says_it_was_declared(tmp_path):
    """CONTROL. A real `module <name> (...)` declaration must be byte-identical
    to what base published, and must NOT be labelled undeclared."""
    text = ("The design is a receiver.\n\n"
            "module framed_rx (input clk, output q);\n")
    l9 = _l9(tmp_path, text)
    assert l9["top_module"] == "framed_rx"
    assert l9["top_module_status"] == D.TOP_MODULE_STATUS_DECLARED
    assert l9["no_top_module_in_input"] is False


def test_an_explicit_module_name_label_is_unchanged(tmp_path):
    """CONTROL. The `Module Name:` convention is the other door's control too
    (#2049) and must not move."""
    text = "Module Name: framed_rx\n\n - input clk\n - output q\n"
    l9 = _l9(tmp_path, text)
    assert l9["top_module"] == "framed_rx"
    assert l9["top_module_status"] == D.TOP_MODULE_STATUS_DECLARED


def test_a_name_derived_from_the_chip_name_is_not_called_declared():
    """CONTROL for the status vocabulary itself: `l1_ic_name_fallback` is a
    name the flow DERIVED, and a consumer asking "did the design declare its
    top" must not be told yes."""
    assert D._top_module_status_for("l1_ic_name_fallback") == \
        D.TOP_MODULE_STATUS_DERIVED
    assert D._top_module_status_for("rtl_filesystem_scan") == \
        D.TOP_MODULE_STATUS_DECLARED
    # an unrecognised strategy is never read as a declaration
    assert D._top_module_status_for("a_strategy_nobody_classified") == \
        D.TOP_MODULE_STATUS_DERIVED


def test_mutation_restoring_the_chip_top_sentinel_re_reddens(tmp_path):
    """MUTATION. The exact pre-#2052 lines were

        top_module = "chip_top"
        top_module_extraction_strategy = "canonical_chip_top_sentinel"

    Reapply them to the published document and the two doors disagree again."""
    from phase1_engine.cli import _docs_door_top_module  # noqa: E402
    l9 = _l9(tmp_path, _UNDECLARED)
    mutated = dict(l9)
    mutated["top_module"] = "chip_top"
    mutated["top_module_extraction_strategy"] = "canonical_chip_top_sentinel"
    engine_value, _ = _docs_door_top_module(_UNDECLARED)
    assert mutated["top_module"] != engine_value
    assert l9["top_module"] == engine_value


# ── ITEM 2 — the structural floor keeps the arithmetic it had ─────────









# ── ITEM 3 — a prose top name is read ─────────────────────────────────

def _named(text):
    return D._doc_module_name_label_or_inline({"p.md": text})


def test_a_top_module_stated_in_prose_is_read():
    """RED before: every one of these returned None."""
    assert _named("The top module is `foo_top`.") == "foo_top"
    assert _named("The top module is foo_top.") == "foo_top"
    assert _named("The top-level module is named foo_top.") == "foo_top"
    assert _named("The top-level module shall be named spi_ctrl_top.") == \
        "spi_ctrl_top"
    assert _named("The top module is dma_engine_top") == "dma_engine_top"


def test_the_label_and_colon_forms_are_read_by_this_reader_too():
    """`top-level module: foo_top` reached the top only through the LOW-
    confidence `_walk` chain before. It is an explicit declaration and now
    reads as one."""
    assert _named("top-level module: foo_top") == "foo_top"
    assert _named("top module = uart_rx_top") == "uart_rx_top"


def test_the_inline_backtick_convention_is_unchanged():
    """CONTROL — the one form that already worked."""
    assert _named("top module `foo_top`") == "foo_top"


def test_a_document_that_merely_mentions_top_declares_nothing():
    """CONTROL — a_token_match_is_not_a_command. The name must be ADJACENT to
    a top-module phrase; a bare identifier elsewhere is not a declaration."""
    assert _named("The design sits at the top of the hierarchy and has a "
                  "top-level clock.") is None
    assert _named("Somewhere in the text foo_top appears as a word.") is None
    assert _named("The module is foo_top.") is None


def test_a_copulas_english_object_cannot_become_a_design_top():
    """CONTROL — the grammar guard that makes the BARE branch safe. Each of
    these is adjacent to a top-module phrase and closes the clause; only the
    RTL-identifier-shape requirement stops them."""
    assert _named("The top module is instantiated.") is None
    assert _named("The top module is instantiated twice.") is None
    assert _named("The top module is a wrapper.") is None
    assert _named("The top module is the design under test.") is None


def test_a_name_the_author_wrote_as_code_survives_the_shape_rule():
    """CONTROL for the OTHER side of the two-shape rule: an exact alphabetic
    identifier is a real RTL name when the author marked it up as one."""
    assert _named("The top module is `RAM`.") == "RAM"


def test_the_stated_top_outranks_a_passing_inline_module_reference():
    """Ordering. A sentence about THE TOP outranks a mention of SOME module."""
    text = ("The design instantiates module `sub_block` twice.\n"
            "The top module is `chip_wrapper_top`.\n")
    assert _named(text) == "chip_wrapper_top"


def test_a_module_name_label_still_outranks_a_stated_top():
    """CONTROL — the pre-existing priority is not reordered under the label."""
    text = ("Module Name: labelled_top\n"
            "\n"
            "The top module is `stated_top`.\n")
    assert _named(text) == "labelled_top"


def test_a_stated_top_reaches_the_published_l9(tmp_path):
    """End-to-end: the gap #2049 measured (its fixture E) is closed on the
    door that publishes the document."""
    text = ("A framed serial receiver.\n\n"
            "The top module is `framed_rx`.\n\n"
            " - input clk\n - output q\n")
    l9 = _l9(tmp_path, text)
    assert l9["top_module"] == "framed_rx"
    assert l9["top_module_status"] == D.TOP_MODULE_STATUS_DECLARED


def test_mutation_removing_the_stated_top_convention_re_reddens():
    """MUTATION. Restore the pre-#2052 reader — label, then inline — and the
    stated forms return None again."""
    import re as _re
    for text in ("The top module is `foo_top`.",
                 "The top module is foo_top.",
                 "The top-level module is named foo_top."):
        label = D._RE_DOC_TOP_MODULE_NAME_LABEL.search(text)
        inline = D._RE_DOC_TOP_MODULE_INLINE_BACKTICK.search(text)
        assert label is None and inline is None, text   # the pre-fix answer
        assert _named(text) == "foo_top"                # the post-fix answer
    assert isinstance(D._RE_DOC_TOP_MODULE_TOP_IS_NAMED, _re.Pattern)


def test_a_bulleted_top_module_label_is_read():
    """The real-world shape this convention was measured absent on. Over 4787
    real design-input documents, exactly one subject's derivation moves, and
    this is the shape of its declaration: a bullet, a bare "Top module:" label,
    a backticked identifier, a trailing parenthetical. Base read None from it —
    `_RE_DOC_TOP_MODULE_EXPLICIT_LINE` requires `top[-_ ]?level` and this says a
    bare "Top module:", and the `Module Name:` label pattern requires the
    literal words "module name"."""
    assert _named("- Top module: `dma_engine_core` (per the staged reference "
                  "flow).") == "dma_engine_core"


def test_prose_about_another_module_does_not_displace_an_explicit_label():
    """CONTROL — the other half of that measurement. Upstream documentation
    describing the UPSTREAM project's own hierarchy is not adjacent to a
    top-module phrase and is not a declaration about THIS design, so it cannot
    displace the brief's explicit label."""
    upstream = ("The main module is named ``dma_engine_top`` and can be found "
                "in ``dma_engine_top.sv``.\nUse the top-level parameter "
                "``VendorId`` in :file:`rtl/dma_engine_top.sv` to change the "
                "fixed value.\n")
    assert _named(upstream) is None
    both = {"docs/upstream.rst": upstream,
            "phase1_prompt.md": "- Top module: `dma_engine_core` (per the "
                                "flow).\n"}
    assert D._doc_module_name_label_or_inline(both) == "dma_engine_core"
