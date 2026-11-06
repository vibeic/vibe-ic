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

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()
_YAML = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()


def _proj(tmp_path, sdc_text, crossings=None, l8=None):
    """`crossings=None` / `l8=None` leave that evidence source ABSENT.

    The two sources are INDEPENDENT: correlation reads step 3's
    `reports/phase2/cdc/crossing.json` AND step D1's
    `phase1/generated_docs/L8_TIMING_WAVEFORM.json`, and a fixture that
    supplies only one is the PARTIAL-evidence case, not the complete one.
    """
    c = tmp_path / "phase2" / "stage2" / "constraints"
    c.mkdir(parents=True)
    (c / "top.sdc").write_text(sdc_text)
    if crossings is not None:
        d = tmp_path / "reports" / "phase2" / "cdc"
        d.mkdir(parents=True)
        (d / "crossing.json").write_text(json.dumps(
            {"crossings": crossings}))
    if l8 is not None:
        d = tmp_path / "phase1" / "generated_docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(l8))
    return tmp_path


def test_yaml_step8_wires_the_screen():
    assert "sdc_exception_correlation_check ." in _YAML


# ── vector power disclosure (source pins) ──────────────────────────────────

def test_power_emitter_uses_vcd_when_present():
    """RE-POINTED, NOT WEAKENED (T91 step 4, 2026-09-26). This anchored on the
    literal `read_power_activities -vcd`. MEASURED in the released image
    (OpenSTA 3.1.0, vibeic-eda 0.3.77) that command is deprecated and raises
    `default is not a mode object`, so every deck carrying it annotated no
    activity. The deck line is now `_ppa.power.activity_read_tcl` (`read_vcd`,
    with `-scope` when step 4 verified one). The property asserted is
    unchanged: the emitter declares vector_vcd exactly when a VCD is used."""
    i = _P3_SRC.index("_ppa_power.activity_read_tcl(")
    window = _P3_SRC[i - 1400:i + 600]
    assert 'analysis_mode = "vector_vcd" if vcd else "vectorless_sdc"' \
        in window
    assert "POWER_ANALYSIS_MODE" in _P3_SRC


def test_power_json_discloses_analysis_mode():
    """AMENDED, NOT WEAKENED (lane icspm5, 2026-09-23).

    This pinned the source literal `"analysis_mode": _mode` inside the
    runner's inline power.json dict. That dict is gone: the record is now
    built by `_ppa.power.signoff_record` and written by
    `_ppa.power.emit_signoff_record`, because
    `test_ppa_runner_extraction_ledger` names `_ppa/power.py` as where the
    logic belongs and the runner as the thing that only orchestrates.

    The QUESTION is unchanged and the answer is now checked one level
    stronger: the source pin remains (the runner must still resolve the mode
    from the transcript's own POWER_ANALYSIS_MODE line and hand it on), and
    a BEHAVIOUR assertion is added beneath it, so a future edit that keeps
    the literal while dropping the field from the emitted document is caught
    here rather than by a reader of the file.
    """
    # The runner still derives the mode from the transcript and passes it on.
    i = _P3_SRC.index("_mode = (\"vector_vcd\" if \"POWER_ANALYSIS_MODE: vector_vcd\"")
    window = _P3_SRC[i - 200:i + 1600]
    assert "vectorless_sdc" in window
    assert "emit_signoff_record" in window, (
        "the runner must hand the resolved mode to the module that owns the "
        "record")

    # And the emitted document actually carries it.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from _ppa import power as _P
    for mode in ("vector_vcd", "vectorless_sdc"):
        rec = _P.signoff_record({"total_row": {"total_w": 1.0,
                                               "total_raw": "1.00e+00"},
                                 "rows": []},
                                source="reports/phase3/power.rpt",
                                analysis_mode=mode)
        assert rec["analysis_mode"] == mode, rec


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
