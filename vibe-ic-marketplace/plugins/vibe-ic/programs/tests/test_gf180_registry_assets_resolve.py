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
import fnmatch
import json
import shlex
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

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


def _unquote(s):
    try:
        parts = shlex.split(s)
        return parts[0] if parts else s
    except ValueError:
        return s


class _FakeContainer:
    """Same shape as the #211 fake: banner on stdout, then the answer."""

    def __init__(self, existing):
        self.existing = set(existing)

    def __call__(self, container, cmd, timeout=1800):
        c = cmd.strip()
        if c.startswith(("test -d ", "test -e ")):
            path = _unquote(c[len("test -d "):].strip())
            return (0 if path in self.existing else 1, _BANNER + "\n", "")
        if c.startswith("ls -1d "):
            glob = c[len("ls -1d "):].split(" 2>/dev/null")[0].strip()
            hits = sorted(p for p in self.existing if fnmatch.fnmatch(p, glob))
            return (0, _BANNER + "\n" + ("\n".join(hits) + "\n" if hits else ""), "")
        return (0, _BANNER + "\n", "")


def _resolve(monkeypatch, glob):
    monkeypatch.setattr(R, "_docker_exec_raw",
                        _FakeContainer(REAL_CONTAINER_PATHS))
    return R._registry_glob_one("c", ROOT, glob)


# --------------------------------------------------------------- assets ----

def test_liberty_glob_resolves_in_the_real_container(monkeypatch):
    got = _resolve(monkeypatch, GF["liberty_glob"])
    assert got is not None, (
        "liberty_glob matches nothing in the shipped image "
        "(the std-cell liberty is under lib/, there is no liberty/)")
    assert got.endswith("__tt_025C_5v00.lib")


def test_liberty_corner_is_pinned_not_ambiguous(monkeypatch):
    """`lib/*tt*.lib` matches three supply variants; sorted-first is 1v80.

    This library is the 5V (`mcu7t5v0`) library, so an unpinned glob silently
    signs off against the wrong rail.
    """
    monkeypatch.setattr(R, "_docker_exec_raw",
                        _FakeContainer(REAL_CONTAINER_PATHS))
    loose = [p for p in REAL_CONTAINER_PATHS
             if fnmatch.fnmatch(p, f"{SCL}/lib/*tt*.lib")]
    assert len(loose) == 3, "fixture should reproduce the ambiguity"
    assert sorted(loose)[0].endswith("1v80.lib"), "sorted-first is the 1v80 lib"
    pinned = [p for p in REAL_CONTAINER_PATHS
              if fnmatch.fnmatch(p, f"{ROOT}/{GF['liberty_glob']}")]
    assert len(pinned) == 1, f"liberty_glob must pin ONE corner, got {pinned}"


def test_tech_lef_glob_pins_the_nominal_corner(monkeypatch):
    got = _resolve(monkeypatch, GF["tech_lef_glob"])
    assert got is not None
    assert got.endswith("__nom.tlef"), (
        "techlef/*.tlef matches __max/__min/__nom and sorted-first is __max")


def test_cell_lef_and_gds_resolve(monkeypatch):
    assert _resolve(monkeypatch, GF["cell_lef_glob"]) is not None
    assert _resolve(monkeypatch, GF["cell_gds_glob"]) is not None


def test_drc_deck_path_exists_in_the_real_container(monkeypatch):
    got = _resolve(monkeypatch, GF["drc_deck"])
    assert got is not None, (
        "drc_deck does not exist in the shipped image; the real KLayout "
        "sign-off deck is libs.tech/klayout/tech/drc/gf180mcu.drc")
    assert got.endswith("gf180mcu.drc")


def test_no_asset_glob_is_left_unresolvable(monkeypatch):
    """Whole-entry sweep, so a future edit cannot reintroduce a dead glob."""
    dead = [k for k in ("liberty_glob", "tech_lef_glob", "cell_lef_glob",
                        "cell_gds_glob", "drc_deck")
            if _resolve(monkeypatch, GF[k]) is None]
    assert dead == [], f"unresolvable asset glob(s): {dead}"


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
