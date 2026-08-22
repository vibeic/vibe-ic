"""ORGANIC #676 — phantom `por` analog block from the digital "POR" substring,
and 3 analog P0 gates that ignore analog_applicable=false on a pure-digital SoC.

Two independent chip-AGNOSTIC surfaces, both fixed:
  (i)  the Phase-1 L5 analog-block extractor must NOT fabricate an analog `por`
       block from a digital-reset / GPIO-default phrase ("GPIO POR config")
       even when an incidental supply voltage ("1.8 V supply") sits within the
       ±200-char analog-context window. The `por` (power-on-reset / brownout)
       class needs a RESET-SPECIFIC analog cue (trip / threshold voltage /
       brown-out detector / hysteresis) before emitting a block.
  (ii) analog_flow_compliance_check / analog_digital_interface_check /
       analog_a6_block_pv_check must honor the class-N/A predicate the sibling
       analog gates already honor — SKIP (N/A) on a non-analog IC whose only
       blocks are low_confidence phantom keyword hits, instead of hard-FAILing.

§4.05 NEGATIVE no-leak (critical):
  (i)  a REAL analog POR (brown-out detector + POR trip voltage + hysteresis)
       is STILL emitted as a `por` block;
  (ii) a REAL analog IC (has_analog:true) or a confident (spec-backed) block is
       STILL gated A1-A9 — never skipped.

chip-AGNOSTIC: reset-vocabulary structure + IC-class verdict + per-block
low_confidence tag; no chip / vendor / class literal.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import phase1_doc_one_shot_runner as P  # noqa: E402
import _analog_a_check_common as AAC  # noqa: E402
import analog_flow_compliance_check as AFC  # noqa: E402
import analog_digital_interface_check as ADI  # noqa: E402
import analog_a6_block_pv_check as A6  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────
def _phase1_project(tmp_path, l5_text: str):
    docs_dir = tmp_path / "input" / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "L5.md").write_text(l5_text)
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    return {"L5.md": l5_text}


def _l5_blocks(tmp_path, docs):
    res = P.gen_l5_adi_spec(tmp_path, docs)
    l5 = json.loads((tmp_path / res.path).read_text())
    return [b.get("name") for b in l5.get("analog_blocks", [])]


# the caravel round-5 trigger: a digital port table with a "1.8 V supply" row a
# few lines above a "GPIO POR config" phrase.
_CARAVEL_DIGITAL_L5 = (
    "# L3 — External Interface\n\n"
    "| Port | Dir | Width | Description |\n"
    "| `analog_io` | inout | 29 | Analog I/O (unused by this design) |\n"
    "| `vccd1`/`vssd1` | inout | 1 | User area 1 1.8 V supply / ground |\n\n"
    "The example block consumes `io_*[37:0]` mapped down to `BITS`; upper/"
    "unused bits\nare tied per `user_defines.v` GPIO POR config.\n"
)

_REAL_ANALOG_POR_L5 = (
    "# Analog Blocks\n\n"
    "The brown-out detector (BOD) provides power-on-reset (POR): it asserts "
    "reset when\nthe 1.8 V analog supply droops below the POR trip voltage of "
    "1.62 V, with 50 mV\nhysteresis. The detector monitors Vdd continuously.\n"
)


# ── (i) extractor: phantom por suppressed / real por kept ───────────────────
def test_extractor_suppresses_phantom_por_on_digital_soc(tmp_path):
    docs = _phase1_project(tmp_path, _CARAVEL_DIGITAL_L5)
    names = _l5_blocks(tmp_path, docs)
    assert "por" not in names, names


def test_extractor_keeps_real_analog_por(tmp_path):
    """§4.05 no-leak: a real analog POR (brown-out detector + trip voltage +
    hysteresis) is STILL extracted as a `por` block."""
    docs = _phase1_project(tmp_path, _REAL_ANALOG_POR_L5)
    names = _l5_blocks(tmp_path, docs)
    assert "por" in names, names


def test_por_digital_reset_predicate():
    assert P._v676_por_is_digital_reset(
        "tied per user_defines.v GPIO POR config; 1.8 V supply") is True
    assert P._v676_por_is_digital_reset(
        "POR trip voltage 1.62 V brown-out detector hysteresis") is False


# ── (ii) class-N/A predicate ────────────────────────────────────────────────
def _setup_class(tmp_path, ic_class_json, blocks):
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "ic_class.json").write_text(
        json.dumps(ic_class_json))
    (tmp_path / "phase3" / "analog").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def test_class_na_digital_phantom_block(tmp_path):
    _setup_class(tmp_path, {"ic_class": "bus_peripheral", "has_analog": False},
                 [{"name": "por", "low_confidence": True}])
    assert AAC.analog_class_is_na(tmp_path) is True


def test_class_na_false_for_real_analog_ic(tmp_path):
    """§4.05 no-leak: a real analog IC is NEVER skipped."""
    _setup_class(tmp_path,
                 {"ic_class": "pure_analog", "has_analog": True,
                  "is_pure_analog": True},
                 [{"name": "por", "low_confidence": True}])
    assert AAC.analog_class_is_na(tmp_path) is False


def test_class_na_false_for_confident_block(tmp_path):
    """§4.05 no-leak: a confident (spec-backed) block is still gated even on a
    digital-ish class."""
    _setup_class(tmp_path, {"ic_class": "bus_peripheral", "has_analog": False},
                 [{"name": "ldo", "low_confidence": False}])
    assert AAC.analog_class_is_na(tmp_path) is False


def test_class_na_false_when_no_class_verdict(tmp_path):
    """§4.05 no-leak: fail-closed — no ic_class.json → NOT skipped."""
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "por", "low_confidence": True}]}))
    assert AAC.analog_class_is_na(tmp_path) is False


# ── (ii) the 3 P0 gates SKIP on a digital SoC, FAIL/gate on a real one ───────
def test_three_p0_gates_skip_on_digital_soc(tmp_path):
    _setup_class(tmp_path, {"ic_class": "bus_peripheral", "has_analog": False},
                 [{"name": "por", "low_confidence": True}])
    afc = AFC.run_audit(tmp_path)
    assert afc.summary.get("skipped") is True, afc.summary
    # #511 — the class-N/A skip is a DISCLOSED skip, not a PASS: zero A-step
    # obligations were held to the rule, so `passed` (which means "the rule was
    # applied and found nothing wrong") is False and `verdict` carries the
    # tier. It is emphatically not a FAIL — no ERROR finding is emitted, and
    # the CLI exits on the skip tier, which the sibling assertions below pin.
    assert afc.verdict == "VACUOUS_PASS", afc.summary
    assert not [f for f in afc.findings if f.severity == "ERROR"]
    assert AFC.main([str(tmp_path), "--json", str(tmp_path / "afc.json")]) == 2
    adi = ADI.run_audit(tmp_path)
    assert adi.summary.get("skipped") is True, adi.summary
    assert adi.passed is True
    rc = A6.main([str(tmp_path), "--json", str(tmp_path / "a6.json")])
    assert rc == 2, rc  # SKIP


def test_three_p0_gates_still_fail_real_analog_ic(tmp_path):
    """§4.05 no-leak: a real analog IC with a confident block but no A4-A9
    artefacts is STILL FAILed (not skipped) by all 3 gates."""
    _setup_class(tmp_path,
                 {"ic_class": "pure_analog", "has_analog": True,
                  "is_pure_analog": True},
                 [{"name": "ldo", "low_confidence": False}])
    afc = AFC.run_audit(tmp_path)
    assert afc.summary.get("skipped") is not True
    assert afc.passed is False, afc.summary  # A4..A9 missing → FAIL
    rc = A6.main([str(tmp_path), "--json", str(tmp_path / "a6.json")])
    assert rc == 1, rc  # FAIL (per-block PV missing)
