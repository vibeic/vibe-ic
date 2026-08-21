"""A streamout LEF/DEF->GDS layermap that is CONFIGURED (``pdk.lefdef_layermap``
set) but ABSENT on disk must FAIL LOUDLY at streamout, not silently fall back
to legacy/compact numbering.

ROOT CAUSE this pins
--------------------
A PDK branch whose ``lefdef_layermap`` points at a ``*.map`` file the container
image does not ship (observed: the nangate45 branch's
``.../nangate45/libs.tech/klayout/tech/FreePDK45.map``, absent from vibeic-eda
0.2.45 .. 0.2.62). The streamout script's map guard was::

    if _lefdef_map and os.path.exists(_lefdef_map):
        _cfg.map_file = [_lefdef_map]      # apply
        ...
    else:
        print("... legacy numbering")      # <- configured-but-absent ALSO landed here

so a configured-but-absent map fell straight through to legacy (compact)
numbering with a PASS. A sign-off DRC deck then reads every DEF-sourced
routing/via/PDN shape on an FEOL device number and reports a WALL of phantom
implant/VT/well violations that are numbering ARTEFACTS, not design defects
(measured on edge_llm_matmul_accel x nangate45: 7,911,144 DRC items, top rules
IMPLANT.5 / VT.1 / CONTACT.5). "Degrade loudly, never silently."

The step-level missing-map FAIL guard (``if pdk.calibre_drc and not
lefdef_map_c``) does NOT catch this: it is scoped to commercial Calibre decks,
and a KLayout-deck PDK (``calibre_drc`` None) with a non-empty-but-absent map
path satisfies neither condition, so the streamout proceeds.

Bidirectional negative control (also validated end-to-end in the vibeic-eda
0.2.62 container with real klayout, all four scenarios):
  * pre-fix  + missing map  -> silent "legacy numbering", exit != 7   (DEFECT)
  * post-fix + missing map  -> "CONFIGURED_BUT_ABSENT", SystemExit(7)  (FIX)
  * post-fix + empty  map   -> "none configured" legacy, no exit 7     (unchanged)
  * post-fix + present map  -> "LEFDEF_MAP applied", no exit 7         (unchanged)

Chip/PDK-AGNOSTIC: keyed purely on 'configured path that does not exist', no
PDK/vendor literal. sky130A.map and gf180mcu.map ship in the image (present ->
unchanged); only a genuinely-absent configured map newly fails, which is a TRUE
positive (its GDS is mis-numbered).
"""
import sys
import types
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# ---------------------------------------------------------------------------
# Source-level wiring assertions (consistent with
# test_v0_3_12_issue509r2_lefdef_layermap.py's convention).
# ---------------------------------------------------------------------------
def test_streamout_script_has_configured_but_absent_guard():
    s = R._GDS_STREAMOUT_PY
    # the loud guard fires on configured-but-absent, BEFORE the apply branch
    assert "not os.path.exists(_lefdef_map)" in s
    assert "CONFIGURED_BUT_ABSENT" in s
    assert "sys.exit(7)" in s
    # the apply branch and the unconfigured->legacy branch are preserved
    assert "_cfg.map_file = [_lefdef_map]" in s
    assert "legacy numbering" in s


def test_guard_precedes_apply_branch():
    s = R._GDS_STREAMOUT_PY
    # the absent-guard must be evaluated before the apply, else a missing file
    # would already have been dereferenced by map_file.
    assert s.index("not os.path.exists(_lefdef_map)") < \
        s.index("_cfg.map_file = [_lefdef_map]")


# ---------------------------------------------------------------------------
# Runnable behavioural control under a pya stub (no klayout needed).
# ---------------------------------------------------------------------------
class _Stub:
    """Permissive stand-in for a pya object: any attribute read yields another
    _Stub, any call yields a _Stub, attribute writes are accepted, and read()
    is a no-op. Enough to reach the map-decision head of the script; the guard
    exits before anything real is required."""

    def __getattr__(self, _name):
        return _Stub()

    def __call__(self, *a, **k):
        return _Stub()

    def read(self, *a, **k):
        return None


def _exec_streamout(lefdef_map):
    """Exec _GDS_STREAMOUT_PY with a pya stub and LEFDEF_MAP=<lefdef_map>.

    Returns the SystemExit code if the script exited, the string "RAN" if it
    ran to completion, or "POSTGUARD_ERR" if it raised a non-SystemExit
    exception (i.e. it got PAST the absent-map guard and failed later on the
    stub — which for this test means the guard did NOT fire)."""
    import os
    pya = types.ModuleType("pya")

    class _LLO:
        def __init__(self):
            self.lefdef_config = _Stub()

    pya.Layout = lambda *a, **k: _Stub()
    pya.LoadLayoutOptions = _LLO
    old_mod = sys.modules.get("pya")
    sys.modules["pya"] = pya

    env = {
        "TOP": "t", "DEF": "/definitely/not/here.def",
        "GDS_OUT": "/tmp/_acc_out.gds", "LEFS": "", "MACRO_GDS": "",
        "CELL_GDS": "", "STDCELL_MARKER_LAYER": "",
        "LEFDEF_MAP": lefdef_map,
    }
    old_env = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        exec(compile(R._GDS_STREAMOUT_PY, "<streamout>", "exec"),
             {"__name__": "__streamout__"})
        return "RAN"
    except SystemExit as e:
        return e.code
    except Exception:
        return "POSTGUARD_ERR"
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if old_mod is None:
            sys.modules.pop("pya", None)
        else:
            sys.modules["pya"] = old_mod


def test_configured_but_absent_map_exits_7():
    # a configured map path that does not exist -> loud SystemExit(7)
    assert _exec_streamout("/definitely/not/here.map") == 7


def test_unconfigured_map_does_not_trip_guard():
    # empty LEFDEF_MAP -> the absent-guard must NOT fire (legacy numbering path)
    assert _exec_streamout("") != 7


def test_present_map_does_not_trip_guard(tmp_path):
    # a configured map that DOES exist -> the absent-guard must NOT fire
    m = tmp_path / "present.map"
    m.write_text("# dummy\nmetal1 NET 11 0\n")
    assert _exec_streamout(str(m)) != 7
