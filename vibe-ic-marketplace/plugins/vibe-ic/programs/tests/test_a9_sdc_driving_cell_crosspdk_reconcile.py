"""A9 — a STAGED/design-supplied SDC (e.g. a reference-flow `*.nangate.sdc`) may
name a `set_driving_cell` library cell from its ORIGINATING PDK. Re-used verbatim
under a DIFFERENT active PDK that cell is ABSENT from the active liberty, and
OpenSTA/OpenROAD ABORT the entire flow at read_sdc:

    [ERROR STA-0453] 'BUF_X2' not found.

`_reconcile_staged_sdc_driving_cell` drops such a line (with disclosure) when the
named cell is DEFINITIVELY absent from the active liberty, and leaves a cell that
IS present untouched. Dropping can only WEAKEN the constraint set (inputs fall
back to the tool default drive) — it can never manufacture a PASS.

These tests use SYNTHETIC cell names not tied to any real PDK, so a hardcoded
cell/PDK literal in the implementation would fail them (chip-AGNOSTIC guard).
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# A synthetic active liberty that DECLARES `MYBUF_2` but NOT `ALIEN_X9`.
_ACTIVE_LIB = """\
library(active_pdk) {
  time_unit : "1ns" ;
  capacitive_load_unit (1, pf) ;
  cell ("MYBUF_2") { pin (Y) { direction : output ; } }
  cell (INV_1)     { pin (Y) { direction : output ; } }
}
"""


def _lib(tmp, text, name="active.lib"):
    p = tmp / name
    p.write_text(text)
    return str(p)


# ── _extract_driving_cell_name — both SDC spellings ─────────────────────────
def test_extract_explicit_lib_cell_form():
    assert R._extract_driving_cell_name(
        "set_driving_cell [all_inputs] -lib_cell ALIEN_X9") == "ALIEN_X9"


def test_extract_bare_form():
    assert R._extract_driving_cell_name("set_driving_cell ALIEN_X9") == "ALIEN_X9"


def test_extract_bare_form_skips_option_values():
    # an option flag and its VALUE must NOT be mistaken for the cell name.
    assert R._extract_driving_cell_name(
        "set_driving_cell -input_transition_rise 0.1 MYBUF_2 [all_inputs]"
    ) == "MYBUF_2"


# ── FORWARD (defect repro) — absent foreign cell is DROPPED ─────────────────
def test_forward_absent_foreign_cell_is_dropped(tmp_path):
    """BIDIRECTIONAL NEGATIVE CONTROL — forward half. Against the PRE-FIX file
    this SDC reaches read_sdc with `ALIEN_X9` still in it (STA-0453 abort);
    after the fix the line is dropped. Non-comment command lines must not name
    the absent cell."""
    lib = _lib(tmp_path, _ACTIVE_LIB)
    staged = (
        "# VIBEIC_SDC_PDK_PROVENANCE: active_pdk\n"
        "set_driving_cell [all_inputs] -lib_cell ALIEN_X9\n"
        "set_load 10.0 [all_outputs]\n"
        "create_clock -name clk -period 10 [get_ports clk]\n"
    )
    out = R._reconcile_staged_sdc_driving_cell(staged, lib)
    cmd_lines = [l.strip() for l in out.split("\n")
                 if l.strip() and not l.strip().startswith("#")]
    # the fatal driving-cell line is GONE from the executable command set
    assert not any(l.startswith("set_driving_cell") for l in cmd_lines)
    assert "ALIEN_X9" not in "\n".join(cmd_lines)
    # a disclosure comment naming the dropped cell is present
    assert any(l.strip().startswith("#") and "ALIEN_X9" in l
               for l in out.split("\n"))
    # everything else is preserved verbatim
    assert "set_load 10.0 [all_outputs]" in out
    assert "create_clock -name clk -period 10 [get_ports clk]" in out


def test_forward_bare_form_absent_cell_dropped(tmp_path):
    lib = _lib(tmp_path, _ACTIVE_LIB)
    staged = "set_driving_cell ALIEN_X9\ncreate_clock -period 8 clk\n"
    out = R._reconcile_staged_sdc_driving_cell(staged, lib)
    cmd_lines = [l.strip() for l in out.split("\n")
                 if l.strip() and not l.strip().startswith("#")]
    assert not any(l.startswith("set_driving_cell") for l in cmd_lines)
    assert "create_clock -period 8 clk" in out


# ── REVERSE (must STILL pass) — a PRESENT cell is KEPT untouched ─────────────
def test_reverse_present_cell_is_kept(tmp_path):
    """BIDIRECTIONAL NEGATIVE CONTROL — reverse half. A driving cell that IS in
    the active liberty must survive unchanged. This is the guard against
    'tighten the filter until the count hits zero': if the fix dropped valid
    driving cells too, this fails."""
    lib = _lib(tmp_path, _ACTIVE_LIB)
    staged = (
        "set_driving_cell [all_inputs] -lib_cell MYBUF_2\n"
        "create_clock -name clk -period 10 [get_ports clk]\n"
    )
    out = R._reconcile_staged_sdc_driving_cell(staged, lib)
    assert out == staged  # byte-identical — a valid cell is never touched


def test_reverse_bare_present_cell_kept(tmp_path):
    lib = _lib(tmp_path, _ACTIVE_LIB)
    staged = "set_driving_cell MYBUF_2 [all_inputs]\n"
    out = R._reconcile_staged_sdc_driving_cell(staged, lib)
    assert out == staged


# ── DEGRADE-LOUDLY — unknown presence never drops the line ──────────────────
def test_unreadable_liberty_leaves_sdc_untouched(tmp_path):
    """An unreadable/missing liberty ⇒ presence UNKNOWN ⇒ the line is LEFT
    untouched (never dropped on a read failure). Degrade loudly, never
    silently mangle."""
    staged = "set_driving_cell [all_inputs] -lib_cell ALIEN_X9\n"
    # non-existent liberty path, no container
    out = R._reconcile_staged_sdc_driving_cell(
        staged, str(tmp_path / "does_not_exist.lib"))
    assert out == staged


def test_no_driving_cell_line_is_byte_identical(tmp_path):
    lib = _lib(tmp_path, _ACTIVE_LIB)
    staged = ("create_clock -name clk -period 10 [get_ports clk]\n"
              "set_max_transition 1.5 [current_design]\n")
    assert R._reconcile_staged_sdc_driving_cell(staged, lib) == staged


# ── SUBSTANTIVE gap proof — the reconcile chain that ALREADY runs pre-fix does
#    NOT remove the foreign driving cell (behavioural, not missing-symbol) ─────
def test_prefix_drv_reconcile_chain_leaves_driving_cell(tmp_path):
    """The DRV-limit reconcile (`_reconcile_staged_sdc_drv`) and the DRV-parity
    ensure (`_ensure_staged_sdc_drv`) are the functions that ran on the staged
    SDC BEFORE this fix. This test proves — using ONLY those pre-existing
    functions — that they re-derive the DRV limits yet leave the foreign
    `set_driving_cell` cell name untouched, so the fatal STA-0453 survived the
    only reconcile that ran. This is the substantive behavioural gap the new
    function closes (it holds on BOTH the pre-fix and post-fix file)."""
    lib_text = """\
library(active_pdk) {
  time_unit : "1ns" ;
  capacitive_load_unit (1, pf) ;
  default_max_transition : 0.42 ;
  cell ("MYBUF_2") { pin (Y) { direction : output ; max_capacitance : 0.19 ; } }
}
"""
    lib = _lib(tmp_path, lib_text)
    staged = ("# VIBEIC_SDC_PDK_PROVENANCE: sky130A\n"
              "set_driving_cell [all_inputs] -lib_cell ALIEN_X9\n"
              "set_max_transition 1.5 [current_design]\n")
    after_drv = R._reconcile_staged_sdc_drv(staged, "active_pdk", lib)
    after_drv, _ = R._ensure_staged_sdc_drv(after_drv, lib)
    # DRV limits were reconciled (stale 1.5 gone) …
    assert "set_max_transition 1.5" not in after_drv
    # … but the foreign driving cell — the actual read_sdc killer — SURVIVES:
    assert "ALIEN_X9" in after_drv          # <── the gap
    # the new function is what removes it:
    fixed = R._reconcile_staged_sdc_driving_cell(after_drv, lib)
    fixed_cmds = "\n".join(l for l in fixed.split("\n")
                           if not l.strip().startswith("#"))
    assert "ALIEN_X9" not in fixed_cmds


# ── The real-world case that motivated this: a Nangate `BUF_X2` on sky130 ────
def test_nangate_buf_x2_dropped_on_sky130_shaped_liberty(tmp_path):
    """The concrete AES case: a reference-flow SDC names Nangate `BUF_X2`; the
    active sky130-shaped liberty declares `..._buf_2`, not `BUF_X2`. Uses a
    liberty shaped like sky130's `cell ("<lib>__buf_N")` spelling."""
    lib_text = """\
library(sky130ish) {
  cell ("sky130ish_fd_sc_hd__buf_2") { pin (X) { direction : output ; } }
  cell ("sky130ish_fd_sc_hd__buf_4") { pin (X) { direction : output ; } }
}
"""
    lib = _lib(tmp_path, lib_text)
    staged = (
        "# VIBEIC_SDC_PDK_PROVENANCE: sky130ish\n"
        "set_driving_cell [all_inputs] -lib_cell BUF_X2\n"
        "set_load 10.0 [all_outputs]\n"
    )
    out = R._reconcile_staged_sdc_driving_cell(staged, lib)
    cmd_lines = [l.strip() for l in out.split("\n")
                 if l.strip() and not l.strip().startswith("#")]
    assert "BUF_X2" not in "\n".join(cmd_lines)
    # a genuinely-present sky130 buffer would have been kept:
    staged_ok = "set_driving_cell -lib_cell sky130ish_fd_sc_hd__buf_2\n"
    assert R._reconcile_staged_sdc_driving_cell(staged_ok, lib) == staged_ok
