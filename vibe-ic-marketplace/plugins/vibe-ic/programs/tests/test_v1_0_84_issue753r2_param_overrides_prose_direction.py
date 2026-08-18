"""ORGANIC #753 round-2 (field-agent reopen of v1.0.83).

The v1.0.83 #753 fix correctly excluded given-code internal names from
MISSING-PORT, with a §4.05 guard added in adversarial review: a name the prompt
PROSE declares with an EXPLICIT DIRECTION is NOT masked (so a real required port
the prompt declares `an input data_valid` stays flagged even if a helper block
also names it). That direction-aware guard OVER-corrected for one shape: a
skeleton-declared `parameter` with a SPURIOUS prose-direction attribution.

Reopen repro (Synchronous_Muller_C_Element_0001), VERBATIM shapes:
  RTL  : `module ... #(parameter PIPE_DEPTH = 1)(...)`
  spec : skeleton `parameter PIPE_DEPTH = 1` + prose
         "The pipeline takes `PIPE_DEPTH` cycles to propagate input signals to
          the final stage."
`_DIR_NEAR_AFTER_RE` read the trailing "...input signals" as tagging PIPE_DEPTH
an `input` port, so the direction-aware never-mask guard SKIPPED masking and the
parameter was emitted as a phantom MISSING-PORT (rc=1, false BLOCK).

Round-2 fix: a `parameter` is AUTHORITATIVELY never a port, so a skeleton-
declared parameter OVERRIDES even a spurious prose direction (unlike an internal
NET, which a real port could coincidentally share a name with).

§4.05 no-leak (both must still hold):
  - a real spec PORT the RTL omits is STILL flagged MISSING-PORT;
  - the v1.0.83 adversarial-review case (a helper-block internal `reg` must NOT
    mask a prose-DIRECTIONAL real required port) is preserved — a NET, unlike a
    parameter, still respects the direction-aware guard.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import iface_conformance_v2 as I  # noqa: E402

_PROG = _PROGRAMS / "iface_conformance_v2.py"

# the reopen shape, with the discriminating prose line quoted VERBATIM.
_MULLER_PROMPT = (
    "Design a synchronous Muller C-element.\n\n"
    "```\n"
    "module sync_muller_c_element #(parameter PIPE_DEPTH = 1)"
    "(input a, input b, output reg q);\n"
    "endmodule\n"
    "```\n\n"
    "The pipeline takes `PIPE_DEPTH` cycles to propagate input signals to the "
    "final stage.\n")
_MULLER_RTL = ("module sync_muller_c_element #(parameter PIPE_DEPTH = 1)"
               "(input a, input b, output reg q);\nendmodule\n")


def test_753r2_skeleton_parameter_with_prose_direction_not_flagged():
    """REOPEN repro: a skeleton-declared `parameter PIPE_DEPTH` carrying a
    spurious prose direction must NOT be charged as MISSING-PORT."""
    findings = I.check_conformance("cvdp_x", _MULLER_PROMPT, _MULLER_RTL)
    assert not any("PIPE_DEPTH" in getattr(f, "message", str(f))
                   for f in findings), [getattr(f, "message", str(f))
                                        for f in findings]


def test_753r2_given_code_param_names_collects_pipe_depth():
    assert "pipe_depth" in I.given_code_param_names(_MULLER_PROMPT)


def test_753r2_endstate_via_program(tmp_path):
    """#478 end-state via the real program on a tmp_path defect artifact: the
    Muller spec/RTL pair gives rc 0 (no PIPE_DEPTH MISSING-PORT) under --strict."""
    (tmp_path / "spec.md").write_text(_MULLER_PROMPT)
    (tmp_path / "muller.sv").write_text(_MULLER_RTL)
    cp = subprocess.run(
        [sys.executable, str(_PROG), "--id", "cvdp_copilot_muller_0001",
         "--prompt", str(tmp_path / "spec.md"),
         "--rtl", str(tmp_path / "muller.sv"), "--strict"],
        capture_output=True, text=True)
    assert cp.returncode == 0, (cp.returncode, cp.stdout, cp.stderr)
    assert "PIPE_DEPTH" not in cp.stdout


# ── §4.05 no-leak: a real port the RTL omits is STILL flagged ────────────────
def test_753r2_noleak_real_missing_port_still_flagged():
    prompt = "The module foo has an input `data_valid`.\n"
    rtl = "module foo(input clk, output q); endmodule"
    findings = I.check_conformance("cvdp_x", prompt, rtl)
    assert any("data_valid" in getattr(f, "message", str(f))
               and "MISSING-PORT" in getattr(f, "kind", "")
               for f in findings)


# ── §4.05 no-leak: the v1.0.83 remediation preserved — a helper-block internal
#    NET (not a parameter) must NOT mask a prose-DIRECTIONAL real required port ─
def test_753r2_noleak_helper_net_does_not_mask_directional_port():
    prompt = ("The module foo has an input `data_valid`.\n\n"
              "```\nmodule helper(input clk); reg data_valid; endmodule\n```\n")
    rtl = "module foo(input clk, output q); endmodule"
    findings = I.check_conformance("cvdp_x", prompt, rtl)
    assert any("data_valid" in getattr(f, "message", str(f))
               and "MISSING-PORT" in getattr(f, "kind", "")
               for f in findings)


# ── §4.05 (self-review): a parameter scraped from a WIDTH expression (`input
#    [W-1:0] din`) must not false-fire as a phantom MISSING-PORT, and must not
#    evict the genuine `parameter W` from the param-mask set ────────────────────
def test_753r2_width_expr_param_not_phantom_port():
    import re
    prompt = ("```\nmodule foo #(parameter W=8)(input [W-1:0] din, output q);\n"
              "endmodule\n```\nThe module has an input `din`.\n")
    rtl = "module foo(input clk, output q); endmodule"   # omits din
    findings = I.check_conformance("cvdp_x", prompt, rtl)
    # W (a parameter used in the width expr) must NOT be a phantom port…
    assert not any(re.search(r"signal 'W'", getattr(f, "message", str(f)))
                   for f in findings)
    # …but the real omitted port `din` is STILL flagged (no-leak preserved).
    assert any(re.search(r"signal 'din'", getattr(f, "message", str(f)))
               for f in findings)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
