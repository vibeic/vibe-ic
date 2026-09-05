#!/usr/bin/env python3
"""The router must read the RTL where the task actually put it — the PROMPT.

MEASURED DEFECT (2026-08-27). `classify_task_nature` returns `needs_ai_parse`,
documented as the hook that makes a caller "run the real AI first-layer parse
to confirm". Run over all 664 prompts of the four open benchmarks
(VerilogEval-Human 156 + VerilogEval-v2 156 + RTLLM 50 + CVDP-open 302) it was
True on 664 of 664. A field that never varies across its entire input domain
carries no information; giving it a consumer would not have made it a signal,
it would have sent every design down the AI path.

THE MECHANISM WAS NOT A BADLY-TUNED THRESHOLD. Every branch that CLASSIFIED
returned True; the only branch returning False was the one where the caller
passed `nature` outright. The field restated its own argument — `nature is
None` — while presenting itself as a verdict about the prompt. It was a
constant wearing the costume of a measurement, which is why no threshold
change could have fixed it.

WHY IT COULD NEVER BE CONFIDENT. `has_context` asks "did the caller hand me a
FILE PATH". That is a question about the CALL, not about the TASK. Someone who
pastes their module into the prompt has supplied the RTL just as surely as one
who passes `--rtl`, and the four transform natures need the RTL, not the path.
The router held the prompt text and never looked in it. Measured on the same
664 with has_context=False, which is what a bare prompt gives:

  * 94 prompts embed a complete `module … endmodule`; 86 of those are CVDP —
    the dataset whose 224 mis-entered records this file was written for, so
    this is that dataset's dominant shape rather than an oddity.
  * 153 verdicts carried the warning "prose reads as X but no existing RTL was
    supplied". On 85 of the 153 the RTL was IN THE PROMPT: the warning was
    false more often than true (55.6%).
  * The warning is not inert — it is what diverts a run off the hinted entry
    onto a degraded fallback. 85 false statements are 85 wrong routes.

An independent blind reading of all 156 VerilogEval-Human prompts (prompt text
only; no reference solution, no testbench, no sight of the heuristic's answer)
disagreed with the program on 2 of 156. One of the two is fixed by
`fix/router-advisory-contract`; the other is pinned here: a prompt that quotes
a complete module and says "Fix any and all bugs in this code" was classified
`spec_generation`, i.e. a debug task pushed through Phase 1 — the single
failure this module's docstring says it exists to prevent. Two independent
defects produced it, and both are pinned below.

EVERY FIXTURE HERE IS GENERIC. No vendor, SKU or design name appears; the
prompts are minimal synthetic shapes that reproduce the structure.
"""
import os
import sys
import time

import pytest

_PROGRAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _PROGRAMS)

import task_nature_route as tnr  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


_BODY = """  module widget (
      input  a,
      input  b,
      output c
  );
      assign c = a & b;
  endmodule
"""

_PARTIAL_BODY = """module widget (
  input logic a,
  output logic y
);
  logic internal;
  assign internal = a;
  // complete the output logic here
"""

# What every open RTL benchmark appends: the interface the answer must match.
# It has no `endmodule` and is NOT an implementation.
_STUB = """module TopModule (
  input a,
  input b,
  output c
);
"""

SPEC_ONLY = "Build a circuit whose output is the AND of its two inputs.\n\n" + _STUB
DEBUG_EMBEDDED = "Fix any and all bugs in this code:\n\n" + _BODY + "\n" + _STUB
DEBUG_NO_RTL = "The output is incorrect when both inputs are high.\n\n" + _STUB
REFERENCE_EMBEDDED = (
    "Consider this module:\n\n" + _BODY +
    "\nFactor it into a hierarchical design. Create the submodule called\n"
    "TopModule. You do not have to provide the revised parent.\n\n" + _STUB)
COMPLETE_EMBEDDED = ("Complete the following module.\n\n" + _BODY + "\n" + _STUB)


# ── 1. the detector, both ways ───────────────────────────────────────────────

def test_prompt_embeds_rtl_sees_a_module_body():
    assert tnr.prompt_embeds_rtl(DEBUG_EMBEDDED) is True
    assert tnr.prompt_embeds_rtl(REFERENCE_EMBEDDED) is True


def test_prompt_embeds_rtl_is_not_fooled_by_the_interface_stub():
    """The negative half. A detector that says yes to a bare specification
    would report RTL everywhere and be exactly as uninformative as the flag
    it exists to give content to."""
    assert tnr.prompt_embeds_rtl(SPEC_ONLY) is False
    assert tnr.prompt_embeds_rtl(_STUB) is False
    assert tnr.prompt_embeds_rtl("") is False
    assert tnr.prompt_embeds_rtl("Describe a module that adds two numbers.") is False


def test_prompt_embeds_partial_rtl_requires_body_structure():
    assert tnr.prompt_embeds_partial_rtl(_PARTIAL_BODY) is True
    assert tnr.prompt_embeds_partial_rtl(_STUB) is False
    assert tnr.prompt_embeds_partial_rtl(
        "/* " + _PARTIAL_BODY + " */\n" + _STUB) is False


def _cost_ratio_within(fn, small, big, factor, floor, attempts=3):
    """(ok, small_cost, big_cost) — best-of-N, but only spend the extra runs
    when the first one FAILS.

    A correct implementation pays ONE measurement of each size. A scheduling
    blip — the only way a correct implementation can miss — gets two more
    chances, and the MINIMUM is kept because a scheduler can make a run slower
    and never faster. A genuinely quadratic implementation is not run six times
    before anyone is told.
    """
    best_small = best_big = float("inf")
    for _ in range(attempts):
        t0 = time.perf_counter()
        fn(small)
        best_small = min(best_small, time.perf_counter() - t0)
        t0 = time.perf_counter()
        fn(big)
        best_big = min(best_big, time.perf_counter() - t0)
        if best_big <= max(best_small * factor, floor):
            return True, best_small, best_big
    return False, best_small, best_big


def test_the_detector_cannot_be_made_to_hang_on_a_hostile_prompt():
    """LINEARITY, pinned by a budget with 300x headroom rather than a stopwatch.

    The obvious spelling of this detector is ONE regex spanning header through
    `endmodule`, and it backtracks quadratically: every `module` in the text
    rescans to the end for an `endmodule` that is not there. Measured on that
    form, 664 real prompts cost 15 ms in total but a single 1.25 MB input with
    3000 module headers and no `endmodule` cost 12.7 SECONDS. `classify_task_nature`
    takes a prompt string from whoever is calling it, so that is a hang in the
    front door.

    The split form answers the same question with two linear searches.

    HOW THIS IS ASSERTED, AND WHY NOT WITH A STOPWATCH. The claim is about the
    SHAPE of the cost curve, so it is measured as a RATIO between two inputs of
    known relative size, both run on THIS host inside THIS test. Whatever the
    machine is doing scales both measurements together and cancels; an absolute
    second-count does not have that property, and the previous `elapsed < 2.0`
    was a bound on how busy the host was as much as on the code.

    Quartering the input is the discriminator. Linear costs ~4x. Quadratic costs
    ~16x. The backtracking form measured 12.7 SECONDS against ~5 ms, so it is
    orders of magnitude past either. The 8x gate below sits between 4 and 16
    with room on both sides, and the small absolute floor keeps timer noise on a
    sub-millisecond baseline from deciding anything."""
    import time

    hostile = "\n".join("module m%d (a);" % i + " x" * 200 for i in range(3000))
    assert len(hostile) > 1_000_000

    for text in (hostile,                       # no endmodule at all
                 "endmodule\n" + hostile,       # endmodule before every header
                 "module x (a" + "y" * 200_000):  # a header with no semicolon
        assert tnr.prompt_embeds_rtl(text) is False
        quarter = text[: len(text) // 4]
        ok, base, full = _cost_ratio_within(
            tnr.prompt_embeds_rtl, quarter, text, factor=8.0, floor=0.10)
        assert ok, (
            f"prompt_embeds_rtl cost {full * 1000:.1f} ms on {len(text)} chars "
            f"against {base * 1000:.1f} ms on {len(quarter)} — {full / base:.1f}x "
            f"for a 4x input. Linear is ~4x and quadratic ~16x, so this is "
            f"backtracking, and the router accepts prompt text from its caller")


# ── 2. the plural blind spot in the debug hint ───────────────────────────────

def test_plural_bugs_is_a_debug_hint():
    """`\\bbug\\b` cannot match "bugs": the boundary after `bug` needs a
    non-word character and `s` is one. Authors who wrote the plural fell
    through to spec_generation."""
    hints = dict(tnr._PROSE_HINTS)
    assert hints["debug"].search("Fix any and all bugs in this code")
    assert hints["debug"].search("Identify and fix these RTL Bugs")
    assert hints["debug"].search("there is a bug here")


def test_debug_hint_still_ignores_prose_that_is_not_about_a_defect():
    """The widening is one character and must stay that narrow."""
    hints = dict(tnr._PROSE_HINTS)
    for benign in ("Build a debugger interface port",
                   "Build a circuit that sign-extends an 8-bit number",
                   "Implement a fixed-point multiplier"):
        assert not hints["debug"].search(benign), benign


# ── 3. the route the two defects together got wrong ──────────────────────────

def test_pasted_rtl_with_a_debug_verb_does_not_enter_at_phase_1():
    """THE MEASURED MISS. Both defects had to be fixed for this to route:
    the plural verb had to be seen, and the RTL had to be found in the prompt.
    Routing it to Phase 1 is the exact mistake the module docstring names."""
    v = tnr.classify_task_nature(DEBUG_EMBEDDED, False, None)
    assert v["nature"] == "debug", v
    assert v["route"] != "phase1_entry", v
    assert v["source"] == "embedded_rtl_prose_hint", v


def test_embedded_rtl_alone_never_invents_a_transform():
    """ANTI-OVERFIT. Embedded RTL is a PRECONDITION, not a nature. A prompt
    that quotes a working module and then asks for a NEW submodule from a
    description is generation, and 8 of the 94 embedding prompts measured have
    no transform verb at all. A fix that read the module as "transform this"
    would trade one wrong route for another."""
    v = tnr.classify_task_nature(REFERENCE_EMBEDDED, False, None)
    assert v["nature"] == "spec_generation", v
    assert v["route"] == "phase1_entry", v


# ── 4. the warning may not be false ──────────────────────────────────────────

def test_no_warning_that_the_rtl_is_absent_when_it_is_in_the_prompt():
    """85 of 664 carried this warning about a prompt containing the RTL, and
    the warning is what diverts a run onto a degraded fallback."""
    for text in (DEBUG_EMBEDDED, COMPLETE_EMBEDDED):
        v = tnr.classify_task_nature(text, False, None)
        assert "warning" not in v, v


def test_the_warning_survives_where_the_rtl_really_is_absent():
    """The other direction. Silencing the warning everywhere would be a
    regression of its own — when the RTL genuinely was not supplied, the
    named entry genuinely cannot read anything."""
    v = tnr.classify_task_nature(DEBUG_NO_RTL, False, None)
    assert v["source"] == "prose_hint_without_context", v
    assert "warning" in v and "no existing RTL was supplied" in v["warning"], v


def test_runtime_completion_words_do_not_become_code_completion():
    """Captured RTLLM route override: completing a two-sample concatenation
    and asking for complete code still describes generation from a spec."""
    prompt = """
Implement a data width conversion circuit that converts 8-bit input to 16-bit
output. Temporarily store the first valid byte; when the second arrives,
complete the concatenation and assert valid_out. Give me the complete code.
"""
    v = tnr.classify_task_nature(prompt, False, None)
    assert v["nature"] == "spec_generation", v
    assert v["route"] == "phase1_entry", v


def test_completion_without_an_artifact_falls_back_to_generation():
    """Completion transforms an artefact; a bare interface stub is not one."""
    prompt = "Complete the following module.\n\n" + _STUB
    v = tnr.classify_task_nature(prompt, False, None)
    assert v["nature"] == "spec_generation", v
    assert v["source"] == "completion_hint_without_artifact", v
    assert v["needs_ai_parse"] is True


@pytest.mark.parametrize("completion_phrase", [
    "Complete the given partial SystemVerilog code.",
    "Finish this provided incomplete Verilog module.",
    "Complete the following partial SV implementation.",
])
def test_completion_hint_accepts_bounded_code_modifiers(completion_phrase):
    """A code-completion request may qualify the supplied artefact before
    naming it.  Those modifiers must not erase the explicit completion verb."""
    prompt = completion_phrase + "\n\n" + _BODY
    v = tnr.classify_task_nature(prompt, False, None)
    assert v["nature"] == "completion", v
    assert v["route"] != "phase1_entry", v
    assert v["source"] == "embedded_rtl_prose_hint", v


def test_completion_of_structured_partial_module_uses_plugin_loop():
    """A completion artefact is often incomplete by definition and therefore
    has no endmodule yet. Internal declarations/assignments distinguish it from
    the interface-only stub appended to from-scratch benchmark prompts."""
    prompt = "Complete the given partial SystemVerilog code.\n\n" + _PARTIAL_BODY
    v = tnr.classify_task_nature(prompt, False, None)
    assert v["nature"] == "completion", v
    assert v["route"] == "plugin_loop", v
    assert v["source"] == "embedded_rtl_prose_hint", v
    assert v["needs_ai_parse"] is False, v


# ── 5. the flag must be capable of both values ───────────────────────────────

def _corpus():
    """Prompts spanning every branch, and both rtl_present states."""
    for text in (SPEC_ONLY, DEBUG_EMBEDDED, DEBUG_NO_RTL,
                 REFERENCE_EMBEDDED, COMPLETE_EMBEDDED):
        for has_context in (False, True):
            yield text, has_context


def test_needs_ai_parse_is_not_a_constant():
    """THE HEADLINE. True on 664 of 664 measured prompts. A field that cannot
    take its other value over its whole input domain is not a measurement of
    anything, and no consumer can make it one."""
    seen = {tnr.classify_task_nature(t, c, None)["needs_ai_parse"]
            for t, c in _corpus()}
    assert seen == {True, False}, (
        f"needs_ai_parse took only {seen} across every branch of the router — "
        f"it is a constant dressed as a measurement")


def test_needs_ai_parse_does_not_merely_restate_its_own_argument():
    """What it used to be: False exactly when the caller passed `nature`. If
    that is all it says, it is the caller's own input handed back."""
    undeclared = {tnr.classify_task_nature(t, c, None)["needs_ai_parse"]
                  for t, c in _corpus()}
    assert False in undeclared, (
        "every undeclared verdict still asks for an AI parse, so the flag is "
        "just `nature is None` under another name")


def test_confidence_tracks_what_the_router_actually_observed():
    """Not merely variable — variable FOR A REASON the program can state.
    False needs a positive signal for both halves: the RTL is present AND the
    prose names the transform. True whenever the verdict rests on an absence."""
    # both halves positive -> confident
    assert tnr.classify_task_nature(DEBUG_EMBEDDED, False, None)["needs_ai_parse"] is False
    assert tnr.classify_task_nature(DEBUG_NO_RTL, True, None)["needs_ai_parse"] is False
    # RTL present, but nothing says WHICH transform -> not confident
    assert tnr.classify_task_nature(SPEC_ONLY, True, None)["needs_ai_parse"] is True
    # a transform named, but the RTL it needs is absent -> not confident
    assert tnr.classify_task_nature(DEBUG_NO_RTL, False, None)["needs_ai_parse"] is True
    # no RTL and no verb: rests on the hint set having missed nothing, and the
    # one measured blind-reading disagreement landed exactly here
    assert tnr.classify_task_nature(SPEC_ONLY, False, None)["needs_ai_parse"] is True


def test_a_declared_nature_is_still_confirmed():
    v = tnr.classify_task_nature(SPEC_ONLY, False, "debug")
    assert v["source"] == "declared" and v["needs_ai_parse"] is False, v


# ── `smaller` HAD NO OBJECT, so it hinted on the WORD ────────────────────────
#
# MEASURED DEFECT (2026-08-28). Every other alternative in the `optimization`
# prose hint requires an object — `reduce area|cells|wires|power`,
# `fewer cells|wires` — and `smaller` stood bare, so it matched any prose in
# which one thing is described as smaller than another. That is not a rare
# shape in a specification: comparators, sign extension, pointer arithmetic and
# pulse-width prose all say it about the DESIGN'S DATA, never about the design.
#
# The consequence is a route, not a label. `optimization` resolves to
# `optimize_loop`, whose `deterministic_first` is `rtl_hygiene_lint.py` — a
# transform of EXISTING RTL — so a build-this-from-scratch task was pushed off
# `phase1_entry` onto an entry with nothing to transform, carrying the warning
# "prose reads as 'optimization' but no existing RTL was supplied".
#
# It fires on real published prompts. Over the 165 reachable on this host
# (VerilogEval-Human 156 + the 9 RTLLM design descriptions), the whole
# optimization hint fired on exactly ONE — `Prob042_vector4`, "sign-extending a
# smaller number to a larger one", a pure BUILD-THIS spec. One of one hints was
# false. After the repair the same sweep hits 0, which is the correct answer for
# a population that contains no optimization task.
_VE_HUMAN = corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023")

# Real spec-generation prose that merely uses the word. Each states the
# comparison about VALUES, which is what a specification does.
_MERE_PROSE = [
    "Design a 4-bit synchronous counter. Note that the reset pulse is smaller "
    "than one clock period; ignore glitches.",
    "Write a FIFO. The read pointer is smaller than the write pointer while "
    "data is queued.",
    "Create a comparator that asserts lt when a is smaller than b.",
    "Sign-extend a smaller number to a larger one by replicating the sign bit.",
    "The smaller of the two inputs is forwarded to the output.",
]

# Genuine requests to shrink the design, in both word orders. These must still
# be hinted: a check that refuses everything is not a check.
_GENUINE_OPTIMIZATION = [
    "Optimize this module to reduce area.",
    "Rewrite the design so it uses fewer cells.",
    "Make the netlist smaller in area without changing function.",
    "Please make this module smaller.",
    "Produce a smaller area implementation of the same function.",
    "Give me a smaller netlist.",
    "Make it lint clean.",
]


def test_prose_that_merely_says_smaller_is_not_an_optimization_request():
    for prompt in _MERE_PROSE:
        v = tnr.classify_task_nature(prompt, False, None)
        assert v["nature"] == "spec_generation", (
            f"a build-this specification was routed {v['nature']!r} via "
            f"{v['source']!r} because its prose contains the word 'smaller':\n"
            f"  {prompt}")


def test_a_genuine_request_to_shrink_the_design_is_still_hinted():
    """THE OTHER DIRECTION. Narrowing a hint is only correct if what the hint
    was FOR still reaches it — otherwise the repair is a deletion wearing a
    regex."""
    for prompt in _GENUINE_OPTIMIZATION:
        v = tnr.classify_task_nature(prompt, False, None)
        assert v["nature"] == "optimization", (
            f"a real optimization request stopped being hinted: {prompt!r} "
            f"-> {v['nature']!r} / {v['source']!r}")


def test_a_bare_pronoun_is_not_an_object():
    """The boundary, stated so it cannot drift back by accident.

    "Make it smaller" is NOT hinted, and that is deliberate rather than an
    oversight: `reduce` alone is not hinted either, for the same reason. The
    router has `needs_ai_parse` and the AI backup for prompts whose object is
    only recoverable from context — inventing one from a pronoun is the guess
    that produced the defect above."""
    v = tnr.classify_task_nature("Make it smaller.", False, None)
    assert v["nature"] == "spec_generation", v


def test_the_real_corpus_prompt_that_was_misrouted():
    """`Prob042_vector4`, verbatim from the published dataset.

    Skipped rather than asserted-over-nothing when the corpus is absent: a
    green from a file that was never opened is the vacuous pass this repo
    refuses everywhere else."""
    p = _VE_HUMAN / "Prob042_vector4_prompt.txt"
    if not p.is_file():
        pytest.skip("VerilogEval-Human dataset absent; set $VIBEIC_CORPUS_ROOT "
                    "to the external benchmark corpus root")
    prompt = p.read_text(errors="replace")
    assert "smaller" in prompt, (
        "the fixture no longer contains the word this test is about — it is "
        "the wrong prompt, not a passing one")
    v = tnr.classify_task_nature(prompt, False, None)
    assert v["nature"] == "spec_generation", (
        f"Prob042_vector4 is a build-this spec and was routed {v['nature']!r} "
        f"via {v['source']!r}")


# ─────────────────────────────────────────────────────────────────────────────
# a module QUOTED INSIDE A COMMENT is a description of RTL, not RTL
# ─────────────────────────────────────────────────────────────────────────────
#
# `_MODULE_HEAD` is `^[ \t]*module\b[^;]{0,4000};`. A `//` prefix breaks the
# anchor; a `/* ... */` block does not, because a line inside one starts at
# column 0 like any other. So a prompt that quotes an old interface to say "do
# not reuse this" reads as a prompt that CARRIES a module -- and
# `prompt_embeds_rtl` is the positive half of the router's `needs_ai_parse`
# condition and the disarm for the "no existing RTL was supplied" warning.
# A prompt with no RTL in it then routes as though it had some.
#
# Paired throughout: every commented case has the same text uncommented, which
# must still read as embedded.

_QUOTED_IN_A_BLOCK_COMMENT = """Design a 4-bit counter with synchronous reset.

For reference only, the interface we are REPLACING looked like this:
/*
module old_counter (input clk, input rst, output [3:0] q);
  always @(posedge clk) q <= q + 1;
endmodule
*/

Do not reuse it. Write the new module from the description above.
"""


def test_a_module_quoted_inside_a_block_comment_is_not_embedded_rtl():
    assert tnr.prompt_embeds_rtl(_QUOTED_IN_A_BLOCK_COMMENT) is False, (
        "a module body inside /* */ was read as RTL the prompt carries")


def test_control_the_same_module_uncommented_IS_embedded_rtl():
    """The pair. Without it, `return False` satisfies the case above."""
    live = _QUOTED_IN_A_BLOCK_COMMENT.replace("/*\n", "").replace("*/\n", "")
    assert tnr.prompt_embeds_rtl(live) is True, (
        "a real embedded module stopped being found -- the strip has blinded "
        "the reader rather than sharpened it")


def test_a_line_comment_above_a_real_module_does_not_lose_it():
    """Stripping `//` must not reach past the line it is on."""
    assert tnr.prompt_embeds_rtl(
        "// the module below is the one to fix\n"
        "module m (input a, output y);\n  assign y = a;\nendmodule\n") is True


def test_the_warning_the_verdict_drives_follows_the_corrected_reading():
    """Not a property of the helper in isolation: the routed verdict moves.

    A commented quotation must leave the router saying the RTL is absent; the
    same text uncommented must not."""
    quoted = tnr.classify_task_nature(
        "Fix any and all bugs in this code.\n" + _QUOTED_IN_A_BLOCK_COMMENT,
        False, None)
    live = tnr.classify_task_nature(
        "Fix any and all bugs in this code.\n"
        + _QUOTED_IN_A_BLOCK_COMMENT.replace("/*\n", "").replace("*/\n", ""),
        False, None)
    assert quoted["needs_ai_parse"] is True, quoted
    assert live["needs_ai_parse"] is False, live


# ── the corpus control, at scale ────────────────────────────────────────────
#
# The risk this fix carries is not that it fails to strip -- it is that
# stripping goes blind to RTL a prompt really does carry. Measured over the
# real prompts on the author's machine (302 CVDP + 156 VerilogEval-Human) the
# verdict is IDENTICAL for every one: 86 and 4 embed, before and after. This
# pins that sweep wherever the corpus is mounted, and skips with an actionable
# reason where it is not, rather than passing over a file nobody opened.

def _sweep_prompts():
    """(id, text) for every real prompt this machine can supply."""
    import json
    rows = []
    ve = corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023")
    if ve.is_dir():
        for f in sorted(ve.glob("*_prompt.txt")):
            rows.append((f.name, f.read_text(errors="replace")))
    for cand in (corpus_path("cvdp_dataset.jsonl"),
                 corpus_path("_extbench/cvdp/cvdp_dataset.jsonl")):
        if not cand.is_file():
            continue
        with cand.open(errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                v = d.get("input") or d.get("prompt")
                if isinstance(v, dict):
                    v = v.get("prompt") or v.get("question")
                if isinstance(v, str) and v.strip():
                    rows.append((str(d.get("id", "?")), v))
        break
    return rows


def test_stripping_changes_no_verdict_on_the_real_prompt_corpus():
    rows = _sweep_prompts()
    if len(rows) < 50:
        pytest.skip("real prompt corpus absent; set $VIBEIC_CORPUS_ROOT to the "
                    "external benchmark corpus root")
    head = tnr._MODULE_HEAD
    end = tnr._ENDMODULE

    def raw_reading(t):
        h = head.search(t)
        return h is not None and end.search(t, h.end()) is not None

    embeds = [pid for pid, t in rows if tnr.prompt_embeds_rtl(t)]
    assert embeds, (
        f"{len(rows)} prompts and not one reads as embedding RTL -- the "
        f"corpus is the wrong shape, so a green here would be vacuous")
    lost = [pid for pid, t in rows
            if raw_reading(t) and not tnr.prompt_embeds_rtl(t)]
    assert lost == [], (
        f"{len(lost)} of {len(rows)} real prompts stopped reading as embedded "
        f"once comments were stripped: {lost[:10]}")
