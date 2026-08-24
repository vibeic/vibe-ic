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
import subprocess
import sys
import tempfile

_BENCH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "benchmark")
_GATE = os.path.join(_BENCH, "cvdp_gate.py")

_REFUSAL_EXIT = 2


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


def test_the_opt_out_is_honoured():
    """Running unguarded stays possible, as a deliberate disclosed choice."""
    r = _run(["--without-spec-guards"])
    assert r.returncode != _REFUSAL_EXIT, (
        "--without-spec-guards did not clear the refusal:\n" + r.stderr[-1500:])


def test_the_opt_out_is_not_the_default():
    """The whole point: silence must not select the unguarded path."""
    assert _run([]).returncode == _REFUSAL_EXIT
    assert _run(["--without-spec-guards"]).returncode != _REFUSAL_EXIT


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v()
            print("PASS", k)
