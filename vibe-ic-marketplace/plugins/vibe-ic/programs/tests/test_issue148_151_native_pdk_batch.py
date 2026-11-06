"""ORGANIC #148-151 — native custom-PDK analog consumption batch.

All four are chip-AGNOSTIC and exercised with SYNTHETIC PDK families only (no
NDA / vendor / SKU token anywhere):

  #148 design_one_shot_runner: an all-analog top interface must route the
       RTL-dependent digital steps (reference_tb / yosys_synth / the RTL repair/retry loop)
       to SKIP, not FAIL on "rtl/ missing" — even for a class (data_converter)
       that carries a spec-to-rtl fallback. No-leak: a digital-interface design
       still FAILs on the absent rtl/.
  #149 analog_pdk_deck_context.custom_family_context: the primary model lib is
       the one that DEFINES the resolved device-role subckts, not merely the one
       with the most `.lib <section>` corner definitions. No-leak: single-lib
       unchanged; the device-defining lib wins even with fewer sections.
  #150 analog_mc_yield_run: a rung-1 native project consumes the resolved
       mc_libs (native mismatch section) — never a sky130 overlay; no mc lib →
       UNSCOREABLE. No-leak: an open-PDK project still loads sky130 tt_mm; a
       mixed-family MC deck is structurally impossible (assert).
  #151 analog_netlist_pdk_check: a rung-1/2 resolved native model include (or a
       native `.subckt` definition library) passes A3; an out-of-ladder include
       still FAILs. No-leak: non-native projects are entirely unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_pdk_deck_context as APDC             # noqa: E402
import analog_mc_yield_run as MC                   # noqa: E402
import analog_real_corner_sweep as ARS             # noqa: E402
import analog_netlist_pdk_check as NPC             # noqa: E402


# ── shared fixtures ─────────────────────────────────────────────────────────

_ADC_ALL_ANALOG = (
    [{"name": f"in{i}", "direction": "input"} for i in range(1, 7)]
    + [{"name": n, "direction": "input"} for n in ("vhi", "vlo", "vref")]
    + [{"name": "vldo", "direction": "inout"}]
    + [{"name": f"out{i}", "direction": "output"} for i in range(1, 7)]
    + [{"name": "dout", "direction": "output"}]
    + [{"name": n, "direction": "output"} for n in ("ck4", "ck5", "ck6")]
)
_CONV_DIGITAL_IFACE = [
    {"name": "vin_p", "direction": "input"},
    {"name": "vref", "direction": "input"},
    {"name": "vdd", "direction": "input"},
    {"name": "clk", "direction": "input"},
    {"name": "rst_n", "direction": "input"},
    {"name": "start", "direction": "input"},
    {"name": "data_out", "direction": "output"},
    {"name": "valid", "direction": "output"},
]




# ══ #148 — all-analog RTL-dependent steps SKIP, not FAIL ════════════════════















# ══ #149 — primary lib is the device-defining one, not the most-sections one ═

def _two_lib_res(lib_a: str, lib_b: str):
    """Synthetic resolver result with two staged libs (paths only)."""
    return {"available": True, "source": "project_custom_pdk",
            "family": "synthfab", "spice_libs": [lib_a, lib_b]}


def test_149_primary_prefers_device_defining_lib_over_more_sections():
    lib_a = "/stage/pdk/spice/devices.lib"   # defines nmos+pmos, 1 section
    lib_b = "/stage/pdk/spice/corners.lib"   # NO devices, 3 sections
    texts = {
        lib_a: (".subckt nch_dev d g s b\n.ends\n"
                ".subckt pch_dev d g s b\n.ends\n"
                ".lib tt\n"),
        lib_b: ".lib tt\n.lib ss\n.lib ff\n",
    }
    ctx = APDC.custom_family_context(_two_lib_res(lib_a, lib_b),
                                     reader=lambda p: texts.get(p))
    assert ctx.status == "OK"
    # the device-defining lib wins even though it ships FEWER `.lib` sections
    assert ctx.model_lib == lib_a
    assert ctx.device_map.get("nmos") == "nch_dev"
    assert ctx.device_map.get("pmos") == "pch_dev"


def test_149_single_lib_unchanged():
    lib = "/stage/pdk/spice/all.lib"
    texts = {lib: (".subckt nch_dev d g s b\n.ends\n"
                   ".subckt pch_dev d g s b\n.ends\n.lib tt\n.lib ss\n")}
    res = {"available": True, "source": "project_custom_pdk",
           "family": "synthfab", "spice_libs": [lib]}
    ctx = APDC.custom_family_context(res, reader=lambda p: texts.get(p))
    assert ctx.status == "OK"
    assert ctx.model_lib == lib


def test_149_no_device_resolution_degrades_to_section_count():
    """When NO device role resolves, the ranking degrades to the historical
    section-count pick (the lib with the most sections)."""
    lib_a = "/stage/pdk/spice/a.lib"   # 1 section, no MOS devices
    lib_b = "/stage/pdk/spice/b.lib"   # 3 sections, no MOS devices
    texts = {lib_a: ".lib tt\n", lib_b: ".lib tt\n.lib ss\n.lib ff\n"}
    ctx = APDC.custom_family_context(_two_lib_res(lib_a, lib_b),
                                     reader=lambda p: texts.get(p))
    # unresolved devices → NEEDS_NATIVE_TEMPLATE, but the primary pick is still
    # the most-sections lib (no device signal to override it).
    assert ctx.model_lib == lib_b


# ══ #150 — native MC consumes resolved mc_libs, never a sky130 overlay ══════

def _native_mc_project(tmp_path: Path, with_mc: bool = True) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"fields": {"pdk_target": "synthfab180"}}))
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "synthfab_models.lib").write_text(
        ".subckt nch d g s b\n.ends\n.lib tt\n")
    if with_mc:
        (sp / "synthfab_mismatch.lib").write_text(
            ".lib mc_mm\n.subckt nch d g s b\n.ends\n")
    blk = tmp_path / "phase2" / "analog" / "ldo"
    blk.mkdir(parents=True)
    (blk / "ldo.sp").write_text(
        ".lib /stage/pdk/spice/synthfab_models.lib tt\n"
        "* runnable native deck\n.meas dc vout FIND v(out) AT=1u\n.end\n")
    spec = tmp_path / "phase1" / "analog" / "ldo"
    spec.mkdir(parents=True)
    (spec / "spec.json").write_text(json.dumps(
        {"specs": [{"name": "vout", "min": 1.7, "max": 1.9}]}))
    return tmp_path


def _fake_ngspice(values):
    it = iter(values)
    def fake(container, sp, cwd=None):
        v = next(it)
        return True, {"vout": v}, f"vout = {v}\n"
    return fake


def test_150_native_mc_uses_resolved_mismatch_lib(tmp_path, monkeypatch):
    p = _native_mc_project(tmp_path, with_mc=True)
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    monkeypatch.setattr(ARS, "_run_ngspice",
                        _fake_ngspice([1.78, 1.80, 1.82, 1.84, 1.86,
                                       1.88, 1.79, 1.81, 1.83, 1.85]))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    # pdk="sky130" (the default) is deliberately passed — native resolution must
    # OVERRIDE it (this is the exact bug scenario).
    rep = MC.run_block(p, "ldo", "x", "sky130", 10)
    decks = sorted((p / "phase2/analog/ldo/mc_runs").glob("mc_*.sp"))
    assert decks
    for d in decks:
        t = d.read_text()
        assert "synthfab_mismatch.lib" in t          # native mismatch lib
        assert "sky130" not in t.lower()             # NO cross-family overlay
        assert "synthfab_models.lib" not in t        # native corner stripped
        # structurally single-family: exactly one model include line
        assert len(MC._INCLUDE_FORM_MODEL_RE.findall(t)) == 1


def test_150_native_no_mc_lib_is_unscoreable(tmp_path, monkeypatch):
    p = _native_mc_project(tmp_path, with_mc=False)
    called = {"n": 0}
    monkeypatch.setattr(ARS, "_ngspice_available",
                        lambda c: (called.__setitem__("n", called["n"] + 1)
                                   or True))
    rep = MC.run_block(p, "ldo", "x", "sky130", 10)
    assert rep["verdict"] == "UNSCOREABLE"
    assert rep["rc"] == 2
    assert "mismatch" in rep["reason"].lower() or "mc_libs" in rep["reason"]
    # UNSCOREABLE is structural — ngspice is never probed, no decks written
    assert called["n"] == 0
    assert not (p / "phase2/analog/ldo/mc_runs").exists()


def test_150_open_pdk_regression_still_tt_mm(tmp_path, monkeypatch):
    """No-leak: a project with NO L19 native target keeps the open-PDK sky130
    tt_mm path exactly as before."""
    blk = tmp_path / "phase2" / "analog" / "ldo"
    blk.mkdir(parents=True)
    (blk / "ldo.sp").write_text(
        "* ldo deck\n.meas dc vout FIND v(out) AT=1u\n.end\n")
    spec = tmp_path / "phase1" / "analog" / "ldo"
    spec.mkdir(parents=True)
    (spec / "spec.json").write_text(json.dumps(
        {"specs": [{"name": "vout", "min": 1.7, "max": 1.9}]}))
    monkeypatch.setattr(ARS, "_ngspice_available", lambda c: True)
    monkeypatch.setattr(ARS, "_run_ngspice", _fake_ngspice([1.8, 1.81, 1.82]))
    monkeypatch.setattr(ARS, "_container_path", lambda c, r, p_: str(p_))
    MC.run_block(tmp_path, "ldo", "x", "sky130", 3)
    decks = sorted((tmp_path / "phase2/analog/ldo/mc_runs").glob("mc_*.sp"))
    assert decks
    assert all("sky130.lib.spice tt_mm" in d.read_text() for d in decks)


# ══ #151 — native model-include recognition in A3 ══════════════════════════

def _native_pdk_project(tmp_path: Path) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"fields": {"pdk_target": "synthfab180"}}))
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "synthfab_models.lib").write_text(
        ".subckt nch d g s b\n.ends\n.lib tt\n")
    (sp / "synthfab_mismatch.lib").write_text(
        ".lib mc_mm\n.subckt nch d g s b\n.ends\n")
    return tmp_path


def _write_netlist(project: Path, name: str, body: str) -> None:
    d = project / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)


def test_151_native_subckt_definition_lib_accepted(tmp_path):
    p = _native_pdk_project(tmp_path)
    _write_netlist(p, "ldo.sp",
                   ".subckt ldo vdd vref vout\n"
                   "xmn vout vref 0 0 nch w=2 l=2\n.ends ldo\n")
    r = NPC.run_audit(p)
    assert r.passed is True, [f.rule for f in r.findings if f.severity == "ERROR"]
    assert any(f.rule == "NATIVE_SUBCKT_LIB_ACCEPTED" for f in r.findings)
    assert not any(f.rule == "NO_MODEL_INCLUDE" for f in r.findings)


def test_151_native_model_include_accepted(tmp_path):
    p = _native_pdk_project(tmp_path)
    _write_netlist(p, "run_tt.sp",
                   ".lib /wherever/it/mounts/synthfab_models.lib tt\n"
                   "xmn out g 0 0 nch w=2 l=2\n"
                   ".control\nop\n.endc\n.end\n")
    r = NPC.run_audit(p)
    assert r.passed is True, [f.rule for f in r.findings if f.severity == "ERROR"]
    assert any(f.rule == "NATIVE_MODEL_INCLUDE" for f in r.findings)


def test_151_out_of_ladder_include_still_fails(tmp_path):
    """No-leak: a deck including a path OUTSIDE the resolved native set FAILs."""
    p = _native_pdk_project(tmp_path)
    _write_netlist(p, "bad.sp",
                   ".lib /some/random/other_pdk_models.lib tt\n"
                   "xmn out g 0 0 nch w=2 l=2\n.control\nop\n.endc\n.end\n")
    r = NPC.run_audit(p)
    assert r.passed is False
    assert any(f.rule == "NATIVE_PDK_INCLUDE_OUT_OF_LADDER"
               for f in r.findings)


def test_151_sky130_overlay_on_native_still_pdk_mismatch(tmp_path):
    """No-leak: a native project whose deck still carries a sky130 overlay is
    detected as an open-PDK deck and hard-FAILs #438b PDK_MISMATCH."""
    p = _native_pdk_project(tmp_path)
    _write_netlist(p, "mc_0001.sp",
                   ".lib /foss/pdks/sky130A/libs.tech/ngspice/"
                   "sky130.lib.spice tt_mm\n"
                   ".lib /stage/synthfab_models.lib tt\n"
                   "xmn out g 0 0 nch w=2 l=2\n.control\nop\n.endc\n.end\n")
    r = NPC.run_audit(p)
    assert r.passed is False
    assert any(f.rule == "PDK_MISMATCH" for f in r.findings)


def test_151_non_native_project_unchanged(tmp_path):
    """No-leak: a project with NO native resolution keeps the historical gate —
    a `.subckt` library with no model include still FAILs NO_MODEL_INCLUDE."""
    # no L19 target → no native resolution
    _write_netlist(tmp_path, "ldo.sp",
                   ".subckt ldo vdd vref vout\n"
                   "xmn vout vref 0 0 nch w=2 l=2\n.ends ldo\n")
    r = NPC.run_audit(tmp_path)
    assert r.passed is False
    assert any(f.rule == "NO_MODEL_INCLUDE" for f in r.findings)
    assert not any(f.rule == "NATIVE_SUBCKT_LIB_ACCEPTED" for f in r.findings)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
