#!/usr/bin/env python3
"""test_organic_20260704_rcvar_additive_whitebox_suppress.py

ORGANIC-20260704 residual — the "4th mechanism". Under the WHITEBOX opt-in
(VIBE_IC_RCVAR_WHITEBOX_FLAT=1), the ADDITIVE dual-spelling reset synonym must be
SUPPRESSED, because the hidden cocotb harness binds the design's OWN reset
spelling and leaves the AND-combined synonym UNDRIVEN — the `tri1`/`tri0`
inactive pull is NOT honored by the official Icarus-13 scorer, so
`resetn & <undriven tri1>` resolves to x and the design is frozen in reset.

PROVEN (benchmark-agent, run_v1332_delta) on cvdp_copilot_axi_stream_upscale_0001:
  - flat/original module            -> official scorer PASS
  - runner additive wrapper (v1.3.32) -> official scorer FAIL (frozen)
  - additive synonym removed        -> PASS
  - this suppression fix            -> canonical-entry PASS

The suppression is OPT-IN gated (default OFF) so the shipped wrapper path and its
#518/#689/#792 additive guard tests are unchanged.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROG = HERE.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as D  # noqa: E402

# Design ships active-low `resetn` (which the prompt/contract also declares, so
# plan_aliases routes the canonical `rst_n` rename to the ADDITIVE map rather
# than an in-place rename → the exact axi_stream_upscale_0001 shape).
_DUT = (
    "module axis_upscale (\n"
    "    input        clk,\n"
    "    input        resetn,\n"
    "    input        s_valid,\n"
    "    output reg   m_valid\n"
    ");\n"
    "    always @(posedge clk) begin\n"
    "        if (!resetn) m_valid <= 1'b0;\n"
    "        else         m_valid <= s_valid;\n"
    "    end\n"
    "endmodule\n"
)

# A design_description doc that declares `resetn` in a port-declaration context,
# so design_contract_ports() pins `resetn` and the canonical `rst_n` rename lands
# in additive_reset_map (the additive dual-spelling path).
_DESC = (
    "## Interface\n"
    "### Inputs\n"
    "- **`clk`** (1-bit): clock.\n"
    "- **`resetn`** (1-bit): active-low synchronous reset.\n"
    "- **`s_valid`** (1-bit): input valid.\n"
    "### Outputs\n"
    "- **`m_valid`** (1-bit): output valid.\n"
)


def _stage(tmp_path):
    rtl = D._pl.rtl_dir(tmp_path)
    rtl.mkdir(parents=True, exist_ok=True)
    f = rtl / "axis_upscale.sv"
    f.write_text(_DUT)
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "design_description.md").write_text(_DESC)
    return f


def _run(tmp_path, monkeypatch, optin):
    """Run the step on the SAME pure-additive shape, opt-in on or off."""
    f = _stage(tmp_path)
    before = f.read_text()
    if optin:
        monkeypatch.setenv("VIBE_IC_RCVAR_WHITEBOX_FLAT", "1")
    else:
        monkeypatch.delenv("VIBE_IC_RCVAR_WHITEBOX_FLAT", raising=False)
    res = D.step_reset_clock_variant_aliases(tmp_path, "axis_upscale")
    return res, before, f.read_text()


def _assert_untouched(res, before, body):
    """The ruled end state for this shape, asserted on the BYTES.

    RULED by v1.17.48 (76e5960ee): "Automatic flow never constructs additive
    aliases. Retain the emitter's explicit `additive_reset_map` API for
    intentional compatibility callers." This DUT documents its own `resetn`, so
    the step refuses under #689 and leaves the file alone.
    """
    assert res.status == "SKIP", (res.status, res.detail)
    assert "#689" in res.detail, res.detail
    assert body == before, "the ruling promises the RTL is left UNCHANGED"
    # the harness-breaking shapes this file was written about, still absent
    assert "__rcvar_inner" not in body
    assert body.count("module axis_upscale") == 1
    assert "rst_n" not in body                 # no synonym port
    assert "resetn__rcvar_net" not in body     # no AND-combine that freezes
    assert "input        resetn" in body       # design's own reset intact


def test_additive_suppressed_under_whitebox_optin(tmp_path, monkeypatch):
    """POSITIVE: opt-in -> no additive synonym, the original is delivered."""
    _assert_untouched(*_run(tmp_path, monkeypatch, optin=True))


def test_default_off_keeps_additive_wrapper(tmp_path, monkeypatch):
    """RULED by v1.17.48 (76e5960ee). This case pinned the OPPOSITE: without the
    opt-in the shipped ADDITIVE dual-spelling wrapper was emitted, and the
    suppression must not leak into the general flow. The ruling removed the
    automatic additive path outright, so there is no longer a shipped additive
    wrapper for the opt-in to differ from — MEASURED on e1814e28d, this case and
    the one above return the same #689 SKIP on the same bytes.

    The node ID is kept so the census compares by membership; the name still
    describes the pre-v1.17.48 contract.
    """
    _assert_untouched(*_run(tmp_path, monkeypatch, optin=False))


def test_the_optin_changes_nothing_for_a_shape_the_ruling_already_refuses(
        tmp_path, monkeypatch):
    """And this is why the two cases above are not one assertion written twice.

    Their point was that the opt-in and the default DIFFER. Since v1.17.48 they
    do not, for this shape — so the claim worth pinning is the one that can
    still fail: the opt-in must not start mutating a design the automatic flow
    has refused. Compared on the BYTES, not on a status word.
    """
    _, before_on, after_on = _run(tmp_path, monkeypatch, optin=True)
    _, before_off, after_off = _run(tmp_path, monkeypatch, optin=False)
    assert before_on == before_off, "precondition: the same staged DUT"
    assert after_on == after_off == before_on, (
        "the whitebox opt-in must not mutate a shape #689 refuses")
