"""ORGANIC #798 — memory_read_pipeline_check let a `//` line comment mentioning
`module <name> ;` create a PHANTOM module (the DOTALL MODULE_HEAD_RE latched onto
the word after the commented `module` token, swallowed the file, and the REAL
module was never analysed) → false `registered_read_undocumented` WARNs named
after an English word (`is`/`wires`/`into`).

FIX: module-boundary + code detection runs over a `//`-BLANKED, offset-preserving
view; the latency `//` doc-comment is read from the comment-preserving `src` at
the shared offsets. §4.05: a genuinely undocumented registered read in the REAL
module still WARNs (named the real module); a real `// 1-cycle read latency` doc
still suppresses. chip-AGNOSTIC.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import memory_read_pipeline_check as M  # noqa: E402

_GATE = PROGRAMS / "memory_read_pipeline_check.py"

_PHANTOM_PROSE = (
    "// Top-level integration: this module wires the spec_ram module into\n"
    "// the core. See: instantiate module spec_ram ; before reset deasserts.\n"
    "// 1-cycle read latency — rdata is registered, lags addr by one clock.\n")

_DOCUMENTED = _PHANTOM_PROSE + (
    "module spec_ram (input clk, input we, input [7:0] addr,\n"
    "                 input [7:0] wdata, output reg [7:0] rdata);\n"
    "    reg [7:0] mem [0:255];\n"
    "    always @(posedge clk) begin\n"
    "        if (we) mem[addr] <= wdata;\n"
    "        rdata <= mem[addr];\n"
    "    end\nendmodule\n")

_UNDOCUMENTED = (
    "// this module wires the foo module ; into bar\n"
    "module rf (input clk, input [7:0] addr, output reg [7:0] rdata);\n"
    "    reg [7:0] mem [0:255];\n"
    "    always @(posedge clk) rdata <= mem[addr];\nendmodule\n")


def _run(tmp_path, rtl):
    f = tmp_path / "d.v"
    f.write_text(rtl)
    jp = tmp_path / "r.json"
    subprocess.run([sys.executable, str(_GATE), str(f), "--json", str(jp)],
                   capture_output=True, text=True)
    return json.loads(jp.read_text())


def test_798_no_phantom_module_documented_passes(tmp_path):
    d = _run(tmp_path, _DOCUMENTED)
    mods = {f["module"] for f in d["findings"]}
    assert mods <= {"spec_ram"}, f"phantom module leaked: {mods}"
    assert d["verdict"] == "PASS", d


def test_798_noleak_undocumented_real_module_still_warns(tmp_path):
    d = _run(tmp_path, _UNDOCUMENTED)
    assert d["verdict"] == "WARN", d
    mods = {f["module"] for f in d["findings"]}
    assert mods == {"rf"}, f"finding must name the REAL module: {mods}"


def test_798_blank_line_comments_is_offset_preserving():
    s = "module a; // comment module b ;\nx = 1;\n"
    out = M._blank_line_comments(s)
    assert len(out) == len(s)
    assert out.count("\n") == s.count("\n")
    assert "module b" not in out          # comment text blanked
    assert "module a;" in out             # code preserved


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
