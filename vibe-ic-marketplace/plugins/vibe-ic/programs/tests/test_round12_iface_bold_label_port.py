#!/usr/bin/env python3
"""R12C3 regression test for iface_conformance_v2.py (ORGANIC #809).

CLUSTER R12C3 — iface_conformance_v2 under-extracted a structured single-port
spec form: a markdown bullet `- **<name>:** ...` under a direction-asserting
section heading (`## New Input`), or `- **<name> (input, wire)**: ...` with the
direction inside the bold label. extract_prompt_iface() returned ZERO ports for
such a spec, so an RTL that OMITS the spec-mandated port (e.g. `enable`) slipped
through `interface-conformance ok` (rc=0) under --strict — a §4.05 NO-LEAK
failure (a genuinely-missing top port was never flagged).

This test (run against the PATCHED program) asserts:
  (POSITIVE) spec-faithful RTL declaring all bold-label ports → rc 0 (ok), and
             extract_prompt_iface recognizes the bold-label port `enable`.
  (§4.05 NEGATIVE-1) RTL OMITTING the bold-label-declared `enable` → rc 1
             block-eligible MISSING-PORT.
  (§4.05 NEGATIVE-2) RTL declaring `enable` with the WRONG direction (output) →
             rc 1 block-eligible PORT-DIRECTION.
  (NO-PHANTOM) bullets under a NON-direction heading (`## Internal Components`,
             with `[..]` widths in the label) are NOT fabricated as ports.

Self-contained: inline spec/RTL fixtures. The program under test is located via
the VIBE_PROGRAMS env var, defaulting to the repo-relative round12 programs dir
so it runs in CI.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ── locate the program under test ───────────────────────────────────────────
_DEFAULT_PROGRAMS = __import__("pathlib").Path(__file__).resolve().parent.parent


def _programs_dir() -> Path:
    p = os.environ.get("VIBE_PROGRAMS")
    if p:
        return Path(p)
    # default A: a sibling repo-relative path; default B: this test's own dir
    # (the staged /tmp/r12_R12C3 copy) — whichever actually holds the program.
    if (_DEFAULT_PROGRAMS / "iface_conformance_v2.py").is_file():
        return _DEFAULT_PROGRAMS
    return Path(__file__).resolve().parent.parent


PROGRAMS = _programs_dir()
PROG = PROGRAMS / "iface_conformance_v2.py"


# ── inline fixtures ─────────────────────────────────────────────────────────
# Spec uses BOTH bold-label forms (chip-AGNOSTIC, not the moving_average literal):
#   FORM-B: heading-direction `## New Input` + `- **gate_en:** 1-bit`
#   FORM-A: `- **clk (input, wire)**: ...` (direction inline in the bold label)
# plus an `## Internal Components` section whose bullets must NOT become ports.
SPEC = """\
# Widget Module (with gate)

The original module `widget` does work. Add a `gate_en` signal controlling when
the widget updates its internal state.

## New Input
- **gate_en:** 1-bit

## Inputs and Outputs
- **clk (input, wire)**: Clock signal.
- **rst (input, wire)**: Synchronous reset signal.
- **gate_en (input, wire)**: 1-bit control; updates occur only when high.
- **din (input, wire[7:0])**: 8-bit input data.
- **dout (output, wire[7:0])**: 8-bit output result.

## Internal Components
- **store[3:0]**: Array of 4 registers.
- **acc[9:0]**: 10-bit running accumulator.
"""

RTL_GOOD = """\
module widget(
    input  wire clk,
    input  wire rst,
    input  wire gate_en,
    input  wire [7:0] din,
    output wire [7:0] dout
);
    reg [7:0] store [3:0];
    reg [9:0] acc;
    assign dout = acc[9:2];
    always @(posedge clk) if (rst) acc <= 0; else if (gate_en) acc <= acc + din;
endmodule
"""

# §4.05 NEGATIVE-1: the bold-label-declared `gate_en` port is OMITTED.
RTL_MISSING = """\
module widget(
    input  wire clk,
    input  wire rst,
    input  wire [7:0] din,
    output wire [7:0] dout
);
    reg [9:0] acc;
    assign dout = acc[9:2];
    always @(posedge clk) if (rst) acc <= 0; else acc <= acc + din;
endmodule
"""

# §4.05 NEGATIVE-2: `gate_en` declared with the WRONG direction (output).
RTL_WRONGDIR = """\
module widget(
    input  wire clk,
    input  wire rst,
    output wire gate_en,
    input  wire [7:0] din,
    output wire [7:0] dout
);
    assign gate_en = 1'b0;
    assign dout = 8'd0;
endmodule
"""

RID = "cvdp_copilot_widget_0001"


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("r12c3")
    spec = d / "spec.md"
    spec.write_text(SPEC)
    good = d / "good.v"
    good.write_text(RTL_GOOD)
    missing = d / "missing.v"
    missing.write_text(RTL_MISSING)
    wrongdir = d / "wrongdir.v"
    wrongdir.write_text(RTL_WRONGDIR)
    return {"spec": spec, "good": good, "missing": missing,
            "wrongdir": wrongdir}


def _run(spec, rtl):
    cmd = [sys.executable, str(PROG), "--id", RID,
           "--prompt", str(spec), "--rtl", str(rtl), "--strict"]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_program_present():
    assert PROG.is_file(), f"program not found at {PROG} (set VIBE_PROGRAMS)"


def test_extracts_bold_label_port():
    """The bold-label structured form is recognized — `gate_en` is extracted as
    an input from a STRUCTURAL (bold_label) source (else a real missing port
    leaks)."""
    sys.path.insert(0, str(PROGRAMS))
    import iface_conformance_v2 as G
    pif = G.extract_prompt_iface(SPEC)
    assert "gate_en" in pif.ports, f"bold-label port not extracted: {pif.ports}"
    assert pif.ports["gate_en"] == "input", pif.ports
    # direction provenance must be STRUCTURAL so the MISSING/DIRECTION finding
    # is block-eligible.
    assert "bold_label" in pif.dir_sources.get("gate_en", set()), \
        pif.dir_sources
    # NO-PHANTOM: internal-component bullets must NOT be ports.
    for phantom in ("store", "acc"):
        assert phantom not in pif.ports, f"phantom port fabricated: {phantom}"


def test_formb_heading_direction_isolated():
    """FORM-B in ISOLATION (the exact R12C3 form: `## New Input` heading +
    `- **<Name>:** 1-bit` bare bold-label bullet, no inline-direction section) is
    recognized with the HEADING's direction, while a bullet under a NON-direction
    heading (`## Internal Components`, with a `[..]` width) is NOT fabricated."""
    sys.path.insert(0, str(PROGRAMS))
    import iface_conformance_v2 as G
    spec_b = (
        "# Widget\n"
        "## New Input\n"
        "- **gate_en:** 1-bit\n"
        "## Internal Components\n"
        "- **store[3:0]**: Array of 4 registers.\n"
        "- **acc[9:0]**: 10-bit accumulator.\n"
    )
    ports = G.bold_label_ports(spec_b)
    assert ports == {"gate_en": "input"}, ports


def test_no_phantom_on_prose_label_bullets():
    """Prose-label / descriptive bold bullets must NOT be fabricated as ports:
    `- **Input**:` / `- **Note**:` / `- **Behavior**:` under descriptive
    headings, and a bare-name bullet whose body is a prose sentence (not a
    type-spec). Guards the corpus-sweep no-regression result."""
    sys.path.insert(0, str(PROGRAMS))
    import iface_conformance_v2 as G
    spec_prose = (
        "# Decoder\n"
        "## Behavior\n"
        "- **Valid Header**: produces output.\n"
        "## Example Operations\n"
        "- **Input**: `data_in = 1`\n"
        "- **Expected Output**: `data_out = 1`\n"
        "## Interface Signals\n"
        "- **Clock**: drives the logic.\n"      # prose body, non-dir heading
        "- **Note**: this is descriptive.\n"
    )
    assert G.bold_label_ports(spec_prose) == {}, G.bold_label_ports(spec_prose)


def test_positive_good_rtl_passes(files):
    """POSITIVE: spec-faithful RTL declaring all bold-label ports → rc 0 ok."""
    r = _run(files["spec"], files["good"])
    assert r.returncode == 0, f"good RTL hard-blocked: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "interface-conformance ok" in r.stdout


def test_neg1_missing_port_hardblocks(files):
    """§4.05 NEGATIVE-1: RTL OMITTING the bold-label port hard-blocks rc 1."""
    r = _run(files["spec"], files["missing"])
    assert r.returncode == 1, f"missing port did NOT hard-block: rc={r.returncode}\n{r.stdout}"
    assert "MISSING-PORT" in r.stdout and "gate_en" in r.stdout, r.stdout
    assert "block-eligible" in r.stderr, r.stderr


def test_neg2_wrong_direction_hardblocks(files):
    """§4.05 NEGATIVE-2: RTL with the WRONG direction hard-blocks rc 1."""
    r = _run(files["spec"], files["wrongdir"])
    assert r.returncode == 1, f"wrong dir did NOT hard-block: rc={r.returncode}\n{r.stdout}"
    assert "PORT-DIRECTION" in r.stdout and "gate_en" in r.stdout, r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
