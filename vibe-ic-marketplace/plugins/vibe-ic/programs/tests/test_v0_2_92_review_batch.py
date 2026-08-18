"""v0.2.92 — second external-review refinement batch (two reviewer
feedbacks on flow v2.3.1, verified against the codebase).

Pins:
  * A3: every MANUAL_REVIEW PERC category carries `review_criteria`
    (reviewer_role + quantitative_criteria naming PDK/foundry limits,
    record_to pointing back at the checklist) — answers the reviewer's
    "who reviews / against what" gap WITHOUT inventing numbers;
  * the criteria reference PDK/foundry limit NAMES (Jmax tables, P2P
    discharge-path limit, max-tap-distance, Vhold>Vdd, L21 contract),
    never fabricated numeric thresholds;
  * doc coverage guard globs the version-named ALL_STEPS docs (separate test file).
"""
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


def _window(anchor: str, before: int = 200, after: int = 1400) -> str:
    i = _P3_SRC.index(anchor)
    return _P3_SRC[i - before:i + after]


def test_esd_manual_review_has_review_criteria():
    w = _window('esd_cat["review_criteria"]')
    assert "reviewer_role" in w
    assert "quantitative_criteria" in w
    # criteria NAME the limits, not numbers
    assert "Jmax" in w
    assert "P2P" in w or "point-to-point" in w
    assert "record_to" in w


def test_latchup_manual_review_has_review_criteria():
    i = _P3_SRC.index("Latch-up / well-tap (spacing + device-physics)")
    w = _P3_SRC[i:i + 2500]
    assert '"review_criteria"' in w
    assert "max-tap-distance" in w
    assert "Vhold > Vdd" in w


def test_xdomain_manual_review_has_review_criteria():
    w = _window('xdomain_cat["review_criteria"]')
    assert "L21" in w
    assert "level-shifter direction" in w
    assert "isolation clamp value" in w


def test_review_criteria_never_auto_signed():
    # the reviewer_role text must exclude the authoring agent on ALL three.
    n = _P3_SRC.count("never the authoring agent")
    assert n >= 3, f"expected >=3 reviewer_role guards, found {n}"


def test_no_fabricated_numeric_thresholds_in_criteria():
    # quantitative_criteria blocks must not embed invented numeric limits
    # (units like ohm/V/mA with literal numbers) — they reference named
    # PDK/foundry tables instead. Allow cell-name-ish tokens (HBM/CDM).
    for m in re.finditer(r'"quantitative_criteria": \[(.*?)\]',
                         _P3_SRC, re.DOTALL):
        block = m.group(1)
        assert not re.search(r"\d+(?:\.\d+)?\s*(?:ohm|Ω|mA|µV|uV|V\b)",
                             block), block[:200]


_YAML = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()


def test_yaml_step8_wires_derived_clock_check():
    # B-1: the ICG / register-divided-clock SDC guard is WIRED into the
    # Step-8 gate (optional, vacuous-PASS when no derived clock), not
    # just name-dropped in the docs.
    assert ("derived_clock_sdc_required_check phase2/stage1/rtl "
            "--sdc phase2/stage2/constraints") in _YAML
    import yaml as _y
    data = _y.safe_load(_YAML)
    step8 = next(s for s in data["steps"] if s.get("id") == 8)
    assert "derived_clock_sdc_required_check" in step8.get("programs", [])
