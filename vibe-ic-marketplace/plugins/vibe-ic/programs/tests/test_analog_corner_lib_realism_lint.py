"""test_analog_corner_lib_realism_lint.py — R15 stale-corner-lib lint (v1.3.54).

Proves: (a) a foundry-subckt deck (real corner lib, no LEVEL=1) PASSes,
(b) an UNDISCLOSED LEVEL=1 / ideal model deck FAILs (the silent-substitution
defect the lint guards), (c) a DISCLOSED LEVEL=1 standin deck is downgraded to
a non-failing WARN (the legitimate open-PDK case — corpus-clean), (d) SKIP
when no analog decks. Block names synthetic — no chip/SKU literal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "analog_corner_lib_realism_lint.py")

_FOUNDRY_DECK = """* real foundry deck
.include /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice
.subckt amp vdd vss vin vout
xm1 vout vin vss vss sky130_fd_pr__nfet_01v8 w=8 l=1
.ends
"""

_LEVEL1_NO_DISCLOSURE = """* toy deck
.subckt amp vdd vss vin vout
mn1 vout vin vss vss nm w=8u l=1u
.ends
.model nm nmos (LEVEL=1 VTO=0.4 KP=70u)
.model pm pmos (LEVEL=1 VTO=-0.45 KP=28u)
"""

_LEVEL1_DISCLOSED = """* modulator core
* HONEST DISCLOSURE: this PDK has NO public ngspice corner lib. Models are
* DOCUMENTED LEVEL=1 STANDIN = MODELED, not silicon sign-off.
.subckt amp vdd vss vin vout
mn1 vout vin vss vss nm w=8u l=1u
.ends
.model nm nmos (LEVEL=1 VTO=0.42 KP=70u)
.model pm pmos (LEVEL=1 VTO=-0.47 KP=28u)
"""


def _mk_deck(project: Path, block: str, deck_text: str, disclose_sib=False):
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{block}.sp").write_text(deck_text)
    if disclose_sib:
        (d / "corner_results.json").write_text(json.dumps({
            "model_disclosure": "LEVEL=1 standin (MODELED, not silicon sign-off)",
            "corners": [{"name": "TT_27c"}]}))


def _run(project: Path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "r.json")],
        capture_output=True, text=True)
    rpt = json.loads((project / "r.json").read_text())
    return r, rpt


def test_foundry_deck_passes(tmp_path: Path):
    _mk_deck(tmp_path, "amp0", _FOUNDRY_DECK)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert rpt["verdict"] == "PASS"


def test_undisclosed_level1_fails(tmp_path: Path):
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE)
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert rpt["verdict"] == "FAIL"
    assert any(f["rule"] == "CORNER_LIB_IDEAL_MODEL" for f in rpt["findings"])
    assert any(f["severity"] == "ERROR" for f in rpt["findings"])


def test_disclosed_level1_is_warn(tmp_path: Path):
    _mk_deck(tmp_path, "amp0", _LEVEL1_DISCLOSED)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert rpt["verdict"] == "WARN"
    assert all(f["severity"] == "WARNING" for f in rpt["findings"])


def test_disclosure_via_sibling_corner_results(tmp_path: Path):
    """The deck itself has no disclosure prose, but the sibling
    corner_results.json model_disclosure documents the standin -> WARN."""
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE, disclose_sib=True)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0
    assert rpt["verdict"] == "WARN"


def test_skip_no_decks_reaches_the_vacuous_tier(tmp_path: Path):
    """#521 — a lint that read NOTHING must not be credited a plain PASS.

    This test previously asserted rc 0, which is the defect: `[SKIP]` at rc 0
    is indistinguishable from `[PASS]` to `flow_compliance_check`, whose
    `_stdout_signals_vacuous` matches only a line-start `VACUOUS_PASS`. An
    analog-declared project with zero decks was therefore credited a clean
    corner-lib result by a gate that opened no file.
    """
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    r, rpt = _run(tmp_path)
    assert r.returncode == 2
    assert rpt["verdict"] == "SKIP"
    assert "VACUOUS_PASS" in (r.stdout + r.stderr)


# ── vibe-ic#693 regressions ───────────────────────────────────────────────
# The FAIL branch is this lint's whole purpose, and three separate accidents
# silenced it. None had ever been exercised: the lint ran nowhere but this
# file until it was wired at A4.

def test_bare_modeled_in_an_ordinary_comment_is_not_a_disclosure(tmp_path):
    """`_DISCLOSURE_TOKENS` carried the bare word `modeled`, so an ordinary
    remark about channel-length modulation downgraded a silent LEVEL=1
    substitution from FAIL to WARN."""
    deck = ("* toy deck\n"
            "* channel-length modulation is modeled with LAMBDA below\n"
            ".model nm nmos (LEVEL=1 VTO=0.4 KP=70u LAMBDA=0.02)\n")
    _mk_deck(tmp_path, "amp0", deck)
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert rpt["verdict"] == "FAIL"


def test_unrelated_prose_in_sibling_json_is_not_a_disclosure(tmp_path):
    """The sibling check substring-scanned the WHOLE corner_results.json, so
    any document containing `modelled` anywhere silenced the deck beside it.
    Only the structured `model_disclosure` field may disclose."""
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE)
    sib = tmp_path / "phase3" / "analog" / "amp0" / "corner_results.json"
    sib.write_text(json.dumps({"notes": "resistance modelled at 27C"}))
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert rpt["verdict"] == "FAIL"


def test_a_denied_waiver_does_not_silence_the_lint(tmp_path):
    """`_project_waiver` never read a waiver's own status, so a waiver a
    reviewer REFUSED still downgraded every finding project-wide. A blocking
    gate any subject can switch off is a check that lies."""
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE)
    (tmp_path / "waivers.json").write_text(json.dumps({"waivers": [
        {"id": "W1", "topic": "level1", "status": "DENIED",
         "reason": "rejected by reviewer"}]}))
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert rpt["verdict"] == "FAIL"


def test_an_approved_waiver_still_downgrades(tmp_path):
    """The sanctioned escape hatch must keep working."""
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE)
    (tmp_path / "waivers.json").write_text(json.dumps({"waivers": [
        {"id": "W1", "topic": "level1", "status": "APPROVED",
         "reason": "open PDK has no public ngspice corner lib"}]}))
    r, rpt = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert rpt["verdict"] == "WARN"


def test_phase2_analog_layout_is_scanned(tmp_path):
    """A4's own `required_outputs` accepts `phase2/analog/*/...`. Reading only
    `phase3/analog/` made a byte-identical project self-skip and measure
    nothing — a plain PASS from a lint that opened no file."""
    d = tmp_path / "phase2" / "analog" / "amp0"
    d.mkdir(parents=True)
    (d / "amp0.sp").write_text(_LEVEL1_NO_DISCLOSURE)
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert rpt["verdict"] == "FAIL"
