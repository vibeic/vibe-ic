#!/usr/bin/env python3
"""A wrapper default selected a variant the design had deliberately removed.

MEASURED DEFECT
===============
`_autoemit_chip_top_wrapper` copies the DUT's ``#(parameter ...)`` header
verbatim. A security-hardened IP ships several implementation variants of one
block behind a compile-time parameter, and a staging convention may EXCLUDE one
by renaming its file ``<module>.sv.unused-<why>-excluded`` so no RTL glob picks
it up. When the copied default names exactly that variant, the wrapper cannot
elaborate at all — and the flow discovered it several steps later as a raw

    ERROR: Module `\\aes_sbox_dom' referenced in module
    `$paramod\\aes_sbox\\SecSBoxImpl=...' ... is not part of the design

which reads as a synthesis failure and was triaged as one. One unset parameter,
five red steps (l10_unit_tb_run, step4_functional_evidence, yosys_synth,
verilator_coverage, reference_tb) and a BLOCKED dft_lec_chain.

THE LINE THIS MUST NOT CROSS
============================
#586 refuses to pick a variant for the operator, and that refusal survives: a
FREE CHOICE must be DECLARED. The emitter resolves ONLY when the design input
declared something that decides it, and the value is then derived from the
RTL's OWN guard structure — never invented. In every other case it REFUSES BY
NAME, at emission, before a tool is started.

Both directions are pinned below, plus the two controls that must be NO-OPS
byte for byte, plus the two mutations that must re-redden.
"""
import inspect
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import design_one_shot_runner as D  # noqa: E402
import staged_rtl_closure_preflight as _pf  # noqa: E402

WRAPPER_BLOCK = """#(
  parameter bit          SecMasking  = 0,
  parameter sbox_impl_e  SecSBoxImpl = SBoxImplDom
)"""

# A three-variant block behind one selector, with the design's OWN derivation
# (`Masked`) and its OWN default (`VariantLut`). Deliberately NOT the shape of
# any one vendor's file: what is pinned is the STRUCTURE, not a vocabulary.
SBOX_SV = """
module thing_sbox #(
  parameter sbox_impl_e SecSBoxImpl = SBoxImplLut
) (input logic a, output logic b);

  localparam bit Masked = (SecSBoxImpl == SBoxImplCanrightMasked ||
                           SecSBoxImpl == SBoxImplCanrightMaskedNoreuse ||
                           SecSBoxImpl == SBoxImplDom) ? 1'b1 : 1'b0;

  if (!Masked) begin : gen_unmasked
    if (SecSBoxImpl == SBoxImplCanright) begin : gen_canright
      thing_sbox_canright u_sbox (.a(a), .b(b));
    end else begin : gen_lut
      thing_sbox_lut u_sbox (.a(a), .b(b));
    end
  end else begin : gen_masked
    if (SecSBoxImpl == SBoxImplDom) begin : gen_dom
      thing_sbox_dom u_sbox (.a(a), .b(b));
    end else if (SecSBoxImpl == SBoxImplCanrightMaskedNoreuse) begin :
        gen_canright_masked_noreuse
      thing_sbox_canright_masked_noreuse u_sbox (.a(a), .b(b));
    end else begin : gen_canright_masked
      thing_sbox_canright_masked u_sbox (.a(a), .b(b));
    end
  end
endmodule
"""

# The DEFECT NEEDS TWO MODULES, and a fixture with one is vacuous — measured:
# an earlier version of the A/B below wrapped `thing_sbox` itself, whose own
# default is already the in-closure variant, so it PASSED on the pre-fix tree
# and observed nothing. The integration top declares the EXCLUDED variant; the
# module that consumes the parameter declares an in-closure one. That gap is
# the defect, and only a two-module fixture has it.
THING_TOP = """
module thing_top #(
  parameter bit         SecMasking  = 1,
  parameter sbox_impl_e SecSBoxImpl = SBoxImplDom
) (input logic a, output logic b);
  thing_sbox #(.SecSBoxImpl(SecSBoxImpl)) u_sbox (.a(a), .b(b));
endmodule
"""

LEAVES = ("thing_sbox_lut", "thing_sbox_canright",
          "thing_sbox_canright_masked",
          "thing_sbox_canright_masked_noreuse")


def _project(exclude_dom=True, ship_dom=False):
    root = Path(tempfile.mkdtemp(prefix="excl_variant_"))
    rtl = root / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (root / "input").mkdir()
    (rtl / "thing_sbox.sv").write_text(SBOX_SV)
    (rtl / "thing_top.sv").write_text(THING_TOP)
    for leaf in LEAVES:
        (rtl / f"{leaf}.sv").write_text(
            f"module {leaf} (input logic a, output logic b);\n"
            f"  assign b = a;\nendmodule\n")
    if exclude_dom:
        (root / "input" / "thing_sbox_dom.sv.unused-masked-scan-excluded"
         ).write_text("module thing_sbox_dom (input logic a, output logic b);"
                      "\n  assign b = a;\nendmodule\n")
    if ship_dom:
        (rtl / "thing_sbox_dom.sv").write_text(
            "module thing_sbox_dom (input logic a, output logic b);\n"
            "  assign b = a;\nendmodule\n")
    return root, rtl


def _value(block, name):
    m = re.search(r"\b" + name + r"\s*=\s*([^,;)\n]+)", block)
    return m.group(1).strip() if m else None


def test_declared_masking_off_derives_the_unmasked_in_closure_variant():
    """DIRECTION 1 — the input DECLARED it, so the flow derives it."""
    root, rtl = _project()
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert refusals == []
    assert "SecSBoxImpl" in resolved
    assert resolved["SecSBoxImpl"]["value"] == "SBoxImplLut"
    assert _value(block, "SecSBoxImpl") == "SBoxImplLut"
    # The provenance is the point: a reader must be able to re-derive it.
    d = resolved["SecSBoxImpl"]["derivation"]
    assert d["declared_parameter"] == "SecMasking"
    assert d["declared_value"] == "0"
    assert d["rtl_predicate"] == "Masked"
    assert "SBoxImplDom" in d["rtl_predicate_true_for"]
    assert resolved["SecSBoxImpl"]["excluded_modules"] == ["thing_sbox_dom"]
    shutil.rmtree(root, ignore_errors=True)


def test_undeclared_is_refused_by_name_and_nothing_is_picked():
    """DIRECTION 2 — nothing declared, so the choice is FREE and REFUSED."""
    root, rtl = _project()
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["UNDECLARED_FREE_CHOICE"]
    r = refusals[0]
    assert r["parameter"] == "SecSBoxImpl"
    assert r["excluded_modules"] == ["thing_sbox_dom"]
    assert r["excluded_files"] == [
        "input/thing_sbox_dom.sv.unused-masked-scan-excluded"]
    # The wrapper is NOT rewritten on a refusal.
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)




def test_control_a_cell_that_ships_the_variant_keeps_its_default():
    """CONTROL — nothing is excluded, so nothing is resolved and the copied
    block comes back BYTE-IDENTICAL."""
    root, rtl = _project(exclude_dom=False, ship_dom=True)
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert (resolved, refusals) == ({}, [])
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_control_a_design_with_no_exclusion_marker_at_all():
    """CONTROL — the whole mechanism is a no-op on every ordinary design."""
    root, rtl = _project(exclude_dom=False)
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert (resolved, refusals) == ({}, [])
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_mutation_an_unreadable_guard_refuses_instead_of_passing_it_on():
    """MUTATION — the derivation can no longer be read. UNKNOWN is not SAFE:
    skipping here is exactly how the abort reached yosys in the first place."""
    root, rtl = _project()
    p = rtl / "thing_sbox.sv"
    p.write_text(re.sub(r"localparam bit Masked = [^;]+;",
                        "localparam bit Masked = SomeOtherKnob;",
                        p.read_text(), flags=re.S))
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["UNREADABLE_GUARD"]
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_mutation_the_declared_value_decides_and_an_unnameable_arm_refuses():
    """MUTATION — flip the DECLARED value. The answer must follow it, and
    where the surviving arm cannot be NAMED the flow must refuse rather than
    choose out of a set it can only partly spell."""
    root, rtl = _project()
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "1"})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["INCOMPLETE_CANDIDATE_SET"]
    assert refusals[0]["unnameable_in_closure_variants"] == [
        "thing_sbox_canright_masked"]
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_mutation_no_in_closure_variant_matches_the_declaration():
    """MUTATION — declare masking ON while EVERY masked variant is out of the
    closure. There is nothing consistent to choose, and the flow says so by
    name rather than falling back to something unmasked."""
    root, rtl = _project()
    for leaf in ("thing_sbox_canright_masked",
                 "thing_sbox_canright_masked_noreuse"):
        (rtl / f"{leaf}.sv").rename(
            root / "input" / f"{leaf}.sv.unused-masked-scan-excluded")
    block, resolved, refusals = D._chip_top_resolve_excluded_variant_params(
        root, rtl, WRAPPER_BLOCK, {"SecMasking": "1"})
    assert resolved == {}
    assert [r["reason"] for r in refusals] == ["NO_VARIANT_MATCHES_DECLARATION"]
    assert block == WRAPPER_BLOCK
    shutil.rmtree(root, ignore_errors=True)


def test_end_to_end_the_emitted_wrapper_carries_the_derived_value():
    """The A/B THE PRE-FIX TREE CAN ALSO RUN.

    Every other test here calls a function that does not exist before the fix,
    so on the old tree they ERROR rather than observe. This one goes through
    `_autoemit_chip_top_wrapper`, which exists on both sides, and reads the
    emitted file. On the pre-fix tree that wrapper carries the EXCLUDED
    variant; here it must carry the derived one. That is the defect, stated so
    both trees can answer it.
    """
    root, rtl = _project()
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(
        '{"parameters": [{"name": "SecMasking", "value": "0",'
        ' "override": true}]}')
    (gd / "L9_INTEGRATION_SPEC.json").write_text('{"top_module": "thing_top"}')
    out = D._autoemit_chip_top_wrapper(root, rtl, "chip_top")
    assert out is not None, "no wrapper emitted"
    text = out.read_text()
    assert "SBoxImplLut" in text
    assert "SBoxImplDom" not in text
    shutil.rmtree(root, ignore_errors=True)




# --------------------------------------------------------------------------
# THE `_NOT_PROSE` CLAIM — its falsifier. vibe-ic#2102, row 2.
# --------------------------------------------------------------------------
# `prose_polarity_consulted_check._NOT_PROSE` classifies
# `design_one_shot_runner::_chip_top_resolve_excluded_variant_params` as reading
# a FORMAL GRAMMAR rather than prose, so it is exempt from consulting the
# polarity vocabulary. That is a CLASSIFICATION, not an allowlist, and it has to
# be checkable. The claim is NOT that a denial is read and correctly overruled;
# it is that NO SENTENCE REACHES ANY REGEX HERE — the wrapper header is blanked
# by `_hdl_code_text.strip_hdl_comments_and_strings` and every RTL file arrives
# through `staged_rtl_closure_preflight._gather`, which strips comments.
#
# If a sentence CAN change what this function publishes, the classification is
# false and the instruction is to DELETE THE ENTRY and consult `_prose_polarity`
# — never to relax anything below.
#
# THE SWEEP IS RE-MEASURED HERE RATHER THAN QUOTED. A number written into the
# register's prose stops tracking the thing it counts; this recomputes it on
# every run, and the register cites this test by name.
import _prose_polarity as _PP  # noqa: E402


def _denial_tokens():
    """The vocabulary's own tokens, DERIVED from its regex source.

    Derived, not transcribed: a token list typed here would silently stop
    covering the vocabulary the moment a word is added to it, and this file is
    English-only while that vocabulary is not.
    """
    out = []
    for src in (_PP._DENIAL_CORE, _PP._DENIAL_RETIRED):
        for alt in src.split("|"):
            w = re.sub(r"^\\b|\\b$", "", alt.strip())
            w = w.replace(r"\w*", "").replace("-?", "")
            if w and w not in out:
                out.append(w)
    bad = [w for w in out if not _PP.NEGATION_RE.search(w)]
    assert not bad, f"derived tokens the vocabulary does not match: {bad}"
    return out


def _sentence(tok, payload):
    return f"this variant is {tok} used here: {payload}"


#: Every position a sentence can physically occupy in the two inputs this
#: function reads — both comment forms and the Verilog string literal, in the
#: wrapper header and in each of the two RTL files that decide anything.
#: The PAYLOAD of each is declaration-shaped and chosen so that READING it
#: would move the published answer; `_CODE_ARM` below proves that per position.
_NP_POSITIONS = [
    ("wrapper_line_comment", "param", "// {s}\n"),
    ("wrapper_block_comment", "param", "/* {s} */\n"),
    ("wrapper_string_default", "param", None),
    ("sbox_param_comment", "sbox", "  // {s}\n"),
    ("sbox_block_comment", "sbox", "  /* {s} */\n"),
    ("sbox_inst_comment", "sbox", "    // {s}\n"),
    ("sbox_localparam_comment", "sbox", "  // {s}\n"),
    ("sbox_module_comment", "sbox", "// {s}\n"),
    ("sbox_cond_comment", "sbox", "  // {s}\n"),
    ("top_inst_comment", "top", "  // {s}\n"),
    # A VERILOG STRING LITERAL IN THE RTL, which `_pf._gather` does NOT blank.
    # This position was ADDED after the other ten passed and it was the one
    # that failed: the sentence survived the gatherer, `_pf._PARAM_RE` read it
    # as the module's own declared default, and the wrapper resolved to
    # `SBoxImplCanright"` -- closing quote included -- out of a sentence that
    # DENIES it. The function now blanks strings on this path too.
    ("sbox_string_literal", "sbox", "  initial $display(\"{s}\");\n"),
]
_NP_PAYLOAD = {
    # A second `parameter` record for the SAME name, later in the block: read
    # as a declaration it OVERWRITES `wrapper_defaults` and the whole mechanism
    # silently no-ops, so the emitted wrapper keeps the EXCLUDED variant — the
    # defect this file exists for, arriving through a comment.
    "wrapper_line_comment": "parameter sbox_impl_e SecSBoxImpl = SBoxImplLut",
    "wrapper_block_comment": "parameter sbox_impl_e SecSBoxImpl = SBoxImplLut",
    "wrapper_string_default": "parameter sbox_impl_e SecSBoxImpl = SBoxImplLut",
    # The consuming module's OWN declared default, which feeds both the
    # candidate set and the tie-break.
    "sbox_param_comment": "parameter sbox_impl_e SecSBoxImpl = SBoxImplCanright",
    "sbox_block_comment": "parameter sbox_impl_e SecSBoxImpl = SBoxImplCanright",
    # An instantiation of the EXCLUDED module in an arm that IS reached.
    "sbox_inst_comment": "thing_sbox_dom u_sbox2 (.a(a), .b(b));",
    # A redefinition of the very predicate the derivation is read from.
    "sbox_localparam_comment":
        "localparam bit Masked = (SecSBoxImpl == SBoxImplLut) ? 1'b1 : 1'b0;",
    # A whole extra module definition, which would enter `defined`.
    "sbox_module_comment": "module thing_sbox_dom (input logic a);",
    # A generate condition naming the excluded variant.
    "sbox_cond_comment": "if (SecSBoxImpl == SBoxImplDom) begin : gen_x",
    # A guarded instantiation of the excluded module at the integration top.
    "top_inst_comment": ("if (SecMasking == 0) begin : gen_m "
                         "thing_sbox_dom u_dom (.a(a), .b(b)); end"),
    "sbox_string_literal":
        "parameter sbox_impl_e SecSBoxImpl = SBoxImplCanright",
}
_NP_ANCHOR = {
    "sbox_param_comment":
        "  parameter sbox_impl_e SecSBoxImpl = SBoxImplLut\n",
    "sbox_block_comment":
        "  parameter sbox_impl_e SecSBoxImpl = SBoxImplLut\n",
    "sbox_inst_comment": "    end else begin : gen_lut\n",
    "sbox_localparam_comment":
        "                           SecSBoxImpl == SBoxImplDom) ? 1'b1 : 1'b0;\n",
    "sbox_module_comment": "\nmodule thing_sbox #(",
    "sbox_cond_comment": "  if (!Masked) begin : gen_unmasked\n",
    "top_inst_comment": ") (input logic a, output logic b);\n",
    "sbox_string_literal": ") (input logic a, output logic b);\n",
}
#: The positions the CODE arm proves live. Pinned as a SET, not a count: a
#: change that quietly makes one of them unable to move the answer turns its
#: trials into observations of nothing, and this is the only thing that says so.
#: `sbox_module_comment` is deliberately absent — `_MODULE_DEF_RE` feeds
#: `defined`, a read a sentence can only ADD to, and adding a name never
#: withdraws a candidate. Recorded rather than counted.
_NP_LIVE = {
    "wrapper_line_comment", "wrapper_block_comment", "wrapper_string_default",
    "sbox_param_comment", "sbox_block_comment", "sbox_inst_comment",
    "sbox_localparam_comment", "sbox_cond_comment", "top_inst_comment",
    "sbox_string_literal",
}


def _np_build(pos, tok):
    """(param_block, sbox_sv, top_sv, sentence) — the sentence AS PROSE."""
    s = _sentence(tok, _NP_PAYLOAD[pos])
    param, sbox, top = WRAPPER_BLOCK, SBOX_SV, THING_TOP
    if pos == "wrapper_string_default":
        # A Verilog STRING literal mints declarations exactly as a comment
        # does, which is why the shared blanker blanks both in one alternation.
        return (param.replace(
            "  parameter bit          SecMasking  = 0,\n",
            "  parameter bit          SecMasking  = 0,\n"
            f'  parameter string       Note = "{s}",\n'), sbox, top, s)
    fmt = [f for (n, _w, f) in _NP_POSITIONS if n == pos][0]
    where = [w for (n, w, _f) in _NP_POSITIONS if n == pos][0]
    text = fmt.format(s=s)
    if where == "param":
        param = param.replace(
            "  parameter sbox_impl_e  SecSBoxImpl = SBoxImplDom\n",
            "  parameter sbox_impl_e  SecSBoxImpl = SBoxImplDom\n" + text)
    elif where == "sbox":
        a = _NP_ANCHOR[pos]
        assert a in sbox, pos
        sbox = sbox.replace(a, a + text if not a.startswith("\nmodule")
                            else text + a, 1)
    else:
        a = _NP_ANCHOR[pos]
        assert a in top, pos
        top = top.replace(a, a + text, 1)
    return param, sbox, top, s


def _np_build_code(pos):
    """THE NEGATIVE CONTROL: the SAME payload as CODE, no comment markers and
    outside any string. A position whose answer does not move here observed
    nothing in the prose arm, however green that arm looked."""
    s = _NP_PAYLOAD[pos]
    param, sbox, top = WRAPPER_BLOCK, SBOX_SV, THING_TOP
    if pos.startswith("wrapper_"):  # noqa: E501 — the wrapper header, not a file
        return (param.replace(
            "  parameter sbox_impl_e  SecSBoxImpl = SBoxImplDom\n",
            "  parameter sbox_impl_e  SecSBoxImpl = SBoxImplDom,\n"
            f"  {s}\n"), sbox, top)
    where = [w for (n, w, _f) in _NP_POSITIONS if n == pos][0]
    a = _NP_ANCHOR[pos]
    if where == "sbox":
        assert a in sbox, pos
        sbox = (sbox.replace(a, a + "  " + s + "\n", 1)
                if not a.startswith("\nmodule")
                else sbox.replace(a, "\n" + s + "\nendmodule\n" + a, 1))
    else:
        assert a in top, pos
        top = top.replace(a, a + "  " + s + "\n", 1)
    return param, sbox, top


def _np_run(param, sbox, top):
    root, rtl = _project()
    (rtl / "thing_sbox.sv").write_text(sbox)
    (rtl / "thing_top.sv").write_text(top)
    try:
        _blk, resolved, refusals = \
            D._chip_top_resolve_excluded_variant_params(
                root, rtl, param, {"SecMasking": "0"})
        return ({k: v["value"] for k, v in resolved.items()},
                sorted(r["reason"] for r in refusals))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_not_prose_claim_for_the_wrapper_param_reader_is_falsifiable():
    """Every denial token of the vocabulary, in every position a sentence can
    occupy in this production, carrying a payload that WOULD move the answer.

    The failure instruction is in the assertion message, and it is not
    "loosen this": it is to delete the `_NOT_PROSE` entry and make the
    function consult `_prose_polarity`.
    """
    toks = _denial_tokens()
    base = _np_run(WRAPPER_BLOCK, SBOX_SV, THING_TOP)
    assert base == ({"SecSBoxImpl": "SBoxImplLut"}, []), (
        "the baseline this sweep differences against has moved; every verdict "
        "below is about a different question until it is restored")

    # THE NEGATIVE CONTROL FIRST, so a green sweep cannot be a green fixture.
    live = {pos for pos, _w, _f in _NP_POSITIONS
            if _np_run(*_np_build_code(pos)) != base}
    assert live == _NP_LIVE, (
        f"the set of positions whose payload can move the published answer "
        f"changed: {sorted(live)!r}. The sweep's zero is only evidence over "
        f"positions that could have moved — repair the payloads, do not "
        f"shrink the claim")

    inverted, unchanged, denials = [], 0, 0
    for pos, _w, _f in _NP_POSITIONS:
        for tok in toks:
            param, sbox, top, sentence = _np_build(pos, tok)
            if _PP.is_denied(sentence):
                denials += 1
            got = _np_run(param, sbox, top)
            if got == base:
                unchanged += 1
            else:
                inverted.append((pos, tok, got))

    total = len(toks) * len(_NP_POSITIONS)
    assert inverted == [], (
        f"a SENTENCE changed what this function published: {inverted[:3]!r}. "
        f"The `_NOT_PROSE` entry for design_one_shot_runner::_chip_top_"
        f"resolve_excluded_variant_params claims no prose reaches it, and "
        f"that claim is now false — DELETE the entry and consult "
        f"`_prose_polarity`, rather than weakening this test")
    assert unchanged == total
    # ...and the vocabulary half: the identical strings, read AS PROSE, are
    # denials. The grammar is inert, not the vocabulary.
    assert denials == total, (
        f"only {denials} of {total} injected sentences are read as denials by "
        f"`_prose_polarity`; the sweep is no longer driving the vocabulary")


def test_the_wrapper_param_reader_strips_its_own_inputs_not_via_a_caller():
    """The claim must be a property of THIS function and of the gatherer it
    calls — not of whoever happens to hand it text. Both halves, named."""
    src = inspect.getsource(D._chip_top_resolve_excluded_variant_params)
    assert "_hdl_code_text.strip_hdl_comments_and_strings(param_block)" in src, (
        "the wrapper header is matched on a blanked copy; if that has moved, "
        "the `_NOT_PROSE` claim has to be re-measured")
    assert "_pf._gather(" in src
    gsrc = inspect.getsource(_pf._gather)
    assert "_strip_comments(" in gsrc, (
        "every RTL file this function matches arrives through `_gather`; if "
        "that stops stripping, prose reaches the scans and the `_NOT_PROSE` "
        "entry is false")


# --------------------------------------------------------------------------
# THE FOURTH INPUT — the exclusion MARKER FILENAME, whose `why` slot is the
# only free human text this function reads that is not HDL at all.
# --------------------------------------------------------------------------
# The `_NOT_PROSE` entry claims NO SENTENCE REACHES ANY REGEX HERE, and that is
# a claim about EVERY input, so every input has to be enumerated and probed.
# Three are covered above (`param_block`, the gathered RTL, and `declared`).
# The fourth is `_EXCLUDED_VARIANT_FILE_RE`:
#
#     ^(?P<mod>[A-Za-z_]\w*)\.(?:sv|v)\.unused-[\w.+-]*excluded$
#
# `[\w.+-]*` is a slot an operator fills with a hyphenated phrase explaining WHY
# the variant was staged out, and a phrase is where a denial lives.
#
# THE ANSWER IS NOT "STRIP IT" — IT IS THAT A CONSULT HERE WOULD BE A DEFECT.
# The marker's meaning comes from the NAMING CONVENTION, not from the English
# inside it: `foo.sv.unused-not-excluded-at-all-excluded` is still a file the
# operator moved out of the staged tree, and a flow that read the `not` and then
# IGNORED the marker would stage a variant the operator had deliberately
# removed — the exact failure this whole mechanism exists to prevent, arrived at
# by "consulting polarity". So both directions are pinned: the vocabulary is
# inert in the slot, AND the marker still fires when the slot denies it.
def _why_spellable(tok):
    """Can the filename grammar even carry this token? `[\\w.+-]*` cannot."""
    return all(ch.isalnum() or ch == "_" or ch in ".+-" for ch in tok)


def _run_with_why(why):
    """Rename the marker's WHY clause, then run the production."""
    root, rtl = _project()
    (root / "input" / "thing_sbox_dom.sv.unused-masked-scan-excluded").rename(
        root / "input" / f"thing_sbox_dom.sv.unused-{why}-excluded")
    try:
        _b, resolved, refusals = \
            D._chip_top_resolve_excluded_variant_params(
                root, rtl, WRAPPER_BLOCK, {"SecMasking": "0"})
        return ({k: v["value"] for k, v in resolved.items()},
                sorted(r["reason"] for r in refusals),
                sorted(resolved["SecSBoxImpl"]["excluded_files"])
                if "SecSBoxImpl" in resolved else [])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_denial_in_the_exclusion_marker_why_clause_changes_nothing():
    """Every denial token the filename grammar can spell, in the `why` slot."""
    toks = [t for t in _denial_tokens() if _why_spellable(t)]
    dropped = [t for t in _denial_tokens() if not _why_spellable(t)]
    assert dropped, (
        "at least one vocabulary token must be UNSPELLABLE in `[\\w.+-]*` -- "
        "if that stops being true this test's population claim has moved")
    assert len(toks) >= 15, f"only {len(toks)} tokens are spellable here"
    # Every one of them is still a denial when read as the phrase it is.
    not_denied = [t for t in toks if not _PP.NEGATION_RE.search(t)]
    assert not_denied == [], f"these stopped reading as denials: {not_denied}"

    base = _run_with_why("masked-scan")
    assert base[0] == {"SecSBoxImpl": "SBoxImplLut"} and base[1] == []
    moved = [t for t in toks
             if _run_with_why(f"masked-scan-{t}")[:2] != base[:2]]
    assert moved == [], (
        f"a denial in the marker's `why` slot changed what this function "
        f"published: {moved!r}. The `_NOT_PROSE` entry claims no sentence "
        f"reaches any regex here; delete the entry rather than this test")


def test_the_marker_still_fires_when_its_why_clause_denies_the_exclusion():
    """THE DIRECTION A POLARITY CONSULT WOULD BREAK. The convention says the
    file is staged out; the prose in the slot does not get a vote, and must
    not, or an operator's deliberate exclusion is silently undone."""
    got = _run_with_why("not-excluded-at-all")
    assert got[0] == {"SecSBoxImpl": "SBoxImplLut"}, (
        "the exclusion marker stopped firing because its `why` clause denies "
        "the exclusion -- that is a variant the operator REMOVED being staged "
        "back in")
    assert got[2] == [
        "input/thing_sbox_dom.sv.unused-not-excluded-at-all-excluded"], \
        "the refusal/derivation must still cite the marker it actually read"


def test_the_convention_keyword_is_itself_in_the_denial_vocabulary():
    r"""WHY A CONSULT HERE IS NOT MERELY UNNECESSARY BUT DESTRUCTIVE.

    `_EXCLUDED_VARIANT_FILE_RE` REQUIRES the filename to end in `excluded`, and
    `excluded` is a member of `_prose_polarity`'s own vocabulary
    (`\bexclud\w*\b`). So a polarity consult on this input does not merely
    fire on the rare denying `why` clause -- it fires on EVERY marker of EVERY
    design, because the token that makes a marker a marker is the same token
    the vocabulary reads as a denial, and the whole mechanism switches off.

    MEASURED: planting that consult reddens this file's four core direction
    tests, not just the one above. That is what makes the `_NOT_PROSE` entry a
    claim about the grammar rather than a convenience.
    """
    assert _PP.NEGATION_RE.search("excluded"), (
        "the convention's own terminal keyword is no longer in the denial "
        "vocabulary; the argument in the `_NOT_PROSE` entry has to be "
        "re-measured, not assumed")
    assert D._EXCLUDED_VARIANT_FILE_RE.match(
        "thing_sbox_dom.sv.unused-masked-scan-excluded"), \
        "the marker grammar moved; re-derive which token it requires"
    assert not D._EXCLUDED_VARIANT_FILE_RE.match(
        "thing_sbox_dom.sv.unused-masked-scan"), \
        "`excluded` must be REQUIRED, or the argument above does not hold"
