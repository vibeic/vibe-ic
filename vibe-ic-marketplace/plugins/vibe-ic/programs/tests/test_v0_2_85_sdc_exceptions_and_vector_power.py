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
    """DIRECTION-1 GUARD. When BOTH sources are readable and neither declares
    a matching async relation, the finding must stay UNJUSTIFIED with NO
    disclosure — the disclosure must not soften a real one.

    Note the fixture supplies `l8` as well. An earlier revision of this guard
    passed only `crossings=` and asserted no disclosure; that fixture is the
    PARTIAL case, and it passed only because the disclosure was wrongly gated
    on `not evidence_read` — see
    `test_d5_partial_evidence_is_disclosed_and_the_claim_is_bounded`."""
    p = _proj(tmp_path,
              "set_false_path -from [get_clocks clkA] -to [get_clocks clkB]\n",
              crossings=[{"from_clock": "clkX", "to_clock": "clkY"}],
              l8={"clocks": [{"name": "clkA"}, {"name": "clkB"}]})
    rep = SEC.audit(p)
    assert rep["correlation_evidence_read"] == [
        "phase1/generated_docs/L8_TIMING_WAVEFORM.json",
        "reports/phase2/cdc/crossing.json"], rep
    assert rep["correlation_evidence_unread"] == [], rep
    cats = {f["category"] for f in rep["findings"]}
    assert "SDC_EXCEPTION_UNJUSTIFIED" in cats, rep
    assert "SDC_EXCEPTION_EVIDENCE_UNREAD" not in cats, rep


def test_d5_partial_evidence_is_disclosed_and_the_claim_is_bounded(tmp_path):
    """FALSIFIABILITY of the PARTIAL case — the realistic configuration.

    The Phase-1 L8 doc is present (it essentially always is) and step 3's
    crossing.json is absent. `evidence_read` is then non-empty, so the
    UNVERIFIABLE category and the disclosure were both skipped and the finding
    read `SDC_EXCEPTION_UNJUSTIFIED: ... has no matching CDC crossing / L8
    async relation` — a settled claim about a file that was never opened.

    The finding is still legitimately raised (one source WAS read and it does
    not justify the exception), but the claim must be bounded to that source
    and the unread one named."""
    p = _proj(tmp_path,
              "set_false_path -from [get_clocks clkA] -to [get_clocks clkB]\n",
              l8={"clocks": [{"name": "clkA"}, {"name": "clkB"}]})
    rep = SEC.audit(p)
    assert rep["correlation_evidence_read"] == [
        "phase1/generated_docs/L8_TIMING_WAVEFORM.json"], rep
    assert rep["correlation_evidence_unread"] == [
        "reports/phase2/cdc/crossing.json"], rep
    cats = {f["category"] for f in rep["findings"]}
    assert "SDC_EXCEPTION_UNJUSTIFIED" in cats, rep
    assert "SDC_EXCEPTION_EVIDENCE_UNREAD" in cats, rep
    disclosure = next(f for f in rep["findings"]
                      if f["category"] == "SDC_EXCEPTION_EVIDENCE_UNREAD")
    assert "reports/phase2/cdc/crossing.json" in disclosure["message"], rep
    assert "INCOMPLETE" in disclosure["message"], rep
    unjust = next(f for f in rep["findings"]
                  if f["category"] == "SDC_EXCEPTION_UNJUSTIFIED")
    # The claim cites only what was read, and says what it did NOT read.
    assert unjust["evidence_read"] == [
        "phase1/generated_docs/L8_TIMING_WAVEFORM.json"], rep
    assert unjust["evidence_unread"] == [
        "reports/phase2/cdc/crossing.json"], rep
    assert "the evidence actually read" in unjust["message"], rep
    assert "NOT correlated against reports/phase2/cdc/crossing.json" in (
        unjust["message"]), rep


def test_d5_unread_source_with_nothing_to_correlate_is_not_a_finding(
        tmp_path):
    """NO FALSE ALARM. Both sources unread, but the SDC declares no
    false_path at all — there is nothing whose correlation the missing
    evidence could have changed, so the disclosure must NOT fire."""
    p = _proj(tmp_path, "set_multicycle_path -setup 2 -to [get_pins u1/D]\n")
    rep = SEC.audit(p)
    assert rep["correlation_evidence_unread"], rep
    assert [f["category"] for f in rep["findings"]] == [], rep
    assert rep["verdict"] == "PASS", rep


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
