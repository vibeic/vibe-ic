"""B2/#175 + B1/#174 — ASAP7 sign-off-asset registry wiring (vibeic-eda >=0.2.24).

B2 (rcx/SPEF) — the ORFS asap7 platform ships an OpenRCX extraction model
(`rcx_patterns.rules`, header "Extraction Rules for OpenRCX", the `-ext_model_file`
consumed by `extract_parasitics`). The image now stages it at
`libs.tech/librelane/rules.openrcx.asap7.nom` — the SAME captable-glob convention the
phase3 runner already uses for sky130A/gf180. This test pins the registry pointer AND
proves the staged basename actually MATCHES the runner's live captable glob
(`libs.tech/{librelane,openlane}/rules.openrcx.*.nom[.magic]`), so the runner will
DISCOVER the file → real captable-based SPEF (not the tech-LEF-RC fallback). If the
runner's glob convention ever drifts, this test catches the divergence.

B1 (device-LVS) — asap7 device-level LVS is a DISCLOSED capability gap: KLayout ships
only planar MOS device extractors (no FinFET recognition) AND the staged asap7 platform
ships no transistor-level CDL/SPICE netlist, so `lvs_deck` stays null with a documented
rationale. This test guards that the defer stays honestly disclosed (null + comment),
not silently dropped or fabricated.

All assertions are deterministic (registry JSON + runner source text) — no container.
"""
import fnmatch
import json
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

REGISTRY = PROG / "pdk_registry.json"
RUNNER_SRC = (PROG / "phase3_one_shot_runner.py").read_text()

# The runner's captable-glob convention (must stay in sync with _emit_spef /
# _postroute_repair_estimate_tcl / _discover_openrcx_captables). We assert the runner
# STILL globs this shape so the staged asap7 asset below is guaranteed discoverable.
_CAPTABLE_DIR_GLOB = "libs.tech/{librelane,openlane}"
_CAPTABLE_NOM_PATTERNS = ("rules.openrcx.*.nom.magic", "rules.openrcx.*.nom")


def _asap7_entry():
    reg = json.loads(REGISTRY.read_text())
    entry = next((p for p in reg["pdks"] if p.get("name") == "asap7"), None)
    assert entry is not None, "asap7 must be registered in pdk_registry.json"
    return entry


def test_asap7_rcx_rules_pointer_present_at_librelane_convention():
    a = _asap7_entry()
    rcx = a.get("rcx_rules")
    assert rcx == "libs.tech/librelane/rules.openrcx.asap7.nom", (
        f"asap7 rcx_rules must point at the librelane captable-glob convention, got {rcx!r}"
    )
    assert a.get("_rcx_rules_comment"), "rcx_rules must carry a documenting comment"


def test_asap7_staged_captable_matches_runner_glob():
    """The staged basename MUST match one of the runner's live nom-captable glob
    patterns, so _emit_spef's glob will find it and extract a real SPEF."""
    a = _asap7_entry()
    rcx = a["rcx_rules"]
    bn = rcx.split("/")[-1]
    assert any(fnmatch.fnmatch(bn, pat) for pat in _CAPTABLE_NOM_PATTERNS), (
        f"staged captable {bn!r} does not match the runner nom-glob "
        f"{_CAPTABLE_NOM_PATTERNS!r} → runner would NOT discover it"
    )
    # The staged dir must be one of the two dirs the runner globs (librelane preferred).
    parent = "/".join(rcx.split("/")[:-1])  # libs.tech/librelane
    assert parent in ("libs.tech/librelane", "libs.tech/openlane"), (
        f"asap7 captable must live under a runner-globbed dir, got {parent!r}"
    )


def test_runner_still_globs_the_captable_convention_we_staged_against():
    """Guard the load-bearing assumption: the runner still globs
    libs.tech/{librelane,openlane}/rules.openrcx.*.nom[.magic]. If this drifts the
    staged asap7 asset would silently stop being found."""
    assert _CAPTABLE_DIR_GLOB in RUNNER_SRC, (
        "runner no longer globs libs.tech/{librelane,openlane} — asap7 captable path "
        "convention drifted; re-check the staging path in the Dockerfile"
    )
    assert "rules.openrcx.*.nom" in RUNNER_SRC, (
        "runner no longer globs rules.openrcx.*.nom — asap7 captable name convention drifted"
    )


def test_asap7_lvs_deck_deferred_and_disclosed():
    """B1/#174 — device-LVS stays null WITH a documented defer rationale (never a
    fabricated pass, never a silent drop)."""
    a = _asap7_entry()
    assert a.get("lvs_deck") is None, "asap7 lvs_deck must remain null (B1 defer)"
    comment = a.get("_lvs_deck_comment", "")
    assert comment, "asap7 must document WHY lvs_deck is null (B1 defer rationale)"
    low = comment.lower()
    assert "finfet" in low, "B1 defer rationale must cite the FinFET device-recognition blocker"
    assert "lec" in low, "B1 defer rationale must note LEC covers logical equivalence"


def test_asap7_comment_reflects_captable_now_ships():
    a = _asap7_entry()
    c = a.get("_comment", "").lower()
    assert "openrcx" in c or "rcx_patterns" in c, (
        "asap7 _comment should note the OpenRCX extraction model now ships (B2)"
    )
