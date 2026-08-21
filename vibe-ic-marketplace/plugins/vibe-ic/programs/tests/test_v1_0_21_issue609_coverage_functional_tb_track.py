"""ORGANIC #609 [MEDIUM] — the coverage_actual.json producer emitted a PASS
verdict for only two TB tracks (a reference_tb ref_tb.log, or an oracle.log);
its else-branch wrote verdict=SKIPPED-CONDITION. When the named AI fallback
(testbench-author) authors a self-checking functional TB at the conventional
sim/ path that GENUINELY PASSES (JUnit sim/results.xml tests=1 failures=0) AND
l10_tb_conformance reports N/N, the producer never recognised that path, so
coverage_actual.json stayed SKIPPED-CONDITION and flow_compliance Step 4 (which
keys solely off coverage_actual.json via #433c) hid a real, verified functional
PASS as SKIPPED-CONDITION (excluded from executed-PASS).

OBSERVED (a minimal RISC-V SoC): coverage_actual.json = SKIPPED-CONDITION
(written 00:27:33) while sim/results.xml = testsuite tests=1 failures=0 testcase
blinky_gpio_toggle (00:36:21, AFTER the stale stub) + l10_tb_conformance total
10 ok 10 fail 0.

Fix: a THIRD evidence track — recognise a genuinely-passing authored functional
TB (JUnit failures=0/errors=0, tests>=1 + l10 ok==total>0) as a real PASS, both
in the producer's else-branch AND via an idempotent late re-emit in phase3
step_canonicalize_artefacts (the producer runs BEFORE the AI TB).

POSITIVE (#609): a stale SKIPPED-CONDITION stub + a passing functional TB +
l10 10/10 → upgraded to verdict=PASS, scenarios from the TB's OWN testcase
names (#436: never a canned cross-design list).

NEGATIVE no-leak (honesty — only a real failures=0, non-vacuous transcript
upgrades):
  - a failing TB (failures>=1) → NOT upgraded.
  - a vacuous TB (tests=0) → NOT upgraded.
  - l10 incomplete (ok<total) or absent → NOT upgraded.
  - idempotent: an already-PASS coverage is a no-op.

chip-AGNOSTIC: JUnit/l10 structural fields + the TB's own scenario names.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import design_one_shot_runner as P  # noqa: E402

PASS_XML = ('<testsuite name="func" tests="1" failures="0" errors="0">'
            '<testcase name="blinky_gpio_toggle"/></testsuite>\n')
L10_OK = {"total": 10, "ok": 10, "fail": 0}
STALE = {"verdict": "SKIPPED-CONDITION",
         "reason": "no reference-TB transcript for THIS project — (#436)"}


def _mk(tmp_path, results_xml=None, l10=None, cov=None):
    if results_xml is not None:
        d = tmp_path / "phase2" / "stage1" / "sim"
        d.mkdir(parents=True)
        (d / "results.xml").write_text(results_xml)
    if l10 is not None:
        d = tmp_path / "reports" / "phase2" / "gates"
        d.mkdir(parents=True)
        (d / "l10_tb_conformance.json").write_text(json.dumps(l10))
    if cov is not None:
        d = tmp_path / "reports" / "phase2" / "coverage"
        d.mkdir(parents=True)
        (d / "coverage_actual.json").write_text(json.dumps(cov))
    return tmp_path


def _cov(tmp_path):
    return json.loads(
        (tmp_path / "reports/phase2/coverage/coverage_actual.json").read_text())


def test_payload_recognised_with_real_evidence(tmp_path):
    _mk(tmp_path, PASS_XML, L10_OK)
    payload = P._v1_6_609_functional_tb_pass_payload(tmp_path)
    assert payload is not None
    assert payload["verdict"] == "PASS"
    assert payload["verification_track"] == "authored_functional_tb"
    assert payload["scenarios_covered"] == ["blinky_gpio_toggle"]  # TB's own name
    assert payload["l10_conformance"] == {"ok": 10, "total": 10}


def test_upgrade_stale_skipped_condition_to_pass(tmp_path):
    _mk(tmp_path, PASS_XML, L10_OK, STALE)
    assert P._v1_6_609_upgrade_coverage_from_functional_tb(tmp_path) is True
    assert _cov(tmp_path)["verdict"] == "PASS"


def test_failing_tb_not_upgraded(tmp_path):
    _mk(tmp_path, '<testsuite tests="2" failures="1"><testcase name="x"/></testsuite>',
        L10_OK, STALE)
    assert P._v1_6_609_upgrade_coverage_from_functional_tb(tmp_path) is False
    assert _cov(tmp_path)["verdict"] == "SKIPPED-CONDITION"


def test_vacuous_tb_not_upgraded(tmp_path):
    _mk(tmp_path, '<testsuite tests="0" failures="0"></testsuite>', L10_OK, STALE)
    assert P._v1_6_609_upgrade_coverage_from_functional_tb(tmp_path) is False


def test_l10_incomplete_not_upgraded(tmp_path):
    _mk(tmp_path, PASS_XML, {"total": 10, "ok": 7, "fail": 3}, STALE)
    assert P._v1_6_609_upgrade_coverage_from_functional_tb(tmp_path) is False


def test_no_l10_not_upgraded(tmp_path):
    _mk(tmp_path, PASS_XML, None, STALE)
    assert P._v1_6_609_upgrade_coverage_from_functional_tb(tmp_path) is False


def test_idempotent_already_pass(tmp_path):
    _mk(tmp_path, PASS_XML, L10_OK, {"verdict": "PASS"})
    assert P._v1_6_609_upgrade_coverage_from_functional_tb(tmp_path) is False


def test_producer_shape_results_not_mistaken_for_junit(tmp_path):
    # the producer's own `<results><verdict>` shape is NOT a JUnit testsuite —
    # it must not be read as a passing functional TB.
    _mk(tmp_path, "<results><verdict>PASS</verdict></results>\n", L10_OK, STALE)
    assert P._v1_6_609_functional_tb_pass_payload(tmp_path) is None
