#!/usr/bin/env python3
"""ORGANIC #745 ROUND-2 REOPEN — arith_oracle_tb_gen vacuous N=1 FALSE-PASS on
the PRODUCTION parametric serial-parallel multiplier shape.

The round-13 fix shipped a serial-DEFER path that was latent-broken: its only
protecting test injected a ``declaration.json`` (``size_param``) that the
production spec-to-rtl runner NEVER writes. On the real no-declaration path,
``_resolve_width`` fell through to "widest numeric port" — and for spm only the
1-bit serial control/data lines (clk/rst/y/p) are numeric while the real data
bus ``x`` is parametric — so width collapsed to 1, the SERIAL-DEFER guard
``if width > 1:`` was SKIPPED, and a 4-vector N=1 oracle shipped as PASS for a
32-bit serial-parallel multiplier (FALSE-PASS / TRUE_REGRESSION of #745's own
documented+tested contract).

CAPABILITY UPGRADE (repo-gatekeeper, direct-push): the round-2 fix originally
DEFERred the serial-parallel shape because the serial framing (bit-order +
latency) was thought not closed-form-derivable. It now emits a REAL,
SELF-CALIBRATING N-bit oracle: the golden is computed independently from the
declared function and the serial framing is DISCOVERED from the DUT stream vs
the golden (a wrong-product DUT matches no consistent framing → still fails).
The anti-false-pass invariant this file protects is UNCHANGED and asserted by
``_assert_real_serial_oracle``: the emitted oracle is NON-VACUOUS (declared at
the resolved datapath width N=32, never the 1-bit collapse) and falsifiable —
so a regression that re-collapsed the width to 1 (the original false-pass) still
fails.

This file pins:
  (1) NEW-PATH — the PRODUCTION shape (NO declaration.json, ``x`` parametric,
      ``y``/``p`` literal 1-bit) now EMITs a REAL non-vacuous N=32 self-cal
      oracle (was: vacuous N=1 false-pass; interim: DEFER).
  (2) §4.05 NO-LEAK — the genuine PARALLEL multiplier STILL EMITs a real oracle,
      and a no-oracle CLASS (CPU) STILL DEFERs (fail-closed unchanged).
  (3) #478 END-STATE — direct-write a tmp_path L9/L2 artifact set, invoke the
      REAL ``arith_oracle_tb_gen.py`` via subprocess, assert rc=0 and a
      non-vacuous oracle TB on disk.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import arith_oracle_tb_gen as aotg  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────
def _mk_project(root: Path, *, top: str, ports: list, l2: str,
                decl: dict | None = None) -> Path:
    """Write a minimal L2/L9 doc set. When ``decl`` is None NO declaration.json
    is written — that is the PRODUCTION shape the runner actually emits and the
    one the round-13 masking test never exercised."""
    proj = root / top
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L2_FRS.json").write_text(json.dumps(
        {"ic_name": top, "frs_sections": [{"content": l2}]}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        {"top_module": top, "top_ports": ports}))
    if decl is not None:
        (proj / "plugin_output").mkdir()
        (proj / "plugin_output" / "declaration.json").write_text(
            json.dumps(decl))
    return proj


def _oracle_tbs(project: Path) -> list:
    sd = project / "phase2" / "stage1" / "sim_full_stack"
    return sorted(sd.glob("tb_*_oracle.v")) if sd.is_dir() else []


def _assert_real_serial_oracle(project: Path, *, width: int = 32) -> str:
    """CAPABILITY UPGRADE (repo-gatekeeper, direct-push): the production
    serial-parallel shape (parametric parallel operand + bit-serial operand +
    bit-serial result) is no longer DEFERred — it now emits a REAL, self-
    calibrating N-bit oracle. This helper pins the ANTI-FALSE-PASS invariant the
    round-2 guard actually protects: the emitted oracle is NON-VACUOUS —
    declared at the resolved datapath width N (NOT the 1-bit collapse that was
    the original false-pass), with SEVERAL distinct golden constants and the
    self-calibration search that makes it falsifiable — NOT a 4-vector N=1
    always-pass. Returns the TB text for any further assertions."""
    tbs = _oracle_tbs(project)
    assert len(tbs) == 1, tbs
    tb = tbs[0].read_text()
    assert f"localparam integer N      = {width};" in tb, \
        "serial oracle collapsed to the wrong datapath width (vacuous-N regression)"
    assert "localparam integer N      = 1;" not in tb  # never the 1-bit collapse
    # a genuinely falsifiable oracle: several distinct golden constants + the
    # self-calibration search + the completion marker the runner greps.
    assert tb.count("_gv[") >= 8, "too few golden vectors — coverage too thin"
    assert "ORACLE_TB_DONE pass=" in tb
    assert "_drive_capture" in tb and "_best" in tb  # self-calibration present
    return tb


# the PRODUCTION spm topology: parallel parametric x, serial 1-bit y/p, NO decl.
_SPM_PORTS = [
    {"name": "clk", "direction": "input", "width": 1},
    {"name": "rst", "direction": "input", "width": 1},
    {"name": "x", "direction": "input",
     "width": "N-bit([size-1:0], parameter size 預設 32)",
     "width_symbolic": "size-1:0"},
    {"name": "y", "direction": "input", "width": 1},
    {"name": "p", "direction": "output", "width": 1},
]


# ── (1) NEW-PATH: production parametric-serial shape → REAL self-cal oracle ──
def test_production_no_declaration_parametric_serial_emits_real_oracle(tmp_path):
    """CAPABILITY UPGRADE: the exact reopen repro — spm L9 with a parametric
    ``x`` bus + 1-bit serial ``y``/``p`` and NO declaration.json — now emits a
    REAL, self-calibrating N=32 oracle (functional_verified path), NOT the
    vacuous N=1 oracle that was the original false-pass. The anti-false-pass
    invariant is preserved by _assert_real_serial_oracle (N=32, non-vacuous,
    falsifiable), so a regression that re-collapsed the width to 1 still fails."""
    project = _mk_project(tmp_path, top="spm", ports=_SPM_PORTS,
                          l2="p = (x * y) mod 2^N serial multiplier")
    # production path writes no declaration.json — the oracle self-calibrates
    # the serial framing, so no declaration is needed.
    assert not (project / "plugin_output" / "declaration.json").exists()
    assert not (project / "declaration.json").exists()

    rep, rc = aotg.generate(project, "digital_arithmetic_primitive")
    assert rc == 0, rep
    assert rep["verdict"] == "TB_EMITTED"
    assert rep.get("topology") == "serial_parallel"
    _assert_real_serial_oracle(project, width=32)


def test_resolve_width_does_not_collapse_to_one_with_parametric_bus(tmp_path):
    """Root-cause pin: with only 1-bit numeric ports + a parametric bus,
    _resolve_width must NOT return 1 (the collapse that disarmed the guard)."""
    project = _mk_project(tmp_path, top="spm", ports=_SPM_PORTS,
                          l2="p = (x * y) mod 2^N serial multiplier")
    _top, ports = aotg._load_top_ports(project)
    # x is recognized as a parametric (non-numeric, symbolic) bus, not None-only
    xp = next(p for p in ports if p["name"] == "x")
    assert xp.get("is_parametric") is True
    assert xp.get("numeric_width") is None
    w = aotg._resolve_width(project, ports)
    assert w != 1, "width collapsed to 1 — the serial-DEFER guard would re-arm"


# ── (2) §4.05 NO-LEAK: genuine parallel multiplier must STILL emit ───────────
def test_noleak_parallel_multiplier_still_emits_real_oracle(tmp_path):
    """The relaxation (DEFER on serial mix) must NOT block the genuinely-
    closed-form PARALLEL multiplier — all operands+result are full-width buses,
    so a real computed-golden oracle still ships (functional_verified=true)."""
    ports = [
        {"name": "x", "direction": "input", "width": 8},
        {"name": "y", "direction": "input", "width": 8},
        {"name": "p", "direction": "output", "width": 16},
    ]
    project = _mk_project(tmp_path, top="mult8", ports=ports,
                          l2="p = x * y mod 2^N parallel multiplier",
                          decl={"size_param": 8, "integer_encoding": "unsigned"})
    rep, rc = aotg.generate(project, "digital_arithmetic_primitive")
    assert rc == 0, rep
    assert rep["verdict"] == "TB_EMITTED"
    assert rep["width"] == 8 and rep["operator"] == "*"
    tbs = _oracle_tbs(project)
    assert len(tbs) == 1
    tb = tbs[0].read_text()
    # a real 16-bit-result computed golden, not a phantom 1-bit oracle
    assert "reg [15:0] _golden;" in tb
    assert aotg.compute_golden("*", 85, 85, 16, False) == 7225
    assert "_golden = 16'd7225;" in tb


def test_noleak_fully_parametric_parallel_multiplier_emits(tmp_path):
    """A FULLY-parametric PARALLEL multiplier (all ports parametric, none 1-bit
    serial) is still an unambiguous c = a*b — it must EMIT (resolved to the
    param default width), NOT be over-deferred by the serial mix guard."""
    ports = [
        {"name": "a", "direction": "input", "width": "WIDTH-bit([WIDTH-1:0])",
         "width_symbolic": "WIDTH-1:0"},
        {"name": "b", "direction": "input", "width": "WIDTH-bit([WIDTH-1:0])",
         "width_symbolic": "WIDTH-1:0"},
        {"name": "c", "direction": "output",
         "width": "2WIDTH-bit([2*WIDTH-1:0])", "width_symbolic": "2*WIDTH-1:0"},
    ]
    project = _mk_project(tmp_path, top="pmul", ports=ports,
                          l2="c = a * b parallel multiplier")
    rep, rc = aotg.generate(project, "digital_arithmetic_primitive")
    assert rc == 0 and rep["verdict"] == "TB_EMITTED"
    assert rep["width"] != 1            # resolved to the param default, not 1


def test_noleak_no_oracle_class_still_fail_closed(tmp_path):
    """§4.05 fail-closed unchanged: a no-oracle CLASS (CPU) must still DEFER even
    with a perfectly closed-form operator — the #654 connectivity cap stands."""
    ports = [
        {"name": "a", "direction": "input", "width": 8},
        {"name": "b", "direction": "input", "width": 8},
        {"name": "c", "direction": "output", "width": 8},
    ]
    project = _mk_project(tmp_path, top="cpu", ports=ports, l2="c = a + b")
    rep, rc = aotg.generate(project, "processor_cpu")
    assert rc == 2 and rep["verdict"] == "DEFER"
    assert _oracle_tbs(project) == []


# ── (3) #478 END-STATE: real program via subprocess, returncode assert ───────
def test_478_endstate_subprocess_production_serial_emits(tmp_path):
    """END-STATE via the REAL CLI: direct-write the production serial artifact
    set, invoke arith_oracle_tb_gen.py as a subprocess, and assert the CLI
    returns 0 (TB_EMITTED) and materializes exactly one NON-VACUOUS N=32 self-
    calibrating oracle on disk (never the vacuous N=1 PASS the round-2 guard
    protects against)."""
    project = _mk_project(tmp_path, top="spm", ports=_SPM_PORTS,
                          l2="p = (x * y) mod 2^N serial multiplier")
    prog = PROGRAMS / "arith_oracle_tb_gen.py"
    r = subprocess.run(
        [sys.executable, str(prog), str(project),
         "--ic-class", "digital_arithmetic_primitive"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert json.loads(r.stdout)["verdict"] == "TB_EMITTED"
    _assert_real_serial_oracle(project, width=32)


def test_478_endstate_subprocess_parallel_emits(tmp_path):
    """Companion END-STATE: the genuine parallel multiplier, invoked via the
    REAL CLI, returns 0 and materializes exactly one oracle TB on disk."""
    ports = [
        {"name": "x", "direction": "input", "width": 8},
        {"name": "y", "direction": "input", "width": 8},
        {"name": "p", "direction": "output", "width": 16},
    ]
    project = _mk_project(tmp_path, top="mult8", ports=ports,
                          l2="p = x * y mod 2^N parallel multiplier",
                          decl={"size_param": 8, "integer_encoding": "unsigned"})
    prog = PROGRAMS / "arith_oracle_tb_gen.py"
    r = subprocess.run(
        [sys.executable, str(prog), str(project),
         "--ic-class", "digital_arithmetic_primitive"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert json.loads(r.stdout)["verdict"] == "TB_EMITTED"
    assert len(_oracle_tbs(project)) == 1


# ── Step-2.7 remediation: prose-serial operand + fully-serial collapse ───────
def test_745r2_prose_serial_operand_emits_real_oracle(tmp_path):
    """A serial-parallel shape whose serial operand/result are marked serial by
    WIDTH PROSE (``bit-serial`` / ``serial``, width=None not numeric 1) is
    correctly recognised as the serial-parallel shape and emits a REAL,
    non-vacuous N=32 self-calibrating oracle (NOT a vacuous 1-bit oracle — the
    original prose-escape false-pass is still guarded by the N=32 assertion)."""
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "x", "direction": "input",
         "width": "N-bit([size-1:0], parameter size 32)",
         "width_symbolic": "size-1:0"},
        {"name": "y", "direction": "input", "width": "bit-serial"},
        {"name": "p", "direction": "output", "width": "serial"},
    ]
    proj = _mk_project(tmp_path, top="psm",
                       ports=ports, l2="p = (x * y) mod 2^N, 32-bit multiplier")
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 0 and rep.get("verdict") == "TB_EMITTED", (rc, rep)
    assert rep.get("topology") == "serial_parallel"
    _assert_real_serial_oracle(proj, width=32)


def test_745r2_fully_serial_multiplier_defers(tmp_path):
    """Finding (MED): a fully bit-serial multiplier (ALL data ports 1-bit) whose
    spec declares an N>1 datapath must DEFER — not emit a vacuous N=1 oracle."""
    ports = [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "x", "direction": "input", "width": 1},
        {"name": "y", "direction": "input", "width": 1},
        {"name": "p", "direction": "output", "width": 1},
    ]
    proj = _mk_project(tmp_path, top="fsm",
                       ports=ports, l2="p = (x * y) mod 2^N, a 32-bit multiplier")
    rep, rc = aotg.generate(proj, "digital_arithmetic_primitive")
    assert rc == 2 and rep.get("verdict") == "DEFER", (rc, rep)
    assert _oracle_tbs(proj) == []
