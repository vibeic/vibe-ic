"""v0.2.79 — #437 follow-up comment: SI advisory screen is disclosed,
never laundered into a clean sign-off PASS.

The audited shape: the emitter honestly self-marks its capacitive
(floating-victim) screen as advisory and hardwires violations_count=0,
but the gate read only violations_count (always 0) and reported a
clean PASS — "honest advisory in, sign-off PASS out".

Pins:
  * emitter verdict named ADVISORY_SCREEN_ONLY (source pin);
  * gate surfaces SI_ADVISORY_SCREEN_ONLY (WARNING) + the >0.9
    coupling-dominated watch-list, headline verdict
    ADVISORY_SCREEN_ONLY (rc stays 0 — advisory, not a FAIL);
  * a real SI report (no advisory markers) still gates as before.

chip-AGNOSTIC: structural JSON markers only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import si_crosstalk_check as SI  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


def _proj(tmp_path, payload):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "si_crosstalk.json").write_text(json.dumps(payload))
    return tmp_path


def test_advisory_screen_disclosed(tmp_path):
    _proj(tmp_path, {
        "method": "floating-victim UPPER bound — advisory",
        "max_crosstalk_noise": 1188.0, "violations_count": 0,
        "nets_coupling_dominated_gt0p9": 7,
        "verdict": "ADVISORY_SCREEN_ONLY"})
    findings, stats = SI.audit(tmp_path)
    rep = SI.build_report(findings, stats, str(tmp_path))
    assert rep["verdict"] == "ADVISORY_SCREEN_ONLY"
    assert rep["summary"]["advisory_screen_only"] is True
    assert rep["summary"]["pass"] is True  # advisory: rc 0, but NAMED
    cats = {f["category"] for f in rep["findings"]}
    assert "SI_ADVISORY_SCREEN_ONLY" in cats
    assert "SI_COUPLING_DOMINATED_WATCHLIST" in cats


def test_legacy_screen_verdict_also_detected(tmp_path):
    _proj(tmp_path, {
        "method": "x", "max_crosstalk_noise": 1.0, "violations_count": 0,
        "verdict": "SI_SPEF_SCREEN_PASS"})
    findings, stats = SI.audit(tmp_path)
    assert stats["advisory_screen_only"] is True


def test_real_si_report_plain_pass(tmp_path):
    _proj(tmp_path, {
        "method": "timing-window SI analysis",
        "max_crosstalk_noise": 12.0, "violations_count": 0,
        "verdict": "PASS"})
    findings, stats = SI.audit(tmp_path)
    rep = SI.build_report(findings, stats, str(tmp_path))
    assert rep["verdict"] == "PASS"
    assert not any(f["category"] == "SI_ADVISORY_SCREEN_ONLY"
                   for f in rep["findings"])


def test_emitter_verdict_renamed():
    assert '"verdict": "ADVISORY_SCREEN_ONLY",' in _P3_SRC
    assert '"verdict": "SI_SPEF_SCREEN_PASS"' not in _P3_SRC
