"""ORGANIC DPL-0036 — the well-tap lattice must be able to host the cells the
flow itself places.

The defect these tests pin
--------------------------
`tapcell -distance D -tapcell_master T` tiles EVERY standard-cell row with
FIXED well-tie cells at a pitch of ``2*D``, so the widest single-height cell
the lattice can host between two consecutive taps is::

    G = 2*D - width(T)

A CORE master wider than ``G`` has NO legal site anywhere on the die — at ANY
utilization, on ANY die size.  Nothing upstream knows that: the resizer inside
timing-driven `global_placement` sizes buffers for slew/capacitance and CTS
sizes the clock root for fanout, and both are free to pick the library's widest
masters.  When one of them does, `detailed_placement` aborts and takes the
whole PnR with it::

    [INFO  RSZ-0038] Inserted 564 buffers in 155 nets
    [INFO  DPL-0034] Detailed placement failed on the following 13 instances:
    [ERROR DPL-0036] Detailed placement failed inside DPL.

MEASURED first occurrence (5V 180nm PDK, 8203-instance RISC-V SoC, 839µm die,
42.2% utilization — a 58%-empty die, so this is NOT a density problem, and the
legalizer already had ±500 sites / ±100 rows of displacement headroom):

    D=14.0µm, tap=1.12µm            -> G = 26.88µm
    placed DEF, 205 rows, 5700 inter-tap gaps: 5582 x 26.88µm, 118 x 12.32µm
                                    -> max INTERIOR gap 26.88µm, none wider
    resizer inserted  4 x 34.72µm   -> 0/205 rows can host -> 4/4 FAILED
    resizer inserted 15 x 28.00µm   -> 0/205 interior slots -> 9/15 FAILED
    everything <= 21.28µm (1816)    -> 0 FAILED
    widest master in the SYNTHESIZED netlist: 17.92µm (the design always fitted)

The correlation with cell WIDTH is exact and the cause is entirely inside the
flow, which makes it chip-AGNOSTIC: any PDK whose widest placeable CORE master
exceeds its own configured lattice gap is one resizer decision away from the
same death.

Why the tap pitch is NOT what gets relaxed: the tap distance is a PDK latch-up
rule (the affected library's shipped KLayout deck states a 15µm max
tap-to-device distance for its 5V cells; the flow's 14.0µm sits under it).
Hosting a 34.72µm buffer would need D>=17.9µm and would silently break that
rule — a loud legalization failure traded for a quiet reliability one.  So the
CELL POOL yields: masters the lattice cannot host are removed from the
resizer/CTS/mapper pool, exactly the mechanism the flow already uses for
PnR-forbidden cells, and the tap density is untouched.

NEGATIVE CONTROL: every test below except the pure-geometry ones fails against
the pre-fix runner — `_build_tapcell_lattice_guard_tcl`,
`_lattice_fit_cts_buffer` and `_extract_dpl_legalization_failure` do not exist
there, and `_build_tapcell_tcl` emits a bare `tapcell` call with no guard.

Fixtures are deliberately generic (``PDKX_*``): the mechanism keys on LEF
geometry only, never on a vendor, PDK, cell or design name.
"""
import re
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import phase3_one_shot_runner as R  # noqa: E402
import tapcell_lattice_placeability_check as T  # noqa: E402


# --------------------------------------------------------------------------
# Generic fixtures — a library shaped like the affected one, no real names.
# --------------------------------------------------------------------------
SITE_UM = 0.56
ROW_H_UM = 3.92
TAP_W_UM = 1.12
TAP_DIST_UM = 14.0          # -> G = 2*14.0 - 1.12 = 26.88um

_LEF_MACROS = [
    # (name, width_um, CLASS)
    ("PDKX_TAP", TAP_W_UM, "CORE WELLTAP"),
    ("PDKX_FILL_64", 35.84, "CORE SPACER"),      # SPACER: never lattice-bound
    ("PDKX_ANTENNA", 1.12, "CORE ANTENNACELL"),
    ("PDKX_TIEH", 2.24, "CORE TIEHIGH"),
    ("PDKX_buf_1", 2.24, "CORE"),
    ("PDKX_buf_2", 4.48, "CORE"),
    ("PDKX_buf_4", 7.84, "CORE"),
    ("PDKX_buf_8", 14.56, "CORE"),
    ("PDKX_buf_12", 21.28, "CORE"),              # fits  (21.28 <= 26.88)
    ("PDKX_buf_16", 28.00, "CORE"),              # does NOT fit
    ("PDKX_buf_20", 34.72, "CORE"),              # does NOT fit
    ("PDKX_clkbuf_4", 9.52, "CORE"),
    ("PDKX_clkbuf_12", 21.28, "CORE"),
    ("PDKX_clkbuf_16", 28.00, "CORE"),           # does NOT fit
    ("PDKX_sdff_4", 30.24, "CORE"),              # a FLOP that does not fit
    ("PDKX_inv_1", 1.68, "CORE"),
]


def _lef_text() -> str:
    out = ["VERSION 5.8 ;", "UNITS", "  DATABASE MICRONS 2000 ;", "END UNITS"]
    for name, w, cls in _LEF_MACROS:
        out += [
            f"MACRO {name}",
            f"  CLASS {cls} ;",
            f"  SIZE {w} BY {ROW_H_UM} ;",
            "  SITE PDKX_SITE ;",
            f"END {name}",
        ]
    out.append("END LIBRARY")
    return "\n".join(out) + "\n"


def _pdk(tapcell_master="PDKX_TAP", distance=TAP_DIST_UM):
    return R.PdkConfig(
        name="pdkx", liberty="/p/lib.lib", tech_lef="/p/tech.lef",
        cell_lef="/p/cells.lef", cell_gds="/p/cells.gds", site="PDKX_SITE",
        drc_deck=None, tapcell_master=tapcell_master,
        tapcell_distance_um=distance)


# --------------------------------------------------------------------------
# 1. The geometry itself
# --------------------------------------------------------------------------
def test_lattice_free_gap_reproduces_the_measured_interior_gap():
    """G = 2*D - tap_width, validated against a real placed DEF.

    D=14.0µm with a 1.12µm tap produced 5582 interior gaps of exactly
    26.88µm and none wider, over 205 rows.
    """
    assert T.lattice_free_gap_um(14.0, 1.12) == pytest.approx(26.88)
    # Widening the tap distance widens the gap linearly (2x), which is
    # exactly why relaxing the latch-up rule is the tempting-but-wrong fix.
    assert T.lattice_free_gap_um(20.0, 1.12) == pytest.approx(38.88)


def test_only_plain_core_masters_are_lattice_bound():
    """SPACER / WELLTAP / ANTENNACELL / TIEHIGH are placed by dedicated steps
    at coordinates those steps choose, so the lattice constraint is not theirs
    — a 35.84µm filler must never be reported as unplaceable."""
    macros = T.parse_lef_macro_geometry(_lef_text())
    gap = T.lattice_free_gap_um(TAP_DIST_UM, TAP_W_UM)
    over = dict(T.over_wide_core_masters(macros, gap))
    assert "PDKX_FILL_64" not in over        # 35.84µm SPACER — exempt
    assert "PDKX_TAP" not in over
    assert set(over) == {"PDKX_buf_16", "PDKX_buf_20", "PDKX_clkbuf_16",
                         "PDKX_sdff_4"}
    # Widest-first ordering, so a report leads with the worst offender.
    assert T.over_wide_core_masters(macros, gap)[0][0] == "PDKX_buf_20"


def test_a_library_that_fits_yields_no_exclusion_at_all():
    """The no-op property that makes this safe to ship everywhere.

    Measured on the other registered PDKs: widest usable CORE master 15.18µm
    against a 27.54µm gap, and 9.31µm against a 39.81µm gap — both fit, so the
    guard excludes nothing and the flow is byte-identical there.
    """
    macros = T.parse_lef_macro_geometry(_lef_text())
    roomy = T.lattice_free_gap_um(30.0, TAP_W_UM)     # 58.88um
    assert T.over_wide_core_masters(macros, roomy) == []


def test_widest_fitting_family_member_downgrades_within_the_family():
    macros = T.parse_lef_macro_geometry(_lef_text())
    gap = T.lattice_free_gap_um(TAP_DIST_UM, TAP_W_UM)
    # 28.00µm clock root -> strongest clkbuf that fits, NOT a random buffer.
    assert T.widest_fitting_family_member(
        "PDKX_clkbuf_16", macros, gap) == "PDKX_clkbuf_12"
    # A cell that already fits is never touched.
    assert T.widest_fitting_family_member("PDKX_clkbuf_4", macros, gap) is None
    # Never invent a substitute from a foreign family: a lone over-wide cell
    # with no fitting sibling returns None so the caller keeps the configured
    # name and the failure stays visible.
    lone = T.parse_lef_macro_geometry(
        "MACRO PDKX_only_99\n  CLASS CORE ;\n  SIZE 99 BY 3.92 ;\n"
        "END PDKX_only_99\n")
    assert T.widest_fitting_family_member("PDKX_only_99", lone, gap) is None


# --------------------------------------------------------------------------
# 2. The artifact audit — the negative control that runs on a real DEF
# --------------------------------------------------------------------------
def _synthetic_def(widest_master: str) -> str:
    """A DEF with the SAME lattice shape as the failing run: FIXED taps at a
    2*D pitch in every row, plus one placed instance of ``widest_master``."""
    dbu = 2000
    rows, comps = [], []
    n_rows, n_sites = 6, 200
    # Integer-DBU arithmetic so the emitted gap is EXACT (a real DEF is on the
    # site grid; float accumulation would blur the very number under test).
    pitch_dbu = int(2 * TAP_DIST_UM * dbu)
    x0_dbu = int(10.08 * dbu)
    row_span_dbu = n_sites * int(SITE_UM * dbu)
    for r in range(n_rows):
        y = int(11.76 * dbu) + r * int(ROW_H_UM * dbu)
        rows.append(f"ROW ROW_{r} PDKX_SITE {x0_dbu} {y} "
                    f"{'N' if r % 2 == 0 else 'FS'} DO {n_sites} BY 1 "
                    f"STEP {int(SITE_UM * dbu)} 0 ;")
        x = int(23.52 * dbu)
        i = 0
        while x < x0_dbu + row_span_dbu - pitch_dbu:
            comps.append(f"    - TAP_{r}_{i} PDKX_TAP + SOURCE DIST + FIXED "
                         f"( {x} {y} ) N ;")
            x += pitch_dbu
            i += 1
    y0 = int(11.76 * dbu)
    comps.append(f"    - u_wide {widest_master} + SOURCE TIMING + PLACED "
                 f"( {int(30.0 * dbu)} {y0} ) N ;")
    return ("VERSION 5.8 ;\nDESIGN pdkx_dut ;\n"
            f"UNITS DISTANCE MICRONS {dbu} ;\n"
            f"DIEAREA ( 0 0 ) ( {int(200 * dbu)} {int(100 * dbu)} ) ;\n"
            + "\n".join(rows) + "\n"
            + f"COMPONENTS {len(comps)} ;\n" + "\n".join(comps)
            + "\nEND COMPONENTS\nEND DESIGN\n")


def test_def_audit_fails_when_the_lattice_cannot_host_a_placed_master():
    macros = T.parse_lef_macro_geometry(_lef_text())
    rep = T.measure_def_lattice_gaps(_synthetic_def("PDKX_buf_20"), macros)
    assert rep["verdict"] == "FAIL"
    assert rep["max_interior_tap_free_gap_um"] == pytest.approx(26.88)
    assert rep["widest_placed_width_um"] == pytest.approx(34.72)
    assert rep["rows_that_can_host_widest_placed"] == 0


def test_def_audit_passes_when_every_placed_master_fits():
    macros = T.parse_lef_macro_geometry(_lef_text())
    rep = T.measure_def_lattice_gaps(_synthetic_def("PDKX_buf_12"), macros)
    assert rep["verdict"] == "PASS"
    assert rep["rows_that_can_host_widest_placed"] == rep["rows"]


# --------------------------------------------------------------------------
# 3. The PnR emitter — NEGATIVE CONTROL against the pre-fix runner
# --------------------------------------------------------------------------
def test_tapcell_block_emits_the_lattice_guard_after_insertion():
    tcl = R._build_tapcell_tcl(_pdk())
    assert "tapcell -distance 14.0 -tapcell_master PDKX_TAP" in tcl
    # The guard must come AFTER the taps exist and BEFORE global_placement.
    assert tcl.index("tapcell -distance") < tcl.index("_lat_gap")
    # It must compute G from the tap master's own width, not a constant.
    assert "findMaster PDKX_TAP" in tcl
    assert "2.0 * 14.0 - $_lat_tapw" in tcl
    # It must narrow the optimizer pool, never the tap density.
    assert "set_dont_use" in tcl
    assert "tapcell -distance" in tcl and "-distance 14.0" in tcl
    # Only plain CLASS CORE masters are lattice-bound.
    assert '[$_lat_m getType] ne "CORE"' in tcl
    # Safety valve — never gut the pool on an implausible measurement.
    assert "[llength $_lat_over] * 2 <= $_lat_core" in tcl
    # Everything NONFATAL-guarded: a Tcl/API surprise degrades to a no-op.
    assert "TAPCELL_LATTICE_MEASURE_NONFATAL" in tcl
    assert "TAPCELL_LATTICE_SCAN_NONFATAL" in tcl
    # Machine-readable attestation for the log.
    assert "TAPCELL_LATTICE_GUARD_APPLIED" in tcl
    # A master the NETLIST already carries cannot be un-mapped here, so it is
    # disclosed rather than silently ignored.
    assert "TAPCELL_LATTICE_OVERWIDE_INSTANTIATED" in tcl


def test_no_lattice_guard_without_a_tap_lattice():
    """A PDK that ships no tap master has no lattice, hence no constraint."""
    tcl = R._build_tapcell_tcl(_pdk(tapcell_master=None))
    assert "TAPCELL_SKIPPED" in tcl
    assert "_lat_gap" not in tcl
    assert R._build_tapcell_lattice_guard_tcl(_pdk(tapcell_master=None)) == ""


def test_lattice_guard_is_well_formed_tcl():
    """Balanced braces/brackets — the block is spliced into a live script."""
    tcl = R._build_tapcell_lattice_guard_tcl(_pdk())
    body = "\n".join(ln for ln in tcl.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert body.count("{") == body.count("}")
    assert body.count("[") == body.count("]")


def test_lattice_guard_carries_no_design_or_vendor_literal():
    """The only names in the block are the PDK's own configured tap master and
    Tcl locals — a design name would make the mechanism non-general."""
    tcl = R._build_tapcell_lattice_guard_tcl(_pdk())
    body = "\n".join(ln for ln in tcl.splitlines()
                     if not ln.lstrip().startswith("#"))
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", body):
        assert not token.lower().startswith(("sky130", "gf180", "nangate",
                                             "asap7", "sg13"))


# --------------------------------------------------------------------------
# 4. CTS must obey the same lattice — NEGATIVE CONTROL
# --------------------------------------------------------------------------
def test_cts_root_buffer_is_downgraded_when_it_cannot_be_hosted():
    """`clock_tree_synthesis` takes its buffers BY NAME, so `set_dont_use`
    alone would still let an over-wide clock root in — and its legalization
    failure would land on the catch-guarded post-CTS `detailed_placement`,
    i.e. it would become SILENT overlaps instead of a loud abort."""
    macros = T.parse_lef_macro_geometry(_lef_text())
    gap = T.lattice_free_gap_um(TAP_DIST_UM, TAP_W_UM)
    cell, note = R._lattice_fit_cts_buffer("PDKX_clkbuf_16", macros, gap)
    assert cell == "PDKX_clkbuf_12"
    assert "26.88" in note and "PDKX_clkbuf_16" in note


def test_cts_buffer_untouched_when_it_already_fits_or_geometry_is_unknown():
    macros = T.parse_lef_macro_geometry(_lef_text())
    gap = T.lattice_free_gap_um(TAP_DIST_UM, TAP_W_UM)
    assert R._lattice_fit_cts_buffer("PDKX_clkbuf_4", macros, gap) == (
        "PDKX_clkbuf_4", "")
    # No lattice / no geometry -> never touch the configured cell.
    assert R._lattice_fit_cts_buffer("PDKX_clkbuf_16", macros, None) == (
        "PDKX_clkbuf_16", "")
    assert R._lattice_fit_cts_buffer("PDKX_clkbuf_16", {}, gap) == (
        "PDKX_clkbuf_16", "")


def test_pdk_lattice_gap_is_none_without_a_measurable_tap_master():
    macros = T.parse_lef_macro_geometry(_lef_text())
    assert R._pdk_lattice_gap_um(_pdk(), macros) == pytest.approx(26.88)
    assert R._pdk_lattice_gap_um(_pdk(tapcell_master=None), macros) is None
    assert R._pdk_lattice_gap_um(_pdk(tapcell_master="PDKX_ABSENT"),
                                 macros) is None
    assert R._pdk_lattice_gap_um(_pdk(), {}) is None


def test_lef_geometry_reader_degrades_to_empty_not_to_a_wrong_exclusion(
        monkeypatch):
    """A container read that fails must yield "no geometric knowledge" ({}),
    never a partial map that would exclude the wrong masters."""
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(R, "_docker_exec",
                        lambda c, cmd, **kw: (0, _lef_text(), ""))
    got = R._lef_macro_geometry("ctr", "/p/cells.lef")
    assert got["PDKX_buf_20"][0] == pytest.approx(34.72)
    assert got["PDKX_TAP"][1] == "CORE WELLTAP"

    monkeypatch.setattr(R, "_docker_exec",
                        lambda c, cmd, **kw: (1, "", "no such file"))
    assert R._lef_macro_geometry("ctr", "/p/cells.lef") == {}
    monkeypatch.setattr(R, "_docker_exec",
                        lambda c, cmd, **kw: (_ for _ in ()).throw(
                            RuntimeError("boom")))
    assert R._lef_macro_geometry("ctr", "/p/cells.lef") == {}
    assert R._lef_macro_geometry("ctr", None) == {}


# --------------------------------------------------------------------------
# 5. The failure is self-diagnosing — NEGATIVE CONTROL
# --------------------------------------------------------------------------
_REAL_LOG_TAIL = """\
[INFO DPL-0006] Core area: 649823.10 um^2, Instances area: 274103.65 um^2, \
Utilization: 42.2%
[INFO DPL-0005] Diamond search max displacement: +/- 500 sites horizontally, \
+/- 100 rows vertically.
[INFO DPL-1101] Legalizing using diamond search.
Total Placement Failures:         13
[INFO DPL-0034] Detailed placement failed on the following 13 instances:
[INFO DPL-0035]  place2769
[INFO DPL-0035]  place2568
[INFO DPL-0035]  place2386
[ERROR DPL-0036] Detailed placement failed inside DPL.
Error: pnr.tcl, 137 DPL-0036
"""


def test_dpl_legalization_failure_is_recognised_distinctly():
    got = R._extract_dpl_legalization_failure(_REAL_LOG_TAIL)
    assert got is not None
    n, names = got
    assert n == 3 and names[0] == "place2769"
    # A clean log, an over-util log and an empty log must NOT match: the
    # die-resize retry loop keys on GPL-0301 and must stay in charge there.
    assert R._extract_dpl_legalization_failure("") is None
    assert R._extract_dpl_legalization_failure(
        "[ERROR GPL-0301] Utilization 103% exceeds 100%") is None
    assert R._extract_dpl_legalization_failure(
        "[INFO DPL-1101] Legalizing using diamond search.") is None


def test_overutil_and_legalization_failures_stay_independent():
    """A legalization failure is NOT an over-utilization failure — the first
    measured one happened at 42.2% on a 58%-empty die, so it must never be
    routed into the die-upsize path."""
    assert R._extract_overutil_pct(_REAL_LOG_TAIL) is None
