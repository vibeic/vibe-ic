"""tests/test_digital_hardmacro_gen.py — step 37.5ip producer.

The producer's job is to REFUSE precisely. Every numbered precondition in its
own docstring has a case here, and each asserts BOTH the exit code and that
the JSON record was written — upstream's `pad.tcl` refuses with `exit 1` and a
printed message and leaves no machine-readable record, and not doing that is
the one place this producer is deliberately better than upstream.

The LEF is written by Magic and by nothing else, so what is tested here is the
TCL this producer hands it (against upstream's own `scripts/magic/lef.tcl`
shape) and the refusal to stage a pin-less abstract — not Magic itself.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "digital_hardmacro_gen.py"
sys.path.insert(0, str(PROG.parent))
import digital_hardmacro_gen as mod  # noqa: E402
from test_digital_hardmacro_check import build_gds  # noqa: E402


DEF_OK = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN macro_a ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 100000 50000 ) ;
PINS 5 ;
    - clk + NET clk + DIRECTION INPUT + USE SIGNAL
      + PORT
        + LAYER met2 ( -200 -200 ) ( 200 200 )
        + PLACED ( 200 10000 ) N ;
    - dout[0] + NET dout[0] + DIRECTION OUTPUT + USE SIGNAL
      + PORT
        + LAYER met2 ( -200 -200 ) ( 200 200 )
        + PLACED ( 99800 10000 ) N ;
    - dout[1] + NET dout[1] + DIRECTION OUTPUT + USE SIGNAL
      + PORT
        + LAYER met2 ( -200 -200 ) ( 200 200 )
        + PLACED ( 99800 12000 ) N ;
    - vpwr + NET vpwr + DIRECTION INOUT + USE POWER
      + PORT
        + LAYER met3 ( -200 -200 ) ( 200 200 )
        + PLACED ( 50000 49000 ) N ;
    - vgnd + NET vgnd + DIRECTION INOUT + USE GROUND
      + PORT
        + LAYER met3 ( -200 -200 ) ( 200 200 )
        + PLACED ( 50000 1000 ) N ;
END PINS
END DESIGN
"""


def make_project(tmp_path: Path, def_text: str = DEF_OK,
                 gds: bytes = None, name: str = "macro_a") -> Path:
    (tmp_path / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3/stage4/gds").mkdir(parents=True, exist_ok=True)
    if def_text is not None:
        (tmp_path / "phase3/stage3/pnr/routed.def").write_text(def_text)
    if gds is None:
        gds = build_gds(name, width_um=100.0, height_um=50.0)
    if gds is not None:
        (tmp_path / f"phase3/stage4/gds/{name}.gds").write_bytes(gds)
    return tmp_path


def run(project: Path, *extra):
    out = project / "gen.json"
    cp = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json", str(out), *extra],
        capture_output=True, text=True)
    rec = json.loads(out.read_text()) if out.exists() else None
    return cp, rec


# ───────────────────── the numbered refusals ───────────────────────────────

def test_no_def_is_refused_with_a_record(tmp_path):
    p = make_project(tmp_path, def_text=None)
    cp, rec = run(p)
    assert cp.returncode == 1
    assert rec["status"] == "REFUSED" and "no DEF" in rec["reason"]


def test_def_without_a_design_statement_is_refused(tmp_path):
    p = make_project(tmp_path, def_text=DEF_OK.replace("DESIGN macro_a ;", ""))
    cp, rec = run(p)
    assert cp.returncode == 1
    assert "DESIGN" in rec["reason"]


def test_no_signoff_gds_is_refused(tmp_path):
    p = make_project(tmp_path, gds=None)
    (p / "phase3/stage4/gds/macro_a.gds").unlink()
    cp, rec = run(p)
    assert cp.returncode == 1
    assert "sign-off GDS" in rec["reason"]


def test_gds_with_no_geometry_is_refused(tmp_path):
    p = make_project(tmp_path, gds=b"NOTAGDS!" * 64)
    cp, rec = run(p)
    assert cp.returncode == 1
    assert "no geometry" in rec["reason"]


def test_gds_top_cell_that_is_not_the_design_is_refused(tmp_path):
    """The abstracts would name a cell the layout does not contain."""
    p = make_project(tmp_path, gds=build_gds("some_other_cell"))
    cp, rec = run(p)
    assert cp.returncode == 1
    assert "does not contain" in rec["reason"]


def test_def_with_no_pins_is_refused(tmp_path):
    body = DEF_OK[:DEF_OK.index("PINS 5 ;")] + "END DESIGN\n"
    p = make_project(tmp_path, def_text=body)
    cp, rec = run(p)
    assert cp.returncode == 1
    assert "no PINS entry" in rec["reason"]
    # AND NOTHING WAS STAGED — a refusal must not leave a partial kit.
    assert not (p / "phase3/stage4/hardmacro").exists() or not list(
        (p / "phase3/stage4/hardmacro").iterdir())


def test_absent_magicrc_is_a_capability_gap_not_a_failure(tmp_path):
    """rc 2 — the capability is absent, which is not the design's fault and
    is not a success either."""
    empty = tmp_path / "no_pdk"
    empty.mkdir()
    p = make_project(tmp_path)
    cp, rec = run(p, "--pdk-root", str(empty))
    assert cp.returncode == 2
    assert rec["status"] == "SKIPPED_NO_CAPABILITY"
    assert "magicrc" in rec["reason"] or "magic" in rec["reason"]
    # the three views it CAN produce without Magic are still produced, and the
    # record says the LEF is not among them
    assert "macro_a.lef" not in rec["produced"]
    assert {"macro_a.gds", "macro_a.v", "macro_a.lib"} <= set(rec["produced"])


# ───────────────────── the views it emits ──────────────────────────────────

def test_interface_is_read_from_the_def_with_pg_classified(tmp_path):
    pins = mod.read_interface(DEF_OK)
    assert [p.name for p in pins] == ["clk", "dout[0]", "dout[1]",
                                      "vpwr", "vgnd"]
    assert [p.name for p in pins if p.is_pg] == ["vpwr", "vgnd"]
    assert [p.direction for p in pins][:2] == ["INPUT", "OUTPUT"]


def test_bus_range_is_derived_from_the_bits_the_def_carries():
    pins = mod.read_interface(DEF_OK)
    grouped = dict((b, r) for b, _d, r in mod.group_buses(pins))
    assert grouped["dout"] == (1, 0)
    assert grouped["clk"] is None


def test_verilog_view_omits_supplies_and_declares_the_bus(tmp_path):
    v = mod.emit_verilog("macro_a", mod.read_interface(DEF_OK))
    assert "module macro_a (" in v and "endmodule" in v
    assert "input wire clk" in v
    assert "output wire [1:0] dout" in v
    assert "vpwr" not in v.split("module")[1]     # not a PORT
    assert "vpwr, vgnd" in v                      # but NAMED in the header


def test_liberty_view_declares_the_interface_and_no_timing(tmp_path):
    lib = mod.emit_liberty("macro_a", mod.read_interface(DEF_OK))
    assert "cell (macro_a)" in lib
    assert "pg_pin (vpwr)" in lib and "pg_pin (vgnd)" in lib
    assert "bus (dout)" in lib and "pin (clk)" in lib
    # THE OMISSION IS DECLARED, not silent.
    assert "NO TIMING ARC IS DECLARED" in lib
    for forbidden in ("cell_rise", "cell_fall", "values ("):
        assert forbidden not in lib


def test_emitted_views_satisfy_the_gate_they_are_built_for(tmp_path):
    """The producer and the checker must agree about the convention: the
    Verilog view omits supplies and the Liberty declares them as pg_pins."""
    sys.path.insert(0, str(PROG.parent))
    import digital_hardmacro_check as gate

    pins = mod.read_interface(DEF_OK)
    lib = gate.parse_liberty(mod.emit_liberty("macro_a", pins))
    ver = gate.parse_verilog(mod.emit_verilog("macro_a", pins))
    assert lib["signal"] == {"clk", "dout"} == ver["ports"]
    assert lib["pg"] == {"vpwr", "vgnd"}


# ───────────────────── the Magic call, not Magic itself ────────────────────

def test_lef_tcl_follows_upstreams_shape(tmp_path):
    tcl = mod.build_lef_tcl("macro_a", "a.gds", "a.def", "out.lef",
                            full_lef=False, pinonly=False)
    # geometry from the GDS, PORTS from the DEF — the GDS-only route measured
    # 0 pins on a real signed-off design.
    assert "gds read a.gds" in tcl
    assert "def read a.def" in tcl
    assert tcl.index("gds read") < tcl.index("def read")
    # upstream's default abstraction knob
    assert "lef write out.lef -hide" in tcl


def test_lef_tcl_exposes_upstreams_two_other_knobs():
    full = mod.build_lef_tcl("m", "g", "d", "o", full_lef=True, pinonly=False)
    assert "-hide" not in full                    # MAGIC_WRITE_FULL_LEF
    pin = mod.build_lef_tcl("m", "g", "d", "o", full_lef=False, pinonly=True)
    assert "-hide" in pin and "-pinonly" in pin   # MAGIC_WRITE_LEF_PINONLY


def test_a_pinless_abstract_is_never_staged(tmp_path, monkeypatch):
    """MEASURED: the GDS-only route produced an outline plus obstructions and
    zero PINs. That looks like a delivered view and is not one, so it is not
    left on disk."""
    out = tmp_path / "macro_a.lef"

    def fake_run(cmd, **kw):
        work = Path(kw["cwd"])
        (work / "macro_a.lef").write_text(
            "MACRO macro_a\n  SIZE 100 BY 50 ;\n  OBS\n    LAYER m1 ;\n"
            "      RECT 0 0 100 50 ;\n  END\nEND macro_a\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mod.shutil, "which", lambda _n: "/usr/bin/magic")
    monkeypatch.setattr(mod, "_magicrc_for", lambda _r: "/x/y.magicrc")
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    gds = tmp_path / "in.gds"
    gds.write_bytes(build_gds("macro_a"))
    dfp = tmp_path / "in.def"
    dfp.write_text(DEF_OK)

    ok, why = mod.write_lef_with_magic("macro_a", gds, dfp, out, "/pdk",
                                       False, False)
    assert ok is False
    assert "NO `PIN` block" in why
    assert not out.exists()


def test_an_existing_kit_file_is_never_overwritten(tmp_path):
    p = make_project(tmp_path)
    hm = p / "phase3/stage4/hardmacro"
    hm.mkdir(parents=True)
    (hm / "macro_a.v").write_text("// a human wrote this\nmodule macro_a();\n"
                                  "endmodule\n")
    empty = tmp_path / "no_pdk"
    empty.mkdir()
    _cp, rec = run(p, "--pdk-root", str(empty))
    assert "macro_a.v (already present)" in rec["skipped"]
    assert "a human wrote this" in (hm / "macro_a.v").read_text()


def test_the_record_names_the_abstraction_policy_it_used(tmp_path):
    p = make_project(tmp_path)
    empty = tmp_path / "no_pdk"
    empty.mkdir()
    _cp, rec = run(p, "--pdk-root", str(empty), "--pinonly")
    assert rec["lef_policy"]["pinonly"] is True
    assert rec["lef_policy"]["hide"] is True
    assert "lef.tcl" in rec["lef_policy"]["mirrors"]


def test_chip_agnostic_source(tmp_path):
    """Through the repo's OWN guard, not a token list re-typed here."""
    sys.path.insert(0, str(PROG.parent))
    import source_chip_agnostic_check as guard
    staged = tmp_path / "programs"
    staged.mkdir()
    (staged / PROG.name).write_text(PROG.read_text())
    rc = guard.main([str(tmp_path), "--json", str(tmp_path / "agn.json")])
    findings = json.loads((tmp_path / "agn.json").read_text()).get(
        "findings", [])
    assert rc == 0 and not findings, findings


# ───────────── the wiring: runner invokes it, the GATE never does ──────────

def _runner_src() -> str:
    return (PROG.parent / "phase3_one_shot_runner.py").read_text()


def test_the_runner_invokes_this_producer(tmp_path):
    """Declared in step 37.5ip's `programs:` and dispatched by the runner.

    Measured before this wiring existed:
    `test_matrix_d1_wiring.py::test_probe_declared_programs_array_orphans_are_pinned`
    reddened with `('37.5ip', 'digital_hardmacro_gen')` as a NEW orphan — a
    step advertising a program nothing runs.
    """
    src = _runner_src()
    assert "def step_digital_hardmacro_gen(" in src
    assert 'PROGRAMS_DIR / "digital_hardmacro_gen.py"' in src
    assert "plan.append(step_digital_hardmacro_gen(project))" in src


def test_the_gate_never_invokes_this_producer():
    """A8's rule, and the reason it is a rule.

    `flow_compliance_check` is the phase-2+3 acceptance auditor. A8's GDS
    producer was briefly wired into A8's own gate and that was withdrawn on
    2026-07-28 after the audit was measured creating the very `.gds` its next
    two clauses then read — a step certifying its own output.
    """
    gate_src = (PROG.parent / "digital_hardmacro_check.py").read_text()
    assert "digital_hardmacro_gen" not in gate_src
    yaml_src = (PROG.parent.parent / "flow"
                / "phase1_phase2_phase3.yaml").read_text()
    block = yaml_src[yaml_src.index("id: 37.5ip"):]
    block = block[:block.index("id: 37.5ic")]
    gate_clause = block[block.index("gate:"):]
    assert "digital_hardmacro_gen" not in gate_clause
    assert "digital_hardmacro_check" in gate_clause


def test_the_runner_step_never_fails_the_run(tmp_path, monkeypatch):
    """A producer refusal is the GATE's business, not the run's exit code."""
    sys.path.insert(0, str(PROG.parent))
    import phase3_one_shot_runner as runner

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, seen["rc"], "line one\n", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    for rc, expect in ((0, "PASS"), (1, "SKIP"), (2, "ENV_UNAVAILABLE")):
        seen["rc"] = rc
        res = runner.step_digital_hardmacro_gen(tmp_path)
        assert res.status == expect, (rc, res.status)
        assert res.name == "digital_hardmacro_gen"
    # and it hands the producer the report path the flow names
    assert "--json" in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--json") + 1].endswith(
        "reports/phase3/digital_hardmacro_gen.json")
