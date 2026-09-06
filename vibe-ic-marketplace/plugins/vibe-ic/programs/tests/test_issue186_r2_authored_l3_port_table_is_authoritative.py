"""#186 round-2 — the AUTHORED L3 port table is authoritative, not just its
downstream JSON extraction.

The round-1 fix (#186 r1) taught `authoritative_contract_ports` to read a
STRUCTURED JSON enumeration (`phase1/generated_docs/L3*.json`, L9 `top_ports`)
and pure-suppress the #792 additive reset synonym there, so the emitted top
keeps exactly the documented N ports.

But that JSON is a DOWNSTREAM EXTRACTION of the real source of truth — the L3
external-interface document's own port table. Re-measured on `origin/main`
(v1.4.81) with the sha256 campaign's REAL `input/docs/L3_external_interface.md`
staged and no L3/L9 JSON, the round-1 fix read the documented port grid as loose
prose, so `reset_clock_variant_aliases` re-grafted the NINTH `rst_n` port onto a
top the documents pin at EXACTLY 8:

    emitted top ports (9): clk reset_n rst_n cs we address write_data read_data error

Two project states reach it, both routine:
  * phase-1 has not produced the L3/L9 JSON yet (phase-2 run over staged docs);
  * it produced L9 with an EMPTY `top_ports` — a state the #689 note already
    records as observed in the field ("L9 top_ports==[]"), which makes
    `_all_port_names_from_l3_json` return None.

FIX: `_all_port_names_from_port_table` reads the markdown/pipe port table out of
an AUTHORED L3/L9 document, and `authoritative_contract_ports` falls back to it
when no structured JSON enumeration is on disk.

NO-LEAK — the fallback is keyed on the LAYER FILENAME (L3 external-interface /
L9 integration), never on content shape, so the two free-text carriers keep the
#792 additive dual-spelling reset verbatim:
  * `input/phase1_prompt.md` (RTLLM / VerilogEval Path-B prompt);
  * `input/docs/design_description*` (the auto-bridged prompt) — even when the
    prompt itself happens to contain a signal/direction table.
A project shipping BOTH the JSON and the document keeps round-1 behavior
byte-for-byte (the JSON is consulted first and the fallback never runs).

chip-AGNOSTIC: phase-1 layer filename convention + markdown table grammar + the
closed Verilog direction keyword set; no chip/vendor/SKU literal. The direction
column is matched by VALUE (`input`/`output`/`inout`) so a port table with a
non-English header (`| 訊號 | 寬度 | 方向 | 描述 |`) is read the same way.
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import reset_clock_variant_alias as V  # noqa: E402
import design_one_shot_runner as R  # noqa: E402


# The documented interface: EXACTLY 8 ports, one single active-low reset.
_DOC_PORTS = ["clk", "reset_n", "cs", "we", "address",
              "write_data", "read_data", "error"]

# The L3 external-interface port table, in the shape the design documents ship:
# a markdown grid with a direction column and a non-English header row.
_L3_MD = """---
layer: L3
---

# L3 — External Interface

## Module ports

| 訊號 | 寬度 | 方向 | 描述 |
|---|---|---|---|
| `clk` | 1 | input | system clock |
| `reset_n` | 1 | input | synchronous reset, **active-LOW** |
| `cs` | 1 | input | chip select |
| `we` | 1 | input | write enable |
| `address` | 8 | input | register file address |
| `write_data` | 32 | input | write data |
| `read_data` | 32 | output | read data |
| `error` | 1 | output | error flag |

## Reset flow

1. power-up -> `reset_n = 0`
"""

_RTL = """module dut (
    input clk,
    input reset_n,
    input cs,
    input we,
    input [7:0]  address,
    input [31:0] write_data,
    output [31:0] read_data,
    output error
);
  reg [31:0] q; assign read_data = q; assign error = 1'b0;
  always @(posedge clk) if (!reset_n) q <= 0; else if (cs & we) q <= write_data;
endmodule
"""


def _stage_rtl(proj):
    rtl = R._pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / "dut.v"
    f.write_text(_RTL)
    return f


def _emitted_top_ports(f):
    return [p[2] for p in V.parse_module_ports(f.read_text(), "dut")]


def _write(proj, rel, text):
    p = proj / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ════════════════════════════════════════════════════════════════════════
# A — the markdown port-table reader
# ════════════════════════════════════════════════════════════════════════

def test_port_table_reader_returns_full_documented_set():
    assert V._all_port_names_from_port_table(_L3_MD) == set(_DOC_PORTS)


def test_port_table_reader_strips_bus_suffix_and_backticks():
    md = ("| sig | dir |\n|---|---|\n"
          "| `addr[7:0]` | input |\n| **data_o[31:0]** | output |\n")
    assert V._all_port_names_from_port_table(md) == {"addr", "data_o"}


def test_port_table_reader_ignores_table_without_direction_column():
    # A register map is a table too — but carries no direction keyword, so it is
    # NOT an interface enumeration and must not be mistaken for one.
    md = ("| addr | name | reset |\n|---|---|---|\n"
          "| 0x00 | CTRL | 0x0 |\n| 0x04 | STATUS | 0x1 |\n")
    assert V._all_port_names_from_port_table(md) is None


def test_port_table_reader_ignores_prose():
    assert V._all_port_names_from_port_table(
        "The design has a `clk` and an active-low `reset_n` input.") is None


def test_port_table_reader_requires_two_rows():
    md = "| sig | dir |\n|---|---|\n| clk | input |\n"
    assert V._all_port_names_from_port_table(md) is None


# ════════════════════════════════════════════════════════════════════════
# B — authoritative_contract_ports reads the AUTHORED document
# ════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rel", [
    "input/docs/L3_external_interface.md",
    "phase1/input_doc/L3_external_interface.md",
    "input/docs/L9_constraints_floorplan.md",
    "phase1/input_doc/L9_integration.md",
])
def test_auth_ports_from_authored_l3_l9_document(tmp_path, rel):
    _write(tmp_path, rel, _L3_MD)
    assert V.authoritative_contract_ports(tmp_path) == set(_DOC_PORTS)


def test_auth_ports_none_for_bridged_description_table(tmp_path):
    # NO-LEAK: the auto-bridged free-text prompt is NOT an authoritative layer
    # document, even when the prompt body contains a signal/direction table.
    _write(tmp_path, "input/docs/design_description.md", _L3_MD)
    assert V.authoritative_contract_ports(tmp_path) is None


def test_auth_ports_none_for_free_text_prompt(tmp_path):
    _write(tmp_path, "input/phase1_prompt.md", _L3_MD)
    assert V.authoritative_contract_ports(tmp_path) is None


def test_auth_ports_json_wins_when_both_present(tmp_path):
    # Round-1 behavior is preserved byte-for-byte: the structured JSON is
    # consulted first and the document fallback never runs.
    _write(tmp_path, "input/docs/L3_external_interface.md", _L3_MD)
    _write(tmp_path, "phase1/generated_docs/L3_external_interface.json",
           json.dumps({"module": "dut", "top_ports": [{"name": "only_this"}]}))
    assert V.authoritative_contract_ports(tmp_path) == {"only_this"}


# ════════════════════════════════════════════════════════════════════════
# C — THE #186 REGRESSION: the emitted top equals the documented port list
# ════════════════════════════════════════════════════════════════════════

def test_emitted_top_equals_documented_ports_authored_l3_only(tmp_path):
    # THE REPRO. Documented 8-port top, single active-low reset, only the
    # AUTHORED L3 markdown staged: no wrapper, no 9th port.
    f = _stage_rtl(tmp_path)
    _write(tmp_path, "input/docs/L3_external_interface.md", _L3_MD)
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert res.status == "SKIP", (res.status, res.detail)
    assert _emitted_top_ports(f) == _DOC_PORTS
    body = f.read_text()
    assert "__rcvar_inner" not in body
    assert "rst_n" not in body


def test_emitted_top_equals_documented_ports_with_empty_l9_top_ports(tmp_path):
    # The field-observed state (#689: "L9 top_ports==[]"): the JSON extraction
    # is present but EMPTY, so the authored document is the only enumeration.
    f = _stage_rtl(tmp_path)
    _write(tmp_path, "input/docs/L3_external_interface.md", _L3_MD)
    _write(tmp_path, "phase1/generated_docs/L9_INTEGRATION_SPEC.json",
           json.dumps({"top_module": "dut", "top_ports": [], "ports": []}))
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert res.status == "SKIP", (res.status, res.detail)
    assert _emitted_top_ports(f) == _DOC_PORTS


@pytest.mark.parametrize("reset_name", sorted(V._RESET_ACTIVE_LOW))
def test_emitted_top_never_widened_for_any_active_low_spelling(
        tmp_path, reset_name):
    # chip-AGNOSTIC sweep: EVERY documented single-active-low-reset spelling
    # keeps the documented port count. (`rst_n` is already canonical, so it was
    # never at risk; it is swept anyway to pin the invariant.)
    names = ["clk", reset_name, "data_in", "data_out"]
    rtl = R._pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / "dut.v"
    f.write_text(f"module dut(input clk, input {reset_name},\n"
                 f"  input [7:0] data_in, output [7:0] data_out);\n"
                 f"  reg [7:0] q; assign data_out = q;\n"
                 f"  always @(posedge clk) q <= data_in;\nendmodule\n")
    rows = "".join(f"| `{n}` | 1 | {'output' if n.endswith('_out') else 'input'} | d |\n"
                   for n in names)
    _write(tmp_path, "input/docs/L3_external_interface.md",
           "# L3\n\n| sig | w | dir | desc |\n|---|---|---|---|\n" + rows)
    R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert [p[2] for p in V.parse_module_ports(f.read_text(), "dut")] == names


# ════════════════════════════════════════════════════════════════════════
# D — NO-LEAK: the alias feature still fires where it is genuinely needed
# ════════════════════════════════════════════════════════════════════════

def test_free_text_prompt_still_gets_792_additive(tmp_path):
    # A Path-B free-text prompt ships no authoritative layer document, so the
    # hidden TB may bind EITHER spelling — the additive dual-spelling wrapper
    # must still fire and expose both.
    f = _stage_rtl(tmp_path)
    _write(tmp_path, "input/phase1_prompt.md",
           "Design a register file with a `clk` and an active-low `reset_n`.")
    # RULED by v1.17.48 (76e5960ee, "require a requested interface before
    # aliasing reset/clock names"): the automatic flow never constructs additive
    # aliases, and a contract that DECLARES the authored spelling is authority
    # to KEEP it, not to graft a synonym beside it. Pinned by its REASON, because
    # after the ruling every case in this file SKIPs on unchanged bytes and a
    # bare status assertion would no longer tell them apart.
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert res.status == "SKIP", (res.status, res.detail)
    assert "#689" in res.detail, res.detail
    body = f.read_text()
    assert "__rcvar_inner" not in body and "rst_n" not in body
    got = _emitted_top_ports(f)
    assert "reset_n" in got and "rst_n" not in got


def test_bridged_description_table_still_gets_792_additive(tmp_path):
    # NO-LEAK for the specific carrier this change could have over-captured: a
    # signal/direction table inside the auto-bridged prompt is still NOT
    # authoritative, so #792 additive is preserved.
    f = _stage_rtl(tmp_path)
    _write(tmp_path, "input/docs/design_description.md",
           "| Signal | Dir |\n|---|---|\n| clk | input |\n"
           "| reset_n | input |\n| cs | input |\n")
    # RULED by v1.17.48 (76e5960ee, "require a requested interface before
    # aliasing reset/clock names"): the automatic flow never constructs additive
    # aliases, and a contract that DECLARES the authored spelling is authority
    # to KEEP it, not to graft a synonym beside it. Pinned by its REASON, because
    # after the ruling every case in this file SKIPs on unchanged bytes and a
    # bare status assertion would no longer tell them apart.
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert res.status == "SKIP", (res.status, res.detail)
    assert "#689" in res.detail, res.detail
    body = f.read_text()
    assert "__rcvar_inner" not in body and "rst_n" not in body


def test_no_contract_at_all_still_gets_518_canonical_rename(tmp_path):
    # NO-LEAK: a design shipping NO contract still gets the #518 canonical
    # rename — the field-verified hidden-TB doctrine is untouched.
    f = _stage_rtl(tmp_path)
    before = f.read_text()
    # RULED by v1.17.48 (76e5960ee): the #518 hidden-TB doctrine was a GUESS at a
    # binding nobody stated. No contract is no authority to rename. Pinned by its
    # own reason so it stays distinguishable from the #689 refusals above.
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert res.status == "SKIP", (res.status, res.detail)
    assert "no authoritative interface requests" in res.detail, res.detail
    body = f.read_text()
    assert body == before, "the ruling promises the authored RTL is unchanged"
    assert "__rcvar_inner" not in body and "rst_n" not in body


def test_authored_doc_that_documents_both_spellings_keeps_alias(tmp_path):
    # The alias is suppressed ONLY because the synonym is absent from the
    # documented interface. When the documents THEMSELVES enumerate both reset
    # spellings, the wrapper is legitimately needed and is still emitted.
    rtl = R._pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / "dut.v"
    f.write_text("module dut(input clk, input reset_n,\n"
                 "  input [7:0] data_in, output [7:0] data_out);\n"
                 "  reg [7:0] q; assign data_out = q;\n"
                 "  always @(posedge clk) q <= data_in;\nendmodule\n")
    _write(tmp_path, "input/docs/L3_external_interface.md",
           "# L3\n\n| sig | dir |\n|---|---|\n"
           "| `clk` | input |\n| `reset_n` | input |\n| `rst_n` | input |\n"
           "| `data_in` | input |\n| `data_out` | output |\n")
    # RULED by v1.17.48 (76e5960ee): adaptation needs an interface that names
    # the DESTINATION and does NOT require the SOURCE. A document enumerating
    # BOTH spellings requires `reset_n`, so there is nothing to adapt — the
    # gap between a documented `rst_n` and an RTL that lacks it is the
    # conformance gate's finding, not something the aliaser may paper over.
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert res.status == "SKIP", (res.status, res.detail)
    assert "#689" in res.detail, res.detail
    body = f.read_text()
    assert "__rcvar_inner" not in body
    got = _emitted_top_ports(f)
    # the authored interface survives verbatim: `reset_n` kept, no `rst_n` added
    assert "reset_n" in got and "rst_n" not in got


def test_authored_doc_naming_only_the_canonical_spelling_does_alias(tmp_path):
    """THE POSITIVE ARM, and the reason the four SKIPs above are not vacuous.

    After v1.17.48 every previously-PASSing case in this file returns SKIP on
    unchanged bytes, so nothing here would fail against an aliaser that had been
    disabled outright. This is the shape the ruling asks for: an authoritative
    document that names the DESTINATION spelling (`rst_n`) and does NOT require
    the SOURCE one (`reset_n`), which is exactly when adaptation is authorised.
    """
    rtl = R._pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / "dut.v"
    f.write_text("module dut(input clk, input reset_n,\n"
                 "  input [7:0] data_in, output [7:0] data_out);\n"
                 "  reg [7:0] q; assign data_out = q;\n"
                 "  always @(posedge clk) q <= data_in;\nendmodule\n")
    _write(tmp_path, "input/docs/L3_external_interface.md",
           "# L3\n\n| sig | dir |\n|---|---|\n"
           "| `clk` | input |\n| `rst_n` | input |\n"
           "| `data_in` | input |\n| `data_out` | output |\n")
    res = R.step_reset_clock_variant_aliases(tmp_path, "dut")
    assert res.status == "PASS", (res.status, res.detail)
    body = f.read_text()
    assert "__rcvar_inner" in body and "rst_n" in body
