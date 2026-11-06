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
