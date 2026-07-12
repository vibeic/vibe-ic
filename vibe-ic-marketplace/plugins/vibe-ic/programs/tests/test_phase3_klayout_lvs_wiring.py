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
