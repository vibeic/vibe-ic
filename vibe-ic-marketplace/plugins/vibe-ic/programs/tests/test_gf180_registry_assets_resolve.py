"""The gf180mcuD registry entry's asset globs matched NOTHING in the shipped
container, and it declared no physical-cell masters.

Measured against `ghcr.io/vibeic/vibeic-eda:0.2.24` (the image the runner uses),
on a live `/foss/pdks/gf180mcuD`:

  (a) liberty_glob was `libs.ref/gf180mcu_fd_sc_mcu7t5v0/liberty/*tt*.lib`.
      There is NO `liberty/` directory — the std-cell liberty ships under
      `lib/`. The glob resolved to nothing.

  (b) tech_lef_glob was `.../techlef/*.tlef`, which matches THREE corner
      variants (`__max` / `__min` / `__nom`). The resolver takes the
      deterministic sorted-FIRST hit, i.e. `__max.tlef` — not the nominal
      deck.

  (c) drc_deck was `libs.tech/klayout/drc/gf180mcu.lydrc`, which does not
      exist. The real KLayout sign-off deck is
      `libs.tech/klayout/tech/drc/gf180mcu.drc`.

  (d) No `tapcell_master`, so the PnR step printed
      `TAPCELL_SKIPPED: no tapcell_master configured` and placed ZERO well
      taps — a categorical latch-up exposure. Also no `antenna_diode_cell`.

  (e) Even the corrected `lib/*tt*.lib` matches THREE supply variants
      (1v80 / 3v30 / 5v00); sorted-first is 1v80, the wrong rail for this 5V
      (`mcu7t5v0`) library. The corner is therefore PINNED to tt_025C_5v00.

Since issue #211 an unresolvable asset makes the runner REFUSE rather than
silently substitute, so today these globs are a hard blocker for gf180mcuD
rather than a silent one.

These are UNIT tests: the container is the in-memory fake used by the #211
tests, populated from the ACTUAL `ls` output of the real image, so they run
with no docker and no PDK installed.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

REGISTRY = json.loads((PROGRAMS / "pdk_registry.json").read_text())
GF = next(e for e in REGISTRY["pdks"] if e["name"] == "gf180mcuD")
ROOT = GF["container_path"].rstrip("/")
SCL = f"{ROOT}/libs.ref/gf180mcu_fd_sc_mcu7t5v0"

# Verbatim from the real image:
#   docker exec <c> ls /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/
#   -> cdl gds lef lib mag maglef spice techlef verilog      (NO `liberty`)
_LIB_CORNERS = [
    "ff_125C_1v98", "ff_125C_3v60", "ff_125C_5v50",
    "ff_n40C_1v98", "ff_n40C_3v60", "ff_n40C_5v50",
    "ss_125C_1v62", "ss_125C_3v00", "ss_125C_4v50",
    "ss_n40C_1v62", "ss_n40C_3v00", "ss_n40C_4v50",
    "tt_025C_1v80", "tt_025C_3v30", "tt_025C_5v00",
]
REAL_CONTAINER_PATHS = (
    [ROOT, f"{ROOT}/libs.ref", f"{ROOT}/libs.tech", SCL]
    + [f"{SCL}/lib/gf180mcu_fd_sc_mcu7t5v0__{c}.lib" for c in _LIB_CORNERS]
    + [f"{SCL}/techlef/gf180mcu_fd_sc_mcu7t5v0__{v}.tlef"
       for v in ("max", "min", "nom")]
    + [f"{SCL}/lef/gf180mcu_fd_sc_mcu7t5v0.lef",
       f"{SCL}/gds/gf180mcu_fd_sc_mcu7t5v0.gds",
       f"{ROOT}/libs.tech/klayout/tech/drc/gf180mcu.drc"]
)

_BANNER = ("[INFO] Final PATH variable: /headless/.local/bin:/usr/bin\n"
           "[INFO] Final PYTHONPATH variable: /usr/lib/python3.12")










# --------------------------------------------------------------- assets ----













# ------------------------------------------------------- physical cells ----

def test_tapcell_master_is_declared():
    """Without it the PnR step prints TAPCELL_SKIPPED and places 0 taps."""
    assert GF.get("tapcell_master") == "gf180mcu_fd_sc_mcu7t5v0__filltie"


def test_antenna_diode_cell_is_declared():
    assert GF.get("antenna_diode_cell") == "gf180mcu_fd_sc_mcu7t5v0__antenna"


def test_tapcell_distance_is_under_the_pdk_own_rule():
    """DF.13_MV / DF.14_MV in the PDK's own deck both state 15um for this 5V
    library (the LV variants are 20um), so the tap pitch must be < 15."""
    d = GF.get("tapcell_distance_um")
    assert d is not None
    assert 0 < d < 15.0, f"tapcell_distance_um {d} violates the 15um DF rule"


def test_only_the_gf180_entry_declares_these_values():
    """Blast-radius control: no OTHER entry's physical-cell keys drift.

    The register below recorded `sky130A: (None, None)` with the note that its
    tapcell master "is set by the hard-coded named branch in `_detect_pdk`".
    That was true, and it was the hazard rather than a fact: the resolver reads
    the registry with `reg.get("tapcell_master")`, so an OMITTED key and an
    explicit `null` arrive identically as None — and None means "this PDK ships
    no tapcell master", which routes the PERC latch-up gate down the tapless-
    cell path.

    Live consequence on `asap7`, whose branch built its PdkConfig without the
    field: the image ships `MACRO TAPCELL_ASAP7_75t_R` (`CLASS CORE WELLTAP`,
    `SITE asap7sc7p5t` — the site that entry declares), the tapcell step
    self-skipped, and step 28 reported the resulting 0-tap DEF as a tapless-PDK
    INDETERMINATE. A real latch-up exposure carried as a non-blocking
    indeterminate — the direction #586 named as strictly worse than the false
    FAIL it was fixing.

    So three of these values are no longer None. `ihp-sg13g2` stays null because
    it is GENUINELY tapless (ties cell-internal), which is now a stated null
    rather than an indistinguishable absence — `pdk_registry_selectable_check`
    fails an entry that omits the key. The register keeps its original job:
    nothing here may drift silently.
    """
    baseline = {
        "sky130A": ("sky130_fd_sc_hd__tapvpwrvgnd_1", None),
        "ihp-sg13g2": (None, "sg13g2_antennanp"),
        "nangate45": ("TAPCELL_X1", None),
        "asap7": ("TAPCELL_ASAP7_75t_R", None),
        "custom_auto_detect": (None, None),
    }
    for e in REGISTRY["pdks"]:
        if e["name"] == "gf180mcuD":
            continue
        exp = baseline.get(e["name"])
        assert exp is not None, f"new PDK entry {e['name']} — update baseline"
        got = (e.get("tapcell_master"), e.get("antenna_diode_cell"))
        assert got == exp, f"{e['name']} physical-cell keys changed: {got}"


def test_sky130_asset_globs_unchanged():
    """The sky130A entry's own asset globs are not touched by this change."""
    sky = next(e for e in REGISTRY["pdks"] if e["name"] == "sky130A")
    assert sky["liberty_glob"] == (
        "libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib")
