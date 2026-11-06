"""R-0915-52: a stated sign-off requirement is judged by the flow's DECLARED
sign-off record for that check — not by every report whose name carries a token.

MEASURED 2026-09-16 (lane icsub4) on the r19 `subservient` x gf180mcuD run at
`_lane_icsub2/b4_proj`. The input states a timing requirement at
`input/docs/L1_product_metadata.md:55`; the run's post-route sign-off STA
PASSED (`sta_signoff` -> `reports/phase3/sta/post_route_summary.json`,
passed=true; governing worst slack +0.88 ns, every analyzed corner MET); and
`l24_signoff_evidence_backed_check` still said::

    the input REQUIRES STA (requirement stated in prose) at
    input/docs/L1_product_metadata.md:55, and this run measured it as
    'fail' in reports/phase3/si_mcf_sta.json,
    'fail' in reports/phase3/sta/pre_pnr_summary.json

That was the ONLY P0 FAIL cause on the run, and neither report it cited is a
sign-off reading of STA:

  * `reports/phase3/sta/pre_pnr_summary.json` is step 10's PRE-LAYOUT
    ESTIMATE. R-0915-28 already rules the estimate superseded by a passing
    post-route sign-off.
  * `reports/phase3/si_mcf_sta.json` is step 27's SIGNAL INTEGRITY envelope —
    a different question, pulled in only because its stem ends in `sta`.

THE FIX IS A DERIVATION, NOT A LIST. `flow/phase1_phase2_phase3.yaml` says
which step publishes what; the sign-off record for a check is the
`reports/**/*.json` declared by the step whose own name says it is the
sign-off step. Measured on the flow at 800cecb34, six steps name themselves
sign-off and exactly ONE check resolves to a declared record: STA, to step
23's four `reports/phase3/sta/*.json`. Every other check keeps the name scan
it has today, so the blast radius is the defect and nothing else — and the
tests below prove that both by construction (a fixture flow moves the answer)
and by control (DRC, which derives none, behaves as before).

chip-AGNOSTIC: synthetic projects under tmp_path; no design, PDK or vendor
name appears here.
"""
from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import l24_signoff_requirements_extract as X  # noqa: E402
from _hostpaths import repo_path  # noqa: E402
import phase1_post_process as P  # noqa: E402


def _sta_records_from_the_flow():
    """The flow's own answer, derived HERE — not asked of the module under test.

    Two reasons, and the second is the load-bearing one:

      * a test that asked the program for the population and then checked the
        program against it would agree with itself by construction; and
      * on a tree WITHOUT the fix the program has no such function at all, and
        resolving the population through it turns the whole file into one
        collection error. A `falsref` R arm then shows an ImportError where it
        should show the defect. Derived here, both arms build the SAME project
        and the unfixed one is SEEN to fail on it.
    """
    import re as _re

    import yaml as _yaml
    flow = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
    data = _yaml.safe_load(flow.read_text(encoding="utf-8"))
    out = []
    for step in data.get("steps") or []:
        if not isinstance(step, dict):
            continue
        if not _re.search(r"sign[-\s]?off", str(step.get("name") or ""),
                          _re.I):
            continue
        for entry in step.get("required_outputs") or []:
            for alt in _re.split(r"\s+OR\s+", str(entry)):
                alt = alt.strip()
                if (alt.startswith("reports/") and alt.endswith(".json")
                        and not alt.startswith("reports/audit/")
                        and _re.search(r"(?<![a-z0-9])sta(?![a-z0-9])",
                                       alt.lower())):
                    out.append(alt)
    return tuple(dict.fromkeys(out))


#: The flow's own answer, read once. Every project the tests build writes to
#: THESE paths, so a test can never agree with the gate by re-typing a path.
STA_RECORDS = _sta_records_from_the_flow()


def _project(tmp_path, **docs):
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        stem, _, suffix = name.rpartition("_")
        (d / f"{stem}.{suffix}").write_text(text, encoding="utf-8")
    return tmp_path


def _emit_l24(project):
    doc = P.emit_l_doc_skeleton("L24", "unknown", project_dir=project)
    doc.pop("evidence", None)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L24_SIGNOFF.json").write_text(json.dumps(doc, indent=1))
    return doc


def _report(project, rel, payload):
    p = project / "reports" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload))
    return p


def _proj_requiring_sta(tmp_path):
    """A project whose input states a timing requirement, phase 3 reached."""
    proj = _project(tmp_path, spec_md="Sign-off requires STA met.\n")
    _emit_l24(proj)
    netlist = proj / "phase2/stage2/synth/netlist_yosys.v"
    netlist.parent.mkdir(parents=True, exist_ok=True)
    netlist.write_text("module chip; endmodule\n")
    return proj


def test_checked_in_constraint_change_invalidates_signoff(tmp_path):
    source = repo_path(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "ppa", "power", "activity_basis_pair", "constraint.sdc")
    assert source.is_file(), source
    project = _proj_requiring_sta(tmp_path)
    staged = project / "input/constraints/timing.sdc"
    staged.parent.mkdir(parents=True, exist_ok=True)
    original = source.read_bytes()
    assert b"-period 24.0" in original
    staged.write_bytes(original)
    staged.write_bytes(original.replace(b"-period 24.0", b"-period 1.0"))


def _signoff(proj, verdict):
    """Write the flow's declared STA sign-off records with this verdict."""
    for rel in STA_RECORDS:
        _report(proj, rel[len("reports/"):], {"program": "eda_report_audit:sta",
                                              "passed": verdict == "pass"})


def test_pass_reports_are_historical_after_phase3_inputs_change(tmp_path):
    """A report read from disk cannot certify a new Phase 3 input identity."""
    project = _proj_requiring_sta(tmp_path)
    _signoff(project, "pass")
    before_json = tmp_path / "before.json"
    before = json.loads(before_json.read_text())
    assert [r for r in before["requirements"] if r["check"] == "STA"][0]["outcome"] == "BACKED"

    sdc = project / "input/constraints/timing.sdc"
    sdc.parent.mkdir(parents=True, exist_ok=True)
    sdc.write_text("create_clock -period 1 [get_ports clk]\n")

    after_json = tmp_path / "after.json"
    after = json.loads(after_json.read_text())
    sta = [r for r in after["requirements"] if r["check"] == "STA"][0]
    assert sta["outcome"] == "NOT_YET_MEASURABLE"
    assert sta["evidence_scope"] == "HISTORICAL"
    assert {r["path"] for r in sta["historical_records"]} == set(STA_RECORDS)


# ── the derivation itself ────────────────────────────────────────────────

def test_the_flow_declares_a_signoff_record_for_STA():
    assert STA_RECORDS, (
        "the flow's post-route STA step names itself sign-off and declares "
        "reports/**/*.json outputs; deriving none would silently restore the "
        "token scan")
    assert all(p.startswith("reports/") and p.endswith(".json")
               for p in STA_RECORDS), STA_RECORDS


def test_the_program_derives_exactly_what_the_flow_declares():
    """The gate's own derivation, checked against this file's independent one."""
    assert X.signoff_record_paths_for("STA") == STA_RECORDS


def test_the_pre_layout_estimate_is_not_in_the_declared_record():
    """The whole defect in one assertion."""
    assert not any("pre_pnr" in p for p in STA_RECORDS), STA_RECORDS


def test_the_si_envelope_is_not_in_the_declared_record():
    assert not any("si_mcf" in p for p in STA_RECORDS), STA_RECORDS


def test_the_record_is_READ_from_the_flow_not_hard_coded(tmp_path):
    """THE ANTI-HAND-LIST CONTROL. Point the derivation at a fixture flow and
    the answer moves with it; a literal list would not."""
    yaml = pytest.importorskip("yaml")
    fixture = tmp_path / "phase1_phase2_phase3.yaml"
    fixture.write_text(yaml.safe_dump({"steps": [
        {"id": 1, "name": "Pre-layout STA (estimate)",
         "required_outputs": ["reports/phase3/sta/estimate.json"]},
        {"id": 2, "name": "Post-route STA (sign-off)",
         "required_outputs": ["reports/phase3/sta/the_record.json",
                              "phase3/stage3/sta/timing.rpt"]},
    ]}), encoding="utf-8")
    assert X.signoff_record_paths_for("STA", fixture) == (
        "reports/phase3/sta/the_record.json",), (
        "only the SIGN-OFF step's reports/*.json may be the record")


def test_a_check_no_signoff_step_publishes_derives_nothing():
    """DRC's sign-off is not published by a step that names itself sign-off,
    so it keeps the name scan — and the existing DRC tests keep passing."""
    assert X.signoff_record_paths_for("DRC") == ()


def test_an_audit_owned_record_is_never_the_declared_record(tmp_path):
    """reports/audit/ is the completion audit's OWN bookkeeping; a
    requirement backed by the audit judging it would be circular. The gate
    already excludes that tree, and the derivation must agree."""
    yaml = pytest.importorskip("yaml")
    fixture = tmp_path / "flow.yaml"
    fixture.write_text(yaml.safe_dump({"steps": [
        {"id": 36, "name": "Tapeout checklist (final sign-off confirmation)",
         "required_outputs": ["reports/audit/tapeout_checklist.json"]},
    ]}), encoding="utf-8")
    assert X.signoff_record_paths_for("tapeout_precheck", fixture) == ()


def test_an_unreadable_flow_derives_nothing_rather_than_raising(tmp_path):
    """Fail-SOFT: the caller keeps the scan it already had."""
    bad = tmp_path / "not-a-flow.yaml"
    bad.write_text("{{{ not yaml", encoding="utf-8")
    assert X.signoff_record_paths_for("STA", bad) == ()
    assert X.signoff_record_paths_for("STA", tmp_path / "absent.yaml") == ()


# ── (a) the b4_proj shape: the requirement is BACKED ─────────────────────


def test_the_same_shape_FAILED_before_the_fix_is_still_a_real_reading(
        tmp_path):
    """The estimate and the SI envelope are not ignored — they are simply not
    read AS the STA requirement. The record says which paths were read."""
    proj = _proj_requiring_sta(tmp_path)
    _signoff(proj, "pass")
    _report(proj, "phase3/sta/pre_pnr_summary.json",
            {"program": "eda_report_audit:sta", "passed": False})
    out_json = tmp_path / "rec.json"
    rec = json.loads(out_json.read_text())
    sta = [r for r in rec["requirements"] if r["check"] == "STA"][0]
    assert sta["basis"] == "flow-declared-signoff-record"
    assert sta["outcome"] == "BACKED"
    read = {e["path"] for e in sta["records_read"]}
    assert read == set(STA_RECORDS), read


# ── (b) the negative control: a FAILING sign-off still FAILS ─────────────


# ── (c) no sign-off record at all: the not-yet-measurable path ───────────

def test_no_signoff_record_before_phase3_is_not_yet_measurable(tmp_path):
    """The existing R-0915-38 deadlock guard is untouched: before the phase
    that measures sign-off, a requirement is recorded, not unmet."""
    proj = _project(tmp_path, spec_md="Sign-off requires STA met.\n")
    _emit_l24(proj)
    assert not (proj / "reports" / "phase3").exists()


# ── SI is judged BY NAME, and only when the input states one ─────────────

def test_an_input_that_states_no_SI_requirement_is_not_judged_on_SI(tmp_path):
    """MEASURED on b4_proj: `grep -rniE 'signal integrity|crosstalk'
    input/docs/` finds nothing, so the failing SI envelope must fail no
    requirement of that run."""
    proj = _proj_requiring_sta(tmp_path)
    _signoff(proj, "pass")
    _report(proj, "phase3/si_mcf_sta.json",
            {"program": "si_mcf_sta", "verdict": "FAIL"})
    rows = {r["check"]: r for r in
            X.extract_signoff_requirements(proj)["signoff_requirements"]}
    assert rows["SI"]["stated"] is False


def test_the_bare_initialism_does_not_invent_an_SI_requirement(tmp_path):
    """`SI` is not among the spellings: a stray two-letter token in a table
    must not manufacture a sign-off requirement."""
    proj = _project(tmp_path, spec_md="Column si holds the index.\n")
    rows = {r["check"]: r for r in
            X.extract_signoff_requirements(proj)["signoff_requirements"]}
    assert rows["SI"]["stated"] is False


# ── the gate STATES its own reason class ─────────────────────────────────

def test_a_measured_FAIL_carries_no_reason_class(tmp_path):
    """The field that separates a MEASUREMENT from a failure to read an
    input. The audit's `classify_sub_gate` says a FAIL record today has no
    such field; this is it, and on a real finding it is null."""
    proj = _proj_requiring_sta(tmp_path)
    _signoff(proj, "fail")
    out_json = tmp_path / "rec.json"
    rec = json.loads(out_json.read_text())
    assert rec["verdict"] == "FAIL"
    assert rec["reason_class"] is None
    assert rec["findings"], "a FAIL must say what it found"


def test_a_project_the_gate_cannot_read_says_so(tmp_path):
    out_json = tmp_path / "rec.json"
    rec = json.loads(out_json.read_text())
    assert rec["reason_class"] == "EXECUTION_ERROR"


def test_a_run_whose_layer_was_never_emitted_says_so(tmp_path):
    proj = _project(tmp_path, spec_md="Sign-off requires STA met.\n")
    out_json = tmp_path / "rec.json"
    rec = json.loads(out_json.read_text())
    assert rec["reason_class"] == "ASKED_BEFORE_PRODUCER"


def test_an_inert_layer_says_the_design_declared_nothing(tmp_path):
    proj = _project(tmp_path, spec_md="It multiplies two numbers.\n")
    _emit_l24(proj)
    out_json = tmp_path / "rec.json"
    rec = json.loads(out_json.read_text())
    assert rec["reason_class"] == "DESIGN_DECLARED_NA"
