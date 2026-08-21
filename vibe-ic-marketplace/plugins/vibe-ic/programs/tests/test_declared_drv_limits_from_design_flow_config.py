"""The design declares its max-fanout cap in its OWN staged flow config, and the
SDC builder only ever looked in the L9 markdown — so the cap was never applied and
the sign-off max-fanout table came back empty BY CONSTRUCTION (UNMEASURED, not zero).

現象 (caravel_user_project x sky130A, clean-room v1.8.90): the design ships

    input/design_src/openlane/user_proj_example/config.json
        "MAX_FANOUT_CONSTRAINT": 16,
        "pdk::sky130*":   { "scl::sky130_fd_sc_ls": { "SYNTH_MAX_FANOUT": 5 } },
        "pdk::gf180mcuC": { "SYNTH_MAX_FANOUT": 4 }

    input/design_src/openlane/user_project_wrapper/signoff.sdc
        set_max_fanout $::env(MAX_FANOUT_CONSTRAINT) [current_design]

and the emitted `phase3/stage3/pnr/constraint.sdc` carried

    create_clock -name clk -period 25.0 [get_ports wb_clk_i]
    set_max_transition 1.5 [current_design]
    set_max_capacitance 5.0 [current_design]
    # <- no set_max_fanout

`_l9_declared_max_fanout` reads ONLY `input/docs/L9*` + the generated L-docs, with a
regex that matches a MARKDOWN TABLE ROW (`SYNTH_MAX_FANOUT` | **N** |). This design
declares the cap in a JSON config instead, so the resolver returned None, no
`set_max_fanout` was emitted, `repair_design` never split the high-fanout tie nets,
and post-route sign-off reported 449 DRV violations (max_slew x447, max_capacitance x2)
while the max-fanout table stayed empty by construction.

Fix: `floorplan_contract.declared_drv_limits()` — read the DRV limits from the SAME
staged OpenLane-style configs the floorplan contract already reads for DIE_AREA /
FP_SIZING / FP_PIN_ORDER_CFG, and have `_l9_declared_max_fanout` consult it when the
L-docs declare no number. Pure ADDITION: a design whose L9 states a cap is unaffected.

PER-PDK / PER-SCL is the load-bearing half (this is exactly the v1.8.90 lesson — the
cap is a per-PDK quantity and was being read without the PDK). An OpenLane config
routinely carries caps for PDKs and cell libraries this run is NOT building for:

  * `pdk::gf180mcuC -> SYNTH_MAX_FANOUT 4` must NOT be applied to a sky130A run;
  * `scl::sky130_fd_sc_ls -> SYNTH_MAX_FANOUT 5` must NOT be applied to a
    sky130_fd_sc_hd run;
  * a block that DOES match overrides the top-level value.

Applying a foreign PDK's cap would silently over-constrain a design — the leak this
guards. chip-AGNOSTIC: pure OpenLane config-key grammar; no chip, PDK or design
literal decides anything (the PDK/SCL names come from the caller).
"""
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import floorplan_contract as FC  # noqa: E402
import phase3_one_shot_runner as P3  # noqa: E402


# The real shape, reduced: a top-level cap plus two non-applicable scoped caps.
CFG = {
    "DESIGN_NAME": "user_proj_example",
    "DIE_AREA": [0, 0, 2800, 1760],
    "FP_SIZING": "absolute",
    "CLOCK_PERIOD": 25,
    "MAX_TRANSITION_CONSTRAINT": 1.0,
    "MAX_FANOUT_CONSTRAINT": 16,
    "pdk::sky130*": {
        "RT_MAX_LAYER": "met4",
        "scl::sky130_fd_sc_hd": {"CLOCK_PERIOD": 25},
        "scl::sky130_fd_sc_ls": {"CLOCK_PERIOD": 10, "SYNTH_MAX_FANOUT": 5},
    },
    "pdk::gf180mcuC": {
        "STD_CELL_LIBRARY": "gf180mcu_fd_sc_mcu7t5v0",
        "SYNTH_MAX_FANOUT": 4,
    },
    "meta": {"version": 2},
}


def _stage(tmp_path: Path, cfg: dict, sub: str = "design_src/openlane/blk") -> Path:
    d = tmp_path / "input" / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.json").write_text(json.dumps(cfg, indent=2))
    return tmp_path


# ── the fix: the design's own config is a declaration the flow must read ──────

def test_top_level_cap_is_read_for_the_active_pdk(tmp_path):
    proj = _stage(tmp_path, CFG)
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_fanout") == 16, lim
    assert "config.json" in (lim.get("max_fanout_source") or ""), lim


def test_matching_scl_block_overrides_the_top_level(tmp_path):
    proj = _stage(tmp_path, CFG)
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_ls")
    assert lim.get("max_fanout") == 5, lim


def test_max_transition_is_read_too(tmp_path):
    proj = _stage(tmp_path, CFG)
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_transition_ns") == 1.0, lim


# ── NEGATIVE no-leak: a cap scoped to a PDK/SCL we are NOT building must not apply ──

def test_foreign_pdk_cap_does_not_leak(tmp_path):
    """`pdk::gf180mcuC -> SYNTH_MAX_FANOUT 4` must never reach a sky130A run."""
    proj = _stage(tmp_path, CFG)
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_fanout") != 4, f"foreign-PDK cap leaked: {lim}"


def test_foreign_scl_cap_does_not_leak(tmp_path):
    """`scl::sky130_fd_sc_ls -> 5` must not apply to a sky130_fd_sc_hd run."""
    proj = _stage(tmp_path, CFG)
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_fanout") != 5, f"foreign-SCL cap leaked: {lim}"


def test_only_scoped_caps_and_none_match_yields_nothing(tmp_path):
    """No top-level cap + no matching scope => no fabricated cap."""
    cfg = {"DESIGN_NAME": "blk", "DIE_AREA": [0, 0, 10, 10],
           "pdk::gf180mcuC": {"SYNTH_MAX_FANOUT": 4}}
    proj = _stage(tmp_path, cfg)
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_fanout") is None, lim


def test_no_config_yields_nothing(tmp_path):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    lim = FC.declared_drv_limits(tmp_path, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_fanout") is None, lim


def test_non_positive_cap_is_not_a_declaration(tmp_path):
    proj = _stage(tmp_path, {"DESIGN_NAME": "blk", "DIE_AREA": [0, 0, 10, 10],
                             "MAX_FANOUT_CONSTRAINT": 0})
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_fanout") is None, lim


def test_oracle_tree_is_not_read(tmp_path):
    """§4.05 — a cap sitting in a golden / reference-flow tree is off-limits."""
    proj = _stage(tmp_path, CFG, sub="reference_flow/openlane/blk")
    lim = FC.declared_drv_limits(proj, pdk="sky130A", scl="sky130_fd_sc_hd")
    assert lim.get("max_fanout") is None, f"read an off-limits tree: {lim}"


# ── the consumer: _l9_declared_max_fanout must now resolve it ────────────────

def test_runner_resolver_picks_up_the_design_config(tmp_path):
    proj = _stage(tmp_path, CFG)
    (proj / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (proj / "input" / "docs" / "L9_constraints_floorplan.md").write_text(
        "# L9\n\n- PDK: SKY130A. Standard-cell lib: sky130_fd_sc_hd.\n"
        "- CLOCK_PERIOD = 25 ns.\n")
    assert P3._l9_declared_max_fanout(proj, "sky130A") == 16


def test_l9_explicit_number_still_wins(tmp_path):
    """Pure addition: an L9 that states the cap keeps deciding it."""
    proj = _stage(tmp_path, CFG)
    (proj / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (proj / "input" / "docs" / "L9_constraints_floorplan.md").write_text(
        "| key | value |\n|---|---|\n| `SYNTH_MAX_FANOUT` | **9** |\n")
    assert P3._l9_declared_max_fanout(proj, "sky130A") == 9


def test_runner_resolver_returns_none_without_any_declaration(tmp_path):
    (tmp_path / "input" / "docs").mkdir(parents=True)
    (tmp_path / "input" / "docs" / "L9_constraints_floorplan.md").write_text(
        "# L9\n\nnothing about fanout here\n")
    assert P3._l9_declared_max_fanout(tmp_path, "sky130A") is None
