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


def test_no_decks_is_vacuous_not_a_pass(tmp_path: Path):
    """#521 — this assertion used to read `returncode == 0`.

    A scan that read no deck examined nothing, and rc 0 puts it in the plain
    PASS tier beside a project whose every deck was read and cleared. The
    tier is decided PURELY by the exit code (`flow_compliance_check`
    `_check_program_exit_zero`), so the `[SKIP]` word printed alongside it
    changed nothing that any consumer reads.
    """
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    r, rpt = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert rpt["verdict"] == "SKIP"
    assert "VACUOUS_PASS" in (r.stdout + r.stderr)


# ── REGRESSIONS: five wrong answers measured the first time this lint was
#    handed trees that tried to abuse its disclosure path. Three of them
#    turn the FAIL branch off; two of them mean it never reads the decks.


def test_an_ordinary_english_word_does_not_disclose(tmp_path: Path):
    """`_DISCLOSURE_TOKENS` carried the bare word `modeled`, so this comment
    — which discloses nothing — downgraded a SILENT substitution to WARN."""
    deck = _LEVEL1_NO_DISCLOSURE.replace(
        "* toy deck",
        "* toy deck\n* channel-length modulation is modeled with LAMBDA below")
    _mk_deck(tmp_path, "amp0", deck)
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert rpt["verdict"] == "FAIL"


def test_incidental_word_in_sibling_json_does_not_disclose(tmp_path: Path):
    """The sibling channel scanned the WHOLE artefact, so a disclosure word
    anywhere in `corner_results.json` — here in an unrelated note — silenced
    the finding. Disclosure is what a document files under a disclosure key."""
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE)
    (tmp_path / "phase3" / "analog" / "amp0" / "corner_results.json").write_text(
        json.dumps({"block": "amp0", "total_corners": 9,
                    "note": "SC integrator settle modelled at 27C"}))
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert rpt["verdict"] == "FAIL"


def test_a_denied_waiver_silences_nothing(tmp_path: Path):
    """`_project_waiver` substring-matched the raw text of waivers.json and
    never read a waiver's STATUS, so the RECORD OF A REFUSAL disabled the
    check project-wide."""
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE)
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"waivers": [{"id": "W-1", "rule": "level1", "status": "DENIED",
                      "note": "LEVEL=1 standin waiver requested; REJECTED"}]}))
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert rpt["verdict"] == "FAIL"


def test_a_live_waiver_still_downgrades(tmp_path: Path):
    """The other direction of the same repair: an approved waiver must keep
    working, or the fix would just be a stricter gate with no seam."""
    _mk_deck(tmp_path, "amp0", _LEVEL1_NO_DISCLOSURE)
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"waivers": [{"id": "W-1", "rule": "corner_lib_level1",
                      "status": "APPROVED",
                      "note": "documented standin approved by the owner"}]}))
    r, rpt = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert rpt["verdict"] == "WARN"


def test_phase2_analog_layout_is_read(tmp_path: Path):
    """The scan read only `phase3/analog/`, while A4's own `required_outputs`
    accepts `phase2/analog/*/corner_results.json`. A byte-identical project
    laid out there had its decks read by nobody and was credited a PASS."""
    d = tmp_path / "phase2" / "analog" / "amp0"
    d.mkdir(parents=True)
    (d / "amp0.sp").write_text(_LEVEL1_NO_DISCLOSURE)
    r, rpt = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert rpt["verdict"] == "FAIL"
    assert "phase2/analog" in rpt["roots_scanned"], rpt
