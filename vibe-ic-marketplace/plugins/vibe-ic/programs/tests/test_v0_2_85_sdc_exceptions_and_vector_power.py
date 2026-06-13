"""v0.2.85 — P2 capabilities: SDC exception correlation (advisory) +
vector-based power disclosure.

Pins:
  * sdc_exception_correlation_check — false_path without a matching
    CDC/L8 async relation → SDC_EXCEPTION_UNJUSTIFIED; bare-wildcard
    scope → SDC_EXCEPTION_TOO_BROAD; multicycle > 4 →
    SDC_MULTICYCLE_SUSPECT; justified exceptions stay clean; always
    rc 0 (advisory, never blocks); no SDC → rc 2;
  * runner power emitter: a present sim VCD switches OpenSTA to
    read_power_activities (vector mode) and the chosen
    `analysis_mode` is disclosed in power.json (source pins).

chip-AGNOSTIC: SDC text + structural fixtures.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sdc_exception_correlation_check as SEC  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()
_YAML = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()


def _proj(tmp_path, sdc_text, crossings=None):
    c = tmp_path / "phase2" / "stage2" / "constraints"
    c.mkdir(parents=True)
    (c / "top.sdc").write_text(sdc_text)
    if crossings is not None:
        d = tmp_path / "reports" / "phase2" / "cdc"
        d.mkdir(parents=True)
        (d / "crossing.json").write_text(json.dumps(
            {"crossings": crossings}))
    return tmp_path


def test_unjustified_false_path_flagged(tmp_path):
    p = _proj(tmp_path,
              "set_false_path -from [get_clocks clkA] -to [get_clocks clkB]\n",
              crossings=[])
    rep = SEC.audit(p)
    assert rep["rc"] == 0 and rep["verdict"] == "REVIEW"
    assert any(f["category"] == "SDC_EXCEPTION_UNJUSTIFIED"
               for f in rep["findings"])


def test_cdc_justified_false_path_clean(tmp_path):
    p = _proj(tmp_path,
              "set_false_path -from [get_clocks clkA] -to [get_clocks clkB]\n",
              crossings=[{"from_clock": "clkA", "to_clock": "clkB"}])
    rep = SEC.audit(p)
    assert rep["verdict"] == "PASS"
    assert not rep["findings"]


def test_bare_wildcard_scope_flagged(tmp_path):
    p = _proj(tmp_path, "set_false_path -from {*} -to [get_clocks clkB]\n")
    rep = SEC.audit(p)
    assert any(f["category"] == "SDC_EXCEPTION_TOO_BROAD"
               for f in rep["findings"])


def test_large_multicycle_flagged(tmp_path):
    p = _proj(tmp_path,
              "set_multicycle_path 8 -setup -from [get_clocks clkA]\n")
    rep = SEC.audit(p)
    assert any(f["category"] == "SDC_MULTICYCLE_SUSPECT"
               for f in rep["findings"])
    assert rep["multicycle_paths"] == 1


def test_sane_multicycle_clean(tmp_path):
    p = _proj(tmp_path,
              "set_multicycle_path 2 -setup -from [get_clocks clkA] "
              "-to [get_clocks clkA]\n")
    rep = SEC.audit(p)
    assert rep["verdict"] == "PASS"


def test_no_sdc_is_vacuous(tmp_path):
    assert SEC.audit(tmp_path)["rc"] == 2


def test_yaml_step8_wires_the_screen():
    assert "sdc_exception_correlation_check ." in _YAML


# ── vector power disclosure (source pins) ──────────────────────────────────

def test_power_emitter_uses_vcd_when_present():
    i = _P3_SRC.index("read_power_activities -vcd")
    window = _P3_SRC[i - 1400:i + 600]
    assert 'analysis_mode = "vector_vcd" if vcd else "vectorless_sdc"' \
        in window
    assert "POWER_ANALYSIS_MODE" in _P3_SRC


def test_power_json_discloses_analysis_mode():
    i = _P3_SRC.index('"analysis_mode": _mode')
    window = _P3_SRC[i - 800:i + 400]
    assert "POWER_ANALYSIS_MODE: vector_vcd" in window
    assert "vectorless_sdc" in window
