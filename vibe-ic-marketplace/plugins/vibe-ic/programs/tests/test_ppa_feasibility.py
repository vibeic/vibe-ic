#!/usr/bin/env python3
"""The four fixtures for the hard promotion gate: positive, negative, vacuous.

Each test here is named after the thing that would go wrong without it. The
gate's whole job is to be the one place where a number cannot buy an eligibility
decision, so most of these are about REFUSING something that looks fine.
"""
import json
import pathlib
import subprocess
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F  # noqa: E402

CHECK = _PROGRAMS / "ppa_feasibility_check.py"

DIGEST = "sha256:" + "0" * 64
VIEW = {"stage": "post_route_extracted", "process": "ss"}
VIEW_FF = {"stage": "post_route_extracted", "process": "ff"}


def metric(name, value, unit="", scope=None, status="MEASURED", source=True):
    rec = {"schema": F.METRIC_SCHEMA, "metric": name, "status": status,
           "unit": unit, "scope": dict(scope if scope is not None else VIEW)}
    if status == "MEASURED":
        rec["value"] = value
    elif value is not None:
        rec["value"] = value
    if source:
        rec["source"] = {"path": "phase3/stage3/x.rpt", "sha256": DIGEST,
                         "tool": "t", "parser": "p"}
    return rec


def clean_metrics(scope=None):
    s = scope if scope is not None else VIEW
    return [
        metric("timing.setup.wns_ns", 0.050, "ns", s),
        metric("timing.hold.wns_ns", 0.010, "ns", s),
        metric("timing.drv.violations", 0, "count", s),
        metric("physical.drc.violations", 0, "count", s),
        metric("physical.lvs.verdict", "CLEAN", "", s),
        metric("physical.antenna.violations", 0, "count", s),
        metric("power.ir.violations", 0, "count", s),
        metric("reliability.em.violations", 0, "count", s),
        metric("equivalence.verdict", "PROVEN", "", s),
    ]


def candidate(cid="c1", metrics=None, waivers=None):
    d = {"candidate_id": cid,
         "metrics": clean_metrics() if metrics is None else metrics}
    if waivers is not None:
        d["waivers"] = waivers
    return d


def policy(views=(VIEW,), **kw):
    doc = {"required_views": [dict(v) for v in views]}
    doc.update(kw)
    return F.policy_from_document(doc)


def run(tmp_path, doc, *extra):
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / "feas.json"
    r = subprocess.run([sys.executable, str(CHECK), "--candidates", str(p),
                        "--json", str(out), *extra],
                       capture_output=True, text=True)
    payload = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return r, payload


# --- POSITIVE ---------------------------------------------------------------
def test_positive_a_fully_measured_clean_candidate_is_feasible():
    r = F.promotion_verdict(candidate(), policy())
    assert r.verdict == F.FEASIBLE, r.codes
    assert r.eligible_for_promotion
    assert F.set_exit_code([r]) == F.RC_PASS


def test_positive_cli_exits_zero_and_writes_the_declared_artefact(tmp_path):
    r, doc = run(tmp_path, {"required_views": [VIEW],
                            "candidates": [candidate()]})
    assert r.returncode == 0, r.stdout + r.stderr
    assert doc["verdict"] == "FEASIBLE"
    assert doc["schema"] == F.FEASIBILITY_SCHEMA
    assert doc["policy_digest"].startswith("sha256:")


# --- NEGATIVE ---------------------------------------------------------------
def test_negative_one_violated_axis_refuses_however_good_the_others_are():
    """The whole lane in one assertion.

    Setup slack is enormous, everything else is clean, and LVS is dirty. There
    is no arithmetic in this module that could let the first fact outweigh the
    last, because the verdict is not arithmetic.
    """
    ms = clean_metrics()
    ms[0]["value"] = 99.0          # a spectacular WNS
    ms[4]["value"] = "MISMATCH"    # and a dirty LVS
    r = F.promotion_verdict(candidate(metrics=ms), policy())
    assert r.verdict == F.INFEASIBLE
    assert not r.eligible_for_promotion
    assert any(c.startswith("lvs:") for c in r.codes), r.codes


def test_negative_cli_exits_one_and_still_prints_the_finding(tmp_path):
    ms = clean_metrics()
    ms[3]["value"] = 7             # DRC violations
    r, doc = run(tmp_path, {"required_views": [VIEW],
                            "candidates": [candidate(metrics=ms)]})
    assert r.returncode == F.RC_FAIL
    assert "INFEASIBLE" in r.stdout
    assert "[REFUSE]" in r.stderr
    assert doc["candidates"][0]["verdict"] == "INFEASIBLE"


def test_negative_a_negative_slack_is_a_violation_not_a_small_number():
    ms = clean_metrics()
    ms[0]["value"] = -0.001
    r = F.promotion_verdict(candidate(metrics=ms), policy())
    assert r.verdict == F.INFEASIBLE


# --- VACUOUS: every way of not being able to look exits 2, never 0 and never 1
def test_vacuous_absent_input_is_rc2_with_a_marker(tmp_path):
    out = tmp_path / "f.json"
    r = subprocess.run([sys.executable, str(CHECK), "--candidates",
                        str(tmp_path / "nope.json"), "--json", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == F.RC_UNDETERMINED, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stderr
    assert json.loads(out.read_text())["exit_code"] == 2


def test_vacuous_empty_file_is_rc2_not_rc0(tmp_path):
    p = tmp_path / "candidates.json"
    p.write_text("", encoding="utf-8")
    r = subprocess.run([sys.executable, str(CHECK), "--candidates", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == F.RC_UNDETERMINED
    assert "[CANNOT CHECK]" in r.stderr


def test_vacuous_an_empty_candidate_list_is_not_a_clean_set(tmp_path):
    r, doc = run(tmp_path, {"required_views": [VIEW], "candidates": []})
    assert r.returncode == F.RC_UNDETERMINED
    assert doc["codes"] == ["FEAS_NO_CANDIDATES"]


def test_vacuous_unparseable_json_is_rc2(tmp_path):
    p = tmp_path / "candidates.json"
    p.write_text("{not json", encoding="utf-8")
    r = subprocess.run([sys.executable, str(CHECK), "--candidates", str(p)],
                       capture_output=True, text=True)
    assert r.returncode == F.RC_UNDETERMINED


def test_bad_invocation_is_rc3_not_rc2():
    """argparse exits 2 on a usage error and 2 already means `not checked`."""
    assert __import__("ppa_feasibility_check").main([]) == F.RC_BAD_INVOCATION


# --- the rc precedence rule -------------------------------------------------
def test_set_rc_undetermined_outranks_infeasible():
    ms_bad = clean_metrics()
    ms_bad[3]["value"] = 5
    bad = F.promotion_verdict(candidate("bad", ms_bad), policy())
    unknown = F.promotion_verdict(candidate("unk", clean_metrics()),
                                  policy(views=()))
    assert bad.verdict == F.INFEASIBLE
    assert unknown.verdict == F.UNDETERMINED
    assert F.set_exit_code([bad, unknown]) == F.RC_UNDETERMINED


def test_candidate_rc_infeasible_outranks_undetermined():
    """The mirror of the above, and it points the other way on purpose.

    One measured violation is already sound grounds to refuse, so at candidate
    level the confirmed fact wins. At SET level rc=1 asserts a complete finding
    and an unadjudicated candidate makes that assertion false.
    """
    ms = clean_metrics()
    ms[3]["value"] = 5                      # a real DRC violation
    ms[6]["status"] = "NOT_MEASURED"        # and an axis nobody measured
    ms[6].pop("value")
    r = F.promotion_verdict(candidate(metrics=ms), policy())
    assert r.verdict == F.INFEASIBLE


# --- provenance and record hygiene -----------------------------------------
def test_a_measured_record_with_no_artefact_behind_it_is_not_evidence():
    ms = clean_metrics()
    ms[3].pop("source")
    r = F.promotion_verdict(candidate(metrics=ms), policy())
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_NO_PROVENANCE" in c for c in r.codes), r.codes


def test_the_gate_reads_records_only_never_a_summary_field_on_the_candidate():
    """A candidate may carry any convenience field it likes; none of it counts.

    This is the structural half of "DRC 0 but DRC never ran": there is no code
    path that could read `drc_violations` off the candidate, so a producer
    cannot assert cleanliness by writing a number next to the evidence.
    """
    ms = [m for m in clean_metrics() if m["metric"] != "physical.drc.violations"]
    cand = candidate(metrics=ms)
    cand["drc_violations"] = 0
    cand["summary"] = {"drc": "clean", "lvs": "clean"}
    r = F.promotion_verdict(cand, policy())
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_METRIC_ABSENT" in c for c in r.codes)


def test_a_boolean_is_not_a_count():
    ms = clean_metrics()
    ms[3]["value"] = False
    r = F.promotion_verdict(candidate(metrics=ms), policy())
    assert r.verdict == F.UNDETERMINED


def test_a_negative_violation_count_is_a_broken_parse_not_a_clean_run():
    ms = clean_metrics()
    ms[3]["value"] = -1
    r = F.promotion_verdict(candidate(metrics=ms), policy())
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_NEGATIVE_COUNT" in c for c in r.codes)


# --- limits come from the contract, never from this file -------------------
def test_a_limit_axis_with_no_declared_limit_is_undetermined_not_pass():
    ms = [m for m in clean_metrics() if m["metric"] != "power.ir.violations"]
    ms.append(metric("power.ir.worst_drop_v", 0.08, "V"))
    r = F.promotion_verdict(candidate(metrics=ms), policy())
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_LIMIT_NOT_DECLARED" in c for c in r.codes), r.codes


def test_a_declared_limit_adjudicates_the_axis_both_ways():
    base = [m for m in clean_metrics() if m["metric"] != "power.ir.violations"]
    pol = policy(limits={"power.ir.worst_drop_v": {"max": 0.10, "unit": "V"}})
    ok = base + [metric("power.ir.worst_drop_v", 0.08, "V")]
    bad = base + [metric("power.ir.worst_drop_v", 0.15, "V")]
    assert F.promotion_verdict(candidate(metrics=ok), pol).verdict == F.FEASIBLE
    assert F.promotion_verdict(candidate(metrics=bad), pol).verdict == F.INFEASIBLE


def test_a_limit_compared_across_units_is_undetermined():
    base = [m for m in clean_metrics() if m["metric"] != "power.ir.violations"]
    pol = policy(limits={"power.ir.worst_drop_v": {"max": 100.0, "unit": "mV"}})
    ms = base + [metric("power.ir.worst_drop_v", 0.08, "V")]
    r = F.promotion_verdict(candidate(metrics=ms), pol)
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_UNIT_MISMATCH" in c for c in r.codes)


# --- the schema the lane owns ----------------------------------------------
def test_the_emitted_report_validates_against_the_schema_this_lane_owns(tmp_path):
    from _ppa import schema_validation as _SV
    schema = json.loads((_PROGRAMS.parent / "schemas" / "ppa" /
                         "feasibility.v1.schema.json").read_text())
    _, doc = run(tmp_path, {"required_views": [VIEW],
                            "candidates": [candidate()]})
    assert _SV.engine_or_skip(schema).errors(doc) == []
