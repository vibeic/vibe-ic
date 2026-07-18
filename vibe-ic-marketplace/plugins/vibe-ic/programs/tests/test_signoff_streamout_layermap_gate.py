"""Sign-off streamout must not fall back to legacy layer numbering.

#509 wired a foundry LEF/DEF->GDS layer map into the streamout, but a missing
map stayed ADVISORY: the script printed "legacy numbering" and wrote the GDS
anyway, and the step still reported PASS. That is the whole defect, because a
GDS in that state is wrong twice over — the sign-off deck reads routed metal as
purposes the design never drew, and the layout could not be fabricated either.

Measured on the caravel_user_project commercial-PDK clean run: same DEF, same
deck, 4533 rules checked in both directions — 51 rules firing with the map
absent, 1 with it applied, and the foundry via layers empty in the un-mapped
GDS. Every geometry class the deck reports (enclosure / external / internal /
copy) went to zero; only a metal-density rule remained.

These tests pin the two halves of the fix: a declared map is honoured when
glob discovery cannot see the file, and a sign-off streamout with no map at
all fails instead of shipping.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


def _write_map(p: Path) -> Path:
    p.write_text("MET1 drawing 9 0\nVIA1 drawing 10 0\nMET2 drawing 11 0\n")
    return p


# ---------------------------------------------------------------------------
# Declared map (the bundle that stages `lef/*.lef` without the sibling map)
# ---------------------------------------------------------------------------
def test_declared_layermap_resolves_relative_to_pdk_dir(tmp_path: Path):
    _write_map(tmp_path / "streamout.map")
    got = R._declared_lefdef_layermap(
        tmp_path, {"lefdef_layermap": "streamout.map"})
    assert got == str(tmp_path / "streamout.map")


def test_declared_layermap_accepts_absolute_path(tmp_path: Path):
    m = _write_map(tmp_path / "abs.map")
    assert R._declared_lefdef_layermap(tmp_path,
                                       {"lefdef_layermap": str(m)}) == str(m)


def test_declared_layermap_none_when_undeclared_or_absent(tmp_path: Path):
    assert R._declared_lefdef_layermap(tmp_path, {}) is None
    assert R._declared_lefdef_layermap(
        tmp_path, {"lefdef_layermap": "missing.map"}) is None


def test_discovery_still_finds_a_staged_vendor_map(tmp_path: Path):
    """The declaration supplements glob discovery; it does not replace it."""
    lef = tmp_path / "lef"
    lef.mkdir()
    _write_map(lef / "KF_common_layermap_for_SOC_encounter.txt")
    assert R._discover_lefdef_layermap(tmp_path) is not None


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def _pdk(**kw):
    base = dict(name="t", liberty="l", tech_lef="t.lef", cell_lef="c.lef",
                cell_gds="c.gds", site="s", drc_deck=None, metal_prefix="met")
    base.update(kw)
    return R.PdkConfig(**base)


def test_signoff_streamout_without_map_fails(tmp_path: Path, monkeypatch):
    """A foundry deck is present and no map was resolved → FAIL, not PASS."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "top.def").write_text("DESIGN top ;\nEND DESIGN\n")
    monkeypatch.setattr(R._pl, "pnr_dir", lambda _p: pnr)

    res = R.step_gds(
        tmp_path, "top",
        _pdk(calibre_drc="/pdk/deck.rule", lefdef_layermap=None), "container")
    assert res.status == "FAIL"
    assert "layer map" in res.detail.lower()


def test_no_foundry_deck_keeps_legacy_path_open(tmp_path: Path, monkeypatch):
    """OSS PDKs are not gated: without a vendor deck there is no foundry
    numbering to conform to, so the streamout proceeds as before."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "top.def").write_text("DESIGN top ;\nEND DESIGN\n")
    monkeypatch.setattr(R._pl, "pnr_dir", lambda _p: pnr)
    monkeypatch.setattr(R, "_magic_def_to_gds",
                        lambda *a, **k: (False, "no magic"))
    monkeypatch.setattr(R, "_docker_exec", lambda *a, **k: (1, "", "no tool"))

    res = R.step_gds(
        tmp_path, "top",
        _pdk(calibre_drc=None, lefdef_layermap=None), "container")
    # It may still fail for want of a tool, but never for the map reason.
    assert "layer map" not in res.detail.lower()


def test_pdkconfig_carries_signoff_config_path():
    import dataclasses
    f = {x.name: x for x in dataclasses.fields(R.PdkConfig)}
    assert "signoff_config_path" in f
    assert f["signoff_config_path"].default is None
