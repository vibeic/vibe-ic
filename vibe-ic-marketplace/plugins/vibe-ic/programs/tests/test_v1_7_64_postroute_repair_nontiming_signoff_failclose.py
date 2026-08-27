#!/usr/bin/env python3
"""v1.7.64 — Step 32 (d5): "no repair needed" may not be asserted from STA alone.

Step 32's own flow-YAML text reads: "If any sign-off step (STA, PV, IR Drop,
EM, SI, Post-Sim, SPICE) fails, repair applies targeted netlist patches and
re-runs the failing checks."

Reproduced on v1.7.36: `postroute_timing_repair_decision.decide(stance, single_corner_clean)`
took exactly two inputs, both STA-derived. A project carrying
``reports/phase3/ir_drop.json {"verdict": "FAIL"}`` beside a clean STA produced

    postroute_timing_repair_status_gen  →  verdict PASS, artefact phase3/stage3/postroute_timing_repair/no_repair_needed.flag
    postroute_timing_repair_audit  →  repair_needed false, errors 0, pass true, rc 0

i.e. Step 32 certified "no repair needed" over a hard-failed power-integrity
sign-off. The non-timing verdict JSONs were already on disk in the same run,
unconsulted.

The fix is a FAIL-CLOSE, not new repair capability:
  * `decide()` gains an optional project/override input and refuses
    repair_needed=False while any non-timing sign-off domain reports a HARD
    failure;
  * `timing_repair_needed` (the pre-v1.7.64 meaning of `repair_needed`) still gates
    the timing-repair TCL, so a non-timing failure never fires
    `postroute_timing_repair.tcl` and never fabricates a repaired `repair_log.json`;
  * only EXPLICIT hard-fail signals count — absent, unparseable, advisory and
    review-tier artefacts must not demand a repair, or every run deadlocks.

chip-AGNOSTIC: canonical report paths and verdict tokens only.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS_DIR = Path(__file__).resolve().parent.parent
if str(_PROGRAMS_DIR) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS_DIR))

import postroute_timing_repair_decision as ETD  # noqa: E402

_STATUS_GEN = _PROGRAMS_DIR / "postroute_timing_repair_status_gen.py"
_LOOP_AUDIT = _PROGRAMS_DIR / "postroute_timing_repair_audit.py"

_CLEAN_MCORNER_STANCE = {
    "multi_process_corner": True,
    "report": "reports/phase3/sta_mcorner_ocv.rpt",
    "violated_corners": [],
    "setup_worst_slack_ns": 5.77,
    "hold_worst_slack_ns": 0.18,
}


def _project(tmp_path: Path, signoff: dict | None = None,
             stance: dict | None = None,
             sta_text: str = "worst slack MET\ntns 0.00\nwns 5.77\n") -> Path:
    """Build a project whose single-corner STA is CLEAN, with an optional set
    of non-timing sign-off artefacts keyed by canonical relative path."""
    (tmp_path / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "phase2" / "gates").mkdir(parents=True,
                                                     exist_ok=True)
    (tmp_path / "phase3" / "stage3" / "sta").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3" / "stage3" / "postroute_timing_repair").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3" / "stage3" / "sta" /
     "post_route_timing.rpt").write_text(sta_text)
    (tmp_path / "reports" / "phase3" / "mcorner_ocv_stance.json").write_text(
        json.dumps(stance if stance is not None else _CLEAN_MCORNER_STANCE))
    for rel, payload in (signoff or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload))
    return tmp_path


def _run(prog: Path, project: Path):
    proc = subprocess.run([sys.executable, str(prog), str(project)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


# ===========================================================================
# The defect: a hard-failed non-timing sign-off must block the certificate
# ===========================================================================
@pytest.mark.parametrize("rel,payload,domain", [
    ("reports/phase3/ir_drop.json",
     {"tool": "openroad-psm", "worst_ir_pct_vdd": 18.4,
      "budget_pct_vdd": 10.0, "verdict": "FAIL"}, "ir_drop"),
    ("reports/phase3/em.json",
     {"tool": "openroad-psm", "verdict": "VIOLATED"}, "em"),
    ("reports/phase3/lvs.json",
     {"program": "eda_report_audit:lvs", "passed": False}, "lvs"),
    ("reports/phase3/antenna.json",
     {"net_violations": 5, "clean": False, "verdict": "FAIL"}, "antenna"),
    ("reports/phase2/gates/erc_density.json",
     {"program": "erc_density_check",
      "summary": {"pass": False, "errors_count": 2}}, "erc_density"),
])
def test_hard_failed_signoff_domain_blocks_no_repair_needed(
        tmp_path, rel, payload, domain):
    """Every canonical non-timing sign-off domain, on its own, must withhold
    the `no_repair_needed.flag` certificate."""
    proj = _project(tmp_path, signoff={rel: payload})
    decision = ETD.decide(proj / "reports/phase3/mcorner_ocv_stance.json",
                          True, project=proj)
    assert decision["timing_repair_needed"] is False, "timing is clean here"
    assert decision["repair_needed"] is True, (
        f"a hard-failed {domain} sign-off must not certify 'no repair needed'"
    )
    assert [r["domain"] for r in decision["nontiming_failures"]] == [domain]
    assert domain in decision["reason"]

    rc, out = _run(_STATUS_GEN, proj)
    assert rc == 0, out
    assert not (proj / "phase3/stage3/postroute_timing_repair/no_repair_needed.flag").is_file(), (
        "no_repair_needed.flag must NOT be written over a failed sign-off"
    )


def test_step32_gate_goes_red_instead_of_certifying(tmp_path):
    """End-to-end: the withheld certificate must surface as a red Step 32,
    not as a silently-green one."""
    proj = _project(tmp_path, signoff={
        "reports/phase3/ir_drop.json": {"worst_ir_pct_vdd": 18.4,
                                        "verdict": "FAIL"}})
    rc_gen, out_gen = _run(_STATUS_GEN, proj)
    assert rc_gen == 0, out_gen
    rc_audit, out_audit = _run(_LOOP_AUDIT, proj)
    assert rc_audit == 1, (
        "postroute_timing_repair_audit must report Step 32 red; got rc=0\n" + out_audit
    )
    # This assertion used to pin the two finding CODES that happened to carry
    # the redness (NOT_REVERIFIED / EMPTY_CHANGES). Those two describe a repair
    # that was APPLIED — which, in this very scenario, v1.7.64 guarantees never
    # happened — so the audit now reports the blocking domain instead. The
    # property this test exists for is UNCHANGED and is asserted above and
    # below: rc==1 and pass==False. Asserting the reason is NAMED is strictly
    # stronger than the old code list, which allowed a red step whose finding
    # explained nothing.
    payload = json.loads(out_audit[out_audit.index("{"):
                                   out_audit.rindex("}") + 1])
    assert payload["summary"]["pass"] is False, out_audit
    assert "ir_drop" in out_audit, (
        "a red Step 32 must name the sign-off domain that blocks it\n"
        + out_audit)


def test_no_repaired_repair_log_is_fabricated_for_a_nontiming_failure(tmp_path):
    """A non-timing failure has no runnable timing repair. The repair record must
    therefore NOT claim changes or re-verification."""
    proj = _project(tmp_path, signoff={
        "reports/phase3/em.json": {"verdict": "VIOLATED"}})
    _run(_STATUS_GEN, proj)
    log = json.loads(
        (proj / "phase3/stage3/postroute_timing_repair/repair_log.json").read_text())
    assert log["verdict"] == "REPAIR_REQUIRED"
    assert not log.get("changes")
    assert log.get("re_verified", False) is False
    assert log["timing_repair_needed"] is False
    assert [r["domain"] for r in log["nontiming_failures"]] == ["em"]


def test_timing_repair_stays_gated_on_a_timing_violation(tmp_path):
    """`timing_repair_needed` must remain the ONLY signal that may fire
    `postroute_timing_repair.tcl` — a non-timing failure must not fire a repair that
    cannot address it."""
    proj = _project(tmp_path, signoff={
        "reports/phase3/ir_drop.json": {"verdict": "FAIL"}})
    d = ETD.decide(_CLEAN_MCORNER_STANCE, True, project=proj)
    assert d["repair_needed"] is True
    assert d["timing_repair_needed"] is False
    assert d["violated_corners"] == []


def test_multiple_failed_domains_are_all_named(tmp_path):
    proj = _project(tmp_path, signoff={
        "reports/phase3/ir_drop.json": {"verdict": "FAIL"},
        "reports/phase3/lvs.json": {"passed": False},
        "reports/phase3/erc.json": {"verdict": "MISMATCH"},
    })
    d = ETD.decide(_CLEAN_MCORNER_STANCE, True, project=proj)
    assert {r["domain"] for r in d["nontiming_failures"]} == {
        "ir_drop", "lvs", "erc"}


# ===========================================================================
# Conservatism: only EXPLICIT hard failures may demand a repair
# ===========================================================================
@pytest.mark.parametrize("payload,why", [
    ({}, "empty artefact"),
    ({"verdict": "PASS"}, "plain pass"),
    ({"verdict": "MEASURED"}, "measurement-only tier (em.json)"),
    ({"verdict": "REVIEW", "clean": False},
     "ERC review tier — a warning, not a hard failure"),
    ({"verdict": "BENIGN-ERC"}, "waiver-eligible benign ERC"),
    ({"verdict": "ADVISORY_SCREEN_ONLY"}, "SI advisory screen"),
    ({"verdict": "PASS_WITH_OPEN_ITEMS"}, "PERC pass with open items"),
    ({"verdict": "PASS_WITH_ADVISORIES"}, "DFM advisories"),
    ({"summary": {"pass": True}}, "gate summary pass"),
])
def test_non_hard_failure_tiers_do_not_demand_a_repair(tmp_path, payload, why):
    """Reading warnings / advisories as failure would deadlock Step 32 on
    essentially every open-source run."""
    proj = _project(tmp_path, signoff={
        "reports/phase3/ir_drop.json": payload})
    d = ETD.decide(_CLEAN_MCORNER_STANCE, True, project=proj)
    assert d["repair_needed"] is False, f"{why} must not demand a repair"
    assert d["nontiming_failures"] == []


def test_absent_and_unparseable_artefacts_are_not_failures(tmp_path):
    proj = _project(tmp_path)                       # no sign-off files at all
    assert ETD.decide(_CLEAN_MCORNER_STANCE, True,
                      project=proj)["repair_needed"] is False
    (proj / "reports/phase3/ir_drop.json").write_text("{not json")
    assert ETD.decide(_CLEAN_MCORNER_STANCE, True,
                      project=proj)["repair_needed"] is False


# ===========================================================================
# DIRECTION-1 GUARDS — behaviour that must NOT change.
#
# These read `timing_repair_needed` / `nontiming_failures` through .get() with a
# pre-v1.7.64 default, so each guard is meaningful on BOTH trees rather than
# tripping over a field the base tree simply does not emit.
# ===========================================================================
def _timing_needed(d):
    return d.get("timing_repair_needed", d["repair_needed"])


def test_guard_decide_without_project_is_timing_only(tmp_path):
    """The pre-v1.7.64 two-argument call must behave EXACTLY as before, so
    every existing caller and test keeps its semantics."""
    proj = _project(tmp_path, signoff={
        "reports/phase3/ir_drop.json": {"verdict": "FAIL"}})
    d = ETD.decide(proj / "reports/phase3/mcorner_ocv_stance.json", True)
    assert d["repair_needed"] is False
    assert d.get("nontiming_failures", []) == []
    assert d["basis"] == "multi_corner_ocv"
    assert d["mc_ocv_available"] is True


def test_guard_multicorner_violation_still_fires():
    """§4.05 / the ibex fix: a real ss violation with a MET tt STA must still
    fire the repair on the multi_corner_ocv basis. Called in the pre-v1.7.64
    two-argument shape so the guard is meaningful on both trees."""
    stance = dict(_CLEAN_MCORNER_STANCE,
                  violated_corners=["ss"], setup_worst_slack_ns=-88.0)
    d = ETD.decide(stance, True)
    assert d["basis"] == "multi_corner_ocv"
    assert _timing_needed(d) is True
    assert d["repair_needed"] is True
    assert d["violated_corners"] == ["ss"]
    assert d["setup_worst_slack_ns"] == -88.0


def test_multicorner_violation_survives_the_signoff_scan(tmp_path):
    """The new non-timing scan is purely additive: it must never clear a real
    multi-corner timing violation."""
    stance = dict(_CLEAN_MCORNER_STANCE,
                  violated_corners=["ss"], setup_worst_slack_ns=-88.0)
    proj = _project(tmp_path, stance=stance, signoff={
        "reports/phase3/ir_drop.json": {"verdict": "PASS"}})
    d = ETD.decide(stance, True, project=proj)
    assert d["timing_repair_needed"] is True
    assert d["repair_needed"] is True
    assert d["violated_corners"] == ["ss"]
    assert d["nontiming_failures"] == []


def test_guard_single_corner_fallback_unchanged():
    """§4.05 honest fallback: no stance ⇒ tt basis, repair_needed = NOT clean."""
    for clean in (True, False):
        d = ETD.decide(None, clean)
        assert d["basis"] == "single_corner_tt"
        assert d["mc_ocv_available"] is False
        assert d["repair_needed"] is (not clean)
        assert _timing_needed(d) is (not clean)


def test_guard_non_authoritative_stance_stays_tt():
    """A single-corner stance (multi_process_corner False / no report) is NOT
    authoritative — no fabricated multi-corner claim."""
    d = ETD.decide({"multi_process_corner": False, "report": None,
                    "violated_corners": ["ss"]}, True)
    assert d["basis"] == "single_corner_tt"
    assert d["repair_needed"] is False


def test_guard_clean_run_still_writes_the_flag(tmp_path):
    """A genuinely clean run — clean STA and clean sign-off verdicts — must
    still get its honest no_repair_needed.flag and a green audit."""
    proj = _project(tmp_path, signoff={
        "reports/phase3/ir_drop.json": {"verdict": "PASS"},
        "reports/phase3/em.json": {"verdict": "MEASURED"},
        "reports/phase3/si_crosstalk.json": {"verdict": "ADVISORY_SCREEN_ONLY"},
        "reports/phase3/lvs.json": {"passed": True},
        "reports/phase3/erc.json": {"verdict": "PASS"},
        "reports/phase3/antenna.json": {"verdict": "PASS"},
    })
    rc_gen, out_gen = _run(_STATUS_GEN, proj)
    assert rc_gen == 0, out_gen
    assert (proj / "phase3/stage3/postroute_timing_repair/no_repair_needed.flag").is_file()
    rc_audit, out_audit = _run(_LOOP_AUDIT, proj)
    assert rc_audit == 0, out_audit


def test_guard_timing_violation_record_is_unchanged_in_shape(tmp_path):
    """A tt timing violation must still produce the REPAIR_REQUIRED record with
    its pre-existing fields, and no no_repair_needed.flag."""
    proj = _project(tmp_path, stance={"multi_process_corner": False,
                                      "report": None},
                    sta_text="setup VIOLATED\ntns -12.5\nwns -3.1\n")
    rc, out = _run(_STATUS_GEN, proj)
    assert rc == 0, out
    log = json.loads((proj / "phase3/stage3/postroute_timing_repair/repair_log.json").read_text())
    assert log["verdict"] == "REPAIR_REQUIRED"
    assert log["wns_negative"] is True
    assert "sta_source" in log and "raw_lines_inspected" in log
    assert "remediation" in log
    assert not (proj / "phase3/stage3/postroute_timing_repair/no_repair_needed.flag").is_file()


def test_timing_violation_record_names_the_timing_basis(tmp_path):
    """New disclosure: the repair record must say WHICH basis demanded it, so a
    reviewer can tell a timing repair from a non-timing sign-off failure."""
    proj = _project(tmp_path, stance={"multi_process_corner": False,
                                      "report": None},
                    sta_text="setup VIOLATED\ntns -12.5\nwns -3.1\n")
    _run(_STATUS_GEN, proj)
    log = json.loads((proj / "phase3/stage3/postroute_timing_repair/repair_log.json").read_text())
    assert log["timing_repair_needed"] is True
    assert log["nontiming_failures"] == []
    assert "timing violation" in log["trigger_reason"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
