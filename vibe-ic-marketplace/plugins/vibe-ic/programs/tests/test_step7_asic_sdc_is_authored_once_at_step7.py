"""FX_STEP7_ASIC_SDC: the ASIC SDC is authored ONCE, at step 7, and step 15
reads it.

MEASURED (lane lls W23: spm x gf180mcuD, HARDMACRO, main 76a277544): step 7
FAILed on its own because its declared output `phase2/stage2/constraints/*.sdc`
was never produced. The ASIC SDC was authored inside `step_pnr` (and a second
copy of the same chain inside `step_prelayout_signoff`), and step 7's file was
written only when the design staged an SDC.

The split, with its evidence: every line of the SDC is design intent known at
step 7 (clock, I/O delays, the design's exceptions, the fanout ladder, liberty
units / DRV limits). ONE input is PnR-time -- the supply ports the pad-ring
producer (15.5ic) proves, excluded from the signal-only DRV scope -- and that
is a NAMED derivation `step_pnr` records, not a second author.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TESTS = Path(__file__).resolve().parent
PROGRAMS = TESTS.parent
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R                       # noqa: E402
from _ppa import timing as T                              # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "fx_step7_prelayout_fixtures", TESTS / "test_prelayout_signoff_before_pnr.py")
PL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PL)

TOP = "chip_top"
CONS = Path("phase2/stage2/constraints")


def _project(tmp_path: Path) -> Path:
    """A design with L8 clock data (25 ns on `clk`) and NO staged SDC."""
    proj = tmp_path / "proj"
    docs = proj / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clock_domains": [{"name": "clk", "source_pin": "clk",
                           "role": "primary", "period_ns": 25.0}]}))
    return proj


def _pdk(monkeypatch, drv=None):
    pdk = PL._corner_pdk(monkeypatch, "/foss/pdks/x/nom.lib")
    if drv is not None:
        monkeypatch.setattr(R, "_liberty_drv_limits", lambda *a, **k: dict(drv))
    return pdk


def _step7(proj, pdk):
    res = R.step_prelayout_signoff(proj, TOP, pdk, "some-container")
    assert res.status == "PASS", res.detail
    return res


def _record(proj):
    return json.loads((proj / CONS / T.ASIC_SDC_RECORD).read_text())


_DRV = {"max_transition_ns": 1.5, "max_capacitance_pf": 0.2}


def _pad_record(proj):
    rec = proj / "reports" / "phase3" / "io_pad_chip_top.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({
        "verdict": "WROTE",
        "power_pad_plan": {"domain_topology": "single_domain",
                           "power_net": "VDD", "ground_net": "VSS"}}))
    return rec


@pytest.mark.parametrize("change", ["pad", "other_input", "already_stale"])
def test_prepnr_refreshes_only_its_own_pad_change_through_step7(tmp_path, monkeypatch, change):
    from dataclasses import dataclass
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    netlist = proj / "phase2/stage2/synth/chip_top_synth.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module chip_top(input clk); endmodule\n")
    pad = _pad_record(proj)
    T.emit_step7_asic_sdc(R, proj, TOP, pdk, "some-container")
    before = (proj / CONS / T.ASIC_SDC_RECORD).read_bytes()
    l8 = proj / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
    if change == "already_stale":
        l8.write_text(l8.read_text().replace("25.0", "40.0"))

    def produce_pad(*a, **kw):
        pad.write_text(pad.read_text() + "\n")
        if change == "other_input":
            l8.write_text(l8.read_text().replace("25.0", "40.0"))
        return R.StepResult("io_pad_chip_top_gen", "PASS", 0.0, "current pad producer")

    @dataclass
    class Geometry:
        die_w: int = 100
        die_h: int = 100
        core_pad: int = 10

    monkeypatch.setattr(R, "_padring_producer_dispatch", produce_pad)
    monkeypatch.setattr(R, "_chip_path_requests_pad_ring", lambda *a: False)
    monkeypatch.setattr(R, "_prepnr_floorplan", lambda *a: Geometry())
    result = R.step_prepnr(proj, TOP, pdk, "some-container", "auto", .4)
    if change == "pad":
        assert result.status == "PASS", result.detail
        assert result.extras["step7_refresh"]["path"] == str(CONS / f"{TOP}.asic.sdc")
        assert T.read_step7_asic_sdc(R, proj, TOP, pdk)[0] is not None
        assert (proj / CONS / T.ASIC_SDC_RECORD).read_bytes() != before
    else:
        assert result.status == "NOT_MEASURED", result.detail
        assert "SDC_SEAM_PENDING" in result.detail
        assert "step7_refresh" not in result.extras
        assert (proj / CONS / T.ASIC_SDC_RECORD).read_bytes() == before


# --------------------------------------------------------------------------- #
# RED on main: step 7's declared output is absent after step 7
# --------------------------------------------------------------------------- #
def test_step7_writes_its_declared_sdc_when_the_design_stages_none(
        tmp_path, monkeypatch):
    proj = _project(tmp_path)
    res = _step7(proj, _pdk(monkeypatch))
    sdcs = sorted((proj / CONS).glob("*.sdc"))
    assert [p.name for p in sdcs] == [f"{TOP}.asic.sdc"], sdcs
    text = sdcs[0].read_text()
    assert "-period 25" in text, text[:500]
    rec = _record(proj)
    assert rec["step"] == 7 and rec["path"] == str(CONS / f"{TOP}.asic.sdc")
    assert rec["sha256"] == T._sha256_text(text)
    assert str(proj / rec["path"]) in res.output_files
    # never laundered into "design-staged"
    assert R._resolve_staged_silicon_sdc(proj) is None
    # the pre-layout STA reads the very deck step 7 wrote
    deck = (proj / "phase3/stage3/pnr/constraint.sdc").read_text()
    assert T._sha256_text(deck) == rec["deck_sha256"]


def test_a_design_staged_sdc_keeps_its_canonical_name(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    (proj / "input/constraints").mkdir(parents=True)
    (proj / "input/constraints/clock.sdc").write_text(PL._EDGE_LLM_ACCEL_SDC)
    _step7(proj, _pdk(monkeypatch))
    rec = _record(proj)
    assert rec["design_staged"] is True
    assert rec["path"] == str(CONS / f"{TOP}.sdc")
    assert rec["staged_sdc"] == "input/constraints/clock.sdc"
    assert not (proj / CONS / f"{TOP}.asic.sdc").exists()


def test_removed_design_sdc_cannot_return_from_an_old_step7_copy(
        tmp_path, monkeypatch):
    """The old generated <top>.sdc remains flow owned after the record moves."""
    proj = _project(tmp_path)
    staged = proj / "input/constraints/clock.sdc"
    staged.parent.mkdir(parents=True)
    staged.write_text("create_clock -name core -period 10 [get_ports clk]\n")
    pdk = _pdk(monkeypatch)

    _step7(proj, pdk)
    first = _record(proj)
    old_copy = proj / first["path"]
    assert first["design_staged"] is True
    assert old_copy.name == f"{TOP}.sdc"
    assert "-period 10" in old_copy.read_text()

    staged.unlink()
    _step7(proj, pdk)
    second = _record(proj)
    assert old_copy.exists()
    assert second["design_staged"] is False
    assert second["path"] == str(CONS / f"{TOP}.asic.sdc")
    assert "-period 25" in (proj / second["path"]).read_text()

    _step7(proj, pdk)
    third = _record(proj)
    assert third["design_staged"] is False
    assert third["staged_sdc"] is None
    assert "-period 25" in (proj / third["path"]).read_text()
    assert R._resolve_staged_silicon_sdc(proj) is None


# --------------------------------------------------------------------------- #
# step 15 READS step 7's file; it does not author
# --------------------------------------------------------------------------- #
def test_pnr_loads_step7s_file_and_never_calls_the_author(tmp_path,
                                                         monkeypatch):
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    rec = _record(proj)

    def _no_second_author(*a, **k):
        raise AssertionError("step_pnr re-authored the SDC")
    monkeypatch.setattr(T, "author_asic_sdc", _no_second_author)
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert got["regenerated"] is None and got["derivation"] is None
    assert got["step7_sha256"] == rec["sha256"]
    assert T._sha256_text(got["text"]) == rec["deck_sha256"]


def test_step_pnr_itself_contains_no_sdc_author():
    """The inline author is gone from `step_pnr`: it calls
    `asic_sdc_for_pnr`, and none of the authoring builders."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "step_pnr")
    called = {n.func.id if isinstance(n.func, ast.Name) else n.func.attr
              for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, (ast.Name, ast.Attribute))}
    assert "asic_sdc_for_pnr" in called
    assert not called & {"_build_auto_silicon_sdc", "_ensure_staged_sdc_drv",
                         "_scale_sdc_to_liberty_units", "author_asic_sdc"}


# --------------------------------------------------------------------------- #
# windows / old projects: regenerate through the SAME producer, and say so
# --------------------------------------------------------------------------- #
def test_an_old_project_without_step7_sdc_is_regenerated_by_its_producer(
        tmp_path, monkeypatch):
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert got["regenerated"] and "no step-7 record" in got["regenerated"]
    assert (proj / CONS / f"{TOP}.asic.sdc").is_file()
    assert _record(proj)["sha256"] == got["step7_sha256"]


def test_a_step7_file_changed_after_step7_is_regenerated_not_trusted(
        tmp_path, monkeypatch):
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    f = proj / CONS / f"{TOP}.asic.sdc"
    f.write_text(f.read_text() + "set_false_path -from [get_ports x]\n")
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert "changed after step 7" in got["regenerated"]
    assert "set_false_path -from [get_ports x]" not in got["text"]


# --------------------------------------------------------------------------- #
# the honest split: design intent at step 7, the pad-ring supply ports at PnR
# --------------------------------------------------------------------------- #
def test_step7_is_design_intent_even_with_a_stale_pad_record(tmp_path,
                                                             monkeypatch):
    proj = _project(tmp_path)
    _pad_record(proj)                      # a previous run's 15.5ic record
    _step7(proj, _pdk(monkeypatch, drv=_DRV))
    text = (proj / CONS / f"{TOP}.asic.sdc").read_text()
    assert "set_max_transition" in text
    assert "producer-proven supply ports excluded" not in text


def test_the_pad_ring_supply_ports_are_a_named_pnr_time_derivation(
        tmp_path, monkeypatch):
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch, drv=_DRV)
    _step7(proj, pdk)
    step7_text = (proj / CONS / f"{TOP}.asic.sdc").read_text()
    rec = _pad_record(proj)
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    d = got["derivation"]
    assert d["name"] == T.ASIC_SDC_DERIVATION
    assert d["supply_ports"] == ["VDD", "VSS"]
    assert d["from_record"] == "reports/phase3/io_pad_chip_top.json"
    assert d["from_record_sha256"] == T._sha256_text(rec.read_text())
    assert d["base_deck_sha256"] == _record(proj)["deck_sha256"]
    assert "producer-proven supply ports excluded" in got["text"]
    assert d["deck_sha256"] == T._sha256_text(got["text"])
    # step 7's file is not rewritten by the PnR-time derivation
    assert (proj / CONS / f"{TOP}.asic.sdc").read_text() == step7_text


# --------------------------------------------------------------------------- #
# the step-7 deck never feeds itself back as a clock source
# --------------------------------------------------------------------------- #
def test_the_clock_collector_never_reads_step7s_own_deck(tmp_path):
    proj = _project(tmp_path)
    (proj / CONS).mkdir(parents=True)
    (proj / CONS / f"{TOP}.asic.sdc").write_text(
        "create_clock -name clk -period 7.0 [get_ports clk]\n")
    assert R._phase2_emitted_period_ns(proj, top=TOP) is None



# --------------------------------------------------------------------------- #
# the fanout ladder reads the run's OWN standard-cell library at step 7
# --------------------------------------------------------------------------- #
_LIB = ("/foss/pdks/ciel/gf180mcu/gf180mcuD/libs.ref/"
        "gf180mcu_fd_sc_mcu7t5v0/lib/gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00.lib")
_L9_FANOUT_TABLE = """# L9 constraints

## Synthesis Fanout Limit

| library | `MAX_FANOUT_CONSTRAINT` |
|---|---|
| `sky130_fd_sc_ls` | 5 |
| `gf180mcu_*` | 4 |
| 其他 | 工具預設 |
"""


def test_the_std_cell_library_comes_from_the_resolved_liberty(tmp_path):
    """MEASURED on spm x gf180mcuD (DIE): with no liberty, the resolver read
    the pad-ring record's IO-library paths and answered `gf180mcu_fd_io`."""
    proj = _project(tmp_path)
    rec = _pad_record(proj)
    rec.write_text(json.dumps(dict(json.loads(rec.read_text()), io_lefs=[
        "/foss/pdks/x/libs.ref/gf180mcu_fd_io/lib/gf180mcu_fd_io__tt.lib"])))
    assert R._active_std_cell_library(proj, "gf180mcuD") == "gf180mcu_fd_io"
    assert R._active_std_cell_library(proj, "gf180mcuD", _LIB) == \
        "gf180mcu_fd_sc_mcu7t5v0"


def test_step7_applies_l9s_per_library_fanout_cap(tmp_path, monkeypatch):
    """The cap the design declares for its library reaches step 7's SDC
    (before: missed at step 7, found at PnR only through the IO library)."""
    proj = _project(tmp_path)
    (proj / "input/docs").mkdir(parents=True)
    (proj / "input/docs/L9_constraints_floorplan.md").write_text(_L9_FANOUT_TABLE)
    pdk = PL._corner_pdk(monkeypatch, _LIB)
    monkeypatch.setattr(R, "_liberty_drv_limits", lambda *a, **k: dict(_DRV))
    _step7(proj, pdk)
    text = (proj / CONS / f"{TOP}.asic.sdc").read_text()
    assert "set_max_fanout 4 [current_design]" in text, text[-1200:]


def test_the_pnr_derivation_changes_only_the_drv_scope(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    (proj / "input/docs").mkdir(parents=True)
    (proj / "input/docs/L9_constraints_floorplan.md").write_text(_L9_FANOUT_TABLE)
    pdk = PL._corner_pdk(monkeypatch, _LIB)
    monkeypatch.setattr(R, "_liberty_drv_limits", lambda *a, **k: dict(_DRV))
    _step7(proj, pdk)
    base = T.read_step7_asic_sdc(R, proj, TOP, pdk)[0]["text"]
    _pad_record(proj)
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert got["derivation"]["applied"] is True
    removed = [l for l in base.splitlines() if l not in got["text"].splitlines()]
    assert all("[current_design]" in l or l.startswith("#") for l in removed), \
        removed
    assert "set_max_fanout 4 $_vibeic_drv_signal_in_ports" in got["text"]
    assert "set_max_fanout 10" not in got["text"]


# =========================================================================== #
# review_wave7 (step 7)
# =========================================================================== #
def test_the_io_delay_contract_reaches_pnr_under_its_own_key(tmp_path,
                                                            monkeypatch):
    """MAJOR: an `rt.` rename also hit the dict KEY ("rt.io_delay_contract"),
    so step_pnr's `_asic.get("io_delay_contract")` was always None and
    reports/phase3/io_delay_contract.json was never written again."""
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    io_ns, _ = R._declared_io_delay_ns(proj, R._resolve_clock_spec(proj)[0])
    assert got["io_delay_contract"] == dict(
        R.io_delay_contract(io_ns, 2.0, R.io_delay_source()),
        schema="vibe-ic/io-delay-contract/1")
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    step_pnr_src = src.split("def step_pnr(", 1)[1].split("\ndef ", 1)[0]
    assert '_asic.get("io_delay_contract")' in step_pnr_src


def test_step7_never_clobbers_the_pnr_deck(tmp_path, monkeypatch):
    """MAJOR: step 7 overwrote pnr/constraint.sdc every run, BEFORE the PnR
    cache decision; on a cache hit the derived (pad-ring-scoped) deck was
    gone. The PnR deck is written only when absent."""
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch, drv=_DRV)
    _step7(proj, pdk)
    _pad_record(proj)
    derived = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")["text"]
    deck = proj / "phase3/stage3/pnr/constraint.sdc"
    deck.write_text(derived)                   # what step_pnr leaves behind
    _step7(proj, pdk)                          # a re-run, cache hit next
    assert deck.read_text() == derived
    assert "producer-proven supply ports excluded" in deck.read_text()


def test_a_legacy_design_sdc_is_never_overwritten(tmp_path, monkeypatch):
    """MAJOR: when the design's own SDC IS the legacy constraints/<top>.sdc,
    step 7 wrote its rescaled, stamped deck over it; the next run read that
    back as design input and rescaled it again. Two runs under a ps liberty:
    the design file is byte-identical and the period is the same."""
    lib = tmp_path / "ps.lib"
    lib.write_text('library (ps_lib) {\n  time_unit : "1ps";\n'
                   '  capacitive_load_unit (1,ff);\n}\n')
    proj = _project(tmp_path)
    legacy = proj / CONS / f"{TOP}.sdc"
    legacy.parent.mkdir(parents=True)
    design = "create_clock -name core_clock -period 10.0 [get_ports clk]\n"
    legacy.write_text(design)
    pdk = PL._corner_pdk(monkeypatch, str(lib))
    periods = []
    for _ in range(2):
        _step7(proj, pdk)
        rec = _record(proj)
        assert rec["path"] == str(CONS / f"{TOP}.asic.sdc")
        assert rec["staged_sdc"] == str(CONS / f"{TOP}.sdc")
        clk = [l for l in (proj / rec["path"]).read_text().splitlines()
               if "create_clock" in l][0]
        periods.append(clk)
        assert legacy.read_text() == design
    assert periods[0] == periods[1] and "10000" in periods[0], periods


def test_a_changed_step7_copy_cannot_replace_the_legacy_design_sdc(
        tmp_path, monkeypatch):
    """The reserved .asic.sdc name stays flow owned after its sha changes."""
    proj = _project(tmp_path)
    legacy = proj / CONS / f"{TOP}.sdc"
    legacy.parent.mkdir(parents=True)
    design = "create_clock -name hand_clk -period 10 [get_ports clk]\n"
    legacy.write_text(design)
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    flow_copy = proj / CONS / f"{TOP}.asic.sdc"
    flow_copy.write_text(flow_copy.read_text() + "# changed after step 7\n")
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert "changed after step 7" in got["regenerated"]
    assert legacy.read_text() == design
    assert _record(proj)["staged_sdc"] == str(CONS / f"{TOP}.sdc")
    assert "-period 10" in got["text"]


def test_an_input_changed_after_step7_regenerates_the_deck(tmp_path,
                                                          monkeypatch):
    """MAJOR: the record bound only sha/top/PDK, so a run that skipped step 7
    reused a deck authored from older inputs, recorded regenerated=null."""
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    l8 = proj / "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
    l8.write_text(l8.read_text().replace("25.0", "40.0"))
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert "inputs changed since step 7" in got["regenerated"]
    assert "phase1/generated_docs/L8_TIMING_WAVEFORM.json" in got["regenerated"]
    assert "-period 40" in got["text"]


def test_clock_config_changed_after_step7_regenerates_the_deck(tmp_path,
                                                               monkeypatch):
    """Wave-9: config.json is an author input, not an invisible cache key."""
    proj = _project(tmp_path)
    cfg = proj / "config.json"
    cfg.write_text(json.dumps({"CLOCK_PERIOD": 25, "CLOCK_PORT": "clk"}))
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    cfg.write_text(json.dumps({"CLOCK_PERIOD": 10, "CLOCK_PORT": "clk_core"}))
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert "get_ports clk_core" in got["text"]
    assert got["regenerated"] is not None, got
    assert "inputs changed since step 7" in got["regenerated"]
    assert "config.json" in got["regenerated"]
    # L8 remains the period authority in this fixture; CLOCK_PORT is still a
    # real author input and must make the cached deck regenerate.
    assert "get_ports clk_core" in got["text"]


def test_a_new_step7_deck_changes_pnrs_cache_input(tmp_path, monkeypatch):
    """A builder-only change must invalidate routed outputs through step 7."""
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    before = R._step_inputs(proj, "pnr", TOP, object())[1]
    old_deck = _record(proj)["deck_sha256"]
    build = R._build_auto_silicon_sdc
    monkeypatch.setattr(R, "_build_auto_silicon_sdc",
                        lambda *a, **kw: build(*a, **kw) + "\n# changed builder\n")
    T.emit_step7_asic_sdc(R, proj, TOP, pdk, "some-container")
    after = R._step_inputs(proj, "pnr", TOP, object())[1]
    new_deck = _record(proj)["deck_sha256"]
    assert old_deck != new_deck
    assert before.get("step7_deck_sha256") == old_deck
    assert after.get("step7_deck_sha256") == new_deck


def test_external_liberty_bytes_changed_after_step7_regenerate(tmp_path,
                                                                monkeypatch):
    """An unchanged Liberty path does not imply unchanged time units."""
    proj = _project(tmp_path)
    liberty = tmp_path / "outside.lib"
    liberty.write_text('library(test) { time_unit : "1ns"; }\n')
    pdk = _pdk(monkeypatch)
    pdk.liberty = str(liberty)
    _step7(proj, pdk)
    liberty.write_text('library(test) { time_unit : "1ps"; }\n')
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert "-period 25000" in got["text"]
    assert got["regenerated"] is not None, got
    assert "inputs changed since step 7" in got["regenerated"]
    assert "@liberty_sha256" in got["regenerated"]


def test_commented_liberty_time_unit_cannot_scale_the_auto_sdc(tmp_path):
    """A disabled Liberty attribute is not the live library time unit."""
    proj = _project(tmp_path)
    liberty = tmp_path / "units.lib"
    liberty.write_text('library(test) {\n'
                       '  /* time_unit : "1ps"; */\n'
                       '  // time_unit : "1ps";\n'
                       '  time_unit : "1ns";\n}\n')
    text = R._build_auto_silicon_sdc(
        proj, top=TOP, liberty_path=str(liberty))
    assert "create_clock -name clk -period 25.0" in text
    assert "-period 25000" not in text


def test_container_record_changed_after_step7_regenerates(tmp_path,
                                                           monkeypatch):
    """The run's selected PDK-default source participates in SDC freshness."""
    proj = _project(tmp_path)
    report = proj / "reports/container_image.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"container": ""}))
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    report.write_text(json.dumps({"container": "", "changed": True}))
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert got["regenerated"] is not None, got
    assert "inputs changed since step 7" in got["regenerated"]
    assert "reports/container_image.json" in got["regenerated"]


def test_input_sdc_never_clobbers_a_hand_authored_legacy_sdc(tmp_path,
                                                              monkeypatch):
    """Wave-9: a higher-priority input must not make legacy input disposable."""
    proj = _project(tmp_path)
    (proj / "input/constraints").mkdir(parents=True)
    (proj / "input/constraints/clock.sdc").write_text(
        "create_clock -name input_clk -period 10 [get_ports clk]\n")
    legacy = proj / CONS / f"{TOP}.sdc"
    legacy.parent.mkdir(parents=True)
    hand = "create_clock -name hand_clk -period 7 [get_ports clk]\n"
    legacy.write_text(hand)
    _step7(proj, _pdk(monkeypatch))
    assert legacy.read_text() == hand
    assert _record(proj)["path"] == str(CONS / f"{TOP}.asic.sdc")


def test_a_run_whose_step7_deferred_regenerates_at_pnr(tmp_path, monkeypatch):
    """Fewer than 2 corners: step_prelayout_signoff returns NOT_MEASURED
    before step 7's producer; PnR regenerates through it and says why."""
    proj = _project(tmp_path)

    class _OneCorner:
        name = "sky130A"
        liberty = "/foss/pdks/x/nom.lib"
    res = R.step_prelayout_signoff(proj, TOP, _OneCorner(), "no-such-container")
    assert res.status == "NOT_MEASURED"
    monkeypatch.setattr(R, "_liberty_drv_limits", lambda *a, **k: {})
    got = T.asic_sdc_for_pnr(R, proj, TOP, _OneCorner(), "no-such-container")
    assert got["regenerated"] and "no step-7 record" in got["regenerated"]


@pytest.mark.parametrize("escape", ["absolute", "symlink"])
def test_step7_reader_never_opens_a_record_path_outside_constraints(
        tmp_path, monkeypatch, escape):
    proj = _project(tmp_path)
    constraints = proj / CONS
    constraints.mkdir(parents=True)
    outside = tmp_path / "outside.sdc"
    outside.write_text("create_clock -period 1 [get_ports clk]\n")
    if escape == "absolute":
        record_path = str(outside)
    else:
        link = constraints / "escaped.sdc"
        link.symlink_to(outside)
        record_path = str(link.relative_to(proj))
    (constraints / T.ASIC_SDC_RECORD).write_text(json.dumps({
        "path": record_path, "sha256": "deliberately-wrong"}))
    opened = []
    original = Path.read_text

    def trace_read(path, *args, **kwargs):
        if path.resolve() == outside:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", trace_read)
    rec, _ = T.read_step7_asic_sdc(
        R, proj, TOP, SimpleNamespace(name="test"))
    assert rec is None and not opened, opened


def test_step7_owned_ledger_never_hashes_a_symlink_outside_constraints(
        tmp_path, monkeypatch):
    proj = _project(tmp_path)
    constraints = proj / CONS
    constraints.mkdir(parents=True)
    outside = tmp_path / "outside.sdc"
    outside.write_text("external design input\n")
    link = constraints / "escaped.sdc"
    link.symlink_to(outside)
    rel = str(link.relative_to(proj))
    (constraints / T.ASIC_SDC_RECORD).write_text(json.dumps({
        "owned_outputs": {rel: hashlib.sha256(outside.read_bytes()).hexdigest()}}))
    opened = []
    original = Path.read_bytes

    def trace_read(path, *args, **kwargs):
        if path.resolve() == outside:
            opened.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", trace_read)
    assert T.owned_step7_outputs(R, proj) == {}
    assert not opened, opened


# --------------------------------------------------------------------------- #
# llv1 W7a's between-segments seam reads step 7's file through THIS reader
# --------------------------------------------------------------------------- #
def test_the_prepnr_seam_reads_step7s_deck_through_its_reader(
        tmp_path, monkeypatch):
    """W7a's `_prepnr_constraint_file` delegates to `read_step7_asic_sdc`
    when it exists (the handover both lanes named). The real reader accepts
    step 7's own record and refuses the same deck once it changed."""
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    rec = _record(proj)
    path, why = R._prepnr_constraint_file(proj, TOP, pdk)
    assert path == (proj / rec["path"]).resolve(), why
    assert "input-bound design-intent SDC" in why
    (proj / rec["path"]).write_text(
        (proj / rec["path"]).read_text() + "# edited after step 7\n")
    path, why = R._prepnr_constraint_file(proj, TOP, pdk)
    assert path is None
    assert why.startswith("SDC_SEAM_PENDING: fxport step-7 reader:")
    assert "changed after step 7" in why
