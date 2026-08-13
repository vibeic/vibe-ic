"""An absent iverilog/vvp must reach TOOL_ERR, not escape as FileNotFoundError.

`kmap_truth_table_oracle_check` documents its own contract in two places:

* module header — ``2 = tool/usage error (disclosed, non-blocking — caller's
  hard iverilog gate still applies)``
* ``check()`` docstring — ``verdict in PASS|SKIP|BLOCK|TOOL_ERR``

Both were false when the binary was missing. `subprocess.run` raises
`FileNotFoundError` BEFORE returning, so the `TOOL_ERR` branch — which exists
for exactly this situation — was unreachable, and the caller got a traceback:
a fifth, undeclared outcome, and an oracle that COULD NOT RUN presented as one
that crashed.

Measured on a host without iverilog: four tests in
`test_kmap_truth_table_oracle_check.py` died with
``FileNotFoundError: [Errno 2] No such file or directory: 'iverilog'``. A fifth,
`test_dontcare_kmap_check_skips`, passed — because `check()` returns SKIP for a
don't-care prompt before it ever reaches the compiler. The contract already knew
how to say "I did not run"; it just could not say it about the tool.

Host-independent by construction: absence is injected by patching
`subprocess.run` to raise the same `FileNotFoundError` the real call raises, so
these run identically with and without a toolchain.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import kmap_truth_table_oracle_check as ktt  # noqa: E402

_VERDICTS = {"PASS", "SKIP", "BLOCK", "TOOL_ERR"}

# The 4-variable K-map prompt from `test_kmap_truth_table_oracle_check.py`,
# which the parser accepts — so build_oracle() succeeds and the run really
# reaches the compiler instead of short-circuiting to SKIP. (The first draft of
# this file used a DON'T-CARE prompt by mistake; it yields no oracle, so every
# test below would have gone green through the SKIP path while proving nothing.
# The meta-test below is what caught that, and is kept for the same reason.)
_PROMPT = """
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  a
 - input  b
 - input  c
 - input  d
 - output out

The module should implement the Karnaugh map below.

             ab
  cd   00  01  11  10
  00 | 0 | 1 | 0 | 1 |
  01 | 1 | 0 | 1 | 0 |
  11 | 0 | 1 | 0 | 1 |
  10 | 1 | 0 | 1 | 0 |
"""

_RTL = ("module TopModule(input a,input b,input c,input d,output out);"
        " assign out=a^b^c^d; endmodule\n")


def _absent(name):
    def boom(argv, *a, **k):
        if argv and str(argv[0]) == name:
            raise FileNotFoundError(
                2, "No such file or directory", name)
        return _REAL(argv, *a, **k)
    return boom


_REAL = ktt.subprocess.run


def _rtl(tmp_path):
    p = tmp_path / "dut.sv"
    p.write_text(_RTL)
    return str(p)


def test_the_prompt_this_module_uses_really_reaches_the_compiler(tmp_path):
    """Guard on the guards: if the prompt ever stopped parsing, every test
    below would pass vacuously by short-circuiting to SKIP, and would prove
    nothing about tool absence."""
    assert ktt.build_oracle(_PROMPT) is not None, (
        "this module's prompt no longer yields an oracle, so the tests below "
        "never reach the compiler and are vacuous")


def test_absent_iverilog_is_a_verdict_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(ktt.subprocess, "run", _absent("iverilog"))
    verdict, detail = ktt.check(_PROMPT, _rtl(tmp_path))
    assert verdict in _VERDICTS, verdict
    assert verdict == "TOOL_ERR", (verdict, detail)


def test_absent_vvp_is_also_a_verdict(tmp_path, monkeypatch):
    # iverilog present, vvp missing: the oracle COMPILED but could not be RUN.
    monkeypatch.setattr(ktt.subprocess, "run", _absent("vvp"))
    verdict, detail = ktt.check(_PROMPT, _rtl(tmp_path))
    assert verdict == "TOOL_ERR", (verdict, detail)


def test_the_detail_names_the_missing_tool(tmp_path, monkeypatch):
    # A refusal a human cannot act on is barely better than a crash.
    monkeypatch.setattr(ktt.subprocess, "run", _absent("iverilog"))
    _v, detail = ktt.check(_PROMPT, _rtl(tmp_path))
    text = str(detail)
    assert "iverilog" in text, text
    assert "NOT a verdict about the RTL" in text, text


def test_a_tool_that_RAN_and_rejected_is_still_TOOL_ERR_not_swallowed(
        tmp_path, monkeypatch):
    """OVER-CORRECTION GUARD. The fix must not turn every subprocess problem
    into 'the tool is missing'. A compiler that RAN and exited non-zero keeps
    its own stderr, which is how a real compile error stays diagnosable."""
    class _Fail:
        returncode = 1
        stderr = "gate.sv:1: syntax error; I give up."
        stdout = ""

    monkeypatch.setattr(ktt.subprocess, "run", lambda *a, **k: _Fail())
    verdict, detail = ktt.check(_PROMPT, _rtl(tmp_path))
    assert verdict == "TOOL_ERR", verdict
    assert "syntax error" in str(detail), detail
    assert "not on PATH" not in str(detail), detail
