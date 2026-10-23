"""A5's device limits must come OUT OF THE PDK, not out of a probed list.

Round 20 measured a hand-authored layout generator refuse a device the PDK
permits (sg13_lv_pmos w=1.0u, wmin 0.15u) with a bare AssertionError, because
its notion of "drawable" was the set of widths it had happened to probe. These
tests pin the two things that stops recurring: the limits are PARSED from the
PDK's own files, and a geometry outside them is refused BY NAME with the rule
and the file cited.

Every fixture below is synthetic PDK text, so the tests need no container and
no PDK.
"""
import json
import importlib

import pytest
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parents[1] / "analog_a5_pdk_device_limits.py"

# Two gencell blocks for the SAME model, as a real PDK ships them: a
# short-channel and a long-channel variant. The PDK permits the smaller.
GENCELL = """
 gencell sg13_lv_nmos ... \\
        topc 1 botc 1 poverlap 0 doverlap 1 lmin 0.13 wmin 0.15 \\
        more
 gencell sg13_lv_nmos ... \\
        topc 1 botc 1 poverlap 0 doverlap 1 lmin 0.45 wmin 0.15 \\
        more
 gencell sg13_lv_pmos ... lmin 0.13 wmin 0.15 more
"""

DRC = """
planes
 metal1,m1
end
types
 metal1 metal1,m1
 metal1 rmetal1,rm1
 -metal1 obsm1
 -metal1 diffprobe
end
aliases
 allm1 *m1,rm1
end
cifoutput
style drc
 scalefactor 10 nanometers
end
drc
 style drc
 scalefactor 10
 cifstyle drc
 width *m1,rm1 160 "Metal1 width < %d (M1.a)"
 spacing allm1,diffprobe allm1,*obsm1 180 touching_ok \\
\t"Metal1 spacing < %d (M1.b)"
end
"""


def _run(tmp, *args, gencell=GENCELL, drc=DRC):
    g = tmp / "fet.tcl"; g.write_text(gencell)
    d = tmp / "drc.tech"; d.write_text(drc)
    cp = subprocess.run(
        [sys.executable, str(PROG), "--gencell-tcl", str(g),
         "--drc-tech", str(d), *args],
        capture_output=True, text=True)
    return cp.returncode, json.loads(cp.stdout) if cp.stdout.strip() else {}


def test_a_models_limit_is_the_smallest_of_its_gencell_blocks(tmp_path):
    # taking the LAST match gives lmin 0.45 and refuses a legal 0.13u device
    rc, out = _run(tmp_path)
    assert rc == 0
    assert out["limits_um"]["sg13_lv_nmos"]["lmin"] == 0.13
    assert out["limits_um"]["sg13_lv_nmos"]["wmin"] == 0.15


def test_the_metal1_space_rule_is_read_from_the_deck(tmp_path):
    rc, out = _run(tmp_path)
    assert out["m1_space_um"] == 0.18


def test_the_tap_clearance_is_the_rule_plus_the_callers_own_pads(tmp_path):
    # pad size is the GENERATOR's choice; the PDK contributes only the space
    rc, out = _run(tmp_path, "--tap-pad-half-um", "0.15",
                   "--terminal-pad-half-um", "0.15")
    assert out["tap_clear_um"] == 0.48
    assert out["tap_clear_terms"]["m1_space_um"] == 0.18


def test_a_sub_minimum_width_is_refused_by_name_with_the_rule(tmp_path):
    rc, out = _run(tmp_path, "--model", "sg13_lv_nmos",
                   "--check-w", "0.1", "--check-l", "0.5")
    assert rc == 1
    assert out["result"] == "FORBIDDEN"
    joined = " ".join(out["refusals"])
    assert "wmin=0.15u" in joined and "sg13_lv_nmos" in joined
    assert "fet.tcl" in joined          # the file, so a reader can check it


def test_a_sub_minimum_length_is_refused_by_name(tmp_path):
    rc, out = _run(tmp_path, "--model", "sg13_lv_nmos",
                   "--check-w", "0.5", "--check-l", "0.05")
    assert rc == 1
    assert "lmin=0.13u" in " ".join(out["refusals"])


def test_the_guard_is_not_vacuous_a_legal_narrow_device_is_permitted(tmp_path):
    # THE CONTROL THAT MATTERS. A gate that refuses everything also refuses
    # the bug; round 20's whole finding was a generator that said no to a
    # device the PDK says yes to.
    for w, l in (("0.5", "0.5"), ("1.0", "0.5"), ("0.15", "0.13")):
        rc, out = _run(tmp_path, "--model", "sg13_lv_nmos",
                       "--check-w", w, "--check-l", l)
        assert rc == 0, (w, l, out)
        assert out["result"] == "PERMITTED", (w, l, out)


def test_an_unreadable_pdk_is_NOT_CHECKED_never_a_default(tmp_path):
    cp = subprocess.run(
        [sys.executable, str(PROG), "--gencell-tcl", str(tmp_path / "nope"),
         "--drc-tech", str(tmp_path / "nope2")],
        capture_output=True, text=True)
    assert cp.returncode == 2
    out = json.loads(cp.stdout)
    assert out["result"] == "NOT_CHECKED"
    assert "ABSENT, never a default" in out["reason"]


def test_a_model_with_no_gencell_entry_is_NOT_CHECKED(tmp_path):
    rc, out = _run(tmp_path, "--model", "sg13_hv_nmos", "--check-w", "0.5")
    assert rc == 2 and out["result"] == "NOT_CHECKED"


def test_a_deck_missing_the_space_rule_yields_no_clearance(tmp_path):
    # degrade loudly: no rule -> no number, not a guessed one
    rc, out = _run(tmp_path, "--tap-pad-half-um", "0.15",
                   drc=' width *m1,rm1 160 "Metal1 width < %d (M1.a)"\n')
    assert out["m1_space_um"] is None
    assert "tap_clear_um" not in out


# Small exact-form excerpt from the pinned Ciel sky130A.tech, file SHA256
# a9149695613d6ad30f898cfd1cedeaaf0adf38035f2b5818b4f0c9f5cf6f1614.
# Apache-2.0; Copyright (c) 2020 R. Timothy Edwards.
CIEL_METAL1 = """planes
 metal1,m1
 metal2,m2
end
types
 metal1 metal1,m1,met1
 metal1 rmetal1,rm1,rmet1
 -metal1 obsm1
 -metal1 m1fill
 metal2 metal2,m2,met2
 metal2 rmetal2,rm2,rmet2
end
aliases
 allm1 *m1,rm1
end
cifoutput
style drc
 scalefactor 10 nanometers
end
drc
 style drc variants (fast),(full),(routing)
 scalefactor 10
 cifstyle drc
 width mcon/m1 170 "mcon.width < %d (mcon.1)"
 spacing mcon/m1 mcon/m1,obsmcon/m1 190 touching_ok "mcon.spacing < %d (mcon.2)"
 width *m1,rm1 140 "Metal1 width < %d (met1.1)"
 spacing allm1,m1fill allm1,*obsm1,m1fill 140 touching_ok "Metal1 spacing < %d (met1.2)"
 widespacing allm1 3005 allm1,*obsm1,m1fill 280 touching_ok "Metal1 > 3um spacing (met1.3b)"
end
"""


def test_ciel_layer_set_rule_through_existing_cli(tmp_path):
    rc, out = _run(tmp_path, drc=CIEL_METAL1)
    assert rc == 0
    assert out["m1_space_um"] == pytest.approx(0.14)
    assert out["tap_clear_terms"]["m1_space_um"] == pytest.approx(0.14)
    assert out["drc_tech"] == str(tmp_path / "drc.tech")


def test_metal1_scale_comes_from_declared_drc_and_cif_units(tmp_path):
    text = CIEL_METAL1.replace("scalefactor 10 nanometers", "scalefactor 20 nanometers")
    rc, out = _run(tmp_path, drc=text)
    assert rc == 0 and out["m1_space_um"] == pytest.approx(0.28)


@pytest.mark.parametrize("old,new", [
    ("width *m1,rm1 140", "width *m1,rm1 0"),
    ("spacing allm1,m1fill allm1,*obsm1,m1fill 140", "spacing allm1,m1fill allm1,*obsm1,m1fill nan"),
    ("scalefactor 10 nanometers", "scalefactor nan nanometers"),
    ("scalefactor 10 nanometers", "scalefactor 10 unknown_units"),
    ("scalefactor 10\n", "scalefactor 0\n"),
    ("cifstyle drc", "cifstyle absent"),
    ("allm1 *m1,rm1", "allm1 *m2,rm2"),
    ("allm1 *m1,rm1", "allm1 undefined_layer"),
    ("allm1 *m1,rm1", "allm1 allm1"),
    ("allm1 *m1,rm1", "allm1 *m1,rm1\n allm1 *m2,rm2"),
    ("scalefactor 10\n", "scalefactor 10\n scalefactor 20\n"),
    ("cifstyle drc", "cifstyle drc\n cifstyle other"),
    ("types\n metal1 metal1,m1,met1", "types\n metal2 metal1,m1,met1"),
    ("allm1,m1fill allm1,*obsm1,m1fill", "allm1,m2 allm1,*obsm1,m1fill"),
])
def test_metal1_missing_bad_or_foreign_declarations_refuse(tmp_path, old, new):
    assert old in CIEL_METAL1
    rc, out = _run(tmp_path, drc=CIEL_METAL1.replace(old, new))
    assert rc == 0  # preserve the existing CLI's partial-facts contract
    assert out["m1_space_um"] is None
    assert "tap_clear_um" not in out


def test_missing_units_are_not_guessed(tmp_path):
    fragment = ('width m1 140 "Metal1 width < %d (met1.1)"\n'
                'spacing m1 m1 140 touching_ok "Metal1 spacing < %d (met1.2)"\n')
    rc, out = _run(tmp_path, drc=fragment)
    assert out["m1_space_um"] is None and "tap_clear_um" not in out


def test_conflicting_baseline_spacing_is_not_arbitrarily_selected(tmp_path):
    extra = ' spacing allm1,m1fill allm1,*obsm1,m1fill 150 touching_ok "Metal1 spacing < %d (met1.2)"\n'
    text = CIEL_METAL1.rsplit("end", 1)[0] + extra + "end\n"
    rc, out = _run(tmp_path, drc=text)
    assert out["m1_space_um"] is None and "tap_clear_um" not in out


def test_existing_a5_pdk_consumer_accepts_ciel_rule_and_keeps_refusal():
    fixtures = importlib.import_module("test_analog_a5_layout_emit")
    emitter = importlib.import_module("analog_a5_layout_emit")
    stage = fixtures.CielSky130Stage()
    stage.CIEL_TECH = CIEL_METAL1
    facts, why = emitter.read_pdk(stage, "/pdk", "sky130A", None, None)
    assert facts is not None, why
    assert facts.m1_space_um == pytest.approx(0.14)
    assert facts.sources["drc_tech"] == "/pdk/sky130A/libs.tech/magic/sky130A.tech"
    stage.CIEL_TECH = CIEL_METAL1.replace("allm1 *m1,rm1", "allm1 *m2,rm2")
    facts, why = emitter.read_pdk(stage, "/pdk", "sky130A", None, None)
    assert facts is None and "ENV_UNAVAILABLE" in why and "Metal1" in why


# The split-file form observed in the native PDK: the DRC fragment names
# M1.b=180; its physical scale and layer table are in sibling include files.
# Values below preserve that rule/scale relationship rather than guessing nm.
SPLIT_ROOT = DRC.split("cifoutput", 1)[0] + """
include generic-cifout
include generic-drc
"""
SPLIT_CIF = """cifoutput
style drc
 scalefactor 10 nanometers
end
"""
SPLIT_DRC = """drc
 style drc variants (fast),(full),(routing)
 scalefactor 10
 cifstyle drc
 width *m1,rm1,diffprobe 160 "Metal1 width < %d (M1.a)"
 spacing allm1,diffprobe allm1,*obsm1 180 touching_ok \\
        "Metal1 spacing < %d (M1.b)"
end
"""


def test_split_magic_deck_reads_real_scale_and_layer_context():
    owner = importlib.import_module("analog_a5_pdk_device_limits")
    files = {"/pdk/generic.tech": SPLIT_ROOT,
             "/pdk/generic-cifout.tech": SPLIT_CIF,
             "/pdk/generic-drc.tech": SPLIT_DRC}
    assert owner.m1_space_um(SPLIT_DRC) is None
    context = owner.magic_technology_text("/pdk/generic.tech", files.get)
    assert owner.m1_space_um(SPLIT_DRC, technology_text=context) == pytest.approx(0.18)
    changed = context.replace("scalefactor 10 nanometers", "scalefactor 20 nanometers")
    assert owner.m1_space_um(SPLIT_DRC, technology_text=changed) == pytest.approx(0.36)


@pytest.mark.parametrize("cif", ["", SPLIT_CIF.replace("10 nanometers", "nan nanometers"),
    SPLIT_CIF.replace("10 nanometers", "10 unknown_units")])
def test_split_magic_missing_or_invalid_scale_never_supplies_clearance(cif):
    owner = importlib.import_module("analog_a5_pdk_device_limits")
    context = SPLIT_ROOT.split("include", 1)[0] + cif
    assert owner.m1_space_um(SPLIT_DRC, technology_text=context) is None


def test_split_magic_unreadable_include_and_cycle_are_named_refusals():
    owner = importlib.import_module("analog_a5_pdk_device_limits")
    with pytest.raises(ValueError, match="unreadable Magic technology include"):
        owner.magic_technology_text("/pdk/root.tech", lambda p: "include absent" if p.endswith("root.tech") else None)
    with pytest.raises(ValueError, match="cyclic Magic technology include"):
        owner.magic_technology_text("/pdk/root.tech", lambda p: "include root")


def test_actual_layout_consumer_uses_split_context_and_refuses_unreadable_scale():
    fixtures = importlib.import_module("test_analog_a5_layout_emit")
    emitter = importlib.import_module("analog_a5_layout_emit")
    class SplitStage(fixtures.FakeStage):
        missing_scale = False
        def sh(self, cmd, timeout=900):
            if cmd.startswith("cat "):
                path = cmd.split(None, 1)[1].strip("'\"")
                if path.endswith("/generic.tech"):
                    return 0, SPLIT_ROOT, ""
                if path.endswith("/generic-drc.tech"):
                    return 0, SPLIT_DRC, ""
                if path.endswith("/generic-cifout.tech"):
                    return (1, "", "missing CIF scale") if self.missing_scale else (0, SPLIT_CIF, "")
            return super().sh(cmd, timeout)
    stage = SplitStage()
    facts, why = emitter.read_pdk(stage, "/pdk", "generic", None, None)
    assert facts is not None, why
    assert facts.m1_space_um == pytest.approx(0.18)
    stage.missing_scale = True
    facts, why = emitter.read_pdk(stage, "/pdk", "generic", None, None)
    assert facts is None and "context is unreadable" in why and "generic-cifout.tech" in why
