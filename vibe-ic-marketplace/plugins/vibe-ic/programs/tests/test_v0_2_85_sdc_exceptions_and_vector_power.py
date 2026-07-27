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


# ===========================================================================
# d5 — the CDC evidence step 8 correlates against belongs to STEP 3, and step 8
# must both DEPEND on it and SAY when it could not read it.
#
# `_known_async_pairs` read reports/phase2/cdc/crossing.json under a bare
# `except (OSError, ValueError): pass`, so an ABSENT or corrupt report produced
# an EMPTY known-async set and every legitimate CDC false_path was then reported
# SDC_EXCEPTION_UNJUSTIFIED — a verdict about the SDC attributed to a file the
# checker never opened. And step 8 declared `blocks_on: [7]`, whose closure
# {7, 1, D1} does not reach step 3, so on a resumed project the report it did
# read could be the PREVIOUS run's.
# ===========================================================================


def test_d5_absent_cdc_evidence_is_disclosed_not_silently_empty(tmp_path):
    """THE d5 DISCRIMINATOR. No crossing.json, no L8: the report must say so
    per source, and the per-exception finding must be UNVERIFIABLE, not
    UNJUSTIFIED."""
    p = _proj(tmp_path,
              "set_false_path -from [get_clocks clkA] -to [get_clocks clkB]\n")
    rep = SEC.audit(p)
    assert rep["correlation_evidence_read"] == [], rep
    assert rep["correlation_evidence"][
        "reports/phase2/cdc/crossing.json"] == "ABSENT", rep
    cats = {f["category"] for f in rep["findings"]}
    assert "SDC_EXCEPTION_EVIDENCE_UNREAD" in cats, rep
    assert "SDC_EXCEPTION_UNVERIFIABLE" in cats, rep
    assert "SDC_EXCEPTION_UNJUSTIFIED" not in cats, rep


def test_d5_corrupt_cdc_evidence_is_disclosed_as_unreadable(tmp_path):
    """A corrupt crossing.json is not "no crossings" either."""
    p = _proj(tmp_path,
              "set_false_path -from [get_clocks clkA] -to [get_clocks clkB]\n",
              crossings=[])
    (p / "reports" / "phase2" / "cdc" / "crossing.json").write_text("{not json")
    rep = SEC.audit(p)
    assert rep["correlation_evidence"][
        "reports/phase2/cdc/crossing.json"].startswith("UNREADABLE"), rep
    assert "SDC_EXCEPTION_EVIDENCE_UNREAD" in {
        f["category"] for f in rep["findings"]}, rep


def test_d5_direction1_present_evidence_still_says_unjustified(tmp_path):
    """DIRECTION-1 GUARD. When the CDC report IS readable and genuinely
    declares no matching crossing, the finding must stay UNJUSTIFIED — the
    disclosure must not soften a real one."""
    p = _proj(tmp_path,
              "set_false_path -from [get_clocks clkA] -to [get_clocks clkB]\n",
              crossings=[{"from_clock": "clkX", "to_clock": "clkY"}])
    rep = SEC.audit(p)
    assert rep["correlation_evidence_read"] == [
        "reports/phase2/cdc/crossing.json"], rep
    cats = {f["category"] for f in rep["findings"]}
    assert "SDC_EXCEPTION_UNJUSTIFIED" in cats, rep
    assert "SDC_EXCEPTION_EVIDENCE_UNREAD" not in cats, rep


def test_d5_step8_declares_the_edge_to_the_producer_of_crossing_json():
    """The flow-side half. Step 8's gate reads step 3's declared
    `reports/phase2/cdc/crossing.json`, so 3 must be in step 8's blocks_on
    closure — otherwise step 8 can be marked done before step 3 ever ran and
    the read silently picks up a PREVIOUS run's report."""
    import yaml
    steps = {str(s["id"]): s
             for s in yaml.safe_load(_YAML)["steps"]}
    assert "reports/phase2/cdc/crossing.json" in (
        steps["3"]["required_outputs"])

    graph = {sid: [str(e) for e in (s.get("blocks_on") or [])]
             for sid, s in steps.items()}
    closure, queue = set(), list(graph["8"])
    while queue:
        n = queue.pop()
        if n in closure:
            continue
        closure.add(n)
        queue.extend(graph.get(n, []))
    assert "3" in closure, (graph["8"], sorted(closure))
    # and the edge must be BACKWARD (declaration order is the evaluation
    # order), so it can actually cut step 8's cascade.
    order = [str(s["id"]) for s in yaml.safe_load(_YAML)["steps"]]
    assert order.index("3") < order.index("8")
