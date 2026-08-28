"""v1.1.83 — four NEW general RTLLM-prose canonical solvers wired into the registry:
calendar_counter / memory_array / serdes_width / signal_gen.

These are the genuinely-GENERAL members of the RTLLM-prose family: every emitted fact
is PARSED from the prose (stated depth / packing order / bit-order / period / bound /
modulo range / cascade order); an unstated fact SKIPs (§4.05 no-leak). They replace the
ad-hoc AI authoring of RTLLM RAM/ROM/LIFO/instr-reg, serial<->parallel/width converters,
signal/square/triangle generators + CDC synchronizers, and cascaded calendar counters.

(The overfit shapes the adversarial audit flagged — a magic-constant traffic-light phase
boundary, a coin-flip barrel-shift direction, a golden-copied pulse FSM — are deliberately
NOT shipped here; they are honest AI-author / Cat-E until a general parse exists.)

Host-verify is GATED on iverilog + the RTLLM dataset; the §4.05 negatives + the registry
wiring + the VE-0-fire guard run anywhere.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import spec_artifact_registry as R   # noqa: E402
import calendar_counter_synth as C   # noqa: E402
import memory_array_synth as M       # noqa: E402
import serdes_width_synth as S       # noqa: E402
import signal_gen_synth as G         # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_RT = corpus_path("_extbench/RTLLM")
_VE = [corpus_path("_extbench/verilog-eval/dataset_code-complete-iccad2023"),
       corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")]


def test_four_new_canonicals_registered():
    for k in ("calendar_counter", "memory_array", "serdes_width", "signal_gen"):
        assert k in R.types()


# ---------------------------------------------------------------- §4.05 negatives
def test_memory_skips_unstated():
    assert M.synth("Implement a module that stores some data.", "TopModule") is None


def test_serdes_skips_unstated_order():
    # a converter whose bit/packing order is not stated must SKIP, never guess
    assert S.synth("Convert the input to the output somehow.", "TopModule") is None


def test_signal_gen_skips_unstated_bound():
    # a triangle wave whose peak/bound is unstated must SKIP (no fabricated full-scale)
    txt = ("Implement a triangle wave generator named TopModule.\n"
           "Module name:\n    TopModule\nOutput ports:\n    wave: the triangle output.\n")
    assert G.synth(txt, "TopModule") is None


def test_calendar_skips_unstated_range():
    assert C.synth("Implement a counter named TopModule.", "TopModule") is None


# ---------------------------------------------------------------- VE 0-fire guard
def test_new_canonicals_never_fire_on_ve():
    n = 0
    for ds in _VE:
        if not ds.is_dir():
            pytest.skip("VE dataset not present")
        for pf in ds.glob("*_prompt.txt"):
            t = pf.read_text(errors="replace")
            for mod in (C, M, S, G):
                try:
                    if mod.synth(t, "TopModule"):
                        n += 1
                except Exception:
                    pass
    assert n == 0


# ---------------------------------------------------------------- host-verify (gated)
def _host(design: str, top: str, rtl: str) -> str:
    d = _RT / design
    if not (d / "testbench.v").is_file():
        pytest.skip("RTLLM design not present")
    with tempfile.TemporaryDirectory() as td:
        dut = Path(td) / f"{top}.v"
        dut.write_text(rtl)
        vvp = Path(td) / "a.vvp"
        ce = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), "testbench.v", str(dut)],
                            capture_output=True, text=True, cwd=str(d))
        assert ce.returncode == 0, ce.stderr[:300]
        r = _pr.run(["vvp", str(vvp)], capture_output=True, text=True, cwd=str(d))
        return "PASS" if "passed" in (r.stdout + r.stderr).lower() else "FAIL"


@pytest.mark.skipif(not _HAVE_IV, reason="iverilog not installed")
@pytest.mark.parametrize("design,top,mod", [
    ("Miscellaneous/RISC-V/RAM", "RAM", M),
    ("Memory/LIFO/LIFObuffer", "LIFObuffer", M),
    ("Miscellaneous/Others/serial2parallel", "serial2parallel", S),
    ("Miscellaneous/Signal generation/signal_generator", "signal_generator", G),
    ("Miscellaneous/Others/synchronizer", "synchronizer", G),
    ("Miscellaneous/Others/calendar", "calendar", C),
])
def test_host_pass(design, top, mod):
    if not (_RT / design / "design_description.txt").is_file():
        pytest.skip("RTLLM dataset not present")
    rtl = mod.synth((_RT / design / "design_description.txt").read_text(), top)
    assert rtl is not None
    assert _host(design, top, rtl) == "PASS"
