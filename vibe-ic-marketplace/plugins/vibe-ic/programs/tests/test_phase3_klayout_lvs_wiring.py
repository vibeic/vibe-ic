"""v1.3.91 — wiring contract for the KLayout geometric-LVS engine + the
DEF→GDS port-label / power-rail restore in phase3_one_shot_runner.

These assert the RUNNER-SIDE integration (config gating + program shipping) that
the three deterministic programs (klayout_pdk_lvs.py, def_gds_port_power_restore.py,
gate_verilog_to_spice.py) plug into. No docker / no pya required — the container-run
compute is exercised end-to-end in the programs' own tests + the proven spm run.

The load-bearing guarantee here: the new engine + restore are STRICTLY OPT-IN
(config-gated), so the general (sky130 / gf180) flow is byte-for-byte unchanged.
"""
import importlib

mod = importlib.import_module("phase3_one_shot_runner")
guard_mod = importlib.import_module("decap_route_short_guard")


class TestPdkConfigDefaults:
    """The new config knobs must default to a no-op so no existing flow changes."""

    def test_lvs_engine_defaults_to_magic(self):
        f = mod.PdkConfig.__dataclass_fields__
        assert f["lvs_engine"].default == "magic"

    def test_port_label_restore_defaults_none(self):
        f = mod.PdkConfig.__dataclass_fields__
        assert f["port_label_restore"].default is None

    def test_lvs_layermap_defaults_none(self):
        f = mod.PdkConfig.__dataclass_fields__
        assert f["lvs_layermap"].default is None


class TestHelpersExist:
    def test_run_klayout_lvs_defined(self):
        assert callable(mod._run_klayout_lvs)

    def test_restore_helper_defined(self):
        assert callable(mod._klayout_restore_port_labels)

    def test_ship_program_defined(self):
        assert callable(mod._ship_program)


class TestShipProgram:
    """_ship_program copies a sibling plugin program into the (mounted) project
    dir so it is reachable at a container path — ONE source of truth, no logic
    duplicated into an embedded script."""

    def test_copies_program_verbatim(self, tmp_path):
        dst = mod._ship_program("klayout_pdk_lvs.py", tmp_path)
        assert dst.is_file()
        src = mod.Path(mod.__file__).resolve().parent / "klayout_pdk_lvs.py"
        assert dst.read_text() == src.read_text()

    def test_ships_all_three_lvs_programs(self, tmp_path):
        for name in ("klayout_pdk_lvs.py", "def_gds_port_power_restore.py",
                     "gate_verilog_to_spice.py"):
            dst = mod._ship_program(name, tmp_path)
            assert dst.is_file() and dst.stat().st_size > 0


class TestRestoreGatedOff:
    """With no port_label_restore config the restore is a pure no-op (returns
    False, never shells into the container)."""

    def test_restore_noop_without_config(self, tmp_path):
        pdk = _min_pdk(mod)
        assert pdk.port_label_restore is None
        ok, note = mod._klayout_restore_port_labels(
            tmp_path, "spm", pdk, "no-such-container",
            tmp_path / "spm.gds", tmp_path / "spm.def")
        assert ok is False
        assert "no port_label_restore config" in note


def _min_pdk(mod):
    """A minimal PdkConfig with only the required positional fields."""
    return mod.PdkConfig(
        name="sky130A", liberty="x.lib", tech_lef="t.lef", cell_lef="c.lef",
        cell_gds=None, site="unit", drc_deck=None)


# --- v1.3.92 post-route decap-under-signal-route SHORT guard wiring ---------

_GUARD_LEF = (
    "MACRO DECAP8\n  CLASS CORE ;\n  SIZE 5.28 BY 5.04 ;\nEND DECAP8\n"
    "MACRO FILL8\n  CLASS CORE SPACER ;\n  SIZE 5.28 BY 5.04 ;\nEND FILL8\n")
_GUARD_DEF = """\
VERSION 5.8 ;
DESIGN guardtest ;
UNITS DISTANCE MICRONS 1000 ;

COMPONENTS 2 ;
    - D1 DECAP8 + PLACED ( 5000 20000 ) N ;
    - D2 DECAP8 + PLACED ( 40000 20000 ) N ;
END COMPONENTS

NETS 1 ;
    - sig1 ( D1 A ) ( D2 B )
      + ROUTED MET1 ( 6000 22000 ) ( 9000 22000 ) ;
END NETS

END DESIGN
"""


def _stage_pnr_def(mod, tmp_path, def_text):
    """Place {top}.def where _decap_route_short_guard expects it, return path."""
    pnr = mod._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True, exist_ok=True)
    dp = pnr / "guardtest.def"
    dp.write_text(def_text)
    return dp


class TestDecapRouteShortGuard:
    """v1.3.92 — the post-route decap->FILL guard is STRICTLY config-gated and,
    when enabled, rewrites {top}.def in place (both streamout paths inherit it)."""

    def test_config_defaults_none(self):
        f = mod.PdkConfig.__dataclass_fields__
        assert f["decap_route_short_guard"].default is None

    def test_helper_defined(self):
        assert callable(mod._decap_route_short_guard)

    def test_noop_without_config(self, tmp_path):
        pdk = _min_pdk(mod)
        assert pdk.decap_route_short_guard is None
        ran, note = mod._decap_route_short_guard(tmp_path, "guardtest", pdk)
        assert ran is False and note == ""

    def test_swaps_and_rewrites_def(self, tmp_path):
        lef = tmp_path / "cells.lef"
        lef.write_text(_GUARD_LEF)
        pdk = _min_pdk(mod)
        pdk.decap_route_short_guard = {"lefs": [str(lef)]}
        dp = _stage_pnr_def(mod, tmp_path, _GUARD_DEF)
        ran, note = mod._decap_route_short_guard(tmp_path, "guardtest", pdk)
        assert ran is True
        assert "1 decap->FILL swap" in note
        # {top}.def now carries FILL8 for the conflicting D1; D2 preserved.
        comps = {c["name"]: c["master"]
                 for c in guard_mod.parse_components(dp.read_text())}
        assert comps == {"D1": "FILL8", "D2": "DECAP8"}
        # the pre-guard DEF is preserved for audit
        assert (dp.parent / "guardtest.pre_decap_guard.def").is_file()

    def test_clean_def_is_noop_note(self, tmp_path):
        lef = tmp_path / "cells.lef"
        lef.write_text(_GUARD_LEF)
        pdk = _min_pdk(mod)
        pdk.decap_route_short_guard = {"lefs": [str(lef)]}
        clean = _GUARD_DEF.replace("( 6000 22000 ) ( 9000 22000 )",
                                   "( 6000 90000 ) ( 9000 90000 )")
        dp = _stage_pnr_def(mod, tmp_path, clean)
        ran, note = mod._decap_route_short_guard(tmp_path, "guardtest", pdk)
        assert ran is True
        assert "0 decap-under-route shorts" in note
        # {top}.def untouched; no backup written on a clean design.
        comps = {c["name"]: c["master"]
                 for c in guard_mod.parse_components(dp.read_text())}
        assert comps == {"D1": "DECAP8", "D2": "DECAP8"}
        assert not (dp.parent / "guardtest.pre_decap_guard.def").is_file()
