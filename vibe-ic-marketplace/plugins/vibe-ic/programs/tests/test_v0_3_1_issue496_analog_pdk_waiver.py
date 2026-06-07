"""v0.3.1 — ORGANIC-20260606 #496 (MEDIUM): analog PDK-substitution
waiver path.

The (correct) #438b PDK-mismatch gate now honestly intercepts even the
runner's OWN sizing/netlist decks when the project's L19 declares a target
process with no public ngspice models (so the deck substitutes the
open-source default PDK). Before this fix, the env-unavailable waiver map
carried NO A-steps and the open-source-blocked list excluded A3/A5-A9 → for
ANY non-default-PDK-target analog chip on the open-source path, A3 was
PERMANENTLY unpassable: fabrication forbidden, no waiver, no disclosure
route.

FIX: extend `_ENV_UNAVAILABLE_STEP_NAME_TO_ID` + `_OPEN_SOURCE_CONTAINER_
_BLOCKED_STEPS` with the A-steps under a NAMED pdk-substitution reason,
applicable ONLY when (a) the deck HONESTLY discloses the substitute PDK AND
(b) L19 declares the real target — then the step becomes WAIVED-DEFERRED
(named reason, ticket, review_required, NOT counted as executed-PASS). An
UNDISCLOSED mismatch still hard-FAILs.

ACCEPTANCE (verbatim from the issue):
  build a project fixture shaped like the issue (L19 declares a non-default
  target; sizing deck carries the honest substitute-PDK disclosure) →
  `python3 programs/flow_compliance_check.py <proj> --strict` → A3 =
  WAIVED-DEFERRED with the named pdk-substitution reason, not counted
  executed-PASS; remove the disclosure → A3 hard-FAILs.

chip-AGNOSTIC: this fixture uses ONLY open-standard PDK family tokens
(sky130A / sg13g2 — public open-source / open-PDK process names) and the
structural `pdk_substitution` deck-disclosure marker. No chip / vendor /
SKU literal appears; the block name is the open-vocabulary analog class
``ldo``. None of these tokens are in programs/tests/chip_deny_list.txt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_PLUGIN_ROOT = _THIS.parent.parent.parent          # …/plugins/vibe-ic
_PROG = _PLUGIN_ROOT / "programs" / "flow_compliance_check.py"
sys.path.insert(0, str(_PLUGIN_ROOT / "programs"))
import flow_compliance_check as fc  # noqa: E402


# ── open-standard PDK family tokens (NOT chip/vendor/SKU literals) ──────────
# sky130A is the SkyWater open-source default PDK; sg13g2 is the IHP open-PDK
# 130nm SiGe BiCMOS process — both are public process names that ship with /
# are recognised by the open-source flow. Neither is a chip codename.
_SUBSTITUTE_PDK = "sky130A"        # the open-source default the deck uses
_TARGET_PDK = "sg13g2"             # a non-default target with NO public ngspice models

_DISCLOSURE_LINE = (
    f"* pdk_substitution: target={_TARGET_PDK} substitute={_SUBSTITUTE_PDK} "
    f"reason=no public ngspice models for target; using open-source default\n"
)
_DECK_BODY = (
    ".lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt\n"
    "XM1 out in vdd vdd sky130_fd_pr__pfet_01v8 W=1 L=0.15\n"
    "XM2 out in vss vss sky130_fd_pr__nfet_01v8 W=1 L=0.15\n"
    ".end\n"
)


def _build_fixture(proj: Path, *, disclose: bool) -> None:
    """Construct a project shaped like the issue: an analog IC whose L19
    declares a NON-default target process, whose sizing/netlist decks
    instantiate the open-source default PDK family. When `disclose=True`
    the decks carry the honest `pdk_substitution` disclosure marker.
    """
    # A3 condition trigger — Phase-1 analog block list.
    pa = proj / "phase1" / "analog"
    pa.mkdir(parents=True, exist_ok=True)
    (pa / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"type": "ldo", "name": "ldo0"}]}))

    # L19 declares the REAL non-default target (predicate b).
    g = proj / "phase1" / "generated_docs"
    g.mkdir(parents=True, exist_ok=True)
    (g / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"fields": {"pdk_target": _TARGET_PDK}}))

    deck = (_DISCLOSURE_LINE if disclose else "* analog deck\n") + _DECK_BODY

    # A3 required_outputs / gate files_exist live under phase2/analog.
    p2 = proj / "phase2" / "analog" / "ldo0"
    p2.mkdir(parents=True, exist_ok=True)
    (p2 / "ldo0.sp").write_text(deck)

    # analog_netlist_pdk_check (the #438b gate) + the disclosure helper both
    # scan the canonical analog dir (phase3/analog) — the deck must be there.
    p3 = proj / "phase3" / "analog" / "ldo0"
    p3.mkdir(parents=True, exist_ok=True)
    (p3 / "ldo0.sp").write_text(deck)


def _run_strict(proj: Path) -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, str(_PROG), str(proj), "--strict"],
        capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr


def _a3_block(out: str) -> str:
    """Return the per-step listing block for Step A3 (the status line plus
    its indented reason lines), so assertions read the actual end-state."""
    lines = out.splitlines()
    grabbed: list[str] = []
    capturing = False
    for ln in lines:
        if "Step A3" in ln and ("[" in ln):
            capturing = True
            grabbed.append(ln)
            continue
        if capturing:
            # indented continuation lines belong to A3.
            if ln.startswith("       ") or ln.lstrip().startswith("└"):
                grabbed.append(ln)
            else:
                break
    return "\n".join(grabbed)


# ───────────────────────── unit: disclosure predicate ──────────────────────

def test_disclosed_predicate_true_when_both_halves_hold(tmp_path):
    proj = tmp_path / "chip"
    _build_fixture(proj, disclose=True)
    d = fc._pdk_substitution_disclosed(proj)
    assert d is not None
    assert d["target"].lower() == _TARGET_PDK.lower()
    # detected substitute family is the open-source default token.
    assert "sky130" in d["substitute"].lower()
    assert d["deck"].endswith("ldo0.sp")


def test_disclosed_predicate_none_when_marker_absent(tmp_path):
    proj = tmp_path / "chip"
    _build_fixture(proj, disclose=False)
    assert fc._pdk_substitution_disclosed(proj) is None


def test_disclosed_predicate_none_when_no_l19_target(tmp_path):
    """Predicate (b) requires L19 to declare a concrete real target. A
    disclosed deck with no L19 target gets no auto-waiver (the gate then
    only emits the visible PDK_TARGET_UNDECLARED warning)."""
    proj = tmp_path / "chip"
    _build_fixture(proj, disclose=True)
    (proj / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json").unlink()
    assert fc._pdk_substitution_disclosed(proj) is None


def test_disclosed_predicate_none_when_target_matches_deck(tmp_path):
    """No REAL mismatch (L19 target == deck family) → no deferral synth."""
    proj = tmp_path / "chip"
    _build_fixture(proj, disclose=True)
    (proj / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json"
     ).write_text(json.dumps({"fields": {"pdk_target": _SUBSTITUTE_PDK}}))
    assert fc._pdk_substitution_disclosed(proj) is None


# ───────────────────────── unit: waiver synthesis ──────────────────────────

def test_load_waivers_synthesises_all_affected_a_steps(tmp_path):
    proj = tmp_path / "chip"
    _build_fixture(proj, disclose=True)
    waivers = fc._load_waivers(proj)
    for sid in fc._PDK_SUBSTITUTION_AFFECTED_A_STEPS:
        assert sid in waivers, sid
        w = waivers[sid]
        # mirrors the digital ENV_UNAVAILABLE waiver shape exactly.
        assert w["verdict_tier"] == "ENV_UNAVAILABLE"
        assert w["_env_unavailable"] is True
        assert w["_pdk_substitution"] is True
        assert w["review_required"] is True
        assert w["ticket"] == fc._PDK_SUBSTITUTION_TICKET
        assert w["evidence"]                       # non-empty pointer
        assert "PDK_SUBSTITUTION" in w["reason"]
        assert "not executed-PASS" in w["reason"]


def test_load_waivers_empty_when_undisclosed(tmp_path):
    proj = tmp_path / "chip"
    _build_fixture(proj, disclose=False)
    assert fc._load_waivers(proj) == {}


def test_a_steps_in_env_map_and_os_blocked_list():
    """The A-steps are wired into BOTH the env-unavailable name→id map and
    the open-source-blocked list (the two structures the issue names)."""
    assert set(fc._ENV_UNAVAILABLE_STEP_NAME_TO_ID.values()) >= {
        "A3", "A5", "A7", "A8", "A9"}
    for sid in ("A3", "A5", "A7", "A8", "A9"):
        assert sid in fc._OPEN_SOURCE_CONTAINER_BLOCKED_STEPS


# ───────────────────── ACCEPTANCE (verbatim from the issue) ─────────────────

def test_acceptance_a3_waived_deferred_with_disclosure_then_fail_without(
        tmp_path):
    """`flow_compliance_check.py <proj> --strict` →
       disclosed  : A3 = WAIVED-DEFERRED w/ named pdk-substitution reason,
                    NOT counted executed-PASS;
       undisclosed: A3 hard-FAILs."""
    proj = tmp_path / "chip"

    # ── disclosed → WAIVED-DEFERRED ───────────────────────────────────────
    _build_fixture(proj, disclose=True)
    _, out = _run_strict(proj)
    a3 = _a3_block(out)
    assert "WAIVED-DEFERRED" in a3, out
    assert "pdk-substitution" in a3.lower() or "PDK_SUBSTITUTION" in a3
    assert fc._PDK_SUBSTITUTION_TICKET in a3
    assert "review_required=True" in a3
    # NOT counted as executed-PASS: A3 status is not PASS, and the deferral
    # reason says so explicitly.
    assert "[PASS" not in a3
    assert "not executed-PASS" in a3
    # the named target + substitute appear so the reason is honest.
    assert _TARGET_PDK in a3

    # ── remove the disclosure → A3 hard-FAILs ─────────────────────────────
    # Strip the marker line from BOTH decks (predicate a fails).
    for rel in ("phase2/analog/ldo0/ldo0.sp", "phase3/analog/ldo0/ldo0.sp"):
        p = proj / rel
        kept = [l for l in p.read_text().splitlines()
                if "pdk_substitution" not in l]
        p.write_text("\n".join(kept) + "\n")

    _, out2 = _run_strict(proj)
    a3_2 = _a3_block(out2)
    assert "[FAIL" in a3_2, out2
    assert "WAIVED" not in a3_2


def test_acceptance_undisclosed_no_a3_waiver_in_listing(tmp_path):
    """Cross-check the negative branch from a fresh fixture: an UNDISCLOSED
    mismatch yields no A3 deferral anywhere in the strict listing."""
    proj = tmp_path / "chip"
    _build_fixture(proj, disclose=False)
    _, out = _run_strict(proj)
    a3 = _a3_block(out)
    assert "[FAIL" in a3, out
    assert "WAIVED-DEFERRED" not in a3
