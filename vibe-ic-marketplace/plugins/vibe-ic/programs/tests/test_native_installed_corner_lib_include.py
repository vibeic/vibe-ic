"""Native rung-2 installed-PDK corner-sweep enablement (ORGANIC-analog).

Reproduces — with SYNTHETIC families only (NO chip / vendor / SKU literal) — the
structural shape of an installed open PDK whose ngspice models are laid out as a
`corner<X>.lib` that DEFINES the `.LIB <section>` corner sections (UPPERCASE) and
`.include`s a SEPARATE device-`.subckt` lib inside each section. That topology is
exactly what left every rung-2 native family (an installed non-sky130/gf180 PDK)
dead-ended at NEEDS_NATIVE_TEMPLATE, so a native corner sweep never ran:

  1. `analog_pdk_availability.resolve_pdk` rung-2 did NOT populate `spice_libs`
     → `custom_family_context` had nothing to parse.
  2. `custom_family_context` did not follow `.include`, so the section-bearing
     corner lib looked device-less, and the primary pick chose a section-LESS
     device lib → `.lib <devlib> <section>` (a section that lib does not define).
  3. corner section names were only matched as a LEADING token, so a prefixed
     `proc_tt` / uppercase `.LIB` never mapped to typ/slow/fast → single-corner.

All three are covered here, plus the auxiliary-unreadable-lib non-blocker.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_pdk_availability as APA          # noqa: E402
import analog_pdk_deck_context as APDC          # noqa: E402
import analog_real_corner_sweep as ARS          # noqa: E402


# ── synthetic installed-PDK model libs (corner lib + separate device lib) ────

_PDKS_ROOT = "/pdks"
_MATCHED = "acme-x1"
_MODELS = f"{_PDKS_ROOT}/{_MATCHED}/libs.tech/ngspice/models"
_CORNER_LIB = f"{_MODELS}/cornermos.lib"
_DEV_LIB = f"{_MODELS}/devices.lib"
_AUX_LIB = f"{_MODELS}/aux.lib"

# The device `.subckt`s live in a SEPARATE file (no corner sections of its own).
_DEV_TXT = (
    "* acme device models (NO NDA content)\n"
    ".subckt acme_lv_nmos d g s b w=1 l=1\n.ends\n"
    ".subckt acme_lv_pmos d g s b w=1 l=1\n.ends\n"
)
# The corner lib DEFINES the sections (UPPERCASE `.LIB`, prefixed names) and
# `.include`s the device lib inside each — the deck's `.lib <corner> <section>`
# line pulls the devices in transitively.
_CORNER_TXT = "".join(
    f".LIB proc_{c}\n.include devices.lib\n.ENDL proc_{c}\n"
    for c in ("tt", "ss", "ff", "sf", "fs")
)
_AUX_TXT = "* aux corner lib, no MOS devices\n.LIB aux_tt\n.ENDL aux_tt\n"


def _lister(models=("cornermos.lib", "devices.lib", "aux.lib")):
    tech = f"{_PDKS_ROOT}/{_MATCHED}/libs.tech"
    ng = f"{tech}/ngspice"

    def L(path):
        if path == _PDKS_ROOT:
            return [_MATCHED]
        if path == tech:
            return ["ngspice", "magic", "klayout"]
        if path == ng:
            return []                      # top ngspice dir ships no bare .lib
        if path == f"{ng}/models":
            return list(models)
        return []
    return L


def _reader(p):
    return {_CORNER_LIB: _CORNER_TXT, _DEV_LIB: _DEV_TXT,
            _AUX_LIB: _AUX_TXT}.get(p)


# ── (1) rung-2 resolve_pdk now populates spice_libs ─────────────────────────

def test_rung2_populates_spice_libs():
    res = APA.resolve_pdk("acmex1", pdks_root=_PDKS_ROOT, lister=_lister())
    assert res["available"] and res["rung"] == 2
    assert res["source"] == "container_installed"
    # every model lib under the ngspice models dir is wired, sorted
    assert res["spice_libs"] == sorted([_AUX_LIB, _CORNER_LIB, _DEV_LIB])
    assert res["spice_lib"] == sorted([_AUX_LIB, _CORNER_LIB, _DEV_LIB])[0]


def test_rung2_no_models_dir_keeps_empty_spice_libs():
    """A PDK whose ngspice dir ships nothing parseable keeps spice_libs empty —
    the honest NEEDS_NATIVE_TEMPLATE path is preserved (no fabricated lib)."""
    res = APA.resolve_pdk("acmex1", pdks_root=_PDKS_ROOT, lister=_lister(models=()))
    assert res["available"] and res["spice_libs"] == []


# ── (2) transitive `.include` + section-bearing primary + device consistency ─

def test_installed_corner_lib_include_resolves_native():
    res = APA.resolve_pdk("acmex1", pdks_root=_PDKS_ROOT, lister=_lister())
    ctx = APDC.resolve_deck_context("sky130", res=res, reader=_reader)
    assert ctx.status == "OK"
    assert ctx.source == "container_installed"
    # primary is the SECTION-BEARING corner lib (the file `.lib <p> <sec>` loads)
    assert ctx.model_lib == _CORNER_LIB
    # devices came from the corner lib's transitive `.include` closure — and are
    # consistent with the primary (never a section-less device lib mismatch)
    assert ctx.device_map == {"nmos": "acme_lv_nmos", "pmos": "acme_lv_pmos"}
    # uppercase `.LIB proc_tt/ss/ff` mapped to typ/slow/fast by COMPONENT
    assert ctx.typ_section == "proc_tt"
    assert [c[0] for c in ctx.process_corners] == ["proc_ss", "proc_tt", "proc_ff"]


def test_installed_corner_lib_deck_uses_family_devices_and_section():
    res = APA.resolve_pdk("acmex1", pdks_root=_PDKS_ROOT, lister=_lister())
    ctx = APDC.resolve_deck_context("sky130", res=res, reader=_reader)
    deck, _ = ARS.render_deck("ldo", "u_ldo", "acmex1", ctx.model_lib,
                              ctx.typ_section, "m_pass", 40,
                              devices=ctx.device_map)
    assert "acme_lv_nmos" in deck and "acme_lv_pmos" in deck
    assert ".lib " + _CORNER_LIB + " proc_tt" in deck
    assert "sky130_fd_pr" not in deck        # NO cross-family sky130 literal


# ── (3) auxiliary unreadable lib must NOT block a resolved deck ──────────────

def test_unreadable_auxiliary_lib_does_not_block():
    """When roles + a corner section + primary ALL resolve from the readable
    libs, a couple of unreadable AUXILIARY libs (e.g. a non-CMOS bipolar/ESD
    model file rung-2 also lists) are informational, not NEEDS_NATIVE_TEMPLATE."""
    res = APA.resolve_pdk("acmex1", pdks_root=_PDKS_ROOT,
                          lister=_lister(models=("cornermos.lib", "devices.lib",
                                                 "hbt_bipolar.lib")))
    # reader returns None for the unlisted hbt lib → it is "unread"
    ctx = APDC.resolve_deck_context("sky130", res=res, reader=_reader)
    assert ctx.status == "OK"
    assert ctx.device_map == {"nmos": "acme_lv_nmos", "pmos": "acme_lv_pmos"}
    assert "not readable" in ctx.disclosure   # surfaced as a note, not a blocker


# ── unit coverage of the new primitives ─────────────────────────────────────

def test_map_corner_sections_prefixed_component_names():
    typ, proc = APDC.map_corner_sections(["proc_tt", "proc_ss", "proc_ff"])
    assert typ == "proc_tt"
    assert [p[0] for p in proc] == ["proc_ss", "proc_tt", "proc_ff"]


def test_map_corner_sections_component_equality_no_false_hit():
    # `cutt` is a single component != `tt` (component equality, not substring),
    # so it must NOT be misread as the typ corner; a real `nom` is.
    typ, _ = APDC.map_corner_sections(["cutt", "nom_x"])
    assert typ != "cutt"


def test_transitive_subckts_follows_include():
    sub = APDC.transitive_subckts(_CORNER_LIB, _CORNER_TXT, _reader)
    assert sub.get("acme_lv_nmos") == 4
    assert sub.get("acme_lv_pmos") == 4


def test_transitive_subckts_degrades_without_reader():
    # No reader → cannot follow includes → returns only the file's OWN subckts
    # (here none), never raising.
    assert APDC.transitive_subckts(_CORNER_LIB, _CORNER_TXT, None) == {}


def test_hardmacro_lib_lef_not_taken_as_staged_spice_pdk(tmp_path):
    """A generated hardmacro (Liberty `.lib` + LEF `.lef`) under
    phase3/analog/hardmacro/ must NOT be mistaken for a rung-1 staged SPICE PDK
    — otherwise resolve_pdk returns a device-less custom family that SHADOWS the
    real installed rung-2 PDK, dead-ending a sibling block's corner sweep."""
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / "blk"
    hm.mkdir(parents=True)
    (hm / "blk.lib").write_text(
        "library(blk_stub) {\n  cell(blk) {\n    area : 10000 ;\n  }\n}\n")
    (hm / "blk.lef").write_text("VERSION 5.8 ;\nMACRO blk\nEND blk\n")
    # rung 1 must find NO simulatable spice model lib → not available
    r1 = APA._resolve_project_custom_pdk(tmp_path, "sg13g2")
    assert r1["available"] is False
    assert r1["spice_libs"] == []


def test_is_spice_model_lib_discriminates(tmp_path):
    lef = tmp_path / "m.lef"; lef.write_text("VERSION 5.8 ;\n")
    lib_liberty = tmp_path / "t.lib"
    lib_liberty.write_text("library(x) {\n cell(y) { area: 1; }\n}\n")
    lib_spice = tmp_path / "d.lib"
    lib_spice.write_text(".subckt fam_nch d g s b\n.ends\n")
    sp = tmp_path / "n.sp"; sp.write_text("* deck\n")
    assert APA._is_spice_model_lib(str(lef)) is False       # LEF never SPICE
    assert APA._is_spice_model_lib(str(lib_liberty)) is False  # Liberty timing
    assert APA._is_spice_model_lib(str(lib_spice)) is True   # real model lib
    assert APA._is_spice_model_lib(str(sp)) is True          # .sp deck


def test_staged_real_spice_pdk_still_resolves_rung1(tmp_path):
    """Regression guard: a genuinely staged SPICE model lib under input/pdk/
    still resolves rung-1 (the NDA commercial-node case is unaffected)."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "models.lib").write_text(
        ".lib tt\n.subckt fnd_nch d g s b\n.ends\n"
        ".subckt fnd_pch d g s b\n.ends\n.endl\n")
    r1 = APA._resolve_project_custom_pdk(tmp_path, "FoundryNode")
    assert r1["available"] is True and r1["source"] == "project_custom_pdk"
    assert any(p.endswith("models.lib") for p in r1["spice_libs"])


def test_sky130_known_family_still_bypasses_parse():
    """Regression guard: a known open family installed in the container still
    takes the byte-identical known_family fast path (never the parse path),
    even though rung-2 now attaches spice_libs."""
    res = {"available": True, "source": "container_installed",
           "matched_dir": "sky130A", "family": "sky130",
           "spice_libs": ["/foss/pdks/sky130A/x.lib"]}
    ctx = APDC.resolve_deck_context("sky130", res=res, reader=lambda p: None)
    assert ctx.source == "known_family"
    assert ctx.device_map == {"nmos": "sky130_fd_pr__nfet_01v8",
                              "pmos": "sky130_fd_pr__pfet_01v8"}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
