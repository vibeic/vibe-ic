"""SPM-SI-1 — the OpenRCX captable must be found under BOTH shipped layouts.

THE DEFECT
    `phase3_one_shot_runner` discovered the OpenRCX extraction model with a
    SINGLE naming convention, the open_pdks one:

        libs.tech/{librelane,openlane}/rules.openrcx.<pdk>.<corner>.magic

    IHP-Open-PDK ships the same kind of file one level DEEPER and with the
    tokens REVERSED:

        libs.tech/librelane/openrcx/<pdk>.<corner>.magic.rules

    So on ihp-sg13g2 the glob returned nothing, the emitted deck fell through to
    the `-lef_rc` branch (per-layer R + area/fringe C, all lumped TO GROUND) and
    the SPEF came out with ZERO coupling capacitors. Everything downstream that
    reasons about inter-net coupling then became VACUOUS-BY-CONSTRUCTION: the
    signal-integrity screen reported "487 nets, 0 coupling pairs" and could
    never report anything else, on a PDK that does ship a full coupling model
    (`Metal 1 OVER 0` carries a distance-indexed coupling column).

    A check that cannot fail is worse than no check, so this is pinned here.

WHAT IS ASSERTED
    * both conventions are globbed, at every discovery site;
    * a PDK using ONLY the IHP layout resolves (the regression);
    * a PDK using ONLY the open_pdks layout still resolves (no behaviour change);
    * when both exist the pre-existing open_pdks choice still wins, so no PDK
      that resolves today silently starts resolving somewhere else.

chip/PDK-AGNOSTIC: no chip, vendor or corner literal drives the resolution.
"""
import glob as _glob
import shlex as _shlex
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

_CORNERS = ("min", "nom", "max")


def _fake_ls(_container, ls_expr, must_contain, timeout=20):
    """Host stand-in for `_container_ls_paths` (test container path == host)."""
    hits = []
    for pat in _shlex.split(ls_expr):
        for p in sorted(_glob.glob(pat)):
            if p.startswith("/") and must_contain in p and p not in hits:
                hits.append(p)
    return hits


def _stage_openpdks(root: Path, subdir: str = "librelane") -> str:
    """open_pdks / asap7 layout: rules.openrcx.<pdk>.<corner>.magic"""
    d = root / "pdk" / "libs.tech" / subdir
    d.mkdir(parents=True, exist_ok=True)
    for c in _CORNERS:
        (d / f"rules.openrcx.sky130A.{c}.magic").write_text("# captable\n")
    ref = root / "pdk" / "libs.ref" / "fix"
    ref.mkdir(parents=True, exist_ok=True)
    return str(ref / "tech.lef")


def _stage_ihp(root: Path, subdir: str = "librelane") -> str:
    """IHP-Open-PDK layout: openrcx/<pdk>.<corner>.magic.rules"""
    d = root / "pdk" / "libs.tech" / subdir / "openrcx"
    d.mkdir(parents=True, exist_ok=True)
    for c in _CORNERS:
        (d / f"ihp-sg13g2.{c}.magic.rules").write_text("# captable\n")
    ref = root / "pdk" / "libs.ref" / "fix"
    ref.mkdir(parents=True, exist_ok=True)
    return str(ref / "tech.lef")


def _pdk_with(tech_lef: str):
    class _P:
        pass
    p = _P()
    p.tech_lef = tech_lef
    return p


# ── the regression: IHP-only layout must resolve ─────────────────────────────
def test_discover_captables_finds_ihp_openrcx_subdir_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_container_ls_paths", _fake_ls)
    tlef = _stage_ihp(tmp_path)
    out = R._discover_openrcx_captables(_pdk_with(tlef), container="fake")
    assert set(out) == set(_CORNERS), (
        f"IHP openrcx/<pdk>.<corner>.magic.rules layout not discovered: {out}")
    for c in _CORNERS:
        assert out[c].endswith(f".{c}.magic.rules"), out[c]
        assert "/libs.tech/librelane/openrcx/" in out[c], out[c]


def test_ihp_layout_also_found_under_openlane_subdir(tmp_path, monkeypatch):
    """Backward-compat: an older image puts the same tree under openlane/."""
    monkeypatch.setattr(R, "_container_ls_paths", _fake_ls)
    tlef = _stage_ihp(tmp_path, subdir="openlane")
    out = R._discover_openrcx_captables(_pdk_with(tlef), container="fake")
    assert set(out) == set(_CORNERS), out
    for c in _CORNERS:
        assert "/libs.tech/openlane/openrcx/" in out[c], out[c]


# ── no behaviour change for PDKs that already resolved ───────────────────────
def test_openpdks_layout_still_resolves(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_container_ls_paths", _fake_ls)
    tlef = _stage_openpdks(tmp_path)
    out = R._discover_openrcx_captables(_pdk_with(tlef), container="fake")
    assert set(out) == set(_CORNERS), out
    for c in _CORNERS:
        assert out[c].endswith(f".{c}.magic"), out[c]


def test_openpdks_layout_wins_when_both_present(tmp_path, monkeypatch):
    """Adding the second convention must not re-point a PDK that already
    resolved — the open_pdks `.magic` model stays preferred."""
    monkeypatch.setattr(R, "_container_ls_paths", _fake_ls)
    tlef = _stage_openpdks(tmp_path)
    _stage_ihp(tmp_path)
    out = R._discover_openrcx_captables(_pdk_with(tlef), container="fake")
    assert set(out) == set(_CORNERS), out
    for c in _CORNERS:
        assert out[c].endswith(f".{c}.magic"), (
            f"IHP layout hijacked a PDK that already resolved: {out[c]}")


# ── every discovery site carries both conventions ────────────────────────────
def test_max_captable_helper_globs_both_conventions():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    i = src.find("def _max_captable_c(")
    assert i > 0, "_max_captable_c not found"
    body = src[i:i + 2000]
    assert "rules.openrcx.*.max.magic" in body, body[:400]
    assert "openrcx/*.max.magic.rules" in body, (
        "_max_captable_c still single-convention — an IHP-layout PDK would "
        "silently lose its max-corner captable")


def test_emitted_spef_decks_glob_both_conventions():
    """Every emitted TCL that discovers a captable must try both layouts.

    Guards the exact failure mode: a deck that globs only `rules.openrcx.*`
    falls through to `-lef_rc` and produces a coupling-free SPEF."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    # Count only real emitted globs, not the prose that describes them: a line
    # is a glob site iff it carries BOTH the tcl `glob` call and the pattern.
    glob_lines = [ln for ln in src.splitlines() if "glob -nocomplain" in ln]
    open_pdks_sites = [ln for ln in glob_lines
                       if "rules.openrcx.*.nom.magic" in ln]
    ihp_sites = [ln for ln in glob_lines if "openrcx/*.nom.magic.rules" in ln]
    assert len(open_pdks_sites) >= 2, open_pdks_sites
    assert len(ihp_sites) >= len(open_pdks_sites), (
        f"{len(open_pdks_sites)} open_pdks-convention nom glob site(s) but only "
        f"{len(ihp_sites)} IHP-convention one(s) — at least one emitted deck can "
        f"still degrade to a coupling-free SPEF on an IHP-layout PDK")
