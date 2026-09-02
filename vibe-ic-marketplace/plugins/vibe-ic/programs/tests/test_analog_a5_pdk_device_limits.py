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
 width *m1,rm1 160 "Metal1 width < %d (M1.a)"
 spacing allm1,diffprobe allm1,*obsm1 180 touching_ok \\
\t"Metal1 spacing < %d (M1.b)"
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
