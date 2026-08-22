"""The SV-frontend fallback fired on EVERY failed synth, whatever the cause.

`SLANG_ERROR_SIGNATURES` contained ``"Executing Verilog-2005 frontend"``.
That string is not an error. It is yosys's NORMAL progress banner, printed
once per `read_verilog` invocation — measured on a trivial, syntactically
perfect module::

    $ yosys -p "read_verilog -sv /tmp/t_probe.v; synth -top t"
    1. Executing Verilog-2005 frontend: /tmp/t_probe.v
    2.21.1. Executing Verilog-2005 frontend: .../share/yosys/techmap.v

So for any attempt that used the default frontend, ``sig_hit`` was
UNCONDITIONALLY true::

    sig_hit = any(s in (default_log or "") for s in error_signatures)
    if sig_hit:
        return True, "default frontend errored with an SV signature"

i.e. a predicate that cannot be false. The error-signature half of the
decision never discriminated: the rule degenerated to "always retry when the
default attempt failed", and the recorded reason ASSERTED an SV error that
was never observed. A wall-clock timeout, an OOM kill and a missing-module
error were each re-run under the SV frontend and each labelled an SV
signature failure — misattributing the cause and burning the step's whole
wall budget a second time.

WHY IT HID: the existing honesty gate
``TestSharedSynthFrontendSelection::test_no_sv_no_signature_no_fallback``
passes ``default_log="ERROR: undefined module foo"`` — a hand-written
one-line log. No real yosys log looks like that; every real one opens with
the banner. The fixture omitted the very string that made the predicate
vacuous, so the gate went green against a log no run produces. These tests
therefore assert against REALISTIC logs that carry the banner.

Second defect pinned here: a wall-clock timeout surfaces as rc=124, which
satisfied ``default_failed`` exactly like a parse abort. Swapping the Verilog
frontend cannot buy wall clock, so the retry could not succeed.

chip-AGNOSTIC: synthetic module names and synthetic logs only.
"""
from __future__ import annotations

import importlib

sf = importlib.import_module("synth_frontend")

# Every real `read_verilog` log opens with this. That is the whole point.
_BANNER = "1. Executing Verilog-2005 frontend: /synthetic/gemm_tile.v\n"

_PLAIN_V = ["/synthetic/gemm_tile.v", "/synthetic/mac_cell.v"]
_SV_IN = ["/synthetic/pkg_top.sv"]

_TIMEOUT_LOG = _BANNER + (
    "4.23.2. Executing OPT_MERGE pass (detect identical cells).\n"
    "Removed a total of 201664 cells.\n"
    "4.23.4. Executing OPT_CLEAN pass (remove unused cells and wires).\n"
    "TIMEOUT after 300s: Command '['yosys', '-p', 'synth -top gemm_tile "
    "-flatten; techmap; opt; dffunmap; abc -g cmos2']' timed out after "
    "300 seconds"
)
_OOM_LOG = _BANNER + "terminate called after throwing 'std::bad_alloc'\nKilled"
_MISSING_MOD_LOG = _BANNER + (
    "ERROR: Module `\\some_missing_leaf' referenced in module `\\gemm_tile' "
    "in cell `\\u_leaf' is not part of the design."
)
_REAL_SV_LOG = _BANNER + "ERROR: syntax error, unexpected TOK_PACKAGE"
_SUCCESS_LOG = _BANNER + "Number of cells: 1400000"


class TestBannerIsNotAnErrorSignature:
    def test_banner_alone_is_not_a_signature(self):
        """The banner on its own must not classify a failure as SV."""
        need, reason = sf.decide_synth_frontend(
            _PLAIN_V, default_rc=1, default_netlist_exists=False,
            default_log=_BANNER + "ERROR: something entirely unrelated")
        assert need is False, (
            "yosys's progress banner must not select the SV fallback")
        assert "errored with an SV signature" not in reason

    def test_banner_not_in_signature_set(self):
        """Pin the membership itself: a non-error must not be a signature."""
        assert "Executing Verilog-2005 frontend" not in \
            sf.SLANG_ERROR_SIGNATURES

    def test_timeout_is_not_a_frontend_failure(self):
        """rc=124 is a wall cap. An SV retry cannot buy wall clock."""
        need, reason = sf.decide_synth_frontend(
            _PLAIN_V, default_rc=124, default_netlist_exists=False,
            default_log=_TIMEOUT_LOG)
        assert need is False
        assert "errored with an SV signature" not in reason
        assert "wall-clock cap" in reason

    def test_oom_is_not_an_sv_signature(self):
        need, reason = sf.decide_synth_frontend(
            _PLAIN_V, default_rc=137, default_netlist_exists=False,
            default_log=_OOM_LOG)
        assert need is False
        assert "errored with an SV signature" not in reason

    def test_missing_module_is_not_an_sv_signature(self):
        """A real design defect must stay visible, not be retried away."""
        need, reason = sf.decide_synth_frontend(
            _PLAIN_V, default_rc=1, default_netlist_exists=False,
            default_log=_MISSING_MOD_LOG)
        assert need is False
        assert "errored with an SV signature" not in reason


class TestGenuineSvStillFallsBack:
    """The paths the fallback exists for must be untouched."""

    def test_real_sv_abort_still_triggers(self):
        need, _ = sf.decide_synth_frontend(
            _SV_IN, default_rc=1, default_netlist_exists=False,
            default_log=_REAL_SV_LOG)
        assert need is True

    def test_sv_signature_on_plain_v_still_triggers(self):
        """A .v file carrying SV constructs still reaches the fallback."""
        need, _ = sf.decide_synth_frontend(
            _PLAIN_V, default_rc=1, default_netlist_exists=False,
            default_log=_BANNER + "ERROR: syntax error, unexpected TOK_TYPEDEF")
        assert need is True

    def test_sv_extension_on_failure_still_triggers(self):
        need, _ = sf.decide_synth_frontend(
            _SV_IN, default_rc=1, default_netlist_exists=False,
            default_log=_BANNER + "some unrelated error")
        assert need is True

    def test_design_property_beats_log_phrasing(self):
        """rtl_text_blob must win: real SV constructs, unhelpful log."""
        need, reason = sf.decide_synth_frontend(
            _PLAIN_V, default_rc=1, default_netlist_exists=False,
            default_log=_BANNER + "ERROR: unhelpful",
            rtl_text_blob="package my_pkg; endpackage\n")
        assert need is True
        assert "modern-SV constructs" in reason

    def test_clean_success_never_retries(self):
        need, reason = sf.decide_synth_frontend(
            _PLAIN_V, default_rc=0, default_netlist_exists=True,
            default_log=_SUCCESS_LOG)
        assert need is False
        assert "succeeded" in reason
