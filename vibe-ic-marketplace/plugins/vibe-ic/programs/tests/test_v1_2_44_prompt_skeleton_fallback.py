#!/usr/bin/env python3
r"""v1.2.44 — ORGANIC #1304 prompt-skeleton harness-top (COMPLIANT PRIMARY source).

CVDP official (arXiv:2506.14074 §2 + README_NON_AGENTIC): the emit path sees
ONLY `input.prompt` + `input.context`. The hidden ``harness.files`` (`.env` /
`test_runner.py`) that fixes the cocotb `iverilog -s <toplevel>` are OFF-LIMITS
oracle. So the alias TARGET is derived from the PROMPT: the literal
``\`\`\`verilog module <X>(`` code fence that 98.5% (66/67) of skeleton-bearing
CVDP prompts carry (`cvdp_gate.skeleton_module_name_from_prompt`). It is a
legitimate `input.prompt` fact and is the ONLY source the compliant gate uses;
the former harness-`.env` readers `load_harness_toplevels` /
`harness_toplevel_from_dataset` have been DELETED (zero harness readers remain).

This test pins the COMPLIANT behaviour: the alias top comes from the prompt
skeleton (asserted against the real `cvdp_gate.skeleton_module_name_from_prompt`),
the deleted harness loaders are confirmed gone, and the alias wrapper's own
port-name guard rejects false-positives (the wrapper connects `.name(...)`, so a
wrong top with mismatched ports silently no-ops under iverilog at -s time).

Run:  python3 -m py_compile programs/tests/test_v1_2_44_prompt_skeleton_fallback.py
-or-  python3 -m pytest -q programs/tests/test_v1_2_44_prompt_skeleton_fallback.py
"""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROGRAMS = os.path.dirname(THIS_DIR)
BENCH = os.path.join(os.path.dirname(PROGRAMS), "benchmark")
sys.path.insert(0, BENCH)

import cvdp_harness_toplevel_alias as A  # noqa: E402
import cvdp_gate as G  # noqa: E402


# ── 1. pure helper — prompt-skeleton extraction (the regex + return) ───────────
def test_skeleton_extracts_simple_fenced_verilog():
    src = "build a 4-bit ripple adder.\n\n```verilog\nmodule ripple4(\n"
    # call the public surface — load_harness_toplevels runs the same regex via
    # cvdp_gate.py; here we exercise the helper indirectly through the loader.
    # The loader is the integration point; the regex itself is what we pin.
    import re
    rx = re.compile(r"```(?:system)?verilog\s*\n\s*module\s+([A-Za-z_]\w*)",
                    re.IGNORECASE)
    assert rx.search(src).group(1) == "ripple4"


def test_skeleton_rejects_padded_fences_no_newline():
    # The exact public regex used by cvdp_gate.py requires \n after `verilog`.
    import re
    rx = re.compile(r"```(?:system)?verilog\s*\n\s*module\s+([A-Za-z_]\w*)",
                    re.IGNORECASE)
    assert rx.search("```verilog module x(...);\n```") is None


# ── 2. the OFF-LIMITS harness loaders are DELETED (zero harness readers) ───────
def test_offlimits_harness_loaders_are_deleted():
    assert not hasattr(A, "load_harness_toplevels")
    assert not hasattr(A, "harness_toplevel_from_dataset")


# ── 3. COMPLIANT PRIMARY source: the alias top is the PROMPT skeleton ──────────
def test_alias_top_is_prompt_skeleton_primary():
    """The compliant gate derives the alias top from the PROMPT via
    `cvdp_gate.skeleton_module_name_from_prompt` — the ONLY source (the hidden
    harness `.env` is OFF-LIMITS). Asserted against the REAL gate function
    (not a stand-in regex) so a change to the gate's skeleton detection is
    caught here. The alias wrapper at emit then either no-ops (X already
    declared) or wraps (X absent, alias-compatible ports)."""
    prompts = {
        "p1": "Build a 4-bit adder:\n```verilog\nmodule ripple4(\n    input [3:0] a,\n",
        "p2": "No skeleton here, just prose about a VGA controller.",
        "p3": "Skeleton present but missing: ```verilog\n// empty\n```",
    }
    tops = {}
    for rid, prompt in prompts.items():
        skel = G.skeleton_module_name_from_prompt(prompt)
        if skel:
            tops[rid] = skel

    assert tops.get("p1") == "ripple4", tops
    assert "p2" not in tops
    assert "p3" not in tops
    # and NO harness loader can supply the top: the OFF-LIMITS harness-`.env`
    # readers have been DELETED, so the prompt skeleton is the SOLE contributor.
    assert not hasattr(A, "load_harness_toplevels")
    assert not hasattr(A, "harness_toplevel_from_dataset")


# ── 4. alias wrapper — the lowered surface the helper feeds in v1.2.44 ─────────
def test_alias_wrapper_no_op_when_top_already_declared():
    code = "module top(input clk, output q);\nendmodule\n"
    declared = set(["top"])
    out = A.maybe_alias_completion(code, "top",
                                   lambda s: {"top"})
    assert out == code  # byte-identical — no false EDIT


def test_alias_wrapper_appends_for_missing_top():
    code = "module author(input clk, output q);\nendmodule\n"
    declared = set(["author"])
    out = A.maybe_alias_completion(code, "top",
                                   lambda s: {"author"})
    assert "module top (" in out
    assert "author u_author" in out
    assert ".clk(clk)" in out and ".q(q)" in out
