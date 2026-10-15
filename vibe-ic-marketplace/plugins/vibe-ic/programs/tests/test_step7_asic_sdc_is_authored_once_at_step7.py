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
import sdc_environment as E                              # noqa: E402
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


@pytest.fixture(autouse=True)
def _complete_corner_fixture_contract(monkeypatch, tmp_path):
    # Some legacy cases call PL._corner_pdk directly to select another
    # Liberty. Complete that shared fixture edge, including those callers,
    # without changing their input setup or acceptance assertions.
    corner_pdk = PL._corner_pdk
    def complete(*args, **kwargs):
        pdk = corner_pdk(*args, **kwargs)
        if not Path(str(pdk.liberty)).is_file():
            material = tmp_path / "fixture_pdk" / Path(str(pdk.liberty)).name
            material.parent.mkdir(exist_ok=True)
            material.write_text('library(neutral) { time_unit : "1ns"; }\n')
            pdk.liberty = str(material)
        monkeypatch.setattr(R, "_emit_multi_corner_sta", _fixture_corner_sta)
        return pdk
    monkeypatch.setattr(PL, "_corner_pdk", complete)


def _fixture_corner_sta(project, top, pdk, container, libs, out, notes,
                        *, force_prelayout=False, setup_slack=0.4):
    """Native-edge test double; no simulator/STA qualification is claimed.

    Keep real report composition and the normal scoped audit subprocess.
    Two complete setup/hold paths supply the report contract naturally;
    neither the audit verdict nor StepResult is mocked.
    """
    assert force_prelayout is True
    assert len(libs) >= 2
    out.mkdir(parents=True, exist_ok=True)
    for corner in ("SS", "TT"):
        sections = ["# STA_BASIS: PRE_LAYOUT_ESTIMATE\n"
                    "# STA_TIME_UNIT: ns\n"
                    f"# corner: {corner}\nOpenSTA report_checks\n"]
        for kind, arrival, required, slack in (
                ("max", 2.5, 2.5 + setup_slack, setup_slack),
                ("min", 0.35, 0.10, 0.25)):
            sections.append(
                "Startpoint: source_reg (rising edge-triggered flip-flop clocked by clk)\n"
                "Endpoint: sink_reg (rising edge-triggered flip-flop clocked by clk)\n"
                f"Path Group: clk\nPath Type: {kind}\n\n"
                "  Delay    Time   Description\n"
                "---------------------------------------------------------\n"
                "   0.00    0.00   clock clk (rise edge)\n"
                "   0.00    0.00   clock network delay (ideal)\n"
                f"   {arrival:.2f}    {arrival:.2f}   source_reg/Q -> sink_reg/D\n"
                f"           {arrival:.2f}   data arrival time\n"
                f"           {required:.2f}   data required time\n"
                "---------------------------------------------------------\n"
                f"           {slack:.2f}   slack ({'MET' if slack >= 0 else 'VIOLATED'})\n\n")
        sections.append(f"wns max {setup_slack:.2f}\ntns max {min(setup_slack, 0):.2f}\n"
                        "wns min 0.25\ntns min 0.00\n")
        (out / f"sta_{corner}.rpt").write_text("".join(sections))
    notes.append("unit fixture supplied native-edge pre-layout reports; not a native run")
    return True


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


def test_native_prelayout_binds_step7_not_the_later_pnr_deck(tmp_path, monkeypatch):
    """Only the native edge is captured; the normal Step-7 caller still runs."""
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    (proj / "phase3").mkdir(exist_ok=True)
    (proj / "phase3/librelane_switch.json").write_text(json.dumps({
        "steps": {"7": "direct", "8": "librelane", "10": "direct"}}))
    seen = []
    def prelayout(project, top, pdk, sdc, staged, modes, notes):
        seen.append(sdc)
        return {}
    monkeypatch.setattr(R, "_prelayout_librelane", prelayout)
    R.step_prelayout_signoff(proj, TOP, pdk, "some-container")
    record = _record(proj)
    assert seen == [proj / record["path"]]
    assert seen[0] != proj / "phase3/stage3/pnr/constraint.sdc"


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
    report.write_text(json.dumps({"container": "", "image_ref": "other"}))
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert got["regenerated"] is not None, got
    assert "inputs changed since step 7" in got["regenerated"]
    assert "@container_image" in got["regenerated"]


def test_container_cid_rotation_does_not_regenerate_step7(tmp_path, monkeypatch):
    """A fresh continuation container keeps the same pinned image identity."""
    proj = _project(tmp_path)
    report = proj / "reports/container_image.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"container": "old", "image_ref": "same",
                                  "image_id": "sha256:1", "verdict": "PASS"}))
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    report.write_text(json.dumps({"container": "new", "image_ref": "same",
                                  "image_id": "sha256:1", "verdict": "PASS",
                                  "attestation_path": "/new/run.json"}))
    got = T.asic_sdc_for_pnr(R, proj, TOP, pdk, "some-container")
    assert got["regenerated"] is None, got


def test_io_pad_namespace_rotation_preserves_binding_but_supply_change_refuses(
        tmp_path, monkeypatch):
    """Run-local pad paths are ignored; a supply change is bound and refused."""
    proj = _project(tmp_path)
    rec_path = _pad_record(proj)
    payload = json.loads(rec_path.read_text())
    payload.update({
        "project": str(proj),
        "optional_ports_not_implemented": [{
            "netlist": str(proj / "phase2/stage2/synth/netlist.v"),
        }],
    })
    rec_path.write_text(json.dumps(payload, sort_keys=True))
    pdk = _pdk(monkeypatch)
    _step7(proj, pdk)
    record_path = proj / CONS / T.ASIC_SDC_RECORD
    before = record_path.read_bytes()

    payload["project"] = "/private/backend/project"
    payload["optional_ports_not_implemented"][0]["netlist"] = (
        "/private/backend/phase2/stage2/synth/netlist.v")
    rec_path.write_text(json.dumps(payload, sort_keys=True))
    accepted, why = T.read_step7_asic_sdc(R, proj, TOP, pdk)
    observed = ("ACCEPTED" if accepted is not None else "REFUSED", why)
    assert observed == ("ACCEPTED", "")
    assert record_path.read_bytes() == before

    payload["power_pad_plan"]["ground_net"] = "VSSA"
    rec_path.write_text(json.dumps(payload, sort_keys=True))
    refused, why = T.read_step7_asic_sdc(R, proj, TOP, pdk)
    observed = ("REFUSED" if refused is None else "ACCEPTED",
                "@io_pad_record" in why)
    assert observed == ("REFUSED", True)
    assert record_path.read_bytes() == before


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
    material = tmp_path / "one_corner.lib"
    material.write_text('library(neutral) { time_unit : "1ns"; }\n')

    class _OneCorner:
        name = "sky130A"
        liberty = str(material)
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


def test_default_floorplan_reads_this_step7_deck_at_native_boundary(tmp_path, monkeypatch):
    """Default's actual producer must pass the current deck to its native
    floorplan consumer, even when a previous PNR constraint file exists."""
    import execution_backend_producers as producers
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    T.emit_step7_asic_sdc(R, proj, TOP, pdk, '')
    pnr = proj / producers.PNR
    pnr.mkdir(parents=True)
    (pnr / 'constraint.sdc').write_text('create_clock -period 99 [get_ports clk]\n')
    monkeypatch.setattr(producers, '_parameters', lambda *a: (R, SimpleNamespace(), pdk, ''))
    monkeypatch.setattr(R, 'step_prepnr', lambda *a: R.StepResult('prepnr', 'PASS', 0, 'ready'))
    monkeypatch.setattr(R, '_chip_path_requests_pad_ring', lambda *a: True)
    seen = []

    def native_consumer(project, *args, **kwargs):
        sdc = (pnr / 'constraint.sdc').read_text()
        assert '-period 25' in sdc and '-period 99' not in sdc, sdc
        provenance = json.loads((pnr / 'constraint_sdc_provenance.json').read_text())
        assert provenance['step7_sha256'] == _record(proj)['sha256']
        assert provenance['deck_sha256'] == hashlib.sha256(sdc.encode()).hexdigest()
        seen.append(sdc)
        return R.StepResult('pnr', 'PASS', 0, 'native consumer used current SDC'), {}

    monkeypatch.setattr(R, '_prepare_librelane_floorplan_for_route', native_consumer)
    monkeypatch.setattr(producers, '_publish_step15_bounded_state', lambda *a: None)
    result = producers.produce_pnr(proj, {'step_id': '15', 'top': TOP,
                                       'die_um': 100, 'util': 0.4})
    assert result['verdict'] == 'PASS' and len(seen) == 1


def _mode_library(name, cell, pin_limit, arcs):
    return f'''library ({name}) {{
      delay_model : table_lookup;
      time_unit : "1ns";
      voltage_unit : "1V";
      current_unit : "1mA";
      capacitive_load_unit (1,pf);
      nom_process : 1; nom_temperature : 25; nom_voltage : 1.8;
      default_max_transition : {pin_limit};
      lu_table_template (tiny) {{ variable_1 : input_net_transition;
        variable_2 : total_output_net_capacitance;
        index_1 ("0.01, 1"); index_2 ("0.01, 1"); }}
      cell ({cell}) {{ area : 1;
        pin (A) {{ direction : input; capacitance : 0.01; }}
        pin (MODE) {{ direction : input; capacitance : 0.001; }}
        pin (Y) {{ direction : output; function : "A";
          is_pad : true; max_transition : {pin_limit};
          {arcs}
        }}
      }}
    }}'''


def _mode_arc(when, slew):
    return f'''timing () {{ related_pin : "A"; timing_type : combinational;
      timing_sense : positive_unate; {('when : "' + when + '";') if when else ''}
      cell_rise (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
      cell_fall (tiny) {{ values ("0.1, 0.1", "0.1, 0.1"); }}
      rise_transition (tiny) {{ values ("{slew}, {slew}", "{slew}, {slew}"); }}
      fall_transition (tiny) {{ values ("{slew}, {slew}", "{slew}, {slew}"); }}
    }}'''


@pytest.mark.parametrize('consumer', ['openroad', 'sta'])
@pytest.mark.parametrize('mode,core_slew,user_limit,pdk_limits', [
    ('0', 0.5, None, False), ('1', 0.5, None, False), ('m', 0.5, None, False),
    ('0', 2.0, None, False), ('0', 0.5, 1.0, False),
    ('0', 0.5, None, True), ('0', 1.0, None, True)],
    ids=['fixed-normal','fixed-slow','dynamic-mode','core-still-fails','user-ceiling-still-fails',
         'pdk-core-normal','pdk-core-still-fails'])
def test_pad_operating_scene_preserves_actual_mode_and_each_domain_limit(
        tmp_path, monkeypatch, mode, core_slew, user_limit, pdk_limits, consumer):
    import shutil
    import subprocess
    tool = shutil.which(consumer)
    assert tool, 'this native consumer test requires the EDA image'
    proj = _project(tmp_path)
    core_lib = tmp_path / 'core.lib'
    core_lib.write_text(_mode_library('core_lib', 'core_buf', 1.5, _mode_arc('', core_slew)))
    io_lib = tmp_path / 'io.lib'
    io_lib.write_text(_mode_library('io_lib', 'io_pad', 25,
                    _mode_arc('!MODE', 1.87) + _mode_arc('MODE', 225.75)))
    pdk = _pdk(monkeypatch, drv={'max_transition_ns': 1.5,
                               'slew_source': str(core_lib) + ':default_max_transition'})
    pdk.liberty = core_lib
    monkeypatch.setattr(R, '_sdc_environment_pdk_values', lambda *a, **k: ({}, []))
    if pdk_limits:
        values = {'set_max_transition': ('0.75', 'pinned PDK default core/config.tcl:MAX_TRANSITION_CONSTRAINT'),
                  'set_max_capacitance': ('0.2', 'pinned PDK default core/config.tcl:MAX_CAPACITANCE_CONSTRAINT')}
        monkeypatch.setattr(E, '_sdc_environment_pdk_values', lambda *a, **k: (values, []))
        monkeypatch.setattr(R, '_synth_max_fanout', lambda *a, **k:
                            (10, 'pinned PDK default core/config.tcl:MAX_FANOUT_CONSTRAINT', []))
    if user_limit:
        (proj / 'input/constraints').mkdir(parents=True)
        (proj / 'input/constraints/clock.sdc').write_text(
            f'create_clock -period 25 [get_ports clk]\nset_max_transition {user_limit} [current_design]\n')
    # Phase-2 authoring precedes the physical pad producer.
    T.emit_step7_asic_sdc(R, proj, TOP, pdk, '')
    path = _pad_record(proj)
    doc = json.loads(path.read_text())
    doc.update(io_library_liberty=[str(io_lib)],
               pad_instances={'u_io': {'port': 'y', 'master': 'io_pad',
                                       'terminal': 'Y', 'direction': 'output'},
                              'u_supply': {'port': 'VDD', 'master': 'supply_pad',
                                           'terminal': 'BOND', 'direction': 'inout', 'kind': 'power'}})
    path.write_text(json.dumps(doc))
    derived = T.asic_sdc_for_pnr(R, proj, TOP, pdk, '')
    sdc = tmp_path / 'scene.sdc'
    sdc.write_text(derived['text'])
    nl = tmp_path / 'scene.v'
    mode_connection = "1'b" + mode if mode in ('0', '1') else 'm'
    nl.write_text(f'module {TOP}(input a,input m,input clk,output y,inout VDD,inout VSS); '
                  f'wire n; core_buf u_core(.A(a),.MODE(1\'b0),.Y(n)); '
                  f'io_pad u_io(.A(n),.MODE({mode_connection}),.Y(y)); endmodule\n')
    lef = tmp_path / 'scene.lef'
    macros = ''
    for cell in ('core_buf', 'io_pad'):
        pins = ''.join(f'PIN {pin}\n DIRECTION {direction} ;\n USE SIGNAL ;\n'
                       f' PORT\n LAYER Metal1 ;\n RECT 0.1 0.1 0.2 0.2 ;\n END\n END {pin}\n'
                       for pin, direction in [('A', 'INPUT'), ('MODE', 'INPUT'), ('Y', 'OUTPUT')])
        macros += f'MACRO {cell}\n CLASS CORE ;\n ORIGIN 0 0 ;\n SIZE 1 BY 1 ;\n{pins}END {cell}\n'
    lef.write_text('VERSION 5.8 ;\nBUSBITCHARS "[]" ;\nDIVIDERCHAR "/" ;\n'
                   'UNITS\n DATABASE MICRONS 1000 ;\nEND UNITS\n'
                   'LAYER Metal1\n TYPE ROUTING ;\n DIRECTION HORIZONTAL ;\n'
                   ' PITCH 0.5 ;\n WIDTH 0.2 ;\n SPACING 0.3 ;\nEND Metal1\n'
                   + macros + 'END LIBRARY\n')
    script = tmp_path / 'scene.tcl'
    exported = tmp_path / 'scene-export.sdc'
    physical_setup = f'read_lef {{{lef}}}\n' if consumer == 'openroad' else ''
    physical_edit = ('odb::dbInst_create [ord::get_db_block] [[ord::get_db] findMaster core_buf] extra\n'
                     if consumer == 'openroad' else '')
    script.write_text('set sta_report_default_digits 6\n' + physical_setup
                      + f'read_liberty {{{core_lib}}}\nread_liberty {{{io_lib}}}\n'
                      f'read_verilog {{{nl}}}\nlink_design {TOP}\n'
                      f'if {{[catch {{read_sdc {{{sdc}}}}} why]}} {{puts "SCENE_ERROR $why"; exit 1}}\n'
                      'puts "SCENE_COUNT_BEFORE [sta::max_slew_violation_count]"\n'
                      'puts SCENE_CHECK_BEGIN\nreport_check_types -max_slew -violators -digits 6\n'
                      'puts SCENE_CHECK_END\n'
                      'puts "SCENE_COUNT_AFTER [sta::max_slew_violation_count]"\n'
                      'report_edges -from [get_pins u_io/A] -to [get_pins u_io/Y]\n'
                      + physical_edit
                      + f'write_sdc {{{exported}}}\nread_sdc {{{exported}}}\n'
                      'puts SCENE_ROUNDTRIP_BEGIN\nreport_check_types -max_slew -violators -digits 6\n'
                      'puts SCENE_ROUNDTRIP_END\nexit\n')
    run = subprocess.run([tool, '-no_init', '-exit', str(script)], capture_output=True, text=True)
    output = run.stdout + run.stderr
    assert run.returncode == 0 and 'SCENE_CHECK_END' in output and 'SCENE_ERROR' not in output, output
    checked = output.split('SCENE_CHECK_BEGIN', 1)[1].split('SCENE_CHECK_END', 1)[0]
    if mode == '0' and core_slew == 0.5 and user_limit is None:
        assert 'VIOLATED' not in checked, checked
        assert 'SCENE_COUNT_BEFORE 0' in output and 'SCENE_COUNT_AFTER 0' in output, output
    else:
        assert 'VIOLATED' in checked, checked
        before_count = int(output.split('SCENE_COUNT_BEFORE ', 1)[1].splitlines()[0])
        after_count = int(output.split('SCENE_COUNT_AFTER ', 1)[1].splitlines()[0])
        assert before_count > 0 and after_count > 0, output
    assert 'SCENE_ROUNDTRIP_END' in output, output
    edges = output.split('SCENE_CHECK_END', 1)[1].split('SCENE_ROUNDTRIP_BEGIN', 1)[0]
    assert 'Disabled by constraint' not in edges, output
    roundtrip = output.split('SCENE_ROUNDTRIP_BEGIN', 1)[1].split('SCENE_ROUNDTRIP_END', 1)[0]
    assert ('VIOLATED' in roundtrip) == ('VIOLATED' in checked), output
    assert 'set_disable_timing' not in '\n'.join(
        line for line in exported.read_text().splitlines() if not line.startswith(' ')), exported.read_text()
    if core_slew > 1.5:
        assert 'u_core/Y' in checked and '2.000000' in checked
    if user_limit:
        assert 'set_max_transition 1.0 [current_design]' in derived['text']
    if pdk_limits and core_slew > 0.75:
        assert 'u_core/Y' in checked and '1.000000' in checked
    # A normal-mode active edge still exists: no from/to blanket suppression.
    if mode == '0':
        normal = output.split('Condition: !MODE', 1)[-1].split('Condition:', 1)[0]
        assert 'Disabled by constraint' not in normal, output


def test_pdk_core_targets_do_not_constrain_chip_io_ports(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    core_lib = tmp_path / 'core.lib'
    core_lib.write_text(_mode_library('core_lib', 'core_buf', 1.5, _mode_arc('', 0.5)))
    io_lib = tmp_path / 'io.lib'
    io_lib.write_text(_mode_library('io_lib', 'io_pad', 25, _mode_arc('', 1.87)))
    pdk = _pdk(monkeypatch, drv={'max_transition_ns': 1.5,
                               'slew_source': str(core_lib) + ':default_max_transition'})
    pdk.liberty = core_lib
    values = {'set_max_transition': ('0.75', 'pinned PDK default core/config.tcl:MAX_TRANSITION_CONSTRAINT'),
              'set_max_capacitance': ('0.2', 'pinned PDK default core/config.tcl:MAX_CAPACITANCE_CONSTRAINT')}
    monkeypatch.setattr(E, '_sdc_environment_pdk_values', lambda *a, **k: (values, []))
    monkeypatch.setattr(R, '_synth_max_fanout', lambda *a, **k:
                        (10, 'pinned PDK default core/config.tcl:MAX_FANOUT_CONSTRAINT', []))
    T.emit_step7_asic_sdc(R, proj, TOP, pdk, '')
    path = _pad_record(proj)
    doc = json.loads(path.read_text())
    doc.update(io_library_liberty=[str(io_lib)], pad_instances={
        'u_io': {'port': 'y', 'master': 'io_pad', 'terminal': 'Y', 'direction': 'output'}})
    path.write_text(json.dumps(doc))
    derived = T.asic_sdc_for_pnr(R, proj, TOP, pdk, '')
    assert 'set_max_transition 0.75 [current_design]' not in derived['text']
    assert 'set_max_capacitance 0.2 $_vibeic_drv_signal_ports' not in derived['text']
    assert 'set_max_fanout 10 $_vibeic_drv_signal_in_ports' not in derived['text']
    assert 'set_max_transition 0.75 [$_vibeic_core_cell cell]' in derived['text']
    assert 'set_max_capacitance 0.2 [$_vibeic_core_cell cell]' in derived['text']
    assert 'set_max_fanout 10 [$_vibeic_core_cell cell]' in derived['text']
    assert derived['derivation']['core_library_targets'] == {
        'set_max_transition': 0.75, 'set_max_capacitance': 0.2, 'set_max_fanout': 10}


@pytest.mark.parametrize('case', [
    'fresh_detect', 'cache_reuse', 'changed_bytes', 'wrong_library',
    'wrong_corner', 'missing_asset',
])
def test_default_backend_preserves_the_step7_staged_liberty_role(
        tmp_path, monkeypatch, case):
    """SOURCE_CONTROL image/staging ancestry; real emitter/resolver/SDC reader.

    No native synthesis/PnR is performed. The image path is not host-readable;
    the host copy retains the exact selected distribution and intra-PDK role.
    """
    import shutil
    import execution_backend_producers as producers
    import librelane_contract as ll

    proj = _project(tmp_path)
    host_root = tmp_path / 'staged_pdk'
    image_root = tmp_path / 'image_only_pdk'
    within_pdk = Path('sky130A/libs.ref/neutral_cells/lib/neutral_cells__tt.lib')
    material = tmp_path / 'image_material' / within_pdk
    material.parent.mkdir(parents=True)
    material.write_text('library(neutral_cells) { time_unit : "1ns"; }\n')
    staged = host_root / within_pdk
    staged.parent.mkdir(parents=True)
    shutil.copyfile(material, staged)
    pdk = _pdk(monkeypatch)
    pdk.liberty = str(staged)
    T.emit_step7_asic_sdc(R, proj, TOP, pdk, '')
    original_record = (proj / CONS / T.ASIC_SDC_RECORD).read_bytes()
    original_sdc = (proj / _record(proj)['path']).read_bytes()
    assert T.read_step7_asic_sdc(R, proj, TOP, pdk)[0] is not None
    selected = within_pdk
    if case == 'wrong_library':
        selected = within_pdk.with_name('other_cells__tt.lib')
    elif case == 'wrong_corner':
        selected = within_pdk.with_name('neutral_cells__ss.lib')
    if selected != within_pdk:
        shutil.copyfile(material, host_root / selected)
    if case == 'changed_bytes':
        staged.write_text('library(neutral_cells) { time_unit : "2ns"; }\n')
    elif case == 'missing_asset':
        staged.unlink()
    image_liberty = image_root / 'ciel/neutral/versions/frozen' / selected
    detected = SimpleNamespace(name=pdk.name,
                               liberty=str(staged if case == 'cache_reuse' else image_liberty),
                               macro_libs=[])
    resolution = {'path': str(host_root), 'source': 'resolved',
                  'derivation': {'image_pdk_root': str(image_root),
                                 'pdk': pdk.name, 'host_path': str(host_root / pdk.name)}}
    monkeypatch.setattr(ll, 'resolve_image', lambda *a: 'source-control-image')
    monkeypatch.setattr(ll, 'pdk_root_resolution', lambda *a, **k: resolution)
    monkeypatch.setattr(R, '_detect_pdk', lambda *a: detected)
    params = {**R._backend_parameter_values(proj, pdk), 'top': TOP}
    refusal = None
    resolved = None
    try:
        _, _, resolved, _ = producers._parameters(proj, params)
        current_path, why = R._prepnr_constraint_file(proj, TOP, resolved)
    except ll.Refusal as exc:
        refusal = str(exc)
        current_path, why = None, refusal
    accepted = case in ('fresh_detect', 'cache_reuse')
    observation = {'case': case, 'expected_accepted': accepted,
                   'material_sha256': hashlib.sha256(material.read_bytes()).hexdigest(),
                   'stage_before_sha256': _record(proj)['inputs']['@liberty_sha256'],
                   'record_liberty': _record(proj)['inputs']['@liberty'],
                   'detected_liberty': str(image_liberty),
                   'resolved_liberty': str(resolved.liberty) if resolved else None,
                   'reader_accepted': current_path is not None, 'reader_reason': why,
                   'resolver_refusal': refusal}
    (tmp_path / 'observed.json').write_text(json.dumps(observation, indent=2) + '\n')
    print(json.dumps(observation, sort_keys=True))
    assert (current_path is not None) is accepted, observation
    if accepted:
        assert resolved.liberty == str(staged)
        current = T.asic_sdc_for_pnr(R, proj, TOP, resolved, '')
        assert current['regenerated'] is None
        published = T.publish_pnr_sdc(current, proj / producers.PNR)
        evidence = json.loads(published.with_name('constraint_sdc_provenance.json').read_text())
        assert evidence['step7_sha256'] == _record(proj)['sha256']
        assert evidence['deck_sha256'] == hashlib.sha256(published.read_bytes()).hexdigest()
    else:
        assert refusal or why.startswith('SDC_SEAM_PENDING:'), observation
    assert (proj / CONS / T.ASIC_SDC_RECORD).read_bytes() == original_record
    assert (proj / _record(proj)['path']).read_bytes() == original_sdc


# The migrated native-edge fixture must not bypass the current consumer.
def test_sdc_fixture_still_refuses_an_absent_native_sta_report(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    monkeypatch.setattr(R, "_emit_multi_corner_sta", lambda *a, **k: False)
    result = R.step_prelayout_signoff(proj, TOP, pdk, "some-container")
    assert result.status == "NOT_MEASURED", result.detail
    assert "PRELAYOUT_STA_REPORT_ABSENT" in result.detail
    assert not (proj / "reports/phase3/sta/pre_pnr_summary.json").exists()


def test_sdc_fixture_real_summary_consumer_rejects_negative_slack(tmp_path, monkeypatch):
    proj = _project(tmp_path)
    pdk = _pdk(monkeypatch)
    def violated(*args, **kwargs):
        return _fixture_corner_sta(*args, **kwargs, setup_slack=-0.5)
    monkeypatch.setattr(R, "_emit_multi_corner_sta", violated)
    result = R.step_prelayout_signoff(proj, TOP, pdk, "some-container")
    assert result.status == "FAIL", result.detail
    assert "PRELAYOUT_STA_SUMMARY_FAILED" in result.detail
    summary = json.loads((proj / "reports/phase3/sta/pre_pnr_summary.json").read_text())
    assert summary["passed"] is False
    assert any(row["rule"] == "STA_REAL_VIOLATION_FOUND"
               for row in summary["findings"])


@pytest.mark.parametrize('case', [
    'fresh_detect', 'cache_reuse', 'selected_ss', 'selected_ff',
    'wrong_library', 'wrong_corner', 'wrong_distribution', 'changed_bytes',
    'missing_asset', 'missing_at_producer', 'unmapped_selected_asset',
    'unavailable_image', 'wrong_distribution_at_producer',
])
def test_normal_step7_and_backend_share_selected_liberty_binding(
        tmp_path, monkeypatch, case):
    """Real Step7 -> prelayout re-emission -> fresh guest/host strict readers.

    Only the image/runtime I/O boundary is substituted. The host cache is not
    mounted in the named container; its PVT census must retain the image view
    and the reference-selected corners rather than silently using fallbacks.
    """
    import design_one_shot_runner as d
    import execution_backend_producers as producers
    import execution_policy
    import librelane_contract as ll

    proj = _project(tmp_path)
    declaration = proj / 'input/project.json'
    declaration.parent.mkdir()
    declaration.write_text(json.dumps({'pdk': 'neutral_pdk'}))
    image_root = tmp_path / 'image_only_pdk'
    image_pdk = image_root / 'ciel/neutral/versions/frozen/neutral_pdk'
    host_root = tmp_path / 'staged_pdk'
    within_pdk = Path('neutral_pdk/libs.ref/neutral_cells/lib')
    guest_dir = image_pdk / 'libs.ref/neutral_cells/lib'
    reference = ['ss_125C_1v50', 'tt_025C_1v75', 'ff_000C_2v00']
    fallback = ['ss_100C_1v60', 'tt_025C_1v80', 'ff_n40C_1v95']
    libraries = [f'neutral_cells__{corner}.lib' for corner in reference + fallback]
    for name in libraries:
        target = host_root / within_pdk / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'library({Path(name).stem}) {{ time_unit : "1ns"; }}\n')
    selected_corner = {'selected_ss': reference[0], 'selected_ff': reference[2]}.get(
        case, reference[1])
    selected_name = f'neutral_cells__{selected_corner}.lib'
    guest_liberty = guest_dir / selected_name
    staged_liberty = host_root / within_pdk / selected_name
    selected = [guest_liberty]
    detected = []

    def detect(project, name):
        assert project == proj and name == 'neutral_pdk'
        pdk = SimpleNamespace(name=name, liberty=str(selected[0]), macro_libs=[])
        detected.append(pdk)
        return pdk

    resolution = {'path': str(host_root), 'source': 'resolved',
                  'derivation': {'image_pdk_root': str(image_root),
                                 'pdk': 'neutral_pdk',
                                 'host_path': str(host_root / 'neutral_pdk')}}
    stage_calls = []

    def resolve_root(project, name, *, image):
        assert project == proj and name == 'neutral_pdk'
        assert image == 'source-control-image'
        stage_calls.append(image)
        return resolution

    def resolve_image(project):
        assert project == proj
        if case == 'unavailable_image':
            raise ll.Refusal('LL_LOCAL_IMAGE_UNATTESTED', 'fixture has no attested image')
        return 'source-control-image'

    probes = []

    def image_io(container, command, **kwargs):
        assert container == 'fixture-container'
        assert str(host_root) not in command, 'host cache is not container-mounted'
        probes.append(command)
        if command.startswith('ls ') and str(guest_dir) in command:
            return 0, '\n'.join(str(guest_dir / name) for name in libraries), ''
        config = image_pdk / 'libs.tech/librelane/config.tcl'
        if command.startswith('cat ') and str(config) in command:
            return 0, 'set ::env(STA_CORNERS) "' + ' '.join(
                f'nom_{corner}' for corner in reference) + '"\n', ''
        raise AssertionError(f'unexpected native boundary: {command}')

    monkeypatch.setattr(R, '_detect_pdk', detect)
    monkeypatch.setattr(R, '_docker_exec', image_io)
    monkeypatch.setattr(R, '_liberty_drv_limits', lambda *a, **k: {})
    monkeypatch.setattr(R, '_synth_max_fanout', lambda *a, **k: (None, None, []))
    monkeypatch.setattr(E, '_sdc_environment_pdk_values', lambda *a, **k: ({}, []))
    monkeypatch.setattr(ll, 'resolve_image', resolve_image)
    monkeypatch.setattr(ll, 'pdk_root_resolution', resolve_root)
    monkeypatch.setattr(ll, 'selected_mode', lambda *a, **k: 'librelane')
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', {'policy': {'mode': 'default'}})
    if case == 'missing_at_producer':
        staged_liberty.unlink()
    elif case == 'unmapped_selected_asset':
        selected[0] = tmp_path / 'unmapped/missing.lib'
    elif case == 'wrong_distribution_at_producer':
        resolution['derivation']['pdk'] = 'another_distribution'

    result = d.step_asic_sdc(proj, TOP, 'fixture-container',
                            pdk_name='neutral_pdk', _use_controller=False)
    producer_refusals = {
        'missing_at_producer': 'LL_PDK_LIB_MISSING',
        'unmapped_selected_asset': 'SDC_LIBERTY_UNREADABLE',
        'unavailable_image': 'LL_LOCAL_IMAGE_UNATTESTED',
        'wrong_distribution_at_producer': 'LL_PDK_LIB_CONFLICT',
    }
    if case in producer_refusals:
        assert result.status == 'FAIL', result
        assert producer_refusals[case] in result.detail, result.detail
        assert not (proj / CONS / T.ASIC_SDC_RECORD).exists()
        return

    assert result.status == 'NOT_MEASURED', result.detail
    assert result.extras['producer_status'] == 'PASS'
    assert result.extras['deferred_until'] == 'post_prelayout'
    assert result.extras['corner_count'] == 3
    assert detected[0].liberty == str(guest_liberty), 'caller PDK must remain unchanged'
    matrix = json.loads((proj / CONS / 'pvt_matrix.json').read_text())
    assert [(c['label'], c['liberty']) for c in matrix['corners']] == [
        (label, str(guest_dir / f'neutral_cells__{corner}.lib'))
        for label, corner in zip(('SS', 'TT', 'FF'), reference)]
    assert probes and any('STA_CORNERS' not in cmd and 'config.tcl' in cmd for cmd in probes)
    if case == 'cache_reuse':
        first_record = (proj / CONS / T.ASIC_SDC_RECORD).read_bytes()
        result = d.step_asic_sdc(proj, TOP, 'fixture-container',
                                pdk_name='neutral_pdk', _use_controller=False)
        assert result.extras['producer_status'] == 'PASS'
        assert (proj / CONS / T.ASIC_SDC_RECORD).read_bytes() == first_record

    record_before = (proj / CONS / T.ASIC_SDC_RECORD).read_bytes()
    sdc_before = (proj / _record(proj)['path']).read_bytes()
    pvt_before = (proj / CONS / 'pvt_matrix.json').read_bytes()
    prelayout_pdk = detect(proj, 'neutral_pdk')
    native_boundary = []

    def stop_before_native(project, top, pdk, sdc, *args):
        assert pdk is prelayout_pdk and pdk.liberty == str(guest_liberty)
        assert sdc.read_bytes() == sdc_before
        native_boundary.append(str(sdc))
        # The real prelayout function has already re-emitted Step7 here.
        # Stop only the native I/O boundary; do not fabricate a tool PASS.
        raise ll.Refusal('LL_STEP_FAILED', 'unit fixture stopped before native STA')

    monkeypatch.setattr(R, '_prelayout_librelane', stop_before_native)
    prelayout = R.step_prelayout_signoff(proj, TOP, prelayout_pdk, 'fixture-container')
    assert prelayout.status == 'FAIL' and 'unit fixture stopped' in prelayout.detail
    assert native_boundary == [str(proj / _record(proj)['path'])]
    assert prelayout_pdk.liberty == str(guest_liberty)
    assert (proj / CONS / T.ASIC_SDC_RECORD).read_bytes() == record_before
    assert (proj / _record(proj)['path']).read_bytes() == sdc_before
    assert (proj / CONS / 'pvt_matrix.json').read_bytes() == pvt_before
    # Both contexts must accept the actual re-emitted record, including a
    # fresh registry/image selection that has not passed through the backend.
    for reader_pdk in (detect(proj, 'neutral_pdk'),
                       SimpleNamespace(name='neutral_pdk', liberty=str(staged_liberty), macro_libs=[])):
        current, why = T.read_step7_asic_sdc(R, proj, TOP, reader_pdk)
        assert current is not None, why
        assert current['inputs']['@liberty'] == str(staged_liberty)
        assert current['inputs']['@liberty_sha256'] == hashlib.sha256(staged_liberty.read_bytes()).hexdigest()
        assert reader_pdk.liberty in (str(guest_liberty), str(staged_liberty))

    if case in ('wrong_library', 'wrong_corner'):
        selected[0] = guest_dir / ('other_cells__tt.lib' if case == 'wrong_library'
                                   else f'neutral_cells__{reference[0]}.lib')
        target = host_root / within_pdk / selected[0].name
        target.write_bytes(staged_liberty.read_bytes())
    elif case == 'wrong_distribution':
        selected[0] = image_root / 'ciel/neutral/versions/frozen/other_pdk' / within_pdk.relative_to(
            'neutral_pdk') / selected_name
    elif case == 'changed_bytes':
        staged_liberty.write_text('library(changed) { time_unit : "2ns"; }\n')
    elif case == 'missing_asset':
        staged_liberty.unlink()

    accepted = case in ('fresh_detect', 'cache_reuse', 'selected_ss', 'selected_ff')
    fresh_record, fresh_why = T.read_step7_asic_sdc(R, proj, TOP, detect(proj, 'neutral_pdk'))
    assert (fresh_record is not None) is accepted, fresh_why
    if not accepted:
        assert '@liberty' in fresh_why, fresh_why

    params = {'pdk_name': 'neutral_pdk', 'image_id': 'source-control-image',
              'pdk_root': str(host_root), 'top': TOP, 'container': 'fixture-container'}
    refusal = None
    try:
        _, _, current_pdk, _ = producers._parameters(proj, params)
        record, why = T.read_step7_asic_sdc(R, proj, TOP, current_pdk)
        current_path, seam_why = R._prepnr_constraint_file(proj, TOP, current_pdk)
    except ll.Refusal as exc:
        refusal = str(exc)
        record, current_path, why, seam_why = None, None, refusal, refusal
    observation = {'case': case, 'producer_status': result.status,
                   'record_liberty': _record(proj)['inputs']['@liberty'],
                   'record_liberty_sha256': _record(proj)['inputs']['@liberty_sha256'],
                   'reader_accepted': record is not None, 'reader_reason': why,
                   'seam_accepted': current_path is not None, 'seam_reason': seam_why,
                   'corner_count': result.extras['corner_count'], 'resolver_refusal': refusal}
    (tmp_path / 'observed.json').write_text(json.dumps(observation, indent=2) + '\n')
    print(json.dumps(observation, sort_keys=True))
    assert (record is not None) is accepted, observation
    assert (current_path is not None) is accepted, observation
    if accepted:
        assert record['inputs']['@liberty'] == str(staged_liberty)
        assert record['inputs']['@liberty_sha256'] == hashlib.sha256(staged_liberty.read_bytes()).hexdigest()
        assert stage_calls
    else:
        assert refusal or '@liberty' in why, observation
    assert (proj / CONS / T.ASIC_SDC_RECORD).read_bytes() == record_before
    assert (proj / _record(proj)['path']).read_bytes() == sdc_before
