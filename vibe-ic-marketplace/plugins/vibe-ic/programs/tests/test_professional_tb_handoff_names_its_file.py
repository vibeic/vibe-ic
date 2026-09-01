"""The professional-TB handoff pointed the author at the file it overwrites.

WHAT WAS BROKEN, MEASURED
=========================
`professional_tb_gen` emits `tb_<top>.py` carrying a `reference_model()` hook
that raises `TestSkip`, and both the scaffold's own docstring and the runner's
INCOMPLETE message said, in effect, "fill the reference-model hook". Following
that literally is useless: `generate()` writes `tb_<top>.py` unconditionally on
every invocation, so the next runner pass destroys the answer — and deletes the
`results.xml` that proved it, so Step 4 goes back to blocking.

The consumption path is a DIFFERENT file and always was:
`_load_expert_reference_tb` reads `expert_reference_tb.py` and never writes it.
Its docstring even says the separation is deliberate ("so regeneration cannot
erase the expert's work") — the instruction just never named it. An author
following the message lost a full acceptance run to this.

These tests pin the two properties that make the handoff followable: the
message names the file the CONSUMER reads, and it states the conditions the
loader actually enforces. They are about the INSTRUCTION, which is the part
that was wrong; the loader's behaviour is unchanged and is re-asserted here so
a future edit cannot drift the message away from the code again.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import professional_tb_gen as PTB              # noqa: E402

CONSUMED_FILE = "expert_reference_tb.py"
TOKEN = "PROFESSIONAL_TB PASS"


def _project(root: Path) -> Path:
    """A minimal project whose class lands on the hook-unfilled GENERIC
    scaffold — same shape the sibling expert-fallback suite uses."""
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "converter",
        "top_ports": [
            {"name": "sample", "dir": "input", "width": 1},
            {"name": "result", "dir": "output", "width": 1},
            {"name": "ck4", "dir": "input", "width": 1},
        ],
        "clock_domains": [{"name": "ck4", "source_pin": "ck4"}],
    }))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clocks": [{"name": "CK4", "source_pin": "ck4",
                    "freq_hz": 1_000_000, "period_ns": 1000}],
    }))
    rtl = root / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "converter.sv").write_text(
        "module converter(input sample, input ck4, output reg result); "
        "always @(posedge ck4) result <= sample; endmodule\n")
    return root


def _scaffold_text(tmp_path) -> str:
    """The scaffold the producer ACTUALLY emits, read off disk.

    Driven through `generate()` rather than by hand-building a shape dict, and
    with NO fallback to module source: an earlier draft fell back to
    `inspect.getsource(PTB)` when a hand-built shape raised, and the module
    source contains `expert_reference_tb.py` inside `_load_expert_reference_tb`
    — so two of these tests passed against the UNFIXED producer, measuring the
    loader instead of the scaffold."""
    res = PTB.generate(_project(tmp_path))
    tb = Path(res["out_dir"]) / "tb_converter.py"
    text = tb.read_text()
    assert "reference_model" in text, "not the hook-unfilled scaffold"
    return text


def test_the_scaffold_names_the_file_the_loader_reads(tmp_path):
    """RED before the fix: the scaffold named only `reference_model()`."""
    text = _scaffold_text(tmp_path)
    assert CONSUMED_FILE in text, (
        "the generated testbench does not name expert_reference_tb.py, so an "
        "author following it edits the file that is regenerated")


def test_the_scaffold_warns_that_it_is_itself_regenerated(tmp_path):
    text = _scaffold_text(tmp_path).lower()
    assert "regenerated" in text, text[-600:]


def test_the_scaffold_states_the_token_the_loader_requires(tmp_path):
    assert TOKEN in _scaffold_text(tmp_path)


def test_the_runner_message_names_the_file_too():
    """The runner's INCOMPLETE detail is what a reader sees in the log; it must
    carry the same name as the scaffold."""
    import design_one_shot_runner as DOR                 # noqa: E402
    text = inspect.getsource(DOR)
    i = text.index("reference-model hook is unfilled")
    window = text[i:i + 900]
    assert CONSUMED_FILE in window, window
    assert TOKEN in window, window


def test_the_loader_still_refuses_a_testskip_stub(tmp_path):
    """Unchanged behaviour, re-asserted: naming the file must not loosen what
    the loader accepts."""
    (tmp_path / CONSUMED_FILE).write_text(
        "import cocotb\n"
        "@cocotb.test()\n"
        "async def t(dut):\n"
        "    raise cocotb.result.TestSkip('nope')\n")
    assert PTB._load_expert_reference_tb(tmp_path) is None


def test_the_loader_still_requires_the_token(tmp_path):
    (tmp_path / CONSUMED_FILE).write_text(
        "import cocotb\n"
        "@cocotb.test()\n"
        "async def t(dut):\n"
        "    assert dut is not None\n")
    assert PTB._load_expert_reference_tb(tmp_path) is None


def test_the_loader_accepts_a_self_checking_testbench(tmp_path):
    (tmp_path / CONSUMED_FILE).write_text(
        "import cocotb\n"
        "@cocotb.test()\n"
        "async def t(dut):\n"
        "    assert dut is not None\n"
        f"    dut._log.info('{TOKEN}')\n")
    got = PTB._load_expert_reference_tb(tmp_path)
    assert got is not None and TOKEN in got
