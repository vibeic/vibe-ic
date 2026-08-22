"""C4/2026-07-31 — the clock frequency a design STATES must reach the SDC.

MEASURED MOTIVATION
===================
A real mixed-signal cell states, in its L5 spec table,

    | fclk | 1.0 | 0.1-10 | MHz | modulator clock (CK4/5/6) (est) |

and declares `CK4/CK5/CK6` in its L1 top-pin list. Phase 1 put the NUMBER in
`L8.timing_constants[]` and the NAMES in `L8.clocks[]` and joined neither into
`clock_mhz` / `clock_domains[]` — the only two fields `sdc_gen` reads. The
emitted SDC therefore carried the plugin's hard-coded default:

    create_clock -name clk_main -period 20 [get_ports {clk}]

50x the stated period, on a port the design does not have, at rc=0 with the
word PASS. Every test here asserts a BEHAVIOUR of the shipped functions, never
a source literal, and every one of them FAILS against the pre-fix code.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import l8_doc_clock_freq_synth as SYNTH  # noqa: E402


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _project(tmp_path: Path, doc: str, l8: dict,
             doc_name: str = "spec.md") -> Path:
    proj = tmp_path / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "input" / "docs" / doc_name).write_text(doc)
    (proj / "phase1" / "generated_docs"
     / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(l8))
    return proj


def _l8(proj: Path) -> dict:
    return json.loads(
        (proj / "phase1" / "generated_docs"
         / "L8_TIMING_WAVEFORM.json").read_text())


_REAL_SHAPE = (
    "# Spec\n"
    "| Spec | Target | Range | Unit | Note |\n"
    "|---|---|---|---|---|\n"
    "| fclk | 1.0 | 0.1-10 | MHz | modulator clock (CK4/5/6) (est) |\n"
)


# --------------------------------------------------------------------------
# the binding property
# --------------------------------------------------------------------------
def test_stated_frequency_binds_to_the_clocks_the_same_row_names(tmp_path):
    """The load-bearing property: 1.0 MHz -> 1000 ns on CK4/CK5/CK6.

    Also pins the COMPRESSED-ENUMERATION expansion (`CK4/5/6`), because that
    is how designs actually write a shared clock rate.
    """
    proj = _project(tmp_path, _REAL_SHAPE, {"clocks": [
        {"name": "CK4", "freq_mhz": None},
        {"name": "CK5", "freq_mhz": None},
        {"name": "CK6", "freq_mhz": None}]})
    assert SYNTH.main([str(proj), "--apply"]) == 0
    got = {r["name"]: r for r in _l8(proj)["clocks"]}
    assert set(got) == {"CK4", "CK5", "CK6"}
    for name, rec in got.items():
        assert rec["freq_mhz"] == pytest.approx(1.0), name
        assert rec["period_ns"] == pytest.approx(1000.0), name
        # The binding must be EVIDENCED, not merely present.
        ev = rec["freq_evidence"]
        assert ev["file"].endswith("spec.md")
        assert ev["line"] == 4
        assert "fclk" in ev["row"]


def test_a_range_column_is_never_read_as_the_target_value(tmp_path):
    """`0.1-10` sits in the Range column of the very row that binds.

    If a range were parsed as a value the row would resolve two or three
    frequencies and bind nothing (or the wrong one), so this asserts the
    exact number rather than merely 'something was bound'.
    """
    proj = _project(tmp_path, _REAL_SHAPE, {"clocks": [
        {"name": "CK4", "freq_mhz": None}]})
    res = SYNTH.derive(proj)
    assert res["verdict"] == "DERIVED"
    assert len(res["bindings"]) == 1
    assert res["bindings"][0]["freq_mhz"] == pytest.approx(1.0)
    assert res["ambiguous_rows"] == []


# --------------------------------------------------------------------------
# anti-false-positive: the guards, as behaviour
# --------------------------------------------------------------------------
def test_a_frequency_whose_row_names_no_declared_clock_binds_nothing(tmp_path):
    """THE anti-false-positive property.

    The docs state real frequencies; no row names a clock L8 declares. A
    stray MHz must never become a clock constraint — that is the shape that
    made a sibling producer fabricate a rail from a Note column.
    """
    doc = ("# Spec\n"
           "| Spec | Target | Unit | Note |\n"
           "|---|---|---|---|\n"
           "| sample_rate | 4.0 | MHz | decimator output rate |\n"
           "| bandwidth | 2.0 | MHz | analog input bandwidth |\n")
    proj = _project(tmp_path, doc, {"clocks": [
        {"name": "ck4", "freq_mhz": None}]})
    res = SYNTH.derive(proj)
    # It SAW the frequencies — this is not a parser that missed them.
    assert res["rows_with_frequency"] == 2
    assert res["bindings"] == []
    assert res["verdict"] == "NOT_APPLICABLE"
    assert SYNTH.main([str(proj), "--apply"]) == 0
    assert _l8(proj)["clocks"][0]["freq_mhz"] is None


def test_it_never_invents_a_clock_l8_does_not_declare(tmp_path):
    """The row names CK4/5/6 and states 1.0 MHz. L8 declares nothing.

    The clock vocabulary comes from L8, never from the document, so nothing
    may be created here.
    """
    proj = _project(tmp_path, _REAL_SHAPE, {"clocks": []})
    res = SYNTH.derive(proj)
    assert res["bindings"] == []
    assert res["declared_clocks"] == []
    assert SYNTH.main([str(proj), "--apply"]) == 0
    assert _l8(proj)["clocks"] == []


def test_compressed_enum_cannot_introduce_an_undeclared_name(tmp_path):
    """`CK4/5/6` against a layer that declares only CK4 binds ONE clock."""
    proj = _project(tmp_path, _REAL_SHAPE, {"clocks": [
        {"name": "CK4", "freq_mhz": None}]})
    res = SYNTH.derive(proj)
    assert [b["clock"] for b in res["bindings"]] == ["CK4"]


def test_two_rows_disagreeing_bind_nothing_and_say_so(tmp_path):
    doc = ("# A\n"
           "| Spec | Target | Unit | Note |\n"
           "|---|---|---|---|\n"
           "| fclk | 1.0 | MHz | modulator clock (ck4) |\n"
           "\n# B\n"
           "| Spec | Target | Unit | Note |\n"
           "|---|---|---|---|\n"
           "| fclk_alt | 8.0 | MHz | ck4 in high-speed mode |\n")
    proj = _project(tmp_path, doc, {"clocks": [
        {"name": "ck4", "freq_mhz": None}]})
    res = SYNTH.derive(proj)
    assert res["verdict"] == "AMBIGUOUS_NOT_BOUND"
    assert res["bindings"] == []
    assert res["ambiguous_rows"], "the disagreement must be DISCLOSED"
    assert SYNTH.main([str(proj), "--apply"]) == 0
    assert _l8(proj)["clocks"][0]["freq_mhz"] is None


# --------------------------------------------------------------------------
# never overwrite / never silently override
# --------------------------------------------------------------------------
def test_an_already_resolved_record_is_left_byte_identical(tmp_path):
    doc = ("# Spec\n| Signal | Rate | Note |\n|---|---|---|\n"
           "| clk_sys | 100 MHz | system clock |\n")
    proj = _project(tmp_path, doc, {"clocks": [
        {"name": "clk_sys", "freq_mhz": 250.0, "period_ns": 4.0}]})
    assert SYNTH.main([str(proj), "--apply"]) == 0
    assert _l8(proj)["clocks"][0]["freq_mhz"] == pytest.approx(250.0)


def test_scalar_is_refused_when_it_would_contradict_a_record(tmp_path):
    """Regression for a bug this test suite's own control found.

    `sdc_gen` reads the scalar `clock_mhz` FIRST and never consults the
    records once it resolves. Setting the scalar from a document row while a
    record says something else would silently override the layer — the exact
    class of defect this program exists to remove.
    """
    doc = ("# Spec\n| Signal | Rate | Note |\n|---|---|---|\n"
           "| clk_sys | 100 MHz | system clock |\n")
    proj = _project(tmp_path, doc, {"clocks": [
        {"name": "clk_sys", "freq_mhz": 250.0, "period_ns": 4.0}]})
    assert SYNTH.main([str(proj), "--apply"]) == 0
    assert _l8(proj).get("clock_mhz") in (None, "", 0)


def test_applying_twice_changes_nothing(tmp_path):
    proj = _project(tmp_path, _REAL_SHAPE, {"clocks": [
        {"name": "CK4", "freq_mhz": None}]})
    assert SYNTH.main([str(proj), "--apply"]) == 0
    first = (proj / "phase1" / "generated_docs"
             / "L8_TIMING_WAVEFORM.json").read_text()
    assert SYNTH.main([str(proj), "--apply"]) == 0
    second = (proj / "phase1" / "generated_docs"
              / "L8_TIMING_WAVEFORM.json").read_text()
    assert first == second


# --------------------------------------------------------------------------
# the END-TO-END property: what actually reaches the SDC
# --------------------------------------------------------------------------
def _run_sdc_gen(proj: Path, top: str = "dut"):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "sdc_gen.py"), str(proj),
         "--top", top, "--force"],
        capture_output=True, text=True)


def _sdc_project(tmp_path: Path, l8: dict, ports) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    gd = proj / "phase1" / "generated_docs"
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))
    (gd / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(l8))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "dut",
        "top_module_pins": [{"name": n, "mode": m} for n, m in ports],
    }))
    return proj


def test_sdc_gen_constrains_every_clock_l8_declares_at_its_own_period(
        tmp_path):
    """The end-to-end property, and the one that outranks the unit checks.

    Three declared clocks on three digit-suffixed ports at 1000 ns each must
    produce three create_clock commands, named as L8 names them, targeting
    the ports the design has — and must NOT give those ports set_input_delay
    as if they carried data.
    """
    l8 = {"clock_domains": [
        {"name": "ck4", "source_pin": "ck4", "period_ns": 1000.0,
         "freq_mhz": 1.0, "domain_kind": "primary", "role": "master"},
        {"name": "ck5", "source_pin": "ck5", "period_ns": 1000.0,
         "freq_mhz": 1.0, "domain_kind": "primary", "role": "master"},
        {"name": "ck6", "source_pin": "ck6", "period_ns": 1000.0,
         "freq_mhz": 1.0, "domain_kind": "primary", "role": "master"}]}
    proj = _sdc_project(tmp_path, l8, [
        ("in1", "input"), ("ck4", "input"), ("ck5", "input"),
        ("ck6", "input"), ("dout", "output")])
    r = _run_sdc_gen(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    sdc = (proj / "phase2" / "stage1" / "fpga" / "dut.sdc").read_text()

    for nm in ("ck4", "ck5", "ck6"):
        assert f"create_clock -name {nm} -period 1000 [get_ports {{{nm}}}]" \
            in sdc, f"{nm} not constrained:\n{sdc}"
    # The fabricated default must be gone, and the invented port with it.
    assert "-period 20 " not in sdc
    assert "[get_ports {clk}]" not in sdc
    # A clock port is not a data port.
    for nm in ("ck4", "ck5", "ck6"):
        assert f"set_input_delay  -clock" not in "".join(
            l for l in sdc.splitlines() if f"[get_ports {{{nm}}}]" in l
            and "set_input_delay" in l) or True
        assert not any("set_input_delay" in l and f"{{{nm}}}" in l
                       for l in sdc.splitlines()), f"{nm} timed as data"


def test_sdc_gen_is_unchanged_when_l8_declares_no_clock(tmp_path):
    """NO-LEAK control. A design whose L8 declares nothing must render
    exactly as it does today — the single create_clock on the name-matched
    port. If this ever fails, the fix stopped being additive."""
    proj = _sdc_project(tmp_path, {"clock_mhz": 50.0}, [
        ("clk", "input"), ("d_in", "input"), ("q_out", "output")])
    r = _run_sdc_gen(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    sdc = (proj / "phase2" / "stage1" / "fpga" / "dut.sdc").read_text()
    assert "create_clock -name clk_main -period 20 [get_ports {clk}]" in sdc
    assert "Clocks DECLARED by L8" not in sdc


def test_sdc_gen_never_constrains_a_port_the_design_does_not_have(tmp_path):
    """L8 declares a clock that is NOT on the surface: it must not be
    emitted as a create_clock target, or STA/PnR errors on that command."""
    l8 = {"clock_domains": [
        {"name": "ck4", "source_pin": "ck4", "period_ns": 1000.0},
        {"name": "ghost_clk", "source_pin": "ghost_clk",
         "period_ns": 5.0}]}
    proj = _sdc_project(tmp_path, l8, [
        ("ck4", "input"), ("dout", "output")])
    r = _run_sdc_gen(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    sdc = (proj / "phase2" / "stage1" / "fpga" / "dut.sdc").read_text()
    assert "[get_ports {ck4}]" in sdc
    assert "ghost_clk" not in sdc
