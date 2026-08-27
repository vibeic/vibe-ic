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

_PROGRAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, _PROGRAMS)

import task_nature_route as tnr  # noqa: E402


_BODY = """  module widget (
      input  a,
      input  b,
      output c
  );
      assign c = a & b;
  endmodule
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


def test_the_detector_cannot_be_made_to_hang_on_a_hostile_prompt():
    """LINEARITY, pinned by a budget with 300x headroom rather than a stopwatch.

    The obvious spelling of this detector is ONE regex spanning header through
    `endmodule`, and it backtracks quadratically: every `module` in the text
    rescans to the end for an `endmodule` that is not there. Measured on that
    form, 664 real prompts cost 15 ms in total but a single 1.25 MB input with
    3000 module headers and no `endmodule` cost 12.7 SECONDS. `classify_task_nature`
    takes a prompt string from whoever is calling it, so that is a hang in the
    front door.

    The split form answers the same question with two linear searches and does
    the same input in ~5 ms. The 2-second budget below is ~370x the linear cost
    and ~1/6 of the quadratic one, so it is decided by the SHAPE of the code and
    not by how loaded the machine is."""
    import time
    hostile = "\n".join("module m%d (a);" % i + " x" * 200 for i in range(3000))
    assert len(hostile) > 1_000_000

    for text in (hostile,                       # no endmodule at all
                 "endmodule\n" + hostile,       # endmodule before every header
                 "module x (a" + "y" * 200_000):  # a header with no semicolon
        start = time.perf_counter()
        assert tnr.prompt_embeds_rtl(text) is False
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, (
            f"prompt_embeds_rtl took {elapsed:.1f}s on a {len(text)} char "
            f"prompt — it is backtracking, and the router accepts prompt text "
            f"from its caller")


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
