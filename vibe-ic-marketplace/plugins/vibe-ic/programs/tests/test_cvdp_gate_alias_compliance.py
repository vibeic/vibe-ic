#!/usr/bin/env python3
r"""test_cvdp_gate_alias_compliance.py — the CVDP alias-emit compliance guard.

Per the CVDP official rule (arXiv:2506.14074 §2 + README_NON_AGENTIC) the model /
emit path sees ONLY `input.prompt` + `input.context`. The ENTIRE hidden harness
(cocotb `dut.<sig>` test, `.env` TOPLEVEL / VERILOG_SOURCES, `harness_library.py`)
AND `output.*` (golden / reference RTL) are OFF-LIMITS oracle.

`cvdp_gate.py`'s harness-TOPLEVEL alias repair (`maybe_alias_completion` /
`maybe_align_tb_ports`) synthesizes a thin pass-through wrapper so the official
scorer's `iverilog -s <top>` finds its top when a blind author declared the right
interface under a different module name. The COMPLIANT design is that the `<top>`
the wrapper targets comes from the PROMPT skeleton
(`skeleton_module_name_from_prompt(prompt)`) — a legitimate `input.prompt` fact —
NOT from the hidden harness `.env`. The former harness-`.env` readers
(`harness_toplevel_from_dataset` / `load_harness_toplevels`) have been DELETED,
so the alias module now carries ZERO harness `.env` / cocotb readers and there is
nothing left to mis-wire into the emit path.

This guard LOCKS that in with two independent proofs:

  (1) DECOY behavioural invariant — a record whose PROMPT states module `foo` but
      whose hidden `.env` says `toplevel = DECOY_HARNESS_NAME` (a DIFFERENT name)
      and whose golden `output.*` is a DECOY. Driving the SAME functions `main()`
      uses (`skeleton_module_name_from_prompt` + `maybe_rename_top` +
      `maybe_align_tb_ports` + `maybe_alias_completion`, fed EXACTLY as `main()`
      feeds them — prompt-derived top, EMPTY tb-port set) must emit a completion
      that uses the PROMPT name `foo` (or no-ops) and NEVER `DECOY_HARNESS_NAME`.
      Stripping / altering `harness` + `output` must not change the emitted
      completion at all (the definitive prompt+context-only proof).

  (2) STRUCTURAL guard — AST-parsing `cvdp_gate.py` proves the LIVE flow contains
      no CALL to `harness_toplevel_from_dataset(` / `load_harness_toplevels(`
      (they may appear only in comments). This fails LOUDLY the moment someone
      re-wires the hidden `.env` read back into the scored-completion path.

Run:  python3 -m pytest programs/tests/test_cvdp_gate_alias_compliance.py -q
"""
from __future__ import annotations

import ast
import copy
import os
import subprocess
import sys
import tempfile

# cvdp_gate.py + cvdp_harness_toplevel_alias.py live in the plugin's benchmark/
# dir (../../benchmark relative to programs/tests/) — mirror the existing
# cvdp_gate-test import convention.
BENCH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "benchmark")
if BENCH not in sys.path:
    sys.path.insert(0, BENCH)

import cvdp_gate as G                      # noqa: E402
import cvdp_harness_toplevel_alias as A    # noqa: E402


# --------------------------------------------------------------------------- #
# DECOY fixture — the hidden harness `.env` TOPLEVEL and the golden `output.*`
# DISAGREE with the prompt. A compliant emit targets the PROMPT name `foo`, never
# the decoy `.env` `DECOY_HARNESS_NAME`.
# --------------------------------------------------------------------------- #
_PROMPT = (
    "Implement a single-bit register.\n\n"
    "```verilog\n"
    "module foo(\n"
    "    input  wire clk,\n"
    "    input  wire d,\n"
    "    output reg  q\n"
    ");\n"
    "endmodule\n"
    "```\n"
)

# The blind author implemented the CORRECT interface but declared it under a
# DIFFERENT module name (`foo_impl`), so the scorer's `iverilog -s foo` would
# ELAB_ERROR without the alias.
_COMPLETION = (
    "module foo_impl (\n"
    "    input  wire clk,\n"
    "    input  wire d,\n"
    "    output reg  q\n"
    ");\n"
    "  always @(posedge clk) q <= d;\n"
    "endmodule\n"
)

_DECOY_RECORD = {
    "id": "decoy_reg",
    "prompt": _PROMPT,
    "input": {"prompt": _PROMPT, "context": {}},
    "completion": _COMPLETION,
    # output.context (golden) — a DECOY the emit path must never read.
    "output": {"response": "GOLDEN — MUST NOT BE READ",
               "context": {"rtl/foo.sv":
                           "module DECOY_GOLDEN(input x, output y);"
                           " assign y=x; endmodule"}},
    # harness .env + cocotb — DECOY names that disagree with the prompt.
    "harness": {"files": {
        "src/.env": "TOPLEVEL = DECOY_HARNESS_NAME\nMODULE = test_decoy\n",
        "src/test_decoy.py":
            "async def t(dut):\n"
            "    dut.DECOY_IN.value = 0\n"
            "    _ = int(dut.DECOY_OUT.value)\n",
    }},
}


def _strip_oracle(rec: dict) -> dict:
    r = copy.deepcopy(rec)
    r.pop("harness", None)
    r.pop("output", None)
    return r


def _emit_alias(rec: dict) -> str:
    """Mirror the SUBSET of `cvdp_gate.main()` that decides the aliased
    completion, fed EXACTLY as `main()` feeds it (cvdp_gate.py lines ~2895-2986
    + 3337): the harness-top comes from the PROMPT skeleton, the tb-port set is
    EMPTY — both per the CVDP-compliance comments in `main()`. This is the
    load-bearing emit path; if it reads the oracle, this helper's output will
    change when the oracle is stripped."""
    prompt = (rec.get("input") or {}).get("prompt") or rec.get("prompt", "")
    completion = rec.get("completion", "")
    # main(): harness_tops[_rid] = skeleton_module_name_from_prompt(prompt)
    harness_top = G.skeleton_module_name_from_prompt(prompt)
    # main(): harness_tb_ports stays EMPTY (compliance) → the align below is a
    # strict no-op; we keep the branch so the mirror is faithful.
    harness_tb_ports: set = set()
    # 1) module-name → prompt-top rename (main() line ~2968)
    comp = G.maybe_rename_top(completion, harness_top, G.completion_module_names)
    # 2) TB-bound port alignment — EMPTY tb ports → unconditional no-op (line ~2982)
    if harness_top and harness_tb_ports:
        comp, _ = G.maybe_align_tb_ports(comp, harness_top, harness_tb_ports)
    # 3) wrapper alias — the final emit step (main() line ~3337)
    comp = A.maybe_alias_completion(comp, harness_top, G.completion_module_names)
    return comp


# --------------------------------------------------------------------------- #
# (0) The decoy is genuinely a decoy: its hidden `.env` names a DIFFERENT top
#     than the PROMPT skeleton, so the invariance proof below is non-vacuous.
#     The former OFF-LIMITS `.env` reader has been DELETED, so this is proven
#     DIRECTLY from the fixture (never via a harness reader) — and we assert the
#     readers are truly gone.
# --------------------------------------------------------------------------- #
def test_prompt_and_offlimits_env_disagree():
    prompt_top = G.skeleton_module_name_from_prompt(_PROMPT)
    assert prompt_top == "foo", f"prompt skeleton top must be 'foo', got {prompt_top!r}"
    # the decoy harness `.env` literally names a DIFFERENT top ('DECOY_HARNESS_NAME')
    # so the invariance proof below is non-vacuous — read straight from the fixture
    # string, NOT through any harness reader (those are deleted).
    env_blob = _DECOY_RECORD["harness"]["files"]["src/.env"]
    assert "DECOY_HARNESS_NAME" in env_blob and prompt_top not in env_blob, env_blob
    # the OFF-LIMITS harness-`.env` readers have been DELETED — nothing to mis-wire.
    assert not hasattr(A, "harness_toplevel_from_dataset")
    assert not hasattr(A, "load_harness_toplevels")


# --------------------------------------------------------------------------- #
# (1a) The full emit path targets the PROMPT name and NEVER the decoy harness
#      name — and is byte-for-byte INVARIANT to the presence of harness+output.
# --------------------------------------------------------------------------- #
def test_emit_uses_prompt_name_not_decoy():
    emitted = _emit_alias(_DECOY_RECORD)
    assert "DECOY_HARNESS_NAME" not in emitted, (
        "the emitted (scored) completion referenced the hidden harness .env "
        "TOPLEVEL — a live OFF-LIMITS leak:\n" + emitted)
    assert "DECOY_GOLDEN" not in emitted, "emitted completion referenced golden output.*"
    # the prompt name IS the alias target (renamed sole module, since `foo` was
    # absent and there is one unambiguous top)
    assert "module foo" in emitted, emitted
    assert "foo" in G.completion_module_names(emitted)


def test_emit_invariant_to_oracle():
    """Stripping/altering `harness` + `output` must not change the emitted
    completion — the definitive prompt+context-only proof for the gate's alias
    path."""
    with_oracle = _emit_alias(_DECOY_RECORD)
    without = _emit_alias(_strip_oracle(_DECOY_RECORD))
    assert with_oracle == without, (
        "the alias emit is NOT invariant to harness/output presence — it is "
        "reading the oracle.")
    # and altering the decoy `.env` to a THIRD name still changes nothing
    mutated = copy.deepcopy(_DECOY_RECORD)
    mutated["harness"]["files"]["src/.env"] = "TOPLEVEL = ANOTHER_DECOY\n"
    assert _emit_alias(mutated) == with_oracle


# --------------------------------------------------------------------------- #
# (1b) Pass-through-wrapper correctness — fed the PROMPT name directly (the
#      contract the alias must keep: a correctly-interfaced author under a
#      prompt-name mismatch gets a valid wrapper). Independent of the oracle.
# --------------------------------------------------------------------------- #
def _has_iverilog() -> bool:
    try:
        subprocess.run(["iverilog", "-V"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def test_wrapper_correctness_from_prompt_name():
    prompt_top = G.skeleton_module_name_from_prompt(_PROMPT)  # 'foo'
    # feed a completion whose sole ANSI module is named DIFFERENTLY so the
    # wrapper actually fires (no rename step here — direct wrapper exercise).
    out = A.maybe_alias_completion(_COMPLETION, prompt_top, G.completion_module_names)
    assert out != _COMPLETION, "expected a wrapper to be appended"
    assert "module foo (" in out
    assert "foo_impl u_foo_impl" in out
    assert ".clk(clk)" in out and ".d(d)" in out and ".q(q)" in out
    assert "DECOY" not in out
    if _has_iverilog():
        with tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False) as f:
            f.write(out)
            path = f.name
        try:
            r = subprocess.run(
                ["iverilog", "-g2012", "-s", "foo", "-o", os.devnull, path],
                capture_output=True, text=True)
            assert r.returncode == 0, f"wrapper failed to compile: {r.stderr}"
        finally:
            os.unlink(path)


# --------------------------------------------------------------------------- #
# (2) STRUCTURAL guard — the live cvdp_gate.py flow calls NEITHER OFF-LIMITS
#     harness-.env reader. AST-based so comments/strings mentioning the names
#     are ignored; only a real Call trips it.
# --------------------------------------------------------------------------- #
_FORBIDDEN_READERS = frozenset({
    "harness_toplevel_from_dataset",
    "load_harness_toplevels",
})


def _called_names(src: str) -> set:
    calls = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                calls.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                calls.add(fn.attr)
    return calls


def test_gate_flow_does_not_call_offlimits_harness_readers():
    with open(G.__file__, "r", encoding="utf-8") as f:
        src = f.read()
    called = _called_names(src)
    leaked = sorted(_FORBIDDEN_READERS & called)
    assert not leaked, (
        "cvdp_gate.py CALLS an OFF-LIMITS hidden-harness .env reader in its live "
        "flow — this re-wires the harness TOPLEVEL into the scored-completion "
        "path (a CVDP §2 / README_NON_AGENTIC leak). Offending call(s): "
        + ", ".join(leaked) + ". The alias target MUST come from the PROMPT "
        "skeleton (skeleton_module_name_from_prompt).")


def test_gate_flow_top_is_prompt_derived():
    """Positive twin of the structural guard: the live flow DOES build the
    harness-top map from the prompt skeleton."""
    with open(G.__file__, "r", encoding="utf-8") as f:
        src = f.read()
    called = _called_names(src)
    assert "skeleton_module_name_from_prompt" in called, (
        "cvdp_gate.py no longer derives the alias top from the PROMPT skeleton — "
        "the compliant source of the harness TOPLEVEL is gone.")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
