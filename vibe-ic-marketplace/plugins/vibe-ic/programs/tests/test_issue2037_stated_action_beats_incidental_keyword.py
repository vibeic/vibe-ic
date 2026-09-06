#!/usr/bin/env python3
"""Issue #2037 — first-match routing let an incidental word beat the stated action.

`task_nature_route` picked the first `_PROSE_HINTS` tuple that matched anywhere
in the prompt, and `debug` is declared first. The measured consequence, on a
neutral prompt:

    Complete the given partial SystemVerilog code for the register interface.
    When the stored key format is incorrect, the error output must be high.

routed to `debug` (`source=embedded_rtl_prose_hint`, `needs_ai_parse=false`) on
the word `incorrect` — which is not a description of the task. It is part of the
SPECIFICATION OF THE DESIRED ERROR BEHAVIOUR. Both hints matched; declaration
order decided, and declaration order knows nothing about what is being asked.

THE CONTROL THAT MATTERS MOST IS THE OTHER DIRECTION. A fix that just demotes
`debug` moves the bias instead of removing it, so `TestGenuineDebugStillRoutesToDebug`
is written first and is the larger half of this file: a prompt that really is
asking to fix an incorrect implementation must still classify as `debug`.
"""
import importlib
import sys

import pytest

mod = importlib.import_module("task_nature_route")


def _hint(text):
    return mod.resolve_prose_hint(text)[0]


def _classify(text):
    """The real public entry — not a hasattr-guarded maybe."""
    return mod.classify_task_nature(text, has_context=False)


# ---------------------------------------------------------------------------
# The control, first: a genuine debug request must still be debug.
# ---------------------------------------------------------------------------
class TestGenuineDebugStillRoutesToDebug:
    @pytest.mark.parametrize("prompt", [
        "The counter module below has an incorrect implementation. "
        "Fix the counter so that it counts up.",
        "Identify and fix these RTL bugs in the module below.",
        "Fix any and all bugs in this code.",
        "This module fails the regression suite. Debug it and correct the "
        "incorrect output.",
        "The design doesn't work on hardware. Find the bug.",
        "Identify and correct the bugs in the following implementation.",
        "There is a buggy always block in this design; repair it.",
    ])
    def test_debug_prompt_is_debug(self, prompt):
        assert _hint(prompt) == "debug", prompt
        # and end-to-end, with the RTL embedded so the route is not degraded
        full = prompt + "\n\n```verilog\nmodule m(); endmodule\n```"
        assert _classify(full)["nature"] == "debug", full

    def test_debug_survives_a_completion_word_in_a_requirement_clause(self):
        """The mirror image of the reported defect — the fix must not create it.

        The stated action is a fix; `complete the code` appears only inside a
        clause about what the finished design must do.
        """
        prompt = ("Fix the incorrect parity logic in the module below. "
                  "The design must complete the transfer within two cycles.")
        assert _hint(prompt) == "debug"


# ---------------------------------------------------------------------------
# The reported defect.
# ---------------------------------------------------------------------------
ISSUE_PROMPT = """Complete the given partial SystemVerilog code for the register interface.
When the stored key format is incorrect, the error output must be high.
The key is valid when its low two bits are zero.

```systemverilog
module register_interface(input logic [7:0] key, output logic error);
// Insert the missing key-format validation logic here.
endmodule
```
"""


class TestStatedActionWins:
    def test_issue_prompt_is_completion_not_debug(self):
        assert _hint(ISSUE_PROMPT) == "completion"

    def test_issue_prompt_routes_to_completion_end_to_end(self):
        r = _classify(ISSUE_PROMPT)
        assert r["nature"] == "completion", r
        assert r["entry_nature"] == "completion", r
        assert r["source"] == "embedded_rtl_prose_hint", r
        assert r["needs_ai_parse"] is False, r
        assert r["plugin_entry"]["name"] != "debug_loop", r

    def test_a_keyword_only_in_a_when_clause_does_not_decide(self):
        prompt = ("Complete the given partial Verilog code. "
                  "When the input is incorrect the output is zero.")
        assert _hint(prompt) == "completion"

    def test_a_keyword_only_in_a_must_sentence_does_not_decide(self):
        prompt = ("Fill in the missing logic. "
                  "The error flag must assert on an incorrect checksum.")
        assert _hint(prompt) == "completion"

    def test_narration_still_beats_a_requirement_clause(self):
        """Ordinary narration is weaker than a stated action but stronger than
        a behaviour requirement."""
        prompt = ("The following module has a bug. "
                  "Complete the transfer when the request is high.")
        # `complete the transfer` is not a completion hint at all (no code
        # object), so debug is the only candidate and stays.
        assert _hint(prompt) == "debug"


class TestUnchangedForSingleHintPrompts:
    """A prompt with ONE matching hint must route exactly as before — this fix
    is a tie-break, not a reclassification."""

    @pytest.mark.parametrize("prompt,expected", [
        ("Design a 4-bit synchronous up counter with active-low reset.", None),
        ("Optimize the design to reduce the cell count.", "optimization"),
        ("Complete the given partial Verilog code below.", "completion"),
        ("Modify the FSM to add support for a new state.",
         "functional_modification"),
        ("Fix the bugs in the arbiter.", "debug"),
    ])
    def test_single_hint_unchanged(self, prompt, expected):
        assert _hint(prompt) == expected


class TestAmbiguityIsSurfacedNotGuessed:
    def test_two_stated_actions_raise_needs_ai_parse(self):
        prompt = ("Fix the bugs in the module below. "
                  "Complete the missing code as well.\n\n"
                  "```verilog\nmodule m(); endmodule\n```")
        name, ambiguous = mod.resolve_prose_hint(prompt)
        assert ambiguous is True
        assert name in ("debug", "completion")

    def test_a_single_stated_action_is_not_ambiguous(self):
        _name, ambiguous = mod.resolve_prose_hint(
            "Complete the given partial Verilog code below.")
        assert ambiguous is False


class TestNoBenchmarkSpecificRouting:
    """No design identifier, prompt hash or benchmark name may appear in the
    precedence machinery."""

    def test_scoring_helpers_carry_no_identifiers(self):
        import inspect
        src = "".join(
            inspect.getsource(f) for f in
            (mod._prose_view, mod._clause_spans, mod._hint_action_scores,
             mod.resolve_prose_hint))
        for banned in ("cvdp", "verilogeval", "rtllm", "sha256", "md5",
                       "hashlib", "Prob0", "register_interface"):
            assert banned.lower() not in src.lower(), banned
