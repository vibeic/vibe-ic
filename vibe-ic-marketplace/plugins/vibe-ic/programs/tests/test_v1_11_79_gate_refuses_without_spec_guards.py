#!/usr/bin/env python3
"""The gate must REFUSE when its spec guards would be inactive, not degrade.

WHY (measured, 2026-08-24 cvdp-open run, 302 problems). `cvdp_gate.py` takes
`--prompts` (#559 module-name conformance) and `--dataset` (#715/#734
context-module protection + the multi-file hard-BLOCK + the #729 area check).
Omitting them does not disable the gate — it quietly downgrades those blocks to
advisory WARNs, and the gate report still reads `blocked: 0`. An operator
reading that report cannot tell the guards never ran.

That run was gated with NEITHER flag. Cost:
  - 0/5 on problems expecting more than one output file (the multi-file
    hard-BLOCK had been downgraded to a WARN), against 176/257 = 68.5% on
    single-file problems;
  - 4 completions shipped whose module name did not match the filename the
    prompt asked for — each one BLOCKed by #559 when --prompts is supplied;
  - every area-optimization answer emitted with its reduction claim unchecked,
    because #729 needs input.context. Re-gated with --dataset, the very first
    batch BLOCKs one at "wires reduction 10.44% < 20%".

This mirrors the #604 yosys guard directly above it in main(): a yosys-absent
host silently degraded the synth smoke to a no-op PASS, and the fix was to
refuse rather than emit responses gated on iverilog alone. Same defect class,
same remedy.

Running without the guards stays possible — but only as a DELIBERATE, disclosed
choice via --without-spec-guards, never as the accidental default.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

_BENCH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "benchmark")
_GATE = os.path.join(_BENCH, "cvdp_gate.py")

_REFUSAL_EXIT = 2

#: `cvdp_gate.py` refuses with the SAME exit code (2) for two independent
#: reasons that share nothing but the number: the spec-guards this module
#: exists to test (#559/#715/#734, no --prompts/--dataset/--without-spec-guards)
#: and, checked right after, iverilog/yosys absence (#528/#604 — the gate
#: cannot enforce without them, so it refuses rather than emit responses
#: gated on less than the full pipeline). On a host missing either tool, the
#: three tests below that clear the SPEC-guard refusal still see exit 2 from
#: the UNRELATED tool-guard, for the right reason on the gate's part and the
#: wrong reason for what these three assert. Gated exactly like every other
#: iverilog/yosys-dependent module in this directory (registered in
#: WHICH_GATES, `test_tool_gate_opens_when_the_tool_is_present.py`), so the
#: skip is disclosed and proved capable of opening rather than silent.
_HAVE_TOOLS = (shutil.which("iverilog") is not None
              and shutil.which("vvp") is not None
              and shutil.which("yosys") is not None)


def _run(extra_args):
    """Invoke the gate on a syntactically valid but trivial batch."""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": "cvdp_copilot_noop_0001", "completion": '
                '"module noop(input a, output b); assign b = a; endmodule"}\n')
        batch = f.name
    out = tempfile.mktemp(suffix=".jsonl")
    try:
        return subprocess.run(
            [sys.executable, _GATE, "--batch", batch, "--out", out] + extra_args,
            capture_output=True, text=True)
    finally:
        os.unlink(batch)
        if os.path.exists(out):
            os.unlink(out)


def test_refuses_when_no_spec_source_is_given():
    r = _run([])
    assert r.returncode == _REFUSAL_EXIT, (
        "the gate ran with both spec guards inactive instead of refusing; "
        f"exit={r.returncode}\n{r.stderr[-1500:]}")


def test_the_refusal_says_which_guards_would_be_off():
    """A refusal an operator cannot act on is only half a guard."""
    err = _run([]).stderr
    for token in ("--prompts", "--dataset", "--without-spec-guards"):
        assert token in err, f"refusal never mentions {token}:\n{err[-1500:]}"


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="iverilog/vvp/yosys absent — cvdp_gate.py's #528/"
                           "#604 tool-guard would refuse with the same exit "
                           "code this test checks for, for a reason unrelated "
                           "to the spec guard under test")
def test_prompts_alone_is_accepted():
    """Either spec source clears the refusal — it is not an --dataset mandate."""
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": "cvdp_copilot_noop_0001", "prompt": "make a wire"}\n')
        prompts = f.name
    try:
        r = _run(["--prompts", prompts])
        assert r.returncode != _REFUSAL_EXIT, (
            "--prompts did not clear the spec-guard refusal:\n"
            + r.stderr[-1500:])
    finally:
        os.unlink(prompts)


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="iverilog/vvp/yosys absent — cvdp_gate.py's #528/"
                           "#604 tool-guard would refuse with the same exit "
                           "code this test checks for, for a reason unrelated "
                           "to the spec guard under test")
def test_the_opt_out_is_honoured():
    """Running unguarded stays possible, as a deliberate disclosed choice."""
    r = _run(["--without-spec-guards"])
    assert r.returncode != _REFUSAL_EXIT, (
        "--without-spec-guards did not clear the refusal:\n" + r.stderr[-1500:])


@pytest.mark.skipif(not _HAVE_TOOLS,
                    reason="iverilog/vvp/yosys absent — cvdp_gate.py's #528/"
                           "#604 tool-guard would refuse with the same exit "
                           "code this test checks for, for a reason unrelated "
                           "to the spec guard under test")
def test_the_opt_out_is_not_the_default():
    """The whole point: silence must not select the unguarded path."""
    assert _run([]).returncode == _REFUSAL_EXIT
    assert _run(["--without-spec-guards"]).returncode != _REFUSAL_EXIT


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v()
            print("PASS", k)
