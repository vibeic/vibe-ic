#!/usr/bin/env python3
"""A caught PSM error and a clean power grid must not reach the report identically.

eda_ir_drop returned `success: isComplete || isWarn`, where `isWarn` is set when
the Tcl `catch {analyze_power_grid}` FIRED — i.e. PSM produced no IR report at
all. The code argues that deliberately: only an UNCAUGHT abort is a tool failure,
a caught error is a warning by this tool's own design. That argument is
defensible and is NOT what this change overturns.

It is only safe, though, if the caller can tell the two apart by a NUMBER — and
there was no number in either case, because nothing parsed the PSM report. The
only discriminator was the boolean `psm_warn`, and the manifest recorded
NEITHER: writeManifest was called only `if (isComplete)`, so a run whose analysis
threw left no record at all. Read-fail and measured-fine reached the report as
the same thing.

So the fix is not to turn the warning into a failure:
  * the response carries a three-state `status` (MEASURED / NOT_MEASURED), the
    parsed numbers, and `psm_caught_error` saying the analysis threw;
  * EVERY outcome writes a manifest entry, so a run that measured nothing is
    recorded INCONCLUSIVE by the REQUIRED_METRICS gate instead of vanishing.

MEASURED, three arms, live (192.168.1.121, sky130A):
  pdn_pnr.def     success:true  status:MEASURED     total_power_w 2.63e-05
                  -> manifest PASS
  mcp_pnr.def     success:true  status:NOT_MEASURED psm_caught_error:true
                  -> manifest INCONCLUSIVE, missing [worst_ir_drop_v, total_power_w]
                     (on c0b66577e this run wrote NO manifest entry at all)
  NOPWR plant     success:false status:NOT_MEASURED
                  -> manifest INCONCLUSIVE
"""
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
SRC = (MCP_ROOT / "src" / "index.js").read_text()


def _tool(name: str) -> str:
    i = SRC.find(f'"{name}"')
    assert i > 0, f"tool {name} not found"
    j = SRC.find("server.tool(", i)
    return SRC[i:j if j > 0 else len(SRC)]


def test_every_outcome_writes_a_manifest_entry():
    """The measured bug: a caught-error run left no record at all."""
    t = _tool("eda_ir_drop")
    assert 'step: "ir_drop"' in t
    assert "if (isComplete) {\n      const dir = def_file" not in t, (
        "the ir_drop manifest is written only when the analysis completed, so a "
        "run whose analysis threw leaves no record"
    )


def test_the_response_says_which_of_the_three_outcomes_happened():
    t = _tool("eda_ir_drop")
    assert "const irStatus =" in t
    assert '"MEASURED"' in t and '"NOT_MEASURED"' in t
    assert "status: irStatus," in t
    assert "psm_caught_error: isWarn || undefined," in t, (
        "nothing in the response says the Tcl catch fired"
    )
    # the manifest carries the same discriminators, not just the response
    assert "ir_status: irStatus," in t
    assert "power_net_resolved" in t


def test_a_caught_error_is_still_not_promoted_to_a_tool_failure():
    """The deliberate design is preserved: only an UNCAUGHT abort fails the tool."""
    t = _tool("eda_ir_drop")
    assert "success: (isComplete || isWarn) && !noPowerNet," in t, (
        "the caught-warning path was turned into a failure — that is a different "
        "change from making it distinguishable, and this tool argues for it "
        "deliberately in its own comment"
    )
