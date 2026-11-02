#!/usr/bin/env python3
"""D6 — RTL the design SUPPLIES is what gets staged. No generator replaces it.

ORGANIC #403 made one generator decline when the design ships its own build RTL:
`_try_deterministic_rtl_dispatch`. Its check sits behind that function's
`rtl_spec.json` lookup, so it never runs for a doc-driven design. The other
program-first generators in `step_rtl_gen` (serial-parallel multiplier,
canonical primitive, behavioural FSM, prompt-text registry emit) checked only
`phase2/stage1/rtl/`, never `input/`. On a doc-driven design they wrote their
own module first. `consume_reused_ip_rtl` runs after them and stages only into
an rtl/ that holds no design, so it skipped, and the supplied file was dropped
without any record.

MEASURED on main 76a277544 with the spm fixture below: `step_rtl_gen` returned
PASS `deterministic_generator=serial_parallel_mul_synth`, and consume returned
NOT_APPLICABLE "phase2/stage1/rtl/ already holds 1 RTL file(s)". The spm.v left
in rtl/ was the generator's, not the one in `input/vendor_rtl/`.

The rule the code follows now: when the design's input supplies a design source
(`reused_ip_rtl_consume.discover_provided_build_rtl`, restricted to .v/.sv),
every one of those generators DEFERs. rtl_gen ends in the class-registry branch,
and `step_reused_ip_consume` stages the supplied files byte for byte. Nothing
changes when the design supplies nothing.

Each guard is driven for real. The paired halves show each fixture still fires
when nothing is supplied, so a guard that never generates cannot pass here. The
"not a design source" cases (a testbench under tb/, a TB-stem file, a header)
show the definition of "supplied" is consume's, not a bare glob.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
for _p in (str(_PROGRAMS), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import design_one_shot_runner as R  # noqa: E402
from _prose_handoff_assertions import assert_prose_handoff  # noqa: E402
from test_serial_parallel_mul_synth import _SPM_PORTS, _mk_project  # noqa: E402
from test_b4_every_deterministic_emit_states_its_time_unit import (  # noqa: E402
    BEHAVIORAL_PROSE, CANONICAL_PULSE)
from test_organic403_generator_must_not_replace_shipped_rtl import (  # noqa: E402
    SPEC as TRUTH_TABLE_SPEC)

#: spm's class. It has no registry generator (rtl_gen=null), so once the
#: program-first generators decline, rtl_gen ends in the registry branch.
ARITH = "digital_arithmetic_primitive"

#: A supplied implementation that no generator would write: different ports,
#: an asynchronous active-low reset, and a marker comment.
SUPPLIED_SPM = (
    "// D6 marker: the implementation this design supplies\n"
    "module spm #(parameter bits = 8) (\n"
    "    input clk, input rst, input x, input [bits-1:0] a, output y);\n"
    "  reg [bits-1:0] acc;\n"
    "  always @(posedge clk or negedge rst)\n"
    "    if (!rst) acc <= 0; else acc <= {x, acc[bits-1:1]} ^ a;\n"
    "  assign y = acc[0];\n"
    "endmodule\n")
TB_SPM = ("module tb_spm;\n"
          "  reg clk, rst, x; reg [7:0] a; wire y;\n"
          "  spm dut(.clk(clk), .rst(rst), .x(x), .a(a), .y(y));\n"
          "endmodule\n")


def _supplied(module: str) -> str:
    return (f"// D6 marker: the implementation this design supplies\n"
            f"module {module} (input clk, output reg q);\n"
            f"  always @(posedge clk) q <= ~q;\n"
            f"endmodule\n")


@pytest.fixture(autouse=True)
def _isolated_runner_session(monkeypatch):
    """Each case models one runner process and leaves no atexit target."""
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)


def _spm_project(tmp_path: Path) -> Path:
    return _mk_project(
        tmp_path, ports=_SPM_PORTS,
        l2_text="serial-parallel multiplier: p = (x * y) mod 2^N")


def _prose_project(tmp_path: Path, name: str, prose: str) -> Path:
    root = tmp_path / name
    doc = root / "phase1" / "input_doc"
    doc.mkdir(parents=True)
    (doc / "design.md").write_text(prose)
    return root


def _supply(project: Path, rel_dir: str, name: str, text: str) -> Path:
    d = project / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(text)
    return f


def _rtl_sources(project: Path):
    d = project / "phase2" / "stage1" / "rtl"
    if not d.is_dir():
        return []
    return sorted(f.name for f in d.rglob("*")
                  if f.is_file() and f.suffix in (".v", ".sv"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── the case the brief names: spm.v supplied beside its own testbench ─────────

def test_supplied_spm_is_staged_byte_identical_and_its_testbench_is_not(
        tmp_path):
    """RED on main: the serial-parallel generator wrote rtl/spm.v first and
    consume skipped, so the staged spm.v was the generator's."""
    p = _spm_project(tmp_path)
    own = _supply(p, "input/vendor_rtl", "spm.v", SUPPLIED_SPM)
    _supply(p, "input/vendor_rtl/tb", "tb_spm.v", TB_SPM)

    gen = R.step_rtl_gen(p, ARITH)
    assert not (gen.extras or {}).get("deterministic_generator"), gen
    assert _rtl_sources(p) == [], (
        f"rtl_gen wrote RTL over a supplied design: {gen.status} {gen.detail}")
    # rtl_gen=null + input/vendor_rtl → the REUSED-IP hand-off, as before.
    assert gen.status == "PASS_WITH_WAIVERS", gen
    assert gen.extras.get("fallback_skill") == "catalog-glue-author", gen

    con = R.step_reused_ip_consume(p, "spm")
    assert con.status == "PASS", con
    assert con.extras["staged"] == ["spm.v"], con.extras
    assert _rtl_sources(p) == ["spm.v"]
    staged = p / "phase2" / "stage1" / "rtl" / "spm.v"
    assert _sha(staged) == _sha(own), "the staged spm.v is not the supplied one"
    mf = json.loads(
        (p / "phase2" / "stage1" / "rtl" / "SOURCE_MANIFEST.json").read_text())
    assert mf["staged_from_input"] == ["input/vendor_rtl/spm.v"], mf


# ── every program-first generator, through the full dispatch ────────────────
#
# (id, project builder, supply route, supplied module, generator that fires on
# the fixture when nothing is supplied). The behavioural prose is answered by
# `_try_phase1_behavioral_fsm_rtl`; with that one declined it is answered by
# `_try_spec_artifact_registry_rtl`, which is the "later generator" this case
# exists to catch.
CASES = [
    ("serial_parallel", lambda t: _spm_project(t),
     "input/rtl", "spm", "serial_parallel_mul_synth"),
    ("canonical", lambda t: _prose_project(t, "cp", CANONICAL_PULSE),
     "input/design_src/impl/rtl", "pulse_detect", "canonical_primitive_synth"),
    ("behavioral_fsm_then_registry",
     lambda t: _prose_project(t, "bf", BEHAVIORAL_PROSE),
     "input/vendor_rtl", "TopModule", "spec_artifact_registry"),
]


@pytest.mark.parametrize("build,route,module,generator",
                         [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_without_supplied_rtl_the_generator_still_emits(
        tmp_path, build, route, module, generator):
    """The paired half: each fixture really fires. Without it, a guard that
    never generates would pass every case below."""
    p = build(tmp_path)
    gen = R.step_rtl_gen(p, ARITH)
    if generator in {"canonical_primitive_synth", "spec_artifact_registry"}:
        source = (p / "phase1/input_doc/design.md").read_text()
        assert_prose_handoff(gen, source)
        expected_span = {"canonical_primitive_synth": (0, 101),
                         "spec_artifact_registry": (0, 65)}[generator]
        assert expected_span in [tuple(span["source_span"])
                                 for span in gen.extras["unaccounted_source_spans"]]
        assert _rtl_sources(p) == []
        return
    assert gen.status == "PASS", gen
    assert gen.extras.get("deterministic_generator") == generator, gen.extras
    assert _rtl_sources(p), "the generator emitted nothing"


@pytest.mark.parametrize("build,route,module,generator",
                         [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_no_generator_replaces_the_supplied_rtl(
        tmp_path, build, route, module, generator):
    """RED on main for every case: the first generator that fired owned rtl/."""
    p = build(tmp_path)
    own = _supply(p, route, f"{module}.v", _supplied(module))

    gen = R.step_rtl_gen(p, ARITH)
    assert not (gen.extras or {}).get("deterministic_generator"), gen
    assert _rtl_sources(p) == [], (
        f"{gen.extras.get('deterministic_generator')} wrote "
        f"{_rtl_sources(p)} over {own.relative_to(p)}")

    con = R.step_reused_ip_consume(p, module)
    assert con.extras["staged"] == [f"{module}.v"], con.extras
    assert _sha(p / "phase2" / "stage1" / "rtl" / f"{module}.v") == _sha(own)


# ── each generator on its own: the direct call declines ─────────────────────

def _direct_serial_parallel(tmp_path):
    p = _spm_project(tmp_path)
    return p, lambda: R._try_serial_parallel_mul_rtl(p, ARITH, 0.0)


def _direct_canonical(tmp_path):
    p = _prose_project(tmp_path, "cp", CANONICAL_PULSE)
    return p, lambda: R._try_canonical_primitive_rtl(p, 0.0)


def _direct_behavioral(tmp_path):
    p = _prose_project(tmp_path, "bf", BEHAVIORAL_PROSE)
    return p, lambda: R._try_phase1_behavioral_fsm_rtl(p, 0.0)


def _direct_registry_emit(tmp_path):
    p = _prose_project(tmp_path, "sar", BEHAVIORAL_PROSE)
    return p, lambda: R._try_spec_artifact_registry_rtl(
        p, 0.0, phase1_plain_text=BEHAVIORAL_PROSE)


DIRECT = [
    ("_try_serial_parallel_mul_rtl", _direct_serial_parallel),
    ("_try_canonical_primitive_rtl", _direct_canonical),
    ("_try_phase1_behavioral_fsm_rtl", _direct_behavioral),
    ("_try_spec_artifact_registry_rtl", _direct_registry_emit),
]


@pytest.mark.parametrize("drive", [d for _, d in DIRECT],
                         ids=[n for n, _ in DIRECT])
def test_each_generator_emits_when_nothing_is_supplied(tmp_path, drive):
    p, call = drive(tmp_path)
    res = call()
    if drive is _direct_registry_emit:
        assert_prose_handoff(res, BEHAVIORAL_PROSE)
        assert (0, 65) in [tuple(span["source_span"])
                           for span in res.extras["unaccounted_source_spans"]]
        assert _rtl_sources(p) == []
        return
    assert res is not None and res.status == "PASS", res
    assert _rtl_sources(p)


@pytest.mark.parametrize("drive", [d for _, d in DIRECT],
                         ids=[n for n, _ in DIRECT])
def test_each_generator_defers_when_the_design_supplies_rtl(tmp_path, drive):
    """RED on main for all four: each guarded rtl/ only."""
    p, call = drive(tmp_path)
    _supply(p, "input/rtl", "own_top.v", _supplied("own_top"))
    res = call()
    assert res is None, res
    assert _rtl_sources(p) == []


# ── what is NOT a supplied design source ────────────────────────────────────
#
# Each of these is present under input/ and each is something consume would
# never stage as a design. Declining for them would leave rtl/ with no design,
# which is worse than generating.
NOT_SOURCES = [
    ("testbench_dir", "input/vendor_rtl/tb", "tb_spm.v", TB_SPM),
    ("testbench_stem", "input/rtl", "spm_tb.v", TB_SPM),
    ("header_only", "input/rtl", "spm_defs.vh", "`define SPM_BITS 8\n"),
]


@pytest.mark.parametrize("rel_dir,name,text", [c[1:] for c in NOT_SOURCES],
                         ids=[c[0] for c in NOT_SOURCES])
def test_input_that_is_not_a_design_source_does_not_stop_the_generator(
        tmp_path, rel_dir, name, text):
    p = _spm_project(tmp_path)
    _supply(p, rel_dir, name, text)
    gen = R.step_rtl_gen(p, ARITH)
    assert gen.status == "PASS", gen
    assert gen.extras.get("deterministic_generator") == \
        "serial_parallel_mul_synth", gen.extras
    assert _rtl_sources(p) == ["spm.v"]


def test_the_rtl_spec_dispatcher_uses_the_same_definition(tmp_path):
    """RED on main. The #403 probe globbed every candidate dir without the
    testbench screen, so a design whose only input RTL is a testbench DECLINED
    generation, consume then staged nothing, and rtl/ was left empty."""
    stage = tmp_path / "phase2" / "stage1"
    stage.mkdir(parents=True)
    # #403's own fixture: an invented spec may simply not dispatch.
    (stage / "rtl_spec.json").write_text(json.dumps(TRUTH_TABLE_SPEC))
    _supply(tmp_path, "input/vendor_rtl/tb", "tb_top.v",
            "module tb_top; endmodule\n")
    res = R._try_deterministic_rtl_dispatch(tmp_path, 0.0)
    assert res is not None and res.status == "PASS", res
    assert _rtl_sources(tmp_path) == ["TopModule.sv"]
