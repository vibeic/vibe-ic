"""Physical-cell recognition assumed sky130/sg13g2 cell NAMES.

Two screens both key off cell-name shape, and both missed gf180mcu's names.
Measured on the shipped `gf180mcu_fd_sc_mcu7t5v0.lef` (vibeic-eda:0.2.24):

    gf180mcu_fd_sc_mcu7t5v0__fill        plain filler
    gf180mcu_fd_sc_mcu7t5v0__fillcap     decap   (CLASS core)
    gf180mcu_fd_sc_mcu7t5v0__filltie     welltap (CLASS core WELLTAP)
    gf180mcu_fd_sc_mcu7t5v0__tieh        FUNCTIONAL tie-high
    gf180mcu_fd_sc_mcu7t5v0__tiel        FUNCTIONAL tie-low

(1) netgen physical-cell `ignore class` — the family-token regex was
    `(^|_)fill(er)?(_[[:digit:]]+)?$`, which matches `__fill` and `..._fill_8`
    but NOT `__fillcap` / `__filltie`. The `tap` token regex did not match
    `filltie` either. Both stayed in the LVS compare and netgen reported
    "Netlists do not match" on gf180mcuD.

(2) latch-up well-tap screens — `_WELLTAP_RATED` is a sky130-only allowlist and
    `_WELLTAP_TOKEN_RE` requires a `tap` NAME SEGMENT. gf180's welltap is
    `__filltie`: no `tap` token, not on the allowlist. A run that placed 380
    real tap cells (DRC DF.13/DF.14 clean) was still reported as
    "0 rated tap cells" -> WELLTAP_GAP, a conclusive-FAIL verdict on a correct
    design.

Fixes: widen the fill alternation to `fill(er|cap|tie)?`, and thread the PDK's
OWN configured `pdk.tapcell_master` into both tap screens so they trust the
same cell name the tapcell insertion step was told to use.

NO-LEAK: functional tie cells (`__tieh`/`__tiel`, sg13g2_tiehi/tielo) carry
real constant nets and must STILL be compared — the widened token must start
with `fill`, so they are unaffected. A PDK that configures no tapcell_master
gets no widening at all.
"""
import importlib
import re
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
mod = importlib.import_module("phase3_one_shot_runner")
lat = importlib.import_module("latchup_esd_spacing_check")


GF180 = "gf180mcu_fd_sc_mcu7t5v0__"
SKY = "sky130_fd_sc_hd__"
GF180_TAP = GF180 + "filltie"


# ------------------------------------------------------------------------
# (1) netgen physical-cell ignore regexes
# ------------------------------------------------------------------------

def _phys_regexes():
    """Extract the TCL ERE family-token patterns from the emitter source.

    Read from source rather than re-typed here, so the test cannot drift away
    from what is actually emitted.
    """
    src = Path(mod.__file__).read_text()
    m = re.search(r"_phys_res = \((.*?)\)\n", src, re.S)
    assert m, "could not locate _phys_res in the emitter"
    pats = re.findall(r'r"([^"]+)"', m.group(1))
    assert pats, "no patterns parsed"
    # TCL ERE -> Python: translate the POSIX bracket classes.
    _posix = {"[[:digit:]]": "[0-9]", "[[:alpha:]]": "[A-Za-z]",
              "[[:alnum:]]": "[A-Za-z0-9]"}
    out = []
    for p in pats:
        for k, v in _posix.items():
            p = p.replace(k, v)
        assert "[:" not in p, f"untranslated POSIX class in {p!r}"
        out.append(p)
    return out


def _ignored(master: str) -> bool:
    return any(re.search(p, master) for p in _phys_regexes())


def test_gf180_fillcap_is_ignored():
    assert _ignored(GF180 + "fillcap")


def test_gf180_filltie_is_ignored():
    assert _ignored(GF180 + "filltie")


def test_gf180_plain_fill_is_ignored():
    assert _ignored(GF180 + "fill")


def test_sized_variants_still_ignored():
    for name in ("fill_1", "fillcap_16", "filltie_4", "decap_8"):
        assert _ignored(GF180 + name), name


def test_sky130_physical_cells_unchanged():
    """Blast-radius control: every previously-matched name still matches."""
    for name in ("fill_8", "decap_4", "tapvpwrvgnd_1", "fakediode_2"):
        assert _ignored(SKY + name), name


def test_functional_tie_cells_are_NOT_ignored():
    """NO-LEAK: tie cells drive real constant nets and must stay compared."""
    for name in (GF180 + "tieh", GF180 + "tiel",
                 "sg13g2_tiehi", "sg13g2_tielo"):
        assert not _ignored(name), name


def test_functional_cells_containing_the_substring_are_NOT_ignored():
    """`fill`/`tap` as a mere substring must not trigger the ignore."""
    for name in (GF180 + "nand2_1", "bootstrap_ctl", "captune_5",
                 "my_filler_ctrl_logic"):
        assert not _ignored(name), name


# ------------------------------------------------------------------------
# (2) latch-up well-tap presence (DEF COMPONENTS scan)
# ------------------------------------------------------------------------

def _components(tap_master=None, n_tap=3, n_std=20):
    comps = [(f"_{i}_", GF180 + "nand2_1") for i in range(n_std)]
    if tap_master:
        comps += [(f"TAP_{i}", tap_master) for i in range(n_tap)]
    return comps


def test_gf180_filltie_recognised_when_pdk_declares_it():
    rep = mod._welltap_presence_check(_components(GF180_TAP), [GF180_TAP])
    assert rep["status"] == "WELLTAP_PRESENT"
    assert rep["n_tap"] == 3


def test_gf180_filltie_unrecognised_without_the_pdk_master():
    """Exactly the field failure: taps placed, screen reports a GAP."""
    rep = mod._welltap_presence_check(_components(GF180_TAP))
    assert rep["status"] == "WELLTAP_GAP"
    assert rep["n_tap"] == 0


def test_sky130_taps_still_recognised_with_no_extra_master():
    """Blast-radius control: the shipped allowlist still works alone."""
    rep = mod._welltap_presence_check(
        _components(SKY + "tapvpwrvgnd_1"))
    assert rep["status"] == "WELLTAP_PRESENT"
    assert rep["n_tap"] == 3


def test_zero_taps_still_a_conclusive_gap():
    """NO-LEAK: declaring a tapcell master must not manufacture a PASS."""
    rep = mod._welltap_presence_check(_components(None), [GF180_TAP])
    assert rep["status"] == "WELLTAP_GAP"
    assert rep["n_tap"] == 0


def test_unrelated_configured_master_does_not_rate_other_cells():
    """NO-LEAK: only the configured master is added, not a blanket pass."""
    rep = mod._welltap_presence_check(
        _components(GF180 + "somethingelse"), [GF180_TAP])
    assert rep["status"] == "WELLTAP_GAP"


def test_no_std_cells_is_still_NA():
    rep = mod._welltap_presence_check([], [GF180_TAP])
    assert rep["status"] == "NA"


def test_rated_prefixes_helper_is_additive_only():
    base = mod._WELLTAP_RATED
    assert set(base).issubset(set(mod._rated_tap_prefixes()))
    assert mod._rated_tap_prefixes() == base
    widened = mod._rated_tap_prefixes([GF180_TAP])
    assert set(base).issubset(set(widened))
    assert GF180_TAP.lower() in widened


# ------------------------------------------------------------------------
# (3) latch-up tap SPACING screen (geometry layer)
# ------------------------------------------------------------------------

_DEF_HEAD = """\
VERSION 5.8 ;
DESIGN top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 40000 40000 ) ;
"""


def _write_def(tmp_path, tap_master):
    rows = []
    n = 0
    for gx in range(6):
        for gy in range(6):
            rows.append(f"  - u{n} {GF180}nand2_1 + PLACED "
                        f"( {gx*6000+1000} {gy*6000+1000} ) N ;")
            n += 1
    taps = []
    t = 0
    for gx in range(6):
        for gy in range(6):
            taps.append(f"  - t{t} {tap_master} + PLACED "
                        f"( {gx*6000+1500} {gy*6000+1500} ) N ;")
            t += 1
    body = (_DEF_HEAD
            + f"COMPONENTS {len(rows)+len(taps)} ;\n"
            + "\n".join(rows + taps)
            + "\nEND COMPONENTS\nEND DESIGN\n")
    p = tmp_path / "routed.def"
    p.write_text(body)
    return p


def test_spacing_screen_sees_gf180_taps_when_declared(tmp_path):
    d = _write_def(tmp_path, GF180_TAP)
    rep = lat.run_geometry_layer(str(d), rated_tap_masters=[GF180_TAP])
    assert rep["spacing"]["n_tap"] == 36
    assert rep["spacing"]["status"] != "WELLTAP_SPACING_GAP"


def test_spacing_screen_blind_to_gf180_taps_without_declaration(tmp_path):
    """The field failure on the spacing screen."""
    d = _write_def(tmp_path, GF180_TAP)
    rep = lat.run_geometry_layer(str(d))
    assert rep["spacing"]["n_tap"] == 0


def test_spacing_screen_sky130_unchanged(tmp_path):
    """Blast-radius control: sky130 needs no declaration and is unaffected."""
    d = _write_def(tmp_path, SKY + "tapvpwrvgnd_1")
    rep = lat.run_geometry_layer(str(d))
    assert rep["spacing"]["n_tap"] == 36


def test_is_rated_tap_default_arg_is_backward_compatible():
    """Pre-fix single-argument call still behaves identically."""
    assert lat._is_rated_tap(SKY + "tapvpwrvgnd_1") is True
    assert lat._is_rated_tap(GF180_TAP) is False
    assert lat._is_rated_tap(GF180_TAP, [GF180_TAP]) is True
