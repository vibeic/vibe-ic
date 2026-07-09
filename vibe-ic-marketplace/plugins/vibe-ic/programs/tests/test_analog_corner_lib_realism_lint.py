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


def test_skip_no_decks(tmp_path: Path):
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    r, rpt = _run(tmp_path)
    assert r.returncode == 0
    assert rpt["verdict"] == "SKIP"
