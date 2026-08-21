#!/usr/bin/env python3
"""#604 — a fixed-pinout wrapper DETERMINISTICALLY selects `fault chain
--skip-boundary`, so the internal scan chain is inserted WITHOUT the top-level
boundary-scan register.

Why this exists (MEASURED on caravel_user_project × sky130A): `fault chain`
defaults to wrapping every top-level port in a boundary-scan register. On a
wrapper whose die outline + pin placement are fixed by a parent's DEF template
(FP_DEF_TEMPLATE) — its ports connect to that parent, not to chip pads — the
606-cell register routed across the fixed 2920×3520 µm die at the functional
25 ns clock gave an SS-corner setup violation of −0.73 ns (TNS −11.63) and a
+707 % instance blow-up. `--skip-boundary` inserts the internal scan chain only
(the correct DFT for this class); the internal chain — and thus scan coverage —
is preserved.

These tests use SYNTHETIC configs/docs with names + numbers DIFFERENT from any
real chip ("top_wrap", "padframe_chip", "sub_blk", 1234x5678, 800x600) to prove
the selector reads the design's own INPUT and hardcodes NOTHING — no chip name,
PDK or SKU literal decides the flag.

flow-change-acceptance (this is a FLOW-level selector every DFT run passes
through):
  * BIDIRECTIONAL negative control — a fixed-pinout wrapper skips the boundary
    register; a padframe chip (no FP_DEF_TEMPLATE) KEEPS it. A test that only
    proved the positive would pass against a program that always returns True.
  * a sub-macro's own DEF template does NOT make the TOP fixed-pinout.
  * explicit on/off overrides are honoured regardless of the contract.
  * a detection failure DEGRADES LOUDLY to the legacy default (insert the
    boundary register) — a fixed-pinout misread must never SILENTLY drop DFT.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import floorplan_contract as FPC          # noqa: E402
import fault_scan_chain_insert as SCI     # noqa: E402


# ---------------------------------------------------------------------------
# helpers — a design's staged OpenLane input, chip-agnostic synthetic values
# ---------------------------------------------------------------------------
def _stage_config(project: Path, design: str, *, die, sizing="absolute",
                  def_template=None, pin_order=None,
                  subdir="input/design_src/openlane") -> Path:
    cfg = {
        "DESIGN_NAME": design,
        "VERILOG_FILES": [f"dir::rtl/{design}.v"],
        "FP_SIZING": sizing,
        "DIE_AREA": die,
    }
    if def_template:
        cfg["FP_DEF_TEMPLATE"] = def_template
    if pin_order:
        cfg["FP_PIN_ORDER_CFG"] = pin_order
    p = project / subdir / design / "config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))
    return p


# ===========================================================================
# 1. is_fixed_pinout_wrapper — the deterministic selector
# ===========================================================================
class TestFixedPinoutDetection:
    def test_fp_def_template_makes_a_wrapper_fixed_pinout(self, tmp_path):
        _stage_config(tmp_path, "top_wrap", die=[0, 0, 1234, 5678],
                      def_template="dir::fixed_dont_change/top_wrap.def",
                      pin_order="dir::pin_order.cfg")
        is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "top_wrap")
        assert is_fixed is True
        # evidence is read from the input, not fabricated
        assert ev["def_template"] == "fixed_dont_change/top_wrap.def"
        assert ev["def_template_design_name"] == "top_wrap"
        assert ev["fp_sizing"] == "absolute"
        assert ev["die_area_um"] == "1234x5678"

    def test_padframe_chip_without_template_keeps_boundary_scan(self, tmp_path):
        # NEGATIVE CONTROL: a real chip-top defines its own pads (no parent DEF
        # template). It must NOT be classified fixed-pinout, so the boundary
        # register stays. Without this the selector could always return True.
        _stage_config(tmp_path, "padframe_chip", die=[0, 0, 800, 600])
        is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "padframe_chip")
        assert is_fixed is False
        assert ev["def_template"] is None

    def test_sub_macro_template_does_not_make_the_top_fixed_pinout(self, tmp_path):
        # A sub-macro ships its OWN fixed template; the TOP being built does
        # not. Selecting --skip-boundary for the top off a child's template
        # would be wrong — the top's ports may well be real pads.
        _stage_config(tmp_path, "sub_blk", die=[0, 0, 200, 200],
                      def_template="dir::fixed_dont_change/sub_blk.def")
        is_fixed, _ev = FPC.is_fixed_pinout_wrapper(tmp_path, "padframe_chip")
        assert is_fixed is False

    def test_top_with_its_own_template_beside_a_sub_macro_is_fixed_pinout(
            self, tmp_path):
        _stage_config(tmp_path, "sub_blk", die=[0, 0, 200, 200],
                      def_template="dir::fixed_dont_change/sub_blk.def")
        _stage_config(tmp_path, "top_wrap", die=[0, 0, 1234, 5678],
                      def_template="dir::fixed_dont_change/top_wrap.def")
        is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "top_wrap")
        assert is_fixed is True
        assert ev["def_template_design_name"] == "top_wrap"

    def test_classic_config_tcl_template_is_read_too(self, tmp_path):
        # The classic OpenLane `config.tcl` grammar, not just JSON.
        p = tmp_path / "input" / "design_src" / "top_wrap" / "config.tcl"
        p.parent.mkdir(parents=True)
        p.write_text(
            'set ::env(DESIGN_NAME) "top_wrap"\n'
            'set ::env(FP_SIZING) "absolute"\n'
            'set ::env(DIE_AREA) "0 0 1234 5678"\n'
            'set ::env(FP_DEF_TEMPLATE) "dir::fixed_dont_change/top_wrap.def"\n')
        is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "top_wrap")
        assert is_fixed is True
        assert "top_wrap.def" in (ev["def_template"] or "")

    def test_no_config_at_all_is_not_fixed_pinout(self, tmp_path):
        (tmp_path / "input").mkdir()
        is_fixed, ev = FPC.is_fixed_pinout_wrapper(tmp_path, "top_wrap")
        assert is_fixed is False
        assert ev["all_def_templates"] == []

    def test_top_unknown_any_template_counts(self, tmp_path):
        # With no top named, any fixed template present is taken as the signal.
        _stage_config(tmp_path, "top_wrap", die=[0, 0, 1234, 5678],
                      def_template="dir::fixed_dont_change/top_wrap.def")
        is_fixed, _ev = FPC.is_fixed_pinout_wrapper(tmp_path, None)
        assert is_fixed is True


# ===========================================================================
# 2. decide_skip_boundary — mode resolution (auto / on / off / error)
# ===========================================================================
class TestDecideSkipBoundary:
    def test_auto_fixed_pinout_skips(self, tmp_path):
        _stage_config(tmp_path, "top_wrap", die=[0, 0, 1234, 5678],
                      def_template="dir::fixed_dont_change/top_wrap.def")
        skip, ev = SCI.decide_skip_boundary(tmp_path, "auto", "top_wrap")
        assert skip is True
        assert ev["mode"] == "auto"
        assert ev["is_fixed_pinout"] is True

    def test_auto_padframe_keeps_boundary(self, tmp_path):
        _stage_config(tmp_path, "padframe_chip", die=[0, 0, 800, 600])
        skip, ev = SCI.decide_skip_boundary(tmp_path, "auto", "padframe_chip")
        assert skip is False
        assert ev["mode"] == "auto"

    def test_explicit_on_always_skips(self, tmp_path):
        # No fixed-pinout contract at all — 'on' overrides anyway.
        _stage_config(tmp_path, "padframe_chip", die=[0, 0, 800, 600])
        skip, ev = SCI.decide_skip_boundary(tmp_path, "on", "padframe_chip")
        assert skip is True
        assert ev["mode"] == "on"

    def test_explicit_off_never_skips(self, tmp_path):
        # A fixed-pinout wrapper, but 'off' forces the legacy default (this is
        # exactly what the #604 control run uses to reproduce the violation).
        _stage_config(tmp_path, "top_wrap", die=[0, 0, 1234, 5678],
                      def_template="dir::fixed_dont_change/top_wrap.def")
        skip, ev = SCI.decide_skip_boundary(tmp_path, "off", "top_wrap")
        assert skip is False
        assert ev["mode"] == "off"

    def test_detection_failure_degrades_to_legacy_default(self, monkeypatch):
        # DEGRADE LOUDLY: if fixed-pinout detection raises, auto mode must fall
        # back to inserting the boundary register (never silently drop it) and
        # SAY why. A silent skip on a real padframe chip would delete its DFT.
        def _boom(_project, _top):
            raise RuntimeError("contract read blew up")
        monkeypatch.setattr(FPC, "is_fixed_pinout_wrapper", _boom)
        skip, ev = SCI.decide_skip_boundary(Path("/nonexistent"), "auto", "x")
        assert skip is False
        assert "detection_error" in ev
        assert ev["mode"] == "auto"


# ===========================================================================
# 3. the flag actually reaches the `fault chain` command
# ===========================================================================
class TestFlagReachesFaultChain:
    """The decision must land as an ACTUAL `--skip-boundary` argument, else the
    boundary register is inserted regardless of what the report claims. Capture
    the exact argv the producer hands to Docker."""

    def _mapped_netlist(self, n=3) -> str:
        body = "".join(
            f"  sky130_fd_sc_hd__dfxtp_1 _f{i}_ (.CLK(clk), .D(d{i}), .Q(q{i}));\n"
            for i in range(n))
        return ("module top_wrap (clk, d0, d1, d2, q0, q1, q2);\n"
                "  input clk, d0, d1, d2;\n  output q0, q1, q2;\n"
                f"{body}endmodule\n")

    def _run_and_capture(self, tmp_path, skip_mode):
        captured = {}

        def _fake_run_docker(project, cmd, timeout=600, pdk_dir=None):
            captured["cmd"] = list(cmd)
            # produce a plausible chained netlist so run_chain proceeds far
            # enough to record the decision, then measures a 3-flop chain.
            out = None
            for i, tok in enumerate(cmd):
                if tok == "-o":
                    out = cmd[i + 1]
            if out and out.startswith("/work/"):
                (project / out[len("/work/"):]).write_text(
                    "/* FAULT METADATA: '" +
                    json.dumps({"internalCount": 3, "boundaryCount": 0,
                                "order": [{"kind": "dff"}] * 3}) +
                    "' END FAULT METADATA */\n"
                    "module top_wrap (clk, sin, shift, test, tck, sout);\n"
                    "  input clk, sin, shift, test, tck; output sout;\n"
                    "endmodule\n")
            return 0, ("Internal scan chain successfully constructed. "
                       "Length: 3\nTotal scan-chain length:  3\n"), ""

        import fault_atpg_run as _fatpg
        nl = tmp_path / "phase2/stage2/synth/netlist.v"
        nl.parent.mkdir(parents=True)
        nl.write_text(self._mapped_netlist())
        # stage the fixed-pinout contract for auto mode
        _stage_config(tmp_path, "top_wrap", die=[0, 0, 1234, 5678],
                      def_template="dir::fixed_dont_change/top_wrap.def")
        # Patch the seam THROUGH THE REFERENCE THE PRODUCTION PATH USES.
        #
        # `run_chain` calls `_fatpg._run_docker(...)`, dereferencing the
        # `fault_atpg_run` object that `fault_scan_chain_insert` bound at ITS
        # import time. That is not necessarily the object this test's own
        # `import fault_atpg_run` returns: 27 files in this suite reload or pop
        # modules from `sys.modules`, so under whole-directory collection the
        # module exists TWICE and `SCI._fatpg is not sys.modules["fault_atpg_run"]`.
        #
        # Patching our copy then left the real one untouched, `run_chain` shelled
        # out for real, returned early at the liberty stage, and the fake was
        # never called at all. Measured on 764fea6df:
        #
        #     pytest <this file>                    14 passed
        #     pytest programs/tests -k <this class>  2 FAILED
        #         fatpg_is_sysmod     True    <- our copy is the sys.modules one
        #         sci_fatpg_is_fatpg  False   <- SCI's copy is a different object
        #
        # Going through `SCI._fatpg` cannot drift: it is by construction the
        # object whose attribute `run_chain` will look up.
        seam = SCI._fatpg
        orig = seam._run_docker
        seam._run_docker = _fake_run_docker
        try:
            SCI.run_chain(tmp_path, "phase2/stage2/synth/netlist.v",
                          "clk", "sky130", skip_boundary=skip_mode,
                          top_module="top_wrap")
        finally:
            seam._run_docker = orig
        # "the transport was never reached" and "the flag was absent" are
        # different failures; `captured.get("cmd", [])` reported the second when
        # it was the first, which is what made this red read as a flag bug for
        # as long as it did. Say which one happened.
        assert "cmd" in captured, (
            "run_chain returned without ever calling the docker transport, so "
            "no command was captured — this says nothing about the "
            "--skip-boundary flag. Check the early returns in run_chain "
            "(liberty resolution) and that `SCI._fatpg` is the patched module.")
        return captured["cmd"]

    def test_auto_fixed_pinout_passes_the_flag(self, tmp_path):
        cmd = self._run_and_capture(tmp_path, "auto")
        assert "chain" in cmd and "--skip-boundary" in cmd

    def test_off_does_not_pass_the_flag(self, tmp_path):
        cmd = self._run_and_capture(tmp_path, "off")
        assert "chain" in cmd and "--skip-boundary" not in cmd


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
