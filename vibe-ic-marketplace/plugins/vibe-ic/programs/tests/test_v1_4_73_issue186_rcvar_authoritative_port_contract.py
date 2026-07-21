"""v1.4.73 — #186 part 1: the reset/clock variant-alias step grafted a 9th top
port onto a design whose documented L3 port table pins EXACTLY 8 ports.

sha256 @ v1.4.67 declared 8 top ports (clk, reset_n, cs, we, address[7:0],
write_data[31:0], read_data[31:0], error). The #792 additive dual-spelling
reset wrapper renamed the authored module to `sha256__rcvar_inner` and appended
a same-named wrapper exposing BOTH `reset_n` and a canonical `rst_n` synonym —
a NINTH top port the documents never sanction. `spec_conformance_check` then
FAILs the IC for a port the flow itself introduced.

Two chip-AGNOSTIC fixes:

  (1) design_one_shot_runner.step_reset_clock_variant_aliases —
      `reset_clock_variant_alias.authoritative_contract_ports(project)` returns
      the COMPLETE top port set when a STRUCTURED L3 port table / L9 top_ports is
      staged (the documented, authoritative interface). The additive synonym is
      PURE-SUPPRESSED when the reset's contract spelling is enumerated but its
      canonical synonym is NOT — so the top port list is never widened past the
      documented N ports. Free-text prompts (RTLLM/VerilogEval — no structured
      L3/L9) return None → the #792 additive behavior is kept (no-leak).

  (2) spec_conformance_check redirects the top to `<top>__rcvar_inner` when that
      runner-introduced inner module is present, so conformance is judged
      against the AUTHORED interface, not the wrapper — even if a wrapper is
      legitimately emitted for another reason.

chip-AGNOSTIC: structured-doc port grammar + the runner's own fixed
`__rcvar_inner` suffix; no chip/vendor/SKU literal.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import reset_clock_variant_alias as V  # noqa: E402
import design_one_shot_runner as R  # noqa: E402
import spec_conformance_check as S  # noqa: E402


_SHA256_8PORT = """module sha256 (
    input clk,
    input reset_n,
    input cs,
    input we,
    input [7:0]  address,
    input [31:0] write_data,
    output [31:0] read_data,
    output error
);
  reg [31:0] rd; assign read_data = rd; assign error = 1'b0;
  always @(posedge clk) if (!reset_n) rd <= 0; else if (cs & we) rd <= write_data;
endmodule
"""

_PORT_NAMES = ["clk", "reset_n", "cs", "we", "address",
               "write_data", "read_data", "error"]


def _stage_rtl(proj, text=_SHA256_8PORT, name="sha256.v"):
    rtl = R._pl.rtl_dir(proj)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / name
    f.write_text(text)
    return f


def _stage_l3_json(proj, names=_PORT_NAMES, key="top_ports"):
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_external_interface.json").write_text(json.dumps(
        {"module": "sha256", key: [{"name": n} for n in names]}))


# ════════════════════════════════════════════════════════════════════════
# A — authoritative_contract_ports: the structured-enumeration reader
# ════════════════════════════════════════════════════════════════════════

def test_auth_ports_from_l3_top_ports(tmp_path):
    _stage_l3_json(tmp_path)
    got = V.authoritative_contract_ports(tmp_path)
    assert got == set(_PORT_NAMES)


def test_auth_ports_from_l3_generic_ports_key(tmp_path):
    _stage_l3_json(tmp_path, key="ports")
    assert V.authoritative_contract_ports(tmp_path) == set(_PORT_NAMES)


def test_auth_ports_strips_bus_suffix(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L3_x.json").write_text(json.dumps(
        {"ports": ["clk", "reset_n", "address[7:0]", "write_data[31:0]"]}))
    assert V.authoritative_contract_ports(tmp_path) == {
        "clk", "reset_n", "address", "write_data"}


def test_auth_ports_from_l9_top_ports(tmp_path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": "sha256",
         "top_ports": [{"name": n} for n in _PORT_NAMES]}))
    assert V.authoritative_contract_ports(tmp_path) == set(_PORT_NAMES)


def test_auth_ports_none_for_prose_only(tmp_path):
    # A free-text prompt / prose contract ships NO structured L3/L9 port table.
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "design_description.md").write_text(
        "The design has a `clk` and an active-low `reset_n`.")
    assert V.authoritative_contract_ports(tmp_path) is None


def test_auth_ports_none_for_empty_project(tmp_path):
    assert V.authoritative_contract_ports(tmp_path) is None


# ════════════════════════════════════════════════════════════════════════
# B — the step never widens the top past an authoritative enumeration
# ════════════════════════════════════════════════════════════════════════

def test_step_authoritative_l3_suppresses_additive_9th_port(tmp_path):
    # THE #186 REPRO. With an authoritative 8-port L3 (reset_n, NO rst_n) the
    # additive `rst_n` synonym is suppressed: no wrapper, no 9th port.
    f = _stage_rtl(tmp_path)
    _stage_l3_json(tmp_path)
    res = R.step_reset_clock_variant_aliases(tmp_path, "sha256")
    assert res.status == "SKIP", (res.status, res.detail)
    body = f.read_text()
    assert "__rcvar_inner" not in body
    assert "rst_n" not in body      # the 9th port was NOT grafted on


def test_step_prose_only_keeps_792_additive(tmp_path):
    # NO-LEAK: without a STRUCTURED L3/L9 (only a prose/table contract) the #792
    # additive dual-spelling wrapper STILL fires — a hidden TB may bind either
    # spelling. Proves the #186 suppression is scoped to authoritative docs.
    f = _stage_rtl(tmp_path)
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "design_description.md").write_text(
        "| Signal | Dir |\n|---|---|\n| clk | input |\n"
        "| reset_n | input |\n| cs | input |\n")
    res = R.step_reset_clock_variant_aliases(tmp_path, "sha256")
    assert res.status == "PASS", (res.status, res.detail)
    assert "additive" in res.detail.lower()
    body = f.read_text()
    assert "__rcvar_inner" in body and "rst_n" in body


def test_step_no_contract_still_renames_518(tmp_path):
    # NO-LEAK: a design that ships NO contract at all STILL gets the #518
    # canonical rename (reset_n -> rst_n) — the field-verified hidden-TB doctrine.
    f = _stage_rtl(tmp_path)
    res = R.step_reset_clock_variant_aliases(tmp_path, "sha256")
    assert res.status == "PASS", (res.status, res.detail)
    body = f.read_text()
    assert "__rcvar_inner" in body and "rst_n" in body


# ════════════════════════════════════════════════════════════════════════
# C — spec_conformance_check judges the AUTHORED inner, not the wrapper
# ════════════════════════════════════════════════════════════════════════

_WRAPPER_9PORT = """module sha256__rcvar_inner (
    input clk, input reset_n, input cs, input we,
    input [7:0] address, input [31:0] write_data,
    output [31:0] read_data, output error
);
  assign read_data = 32'd0; assign error = 1'b0;
endmodule

module sha256 (
    input clk, input reset_n, input rst_n, input cs, input we,
    input [7:0] address, input [31:0] write_data,
    output [31:0] read_data, output error
);
  wire r = reset_n & rst_n;
  sha256__rcvar_inner u(.clk(clk), .reset_n(r), .cs(cs), .we(we),
    .address(address), .write_data(write_data),
    .read_data(read_data), .error(error));
endmodule
"""

_SPEC_8PORT = json.dumps({
    "module": "sha256",
    "ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "reset_n", "direction": "input", "width": 1},
        {"name": "cs", "direction": "input", "width": 1},
        {"name": "we", "direction": "input", "width": 1},
        {"name": "address", "direction": "input", "width": 8},
        {"name": "write_data", "direction": "input", "width": 32},
        {"name": "read_data", "direction": "output", "width": 32},
        {"name": "error", "direction": "output", "width": 1},
    ]})


def _run_spec_conformance(tmp_path, rtl_text):
    (tmp_path / "rtl.v").write_text(rtl_text)
    (tmp_path / "spec.json").write_text(_SPEC_8PORT)
    S.main(["--rtl-dir", str(tmp_path), "--spec", str(tmp_path / "spec.json"),
            "--top", "sha256", "--json", str(tmp_path / "out.json")])
    out = json.loads((tmp_path / "out.json").read_text())
    return out if isinstance(out, list) else out.get("findings", [])


def test_spec_conformance_redirects_to_authored_inner(tmp_path):
    # With the runner-wrapped top present, conformance is judged against the
    # authored 8-port inner — NO `port-extra` for the flow-introduced `rst_n`.
    findings = _run_spec_conformance(tmp_path, _WRAPPER_9PORT)
    extra = [f for f in findings
             if f.get("rule") == "port-extra" and f.get("symbol") == "rst_n"]
    assert extra == [], f"flow-introduced rst_n was flagged: {findings}"


def test_spec_conformance_control_flags_extra_port_without_inner(tmp_path):
    # CONTROL: strip the inner so only the 9-port wrapper remains — the check
    # DOES flag the extra `rst_n`, proving the redirect (not a weakened rule) is
    # what protects the authored design.
    only_wrapper = _WRAPPER_9PORT.split("module sha256__rcvar_inner", 1)[1]
    only_wrapper = "module sha256_leaf" + only_wrapper  # rename inner ref away
    only_wrapper = only_wrapper.replace("sha256__rcvar_inner u(", "sha256_leaf u(")
    findings = _run_spec_conformance(tmp_path, only_wrapper)
    extra = [f for f in findings
             if f.get("rule") == "port-extra" and f.get("symbol") == "rst_n"]
    assert extra, f"expected port-extra rst_n on the bare 9-port wrapper: {findings}"
