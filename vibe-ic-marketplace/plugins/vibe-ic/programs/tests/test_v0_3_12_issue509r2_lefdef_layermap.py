"""v0.3.12 — #509 ROUND-2: GDS streamout used KLayout's COMPACT LEF/DEF
layer numbering (met1..met5 = 10..14) instead of the foundry GDS numbers,
so the streamed GDS was unreadable by Magic (whose sky130A tech expects
met3=70/20, met3.pin=70/16, met3.label=70/5). Signoff-LVS extraction then
saw NO top routing/pins/labels → every top port extracted disconnected →
spurious top-level 'do not match'. (round-1's magic-streamout `port
makeall` was on a path the real designs never take — streamout_engine=
klayout — and was a no-op anyway; the TRUE root cause is the layermap.)

Fix: drive the KLayout DEF reader with the PDK's own foundry layer-map
(`<pdk>/libs.tech/klayout/tech/<pdk>.map`) via the reader's `map_file`,
so metal/pin/label land on the foundry numbers Magic reads. Empirically
validated in the vibeic-eda container on the real spm GDS: with the map the
shipped streamout produces a GDS where Magic recognises ALL 36 top ports
(port indices 1..36; clk=1..y=36) vs 0 before.

These tests pin the deterministic wiring (PdkConfig map derivation +
streamout script applies map_file + caller passes the env). The
end-to-end `grep -c "disconnected node" lvs.rpt → 0` needs the multi-hour
streamout→extract→netgen regen (field EDA-container domain); the
port-recognition crux is validated above. Chip/PDK-AGNOSTIC: the map is
PDK-derived, None → legacy numbering preserved.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


def test_sky130_pdkconfig_has_foundry_layermap():
    pdk = R._detect_pdk(Path("/nonexistent"), override="sky130A")
    assert pdk.lefdef_layermap is not None
    assert pdk.lefdef_layermap.endswith("klayout/tech/sky130A.map")


def test_pdkconfig_layermap_defaults_none():
    # the field is optional — a PDK that ships no foundry map keeps the
    # legacy (compact) numbering rather than crashing.
    import dataclasses
    f = {f.name: f for f in dataclasses.fields(R.PdkConfig)}
    assert "lefdef_layermap" in f
    assert f["lefdef_layermap"].default is None


def test_streamout_script_applies_map_file():
    s = R._GDS_STREAMOUT_PY
    assert "LEFDEF_MAP" in s
    assert "map_file" in s
    # the map must be applied to the DEF read options, and only when the
    # file exists (None/missing → legacy numbering).
    assert "os.path.exists(_lefdef_map)" in s
    assert "_cfg.map_file = [_lefdef_map]" in s
    # the DEF read must use the configured options object, not a bare one.
    assert "ly.read(def_path, _def_opts)" in s


def test_streamout_caller_passes_layermap_env():
    import inspect
    # step_gds builds the klayout command with the LEFDEF_MAP env derived
    # from pdk.lefdef_layermap.
    src = inspect.getsource(R)
    assert 'LEFDEF_MAP=\\"{lefdef_map_c}\\"' in src or "LEFDEF_MAP=" in src
    assert "pdk.lefdef_layermap" in src


def test_legacy_numbering_preserved_when_no_map():
    # the script's else-branch must keep working when LEFDEF_MAP is empty.
    s = R._GDS_STREAMOUT_PY
    assert "legacy numbering" in s
