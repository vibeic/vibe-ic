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

import phase1_one_shot_runner as R            # noqa: E402
import phase1_doc_one_shot_runner as D        # noqa: E402
import l_doc_structured_field_count_check as F  # noqa: E402

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

def test_a_prompt_request_over_a_doc_extraction_input_resolves_to_the_docs_door():
    """RED before: `--mode prompt` was `mode = args.mode`, full stop."""
    mode, why = R._resolve_mode("prompt", "docs")
    assert mode == "docs"
    assert why, "a route the caller did not type must be announced, not silent"
    assert "#2052" in why


def test_auto_routing_is_the_pre_2052_expression_unchanged():
    """CONTROL. AUTO must move by ZERO — it is the door 28 real corpora and
    every existing caller already use."""
    for det in _DETECTED:
        pre_2052 = det if det != "none" else "prompt"
        assert R._resolve_mode("auto", det) == (pre_2052, None), det


def test_the_engine_stays_reachable_where_the_detector_itself_says_prompt():
    """CONTROL. `input/docs/` holding pre-structured `L*.json` is the
    reverse-extractor's actual job; #2052 retires it as a FRONT DOOR for raw
    design input, not as a program."""
    assert R._resolve_mode("prompt", "prompt") == ("prompt", None)
    assert R._resolve_mode("auto", "prompt") == ("prompt", None)


def test_nothing_staged_still_reaches_the_step_that_reports_nothing_to_do():
    """CONTROL. An empty project must keep reporting SKIP, not be routed into
    a doc-extraction track over an empty tree."""
    assert R._resolve_mode("prompt", "none") == ("prompt", None)
    assert R._resolve_mode("auto", "none") == ("prompt", None)


def test_a_docs_request_is_still_honoured():
    """CONTROL. `--mode docs` is a request for the canonical door and stays
    one on every detection."""
    for det in _DETECTED:
        assert R._resolve_mode("docs", det) == ("docs", None), det


def test_mutation_restoring_the_stub_entry_re_reddens_the_one_door_rule():
    """MUTATION. The exact pre-#2052 rule was `mode = args.mode` for any
    non-auto mode. Restore it and the request reaches the engine again."""
    def _pre_2052(requested: str, detected: str):
        if requested == "auto":
            return (detected if detected != "none" else "prompt"), None
        return requested, None

    assert _pre_2052("prompt", "docs") == ("prompt", None)
    assert R._resolve_mode("prompt", "docs")[0] == "docs"
    # and the mutation leaves AUTO alone, which is why AUTO never saw this bug
    for det in _DETECTED:
        assert _pre_2052("auto", det) == R._resolve_mode("auto", det), det


def test_the_bare_prompt_file_is_the_input_the_detector_calls_docs(tmp_path):
    """The join between the two halves: this is the staged shape that made
    `--mode prompt` a second front door in the first place."""
    proj = tmp_path / "proj"
    (proj / "input").mkdir(parents=True)
    (proj / "input" / "phase1_prompt.md").write_text(_UNDECLARED)
    assert R._detect_input_mode(proj) == "docs"
    assert R._resolve_mode("prompt", R._detect_input_mode(proj))[0] == "docs"


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

def _l9_floor(doc):
    return F._check_l_doc(9, dict(doc))[0]


def test_a_declared_absence_fills_the_top_module_slot_exactly_as_the_placeholder_did():
    """The placeholder used to fill this slot for every document that had no
    name to give. Removing it must not turn a vocabulary fix into a new red:
    measured over the 283 published L9 documents on this host, the base
    checker on the published documents and this checker on the #2052-shaped
    documents give the IDENTICAL verdict for all 283 (136 FAIL / 147 PASS, by
    path membership)."""
    base_shaped = {"top_module": "chip_top",
                   "top_module_extraction_strategy":
                       "canonical_chip_top_sentinel",
                   "no_top_module_in_input": True,
                   "submodules": [],
                   "top_ports": [{"name": "clk"}, {"name": "q"}]}
    head_shaped = {"top_module": None,
                   "top_module_extraction_strategy": "top_undeclared",
                   "top_module_status": "top_undeclared",
                   "no_top_module_in_input": True,
                   "submodules": [],
                   "top_ports": [{"name": "clk"}, {"name": "q"}]}
    assert _l9_floor(base_shaped) is True
    assert _l9_floor(head_shaped) is True


def test_a_document_that_states_nothing_about_its_top_still_fails_the_floor():
    """CONTROL — the honesty guard. Neither a name NOR the explicit flag is
    still zero for that slot, on both sides of the change. Without this the
    new clause would be vacuous."""
    silent = {"top_ports": [{"name": "clk"}, {"name": "q"}], "submodules": []}
    assert _l9_floor(silent) is False
    # and `false` — a design whose input DID name a top — never masquerades
    denied = dict(silent, no_top_module_in_input=False)
    assert _l9_floor(denied) is False


def test_mutation_dropping_the_honest_absence_clause_re_reddens_29_real_documents():
    """MUTATION. The pre-clause predicate was `isinstance(top_module, str) and
    top_module`. Applied to a #2052-shaped document it is False, which is the
    counterfactual measured over the corpus: 29 of the 283 published L9
    documents flip PASS -> FAIL without this clause."""
    head_shaped = {"top_module": None,
                   "top_module_status": "top_undeclared",
                   "no_top_module_in_input": True,
                   "submodules": [],
                   "top_ports": [{"name": "clk"}, {"name": "q"}]}
    pre_clause = (isinstance(head_shaped.get("top_module"), str)
                  and bool(head_shaped.get("top_module")))
    assert pre_clause is False
    assert F._has_honest_no_top_module(head_shaped) is True
    assert _l9_floor(head_shaped) is True


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


def test_both_doors_report_the_same_name_for_flow_step_d1():
    """#2052 — D1 was `phase1_doc_extract` on the docs branch and
    `phase1_ingest_render` on the prompt branch: one flow step, two names, so a
    reader could not join two runs of the same design. Both read `D1_STEP_NAME`
    now, and nothing types either literal at a dispatch site."""
    src = (PROGRAMS / "phase1_one_shot_runner.py").read_text(encoding="utf-8")
    assert 'D1_STEP_NAME = "phase1_ingest_render"' in src
    assert '_preflight_refusal("phase1_doc_extract")' not in src
    assert '_preflight_refusal("phase1_ingest_render")' not in src
    assert src.count("_preflight_refusal(D1_STEP_NAME)") == 2


def test_the_docs_branch_reports_a_steps_list_for_a_completed_run():
    """#2052 — `reports/phase1_one_shot.json` carried a `steps` key on the
    prompt branch and, for a COMPLETED run, not on the docs branch: a
    divergence about the DOORS, in the file every caller reads. Measured as the
    two RED rows this lane's 436-file sweep found and this closed —
    `test_phase1_one_shot_runner.py::test_integration_report_shape` and
    `::test_reverse_one_staged_input_and_the_same_run_completes`, both of which
    now pass UNCHANGED. This pins the emitter rather than re-running it."""
    src = (PROGRAMS / "phase1_one_shot_runner.py").read_text(encoding="utf-8")
    docs_branch = src.split('if mode == "docs":', 1)[1].split(
        "# Prompt mode:", 1)[0]
    assert 'summary["steps"] = [' in docs_branch
    # …on the completed path too, not only on the refusal path.
    assert docs_branch.count('summary["steps"]') == 2
    assert "phase1_expert_parse_track" in docs_branch
