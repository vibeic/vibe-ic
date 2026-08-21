#!/usr/bin/env python3
"""LVS ROOT FIX — power-aware gate netlist emitter.

Proves the emitter turns a power-UNAWARE gate netlist (no VPWR/VGND, so netgen
can only match by DROPPING every cell's power pins) into a power-AWARE one whose
power connectivity mirrors the extracted layout, so netgen can reach a GENUINE
power-verified match. The transform must be additive-only (§4.05: never touch a
signal net), idempotent, PDK-derived (chip-AGNOSTIC), and produce parseable
Verilog. The genuine-match behaviour itself is validated LIVE against real netgen
in the run report; here we lock the deterministic transform.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lvs_power_aware_netlist_emit as E  # noqa: E402


# A minimal but realistic yosys-style sky130 gate netlist: non-ANSI header,
# named-connection instances, an empty-port spare cell, and a `wire` net that
# must survive the transform untouched (§4.05 signal-net guard).
_SKY_NETLIST = """\
module spm (clk,
    rst,
    p,
    y,
    x);
 input clk;
 input rst;
 output p;
 input y;
 input [31:0] x;
 wire _000_;
 sky130_fd_sc_hd__nor3_1 _222_ (.A(rst),
    .B(_000_),
    .Y(p));
 sky130_fd_sc_hd__a21oi_1 _223_ (.A1(y),
    .A2(x[0]),
    .B1(clk),
    .Y(_000_));
 (* keep *) sky130_fd_sc_hd__inv_1 spare_inverter_0 (); // spare tied_off
endmodule
"""

_GF_NETLIST = """\
module top (a, z);
 input a;
 output z;
 gf180mcu_fd_sc_mcu7t5v0__inv_1 g0 (.I(a),
    .ZN(z));
endmodule
"""


def _emit(text, pdk="sky130A", **kw):
    return E.emit_power_aware_netlist(text, pdk, **kw)


# ── core transform ─────────────────────────────────────────────────────────
def test_sky130_rails_and_pg_pins_injected():
    out, stats = _emit(_SKY_NETLIST)
    assert stats["pdk"] == "sky130A"
    assert stats["rails"] == ["VPWR", "VGND", "VPB", "VNB"]
    assert stats["modules_patched"] == 1
    # 2 real cells + 1 spare cell all get PG pins.
    assert stats["instances_patched"] == 3
    # the four rails are declared (as globalised wires by default).
    assert re.search(r"\bwire\s+VPWR,\s*VGND,\s*VPB,\s*VNB\s*;", out)
    # every std-cell instance now carries the four PG connections.
    for cell in ("_222_", "_223_", "spare_inverter_0"):
        m = re.search(re.escape(cell) + r"\s*\((?P<conn>.*?)\)\s*;", out, re.S)
        assert m, f"instance {cell} not found"
        conn = m.group("conn")
        for pg in ("VPWR", "VGND", "VPB", "VNB"):
            assert f".{pg}({pg})" in conn, f"{cell} missing .{pg}"


def test_signal_connections_preserved_section_4_05():
    # §4.05: the transform is additive — every original signal connection AND
    # the plain `wire _000_;` net must survive verbatim.
    out, _ = _emit(_SKY_NETLIST)
    for sig in (".A(rst)", ".B(_000_)", ".Y(p)", ".A1(y)", ".A2(x[0])",
                ".B1(clk)", ".Y(_000_)"):
        assert sig in out, f"lost signal connection {sig}"
    assert "wire _000_;" in out


def test_default_mode_does_not_add_top_ports():
    # The CORE-ONLY extracted layout exposes no power top ports; adding rails as
    # top ports makes netgen report `port errors`. Default must keep the module
    # port list signal-only (rails are globalised wires, not ports).
    out, _ = _emit(_SKY_NETLIST)
    header = out.split(");", 1)[0]
    assert "VPWR" not in header and "VGND" not in header
    assert "inout" not in out


def test_rails_as_ports_mode_adds_the_four_rail_ports():
    # Opt-in pad-ring / Caravel convention: rails ALSO become top-level inout
    # ports (satisfies flows whose layout exposes power pins).
    out, _ = _emit(_SKY_NETLIST, rails_as_ports=True)
    header = out.split(");", 1)[0]
    for r in ("VPWR", "VGND", "VPB", "VNB"):
        assert r in header, f"rail {r} not added to port list"
        assert f"inout {r};" in out


def test_idempotent():
    once, s1 = _emit(_SKY_NETLIST)
    twice, s2 = _emit(once)
    assert s2["instances_patched"] == 0
    assert s2["instances_already_pg"] == 3
    assert twice == once            # a second pass is a no-op


def test_gf180_rails():
    out, stats = _emit(_GF_NETLIST, pdk="gf180mcuD")
    assert stats["rails"] == ["VDD", "VSS", "VNW", "VPW"]
    assert stats["instances_patched"] == 1
    for pg in ("VDD", "VSS", "VNW", "VPW"):
        assert f".{pg}({pg})" in out


def test_unknown_pdk_is_skipped_unchanged():
    out, stats = _emit(_SKY_NETLIST, pdk="tsmc7")
    assert stats["skipped_reason"]
    assert out == _SKY_NETLIST      # text untouched on an unrecognised PDK


# ── LVS ROOT FIX (part 2): tie_wells_to_rails (physical well-tie) ────────────
def test_tie_wells_to_rails_sky130():
    # The wells tie to the rails and only the two real rails are declared —
    # the physical model that matches a DEF-direct extraction (VPB→VPWR,
    # VNB→VGND). Default behaviour (four distinct rails) is unchanged.
    out, stats = _emit(_SKY_NETLIST, tie_wells_to_rails=True)
    assert stats["instances_patched"] == 3
    # only the two real rails are declared as wires.
    assert re.search(r"\bwire\s+VPWR,\s*VGND\s*;", out)
    assert not re.search(r"\bwire\s+VPWR,\s*VGND,\s*VPB,\s*VNB\s*;", out)
    # every std-cell VPB pin ties to VPWR and VNB pin ties to VGND.
    for cell in ("_222_", "_223_", "spare_inverter_0"):
        m = re.search(re.escape(cell) + r"\s*\((?P<conn>.*?)\)\s*;", out, re.S)
        conn = m.group("conn")
        assert ".VPWR(VPWR)" in conn and ".VGND(VGND)" in conn
        assert ".VPB(VPWR)" in conn and ".VNB(VGND)" in conn
        assert ".VPB(VPB)" not in conn and ".VNB(VNB)" not in conn


def test_tie_wells_to_rails_gf180():
    out, stats = _emit(_GF_NETLIST, pdk="gf180mcuD", tie_wells_to_rails=True)
    assert re.search(r"\bwire\s+VDD,\s*VSS\s*;", out)
    # gf180: n-well (VNW) → VDD, p-well (VPW) → VSS.
    assert ".VNW(VDD)" in out and ".VPW(VSS)" in out
    assert ".VNW(VNW)" not in out and ".VPW(VPW)" not in out


def test_tie_wells_default_still_four_distinct_rails():
    # Regression guard: the DEFAULT (tie_wells_to_rails=False) is byte-identical
    # to the pre-part-2 behaviour — four distinct name-for-name rails.
    out, _ = _emit(_SKY_NETLIST, tie_wells_to_rails=False)
    assert re.search(r"\bwire\s+VPWR,\s*VGND,\s*VPB,\s*VNB\s*;", out)
    assert ".VPB(VPB)" in out and ".VNB(VNB)" in out


def test_tie_wells_signal_pins_preserved_section_4_05():
    # §4.05: even with wells tied, every ORIGINAL signal connection survives.
    out, _ = _emit(_SKY_NETLIST, tie_wells_to_rails=True)
    assert ".A(rst)" in out and ".Y(p))" in out
    assert ".A1(y)" in out and ".A2(x[0])" in out and ".B1(clk)" in out
    assert "wire _000_;" in out


def test_top_selects_only_named_module():
    two = _SKY_NETLIST + "\nmodule other (a);\n input a;\n" \
        " sky130_fd_sc_hd__buf_1 b0 (.A(a), .X(a));\nendmodule\n"
    out, stats = _emit(two, top="spm")
    assert stats["modules_seen"] == 2
    assert stats["modules_patched"] == 1        # only `spm` patched
    # `other`'s std cell is left without PG pins.
    other = out.split("module other", 1)[1]
    assert ".VPWR(VPWR)" not in other


def test_no_stdcell_module_left_alone():
    plain = "module rtl (a, b); input a; output b; assign b = a; endmodule\n"
    out, stats = _emit(plain)
    assert stats["modules_patched"] == 0
    assert out == plain


# ── parse check (iverilog -E if available, else a structural parse) ─────────
def _structural_ok(text: str) -> bool:
    """A lightweight structural sanity check: balanced module/endmodule and
    balanced parentheses."""
    if text.count("module") - text.count("endmodule") != text.count(
            "endmodule"):
        # crude: #module tokens (incl endmodule) minus 2*#endmodule == 0
        pass
    mods = len(re.findall(r"\bmodule\b", text))
    ends = len(re.findall(r"\bendmodule\b", text))
    return mods == ends and text.count("(") == text.count(")")


def test_emitted_netlist_parses(tmp_path):
    out, _ = _emit(_SKY_NETLIST)
    assert _structural_ok(out)
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not available for -E parse check")
    f = tmp_path / "pa.v"
    f.write_text(out)
    cp = subprocess.run([iv, "-E", "-o", str(tmp_path / "pp.v"), str(f)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, f"iverilog -E failed: {cp.stderr}"


def test_rails_as_ports_parses(tmp_path):
    out, _ = _emit(_SKY_NETLIST, rails_as_ports=True)
    assert _structural_ok(out)
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not available")
    f = tmp_path / "pa_ports.v"
    f.write_text(out)
    cp = subprocess.run([iv, "-E", "-o", str(tmp_path / "pp2.v"), str(f)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr


# ── CLI / file round-trip ───────────────────────────────────────────────────
def test_emit_to_file_and_main(tmp_path):
    src = tmp_path / "in.v"
    src.write_text(_SKY_NETLIST)
    out = tmp_path / "out.v"
    stats = E.emit_to_file(src, "sky130A", out, top="spm")
    assert out.is_file() and stats["instances_patched"] == 3
    jout = tmp_path / "stats.json"
    rc = E.main(["--netlist", str(src), "--pdk", "sky130A", "--top", "spm",
                 "--out", str(tmp_path / "m.v"), "--json", str(jout)])
    assert rc == 0 and jout.is_file()


def test_main_unknown_pdk_returns_nonzero(tmp_path):
    src = tmp_path / "in.v"
    src.write_text(_SKY_NETLIST)
    rc = E.main(["--netlist", str(src), "--pdk", "nope",
                 "--out", str(tmp_path / "o.v")])
    assert rc == 1


def test_scales_linearly_on_many_instances():
    # 5000 instances must not blow up (the real flow hits 200k+ fill cells; the
    # rebuild is single-pass O(N)).
    body = "\n".join(
        f" sky130_fd_sc_hd__inv_1 g{i} (.A(n{i}), .Y(n{i + 1}));"
        for i in range(5000))
    big = f"module big (a, z);\n input a; output z;\n{body}\nendmodule\n"
    out, stats = _emit(big)
    assert stats["instances_patched"] == 5000
    assert out.count(".VPWR(VPWR)") == 5000


# ── runner wiring: _try_power_aware_lvs (mocked netgen, no container) ───────
import phase3_one_shot_runner as R  # noqa: E402


def _prep_project(tmp_path):
    project = tmp_path / "proj"
    pdk = R._detect_pdk(Path("/nonexistent"), override="sky130A")
    top = "top"
    ext_dir = R._pl.extracted_dir(project)
    ext_dir.mkdir(parents=True, exist_ok=True)
    spice_out = ext_dir / f"{top}_extracted.sp"
    spice_out.write_text(".subckt top a\nX0 a sky130_fd_sc_hd__inv_1\n.ends\n")
    lvs_rpt = project / "reports" / "phase3" / "lvs.rpt"
    lvs_rpt.parent.mkdir(parents=True, exist_ok=True)
    # a real std-cell netlist so the emitter actually patches it.
    netlist = ext_dir / f"{top}_pnr.v"
    netlist.write_text(
        "module top (a, y);\n input a; output y;\n"
        " sky130_fd_sc_hd__inv_1 g0 (.A(a), .Y(y));\nendmodule\n")
    return project, top, pdk, spice_out, lvs_rpt, netlist


_PA_MATCH = ("Subcircuit summary:\nNumber of devices: 1  |Number of devices: 1\n"
             "Netlists match uniquely.\nFinal result: Circuits match uniquely.\n")
_PA_POWER_MISMATCH = ("Top level cell failed pin matching.\n"
                      "  VPWR|(no matching pin)\n"
                      "Final result: Netlists do not match.\n")


def test_wiring_power_aware_match_yields_power_verified(tmp_path, monkeypatch):
    project, top, pdk, spice_out, lvs_rpt, netlist = _prep_project(tmp_path)

    def fake_exec(container, cmd, timeout=None, **_):
        if "netgen -batch lvs" in cmd:
            return (0, _PA_MATCH, "")           # power-aware compare → MATCH
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    res = R._try_power_aware_lvs(
        project, top, pdk, "vibeic-eda", spice_out,
        "/c/top_extracted.sp", top, netlist, "/setup.tcl", lvs_rpt, None, 0.0)
    assert res is not None
    assert res.status == "PASS"
    assert res.extras.get("finding") == "LVS_MATCH_POWER_VERIFIED"
    assert res.extras.get("power_aware_signoff") is True
    # LVS ROOT FIX (part 2): the WELL-TIED power-aware netlist is tried FIRST
    # (matches a DEF-direct extraction whose wells are tied to the rails) — it
    # matched, so it is the emitted netlist and carries the physical well-tie.
    pa = R._pl.extracted_dir(project) / f"{top}_pwraware_welltied.v"
    txt = pa.read_text()
    assert pa.is_file() and ".VPWR(VPWR)" in txt
    assert ".VPB(VPWR)" in txt and ".VNB(VGND)" in txt   # wells tied to rails


def test_wiring_power_aware_mismatch_returns_none_falls_through(
        tmp_path, monkeypatch):
    # §4.05 / monotonicity: when the power-aware compare does NOT reach a genuine
    # match, the helper returns None so the caller falls through to the UNCHANGED
    # plain-netlist path (no regression, POWER_PIN_ONLY waiver stays the
    # fallback).
    project, top, pdk, spice_out, lvs_rpt, netlist = _prep_project(tmp_path)

    def fake_exec(container, cmd, timeout=None, **_):
        if "netgen -batch lvs" in cmd:
            return (1, _PA_POWER_MISMATCH, "")
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    res = R._try_power_aware_lvs(
        project, top, pdk, "vibeic-eda", spice_out,
        "/c/top_extracted.sp", top, netlist, "/setup.tcl", lvs_rpt, None, 0.0)
    assert res is None
    # canonical lvs.rpt is NOT overwritten by a non-matching power-aware attempt.
    assert not lvs_rpt.exists() or lvs_rpt.read_text() == ""


def test_wiring_no_stdcells_returns_none(tmp_path, monkeypatch):
    # a netlist with no PDK std cells → nothing to patch → None (fall through).
    project, top, pdk, spice_out, lvs_rpt, netlist = _prep_project(tmp_path)
    netlist.write_text("module top (a, y); input a; output y;"
                       " assign y = a; endmodule\n")
    called = {"netgen": False}

    def fake_exec(container, cmd, timeout=None, **_):
        if "netgen" in cmd:
            called["netgen"] = True
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    res = R._try_power_aware_lvs(
        project, top, pdk, "vibeic-eda", spice_out,
        "/c/top_extracted.sp", top, netlist, "/setup.tcl", lvs_rpt, None, 0.0)
    assert res is None
    assert called["netgen"] is False            # never even ran netgen
