"""Regression: the DFT at-speed ATPG chain (DT1/DT2/DT3) must GRADE real
coverage on a genuinely TECH-MAPPED netlist, never silently self-skip on a
generic pre-map netlist or a degenerate scan cut.

Root cause (measured on spm × sky130A, 2026-07):
  * DT1 ran in phase2 on the GENERIC `netlist.v` (flops are `$_DFF_*` yosys
    primitives the OSS `fault` engine cannot cut) → 0 pseudo-PI/PO pairs →
    ENGINE_LIMITED → the gate BLOCKED it (an unverifiable self-skip).
  * DT2/DT3 ran in phase3 on the mapped netlist but REUSED a DEGENERATE cut
    (0 pairs, no residual flops) left by the pre-map path → ERROR "cut did not
    run correctly".

The fix makes the producer (a) select a genuinely tech-mapped netlist
(`discover_mapped_netlist` skips a `$_DFF_*` generic netlist) and (b) reject a
degenerate cut so it is REGENERATED from the mapped netlist (`_ensure_cut`).
Both are chip/PDK-AGNOSTIC. Proven end-to-end by the spm × sky130A re-run in
the gatekeeper report; these tests lock the PURE decision logic.
"""
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import transition_fault_atpg_run as tdf  # noqa: E402


GENERIC = """\
module spm(clk, D, Q);
  input clk; input D; output Q;
  \\$_DFF_P_  the_reg ( .C(clk), .D(D), .Q(Q) );
endmodule
"""

MAPPED = """\
module spm(clk, D, Q);
  input clk; input D; output Q;
  sky130_fd_sc_hd__dfxtp_1 the_reg ( .CLK(clk), .D(D), .Q(Q) );
endmodule
"""

# A REAL full-scan cut: every flop is turned into a `.d`/`.q` pseudo-PI/PO pair,
# and NO flop cell remains.
VALID_CUT = """\
module spm(clk, D, Q, the_reg, \\the_reg.d );
  input clk; input D; output Q;
  input the_reg;
  output \\the_reg.d ;
  assign \\the_reg.d = D;
  assign Q = the_reg;
endmodule
"""

# A DEGENERATE cut: the flops were neither cut (no `.d`/`.q` pairs) NOR left in
# place (no flop cell) — the exact shape `fault cut` leaves when it fails to
# detect the flops of a generic netlist.
DEGENERATE_CUT = """\
module spm(clk, D, Q);
  input clk; input D; output Q;
  assign Q = D;
endmodule
"""


# ── _is_generic_seq_netlist ────────────────────────────────────────────────

def test_generic_netlist_detected():
    assert tdf._is_generic_seq_netlist(GENERIC) is True


def test_mapped_netlist_not_generic():
    assert tdf._is_generic_seq_netlist(MAPPED) is False


def test_combinational_netlist_not_generic():
    assert tdf._is_generic_seq_netlist(
        "module u(a,b,y); input a,b; output y; assign y=a&b; endmodule") is False


# ── discover_mapped_netlist skips the generic candidate ─────────────────────

def _mk(project: Path, rel: str, text: str):
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_discover_prefers_mapped_over_generic(tmp_path):
    # Both present: the generic netlist.v must be SKIPPED for the mapped
    # <top>_synth.v — otherwise `fault cut` finds 0 flops on the pre-map netlist.
    _mk(tmp_path, "phase2/stage2/synth/netlist.v", GENERIC)
    _mk(tmp_path, "phase2/stage2/synth/spm_synth.v", MAPPED)
    got = tdf.discover_mapped_netlist(tmp_path)
    assert got == "phase2/stage2/synth/spm_synth.v"


def test_discover_uses_phase3_mapped_when_synth_is_generic(tmp_path):
    # Only a generic phase2 netlist + a mapped phase3 routed netlist: the mapped
    # one must win even though it lives under phase3.
    _mk(tmp_path, "phase2/stage2/synth/netlist.v", GENERIC)
    _mk(tmp_path, "phase3/stage3/pnr/spm_pnr.v", MAPPED)
    got = tdf.discover_mapped_netlist(tmp_path)
    assert got == "phase3/stage3/pnr/spm_pnr.v"


def test_discover_falls_back_to_generic_when_nothing_mapped(tmp_path):
    # No mapped netlist anywhere: return the generic one (last resort) so the
    # producer can still record an HONEST engine-limited note — never crash.
    _mk(tmp_path, "phase2/stage2/synth/netlist.v", GENERIC)
    got = tdf.discover_mapped_netlist(tmp_path)
    assert got == "phase2/stage2/synth/netlist.v"


# ── _ensure_cut reuse / regenerate decision (no Docker on the reuse path) ────

def _liberty_seq():
    # The design's Liberty declares its flop cell — the authoritative flop set.
    return {"sky130_fd_sc_hd__dfxtp_1"}


def test_ensure_cut_reuses_a_valid_cut(tmp_path, monkeypatch):
    # A real full-scan cut (has `.d/.q` pairs, no residual flop) is REUSED — the
    # producer must NOT re-cut, so Docker is never touched.
    _mk(tmp_path, "phase2/stage2/synth/spm_synth.v", MAPPED)
    _mk(tmp_path, "phase2/stage2/dft/cut_netlist.v", VALID_CUT)

    def _boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("regeneration attempted on a VALID cut")
    monkeypatch.setattr(tdf, "_run_in_docker", _boom)

    ok, msg = tdf._ensure_cut(
        tmp_path, "phase2/stage2/synth/spm_synth.v",
        "phase2/stage2/dft/cut_netlist.v", "clk", None, None, timeout=60,
        liberty_sequential=_liberty_seq())
    assert ok and "reused" in msg


def test_ensure_cut_regenerates_a_degenerate_cut(tmp_path, monkeypatch):
    # A DEGENERATE cut (0 pairs, no residual flop) on a SEQUENTIAL source must be
    # REGENERATED — the old reuse-on-'no residual flop' rule silently kept it and
    # every sequential design scored 0 pairs → a false ENGINE_LIMITED/ERROR.
    _mk(tmp_path, "phase2/stage2/synth/spm_synth.v", MAPPED)
    _mk(tmp_path, "phase2/stage2/dft/cut_netlist.v", DEGENERATE_CUT)

    calls = {"n": 0}

    def _fake_docker(project, cmd, timeout, pdk_dir=None, extra_mounts=None):
        # Stand in for `fault cut`: write a real cut so _ensure_cut returns ok.
        calls["n"] += 1
        (project / "phase2/stage2/dft/cut_netlist.v").write_text(VALID_CUT)
        return 0, "", ""
    monkeypatch.setattr(tdf, "_run_in_docker", _fake_docker)

    ok, msg = tdf._ensure_cut(
        tmp_path, "phase2/stage2/synth/spm_synth.v",
        "phase2/stage2/dft/cut_netlist.v", "clk", None, None, timeout=60,
        liberty_sequential=_liberty_seq())
    assert ok, msg
    assert calls["n"] == 1, "a degenerate cut must be regenerated, not reused"
    assert "ran fault cut" in msg


def test_ensure_cut_reuses_zero_pair_cut_on_combinational_source(tmp_path,
                                                                 monkeypatch):
    # A 0-pair cut is LEGITIMATE when the source netlist has no flops at all —
    # a combinational design must NOT trigger a pointless (and failing) re-cut.
    comb = "module u(a,b,y); input a,b; output y; assign y=a&b; endmodule\n"
    _mk(tmp_path, "phase2/stage2/synth/u_synth.v", comb)
    _mk(tmp_path, "phase2/stage2/dft/cut_netlist.v", comb)

    def _boom(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("re-cut attempted on a combinational design")
    monkeypatch.setattr(tdf, "_run_in_docker", _boom)

    ok, msg = tdf._ensure_cut(
        tmp_path, "phase2/stage2/synth/u_synth.v",
        "phase2/stage2/dft/cut_netlist.v", "clk", None, None, timeout=60,
        liberty_sequential=_liberty_seq())
    assert ok and "reused" in msg


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
