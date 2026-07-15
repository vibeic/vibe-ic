"""Headline analog-track honesty fix — native PDK availability resolution.

The pdk-SUBSTITUTION waiver (which defers A3/A5-A9) must fire ONLY for a target
genuinely ABSENT from the EDA container. A target that IS natively installed
(e.g. IHP SG13G2, which ships in vibeic-eda at /foss/pdks/ihp-sg13g2) must
NEVER silently substitute — the native analog path applies.

Layers:
  A. analog_pdk_availability.resolve_pdk — family-agnostic match + tech probe;
     installed vs genuinely-absent, container-absent probe honesty.
  B. §4.05 emit-side no-leak — pdk_substitution_header:
       installed target  → NATIVE marker (no `pdk_substitution` disclosure)
       absent target      → substitution disclosure (waiver path preserved)
  C. §4.05 gate-side no-leak — flow_compliance_check._pdk_substitution_disclosed:
       a deck carrying the NATIVE marker earns NO substitution waiver;
       a deck carrying the substitution marker for an absent target does.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_pdk_availability as APA            # noqa: E402
import analog_real_corner_sweep as ARS           # noqa: E402
import flow_compliance_check as FCC              # noqa: E402


def _make_lister(tree: dict):
    """A path→entries lister backed by a dict (no docker)."""
    def L(path: str):
        return list(tree.get(path.rstrip("/"), []))
    return L


# The container's installed-PDK tree (sky130A / gf180mcuD / ihp-sg13g2 present).
_INSTALLED = {
    "/foss/pdks": ["ciel", "gf180mcuD", "ihp-sg13cmos5l", "ihp-sg13g2",
                   "sky130A", "versions.txt"],
    "/foss/pdks/ihp-sg13g2/libs.tech": ["ngspice", "magic", "klayout",
                                        "netgen", "openroad"],
    "/foss/pdks/sky130A/libs.tech": ["ngspice", "magic", "klayout", "netgen"],
    "/foss/pdks/gf180mcuD/libs.tech": ["ngspice", "magic", "klayout", "netgen"],
    "/foss/pdks/ihp-sg13cmos5l/libs.tech": ["ngspice", "magic"],
}


# ── A. resolver ─────────────────────────────────────────────────────────────

def test_resolve_installed_target_is_available():
    L = _make_lister(_INSTALLED)
    r = APA.resolve_pdk("IHP SG13G2 (130nm SiGe BiCMOS)", lister=L)
    assert r["available"] is True
    assert r["matched_dir"] == "ihp-sg13g2"
    assert r["tech_present"]["ngspice"] is True
    assert r["ngspice_dir"].endswith("ihp-sg13g2/libs.tech/ngspice")


def test_resolve_family_token_variants():
    L = _make_lister(_INSTALLED)
    for tok in ("sg13g2", "IHP-SG13G2", "ihp_sg13g2"):
        assert APA.resolve_pdk(tok, lister=L)["matched_dir"] == "ihp-sg13g2"
    # a DIFFERENT installed family is disambiguated, not collapsed
    assert APA.resolve_pdk("ihp-sg13cmos5l", lister=L)["matched_dir"] == "ihp-sg13cmos5l"


def test_resolve_absent_target_is_not_available():
    L = _make_lister(_INSTALLED)
    for tok in ("AcmeFab X28 node", "SynthCorp N65", "NovaFab F22"):
        r = APA.resolve_pdk(tok, lister=L)
        assert r["available"] is False, tok
        assert r["matched_dir"] is None
        assert r["probe_ok"] is True  # we DID probe; it's genuinely absent


def test_resolve_unprobeable_falls_back():
    # empty listing (no container / probe failed) → cannot affirm native
    r = APA.resolve_pdk("sg13g2", lister=_make_lister({}))
    assert r["available"] is False
    assert r["probe_ok"] is False


def test_resolve_dir_present_but_no_ngspice_is_not_available():
    tree = {"/foss/pdks": ["ihp-sg13g2"],
            "/foss/pdks/ihp-sg13g2/libs.tech": ["magic", "klayout"]}
    r = APA.resolve_pdk("sg13g2", lister=_make_lister(tree))
    assert r["matched_dir"] == "ihp-sg13g2"
    assert r["available"] is False  # no ngspice tech → not a native sim path


# ── A2. rung-1 project custom PDK (the NDA / commercial-node case) ──────────
# NDA hygiene: SYNTHETIC family names only — never the real NDA token.

def _stage_custom_pdk(project: Path, with_decks: bool = True) -> None:
    sp = project / "input" / "pdk" / "spice"
    sp.mkdir(parents=True, exist_ok=True)
    (sp / "myfoundry_x180_tt.lib").write_text(
        "* synthetic model lib\n.lib tt\n.model nch nmos\n.endl\n")
    if with_decks:
        cal = project / "input" / "pdk" / "calibre"
        cal.mkdir(parents=True, exist_ok=True)
        (cal / "myfoundry_x180_DRC.rule").write_text("LAYER M1 1\n")
        (cal / "myfoundry_x180_LVS.rule").write_text("LVS ...\n")


def test_rung1_project_custom_pdk_is_native(tmp_path):
    _stage_custom_pdk(tmp_path)
    r = APA.resolve_pdk("MyFoundry X180 (custom NDA node)", project=str(tmp_path))
    assert r["available"] is True
    assert r["source"] == "project_custom_pdk"
    assert r["rung"] == 1
    assert len(r["spice_libs"]) >= 1
    assert r["drc_deck"] and r["lvs_deck"]


def test_rung1_reports_mc_section_slot(tmp_path):
    """ORGANIC #142 addendum — a staged custom PDK that ships statistical /
    mismatch model libs surfaces them as an `mc_libs` slot so the MC-run layer
    selects the statistical variant (not deterministic+MC-overlay). Synthetic
    family names only (NDA hygiene)."""
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "myfoundry_x180_tt.lib").write_text(".lib tt\n.model n nmos\n.endl\n")
    (sp / "myfoundry_x180_mc_global.lib").write_text(".lib mc\n.endl\n")
    (sp / "myfoundry_x180_mismatch.lib").write_text(".lib mm\n.endl\n")
    r = APA.resolve_pdk("MyFoundry X180", project=str(tmp_path))
    assert r["available"] is True
    assert r["tech_present"]["mc"] is True
    assert any("mc_global" in m for m in r["mc_libs"])
    assert any("mismatch" in m for m in r["mc_libs"])
    # a deterministic-only lib is NOT an MC lib
    assert not any("_tt.lib" in m for m in r["mc_libs"])


def test_rung1_no_mc_libs_when_only_deterministic(tmp_path):
    sp = tmp_path / "input" / "pdk" / "spice"
    sp.mkdir(parents=True)
    (sp / "myfoundry_x180_typical.lib").write_text(".lib tt\n.endl\n")
    r = APA.resolve_pdk("MyFoundry X180", project=str(tmp_path))
    assert r["available"] is True
    assert r["mc_libs"] == []
    assert r["tech_present"]["mc"] is False


def test_rung1_takes_precedence_over_container(tmp_path):
    """A project that stages its own PDK resolves rung 1 EVEN when the target
    is also absent from the container listing — rung 1 is checked first."""
    _stage_custom_pdk(tmp_path)
    r = APA.resolve_pdk("MyFoundry X180", project=str(tmp_path),
                        lister=_make_lister(_INSTALLED))  # container lacks it
    assert r["source"] == "project_custom_pdk" and r["rung"] == 1


def test_rung3_no_stage_no_install_is_substitution(tmp_path):
    """Neither staged (input/pdk) nor installed (container) → available=False
    → the honest substitution path (rung 3)."""
    r = APA.resolve_pdk("MyFoundry X180", project=str(tmp_path),
                        lister=_make_lister(_INSTALLED))
    assert r["available"] is False
    assert r["source"] is None


# ── B. emit-side no-leak (pdk_substitution_header) ─────────────────────────

def _project_with_l19(tmp_path: Path, target: str) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps(
        {"fields": {"pdk_target": target}}))
    return tmp_path


def test_emit_rung1_custom_pdk_no_substitution_even_without_container(tmp_path):
    """The NDA case: a project stages input/pdk/ analog assets — the emit side
    resolves rung 1 (local FS, no container needed) → native marker, NO
    substitution disclosure."""
    p = _project_with_l19(tmp_path, "MyFoundry X180 (custom NDA node)")
    _stage_custom_pdk(p)
    head = ARS.pdk_substitution_header(p, "sky130")  # NO container
    assert "pdk_native_available" in head
    assert "source=project_custom_pdk" in head
    assert "pdk_substitution" not in head
    assert "substitut" not in head.lower()


def test_emit_installed_target_no_substitution_disclosure(tmp_path):
    p = _project_with_l19(tmp_path, "IHP SG13G2")
    L = _make_lister(_INSTALLED)
    head = ARS.pdk_substitution_header(p, "sky130", lister=L)
    # installed → NATIVE marker, NOT a substitution disclosure
    assert "pdk_native_available" in head
    assert "pdk_substitution" not in head
    assert "substitut" not in head.lower()   # must not trip the prose predicate


def test_emit_absent_target_keeps_substitution_disclosure(tmp_path):
    p = _project_with_l19(tmp_path, "AcmeFab X28 node")
    L = _make_lister(_INSTALLED)
    head = ARS.pdk_substitution_header(p, "sky130", lister=L)
    assert "pdk_substitution:" in head
    assert "target=AcmeFab X28 node" in head
    assert "substitute=sky130" in head


def test_emit_no_container_no_probe_preserves_legacy(tmp_path):
    """A container-less call with no lister does not probe → legacy
    substitution disclosure (existing behaviour preserved)."""
    p = _project_with_l19(tmp_path, "IHP SG13G2")
    head = ARS.pdk_substitution_header(p, "sky130")  # no container, no lister
    assert "pdk_substitution:" in head


# ── C. gate-side no-leak (_pdk_substitution_disclosed) ─────────────────────

def _sky130_deck_body() -> str:
    return (".option scale=1u\n"
            ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt\n"
            "xmn a b 0 0 sky130_fd_pr__nfet_01v8 w=2 l=2\n"
            ".control\nop\n.endc\n.end\n")


def _mk_analog_deck(project: Path, head: str) -> None:
    import _path_layout as _pl
    ad = _pl.analog_dir(project)
    bdir = ad / "ldo"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "ldo.sp").write_text(head + _sky130_deck_body())


def test_gate_native_marker_earns_no_waiver(tmp_path):
    p = _project_with_l19(tmp_path, "IHP SG13G2")
    res = APA.resolve_pdk("IHP SG13G2", lister=_make_lister(_INSTALLED))
    native = APA.native_available_header(res, "sky130")
    _mk_analog_deck(p, native)
    # a native-marker deck is NOT a disclosed substitution → no waiver
    assert FCC._pdk_substitution_disclosed(p) is None


def test_gate_substitution_marker_absent_target_earns_waiver(tmp_path):
    p = _project_with_l19(tmp_path, "AcmeFab X28 node")
    head = ("* pdk_substitution: target=AcmeFab X28 node substitute=sky130 "
            "reason=no public ngspice models for target; open-source substitute\n")
    _mk_analog_deck(p, head)
    disc = FCC._pdk_substitution_disclosed(p)
    assert disc is not None
    assert disc["substitute"] == "sky130"
    assert disc["target"] == "AcmeFab X28 node"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
