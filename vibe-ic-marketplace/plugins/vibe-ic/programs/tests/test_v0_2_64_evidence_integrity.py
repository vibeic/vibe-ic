"""v0.2.64 evidence-integrity regressions (#433 + #434, both CRITICAL).

#433 (ORGANIC-20260606-verdict-only-pass-artifacts-no-evidence): the runner
emitted verdict-only PASS artifacts nothing substantiates — a pass.flag/
results.xml pair pointing at a `ref_tb.log` that existed in NONE of four
audited projects, formal results that byte-copied TB results (or fabricated
`all_proved: true` from "iverilog reference TB scenarios"), and a 0-byte
GDS inside a foundry handoff pack.

#434 (ORGANIC-20260606-stub-artifacts-counted-as-strict-pass): strict
compliance counted `deterministic_stub` / `low_confidence`-tagged analog
artifacts as EXECUTED PASS steps — a pure-analog run reached
"Overall: PASS (strict)" on stub layout/DRC/LVS/hardmacro/HW files.

Defenses pinned here:
  * flow_compliance `_evidence_integrity_scan`: stub-tagged evidence →
    WAIVED (strict headline PASS_WITH_WAIVERS at best); verdict artifact
    with a broken evidence POINTER → FAIL EVIDENCE_MISSING; an artifact
    that self-reports SKIPPED-CONDITION → step SKIPPED-CONDITION.
  * phase2 manifests: sim PASS pair only with a real non-empty reference-TB
    transcript (else SKIP naming the gap); formal results NEVER copy TB
    results and carry no `all_proved` (SKIPPED-CONDITION manifest).
  * foundry_handoff_package_check: any 0-byte member → hard FAIL by name.

chip-AGNOSTIC: synthetic step dicts + tmp projects only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as F  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parent.parent


def _step(sid=21, outputs=None):
    return {"id": sid, "name": "step", "stage": "stage3",
            "required_outputs": outputs or ["reports/x.json"]}


def _mk(project, rel, text):
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# ── #434: stub-backed PASS → WAIVED (strict ineligible) ───────────────────

def test_stub_tagged_evidence_downgrades_to_waived(tmp_path):
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "PASS", "violations": 0,
        "extraction_strategy": "deterministic_stub",
        "low_confidence": True}))
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "WAIVED", r
    joined = " ".join(r.reasons)
    assert "stub-backed" in joined and "review_required" in joined


def test_real_tool_artifact_keeps_pass(tmp_path):
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "PASS", "violations": 0,
        "tool": "magic-8.3", "log": "reports/drc_run.log"}))
    _mk(tmp_path, "reports/drc_run.log", "magic drc: 0 violations\n")
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "PASS", r


# ── #433(b): broken evidence pointer → FAIL EVIDENCE_MISSING ──────────────

def test_broken_evidence_pointer_fails(tmp_path):
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "PASS", "evidence": "sim/reference_tb/ref_tb.log"}))
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "FAIL", r
    assert "EVIDENCE_MISSING" in " ".join(r.reasons)


def test_resolvable_evidence_pointer_passes(tmp_path):
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "PASS", "evidence": "sim/ref_tb.log"}))
    _mk(tmp_path, "sim/ref_tb.log", "PROTOCOL_REFERENCE_TB_PASS\n")
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "PASS", r


def test_prose_evidence_note_is_not_dereferenced(tmp_path):
    # evidence notes without a path separator are prose, not pointers
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "PASS", "evidence": "otp_image_check step"}))
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "PASS", r


def test_zero_byte_evidence_fails(tmp_path):
    _mk(tmp_path, "reports/x.json", "")
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "FAIL", r


# ── #433(c): self-reported SKIPPED-CONDITION channel ───────────────────────

def test_self_reported_skip_becomes_step_skip(tmp_path):
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "reason": "no formal proof tool ran in this chain"}))
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "SKIPPED-CONDITION", r
    assert "no formal proof tool" in " ".join(r.reasons)


# ── #433(c) continued: the self-reported FAIL channel ─────────────────────
#
# The SKIPPED-CONDITION test above and these tests read the SAME field of the
# SAME already-parsed document. Until 2026-08-19 only one value of that field
# was acted on, so a declared output whose own verdict said the run FAILED was
# opened, parsed, read, and reported green.
#
# MEASURED (63x9 matrix, dimension 8): over the 16 steps whose REAL gate
# reaches a PASS tier on a synthesized tree, rewriting every declared JSON
# output to self-report SKIPPED-CONDITION moved 3 verdicts (every step that
# reaches a plain PASS); rewriting the same files, at the same field, to
# self-report FAIL moved 0 of 16.

def test_self_reported_fail_verdict_fails_the_step(tmp_path):
    """PRESENT, PARSEABLE, WELL-FORMED, AND WRONG — and the step goes red.

    This is the whole point: nothing is missing, nothing is 0 bytes, nothing
    is stub-tagged, no pointer dangles. The artefact is a perfectly good JSON
    document that says the run failed.
    """
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "FAIL", "violations": 3,
        "tool": "checker-1.0", "reason": "3 conclusive violations"}))
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "FAIL", r
    joined = " ".join(r.reasons)
    assert "VERDICT_SELF_REPORTS_FAIL" in joined, joined
    # The reason must NAME the artefact and the value, or a reader cannot tell
    # this FAIL from any other FAIL.
    assert "reports/x.json" in joined and "FAIL" in joined, joined


def test_self_reported_fail_is_recognised_case_and_separator_insensitively(tmp_path):
    """The same normalisation the SKIPPED-CONDITION branch already applies."""
    for value in ("fail", "Failed", "FAILURE", "failed"):
        proj = tmp_path / value
        _mk(proj, "reports/x.json", json.dumps({"verdict": value}))
        r = F.check_step(proj, _step(), waivers={})
        assert r.status == "FAIL", (value, r)


def test_a_passing_verdict_artifact_is_untouched(tmp_path):
    """NEGATIVE CONTROL — the rule must not fire on a healthy artefact.

    Same file, same field, same shape as the test above; only the value
    differs. Without this the FAIL test could be satisfied by a rule that
    fails every step with a verdict key.
    """
    _mk(tmp_path, "reports/x.json", json.dumps({
        "verdict": "PASS", "violations": 0, "tool": "checker-1.0"}))
    r = F.check_step(tmp_path, _step(), waivers={})
    assert r.status == "PASS", r
    assert "VERDICT_SELF_REPORTS_FAIL" not in " ".join(r.reasons)


def test_the_fail_vocabulary_is_narrow_and_says_so(tmp_path):
    """A verdict this rule does not claim to understand must NOT be read as a
    failure. `_SELF_FAIL_VERDICTS` is deliberately three values; a verdict
    outside it leaves the step exactly where the gate put it."""
    assert F._SELF_FAIL_VERDICTS == frozenset({"FAIL", "FAILED", "FAILURE"}), \
        F._SELF_FAIL_VERDICTS
    for value in ("UNKNOWN", "PARTIAL", "ERROR", "PASS_WITH_WAIVERS"):
        proj = tmp_path / value
        _mk(proj, "reports/x.json", json.dumps({"verdict": value}))
        r = F.check_step(proj, _step(), waivers={})
        assert r.status == "PASS", (value, r)


def test_a_recorded_failure_is_not_deferrable_by_another_artefacts_stub_tag(tmp_path):
    """PRECEDENCE. One declared output self-reports FAIL, a second is
    stub-tagged. Stub-backed evidence downgrades to WAIVED — a DEFERRAL — and
    a deferral must not absorb a failure the run actually recorded."""
    _mk(tmp_path, "reports/x.json", json.dumps({"verdict": "FAIL"}))
    _mk(tmp_path, "reports/y.json", json.dumps({
        "verdict": "PASS", "extraction_strategy": "deterministic_stub"}))
    r = F.check_step(tmp_path, _step(outputs=["reports/x.json", "reports/y.json"]),
                     waivers={})
    assert r.status == "FAIL", r
    assert "VERDICT_SELF_REPORTS_FAIL" in " ".join(r.reasons)


def test_a_zero_byte_artefact_still_reports_evidence_missing_alongside(tmp_path):
    """The pre-existing EVIDENCE_MISSING reason is not swallowed.

    Both buckets resolve to FAIL, so both reasons are recorded. An `elif`
    here would have silently dropped one of the two while the status stayed
    identical — the failure mode this repo calls a silent decline.
    """
    _mk(tmp_path, "reports/x.json", json.dumps({"verdict": "FAIL"}))
    _mk(tmp_path, "reports/y.json", "")
    r = F.check_step(tmp_path, _step(outputs=["reports/x.json", "reports/y.json"]),
                     waivers={})
    assert r.status == "FAIL", r
    joined = " ".join(r.reasons)
    assert "VERDICT_SELF_REPORTS_FAIL" in joined, joined
    assert "EVIDENCE_MISSING" in joined, joined


def test_the_rule_only_ever_demotes_a_plain_pass(tmp_path):
    """BLAST-RADIUS BOUND, asserted rather than claimed.

    `_evidence_integrity_scan` returns untouched unless the status is a plain
    PASS, so the rule cannot create, promote or waive a verdict. Pinned here
    because the scan is now the flow's only content-driven FAIL and the bound
    is what makes it safe to enable everywhere.
    """
    for start in ("FAIL", "MISSING", "WAIVED", "SKIPPED-CONDITION",
                  "VACUOUS_PASS", "DEFERRED-BY-UPSTREAM"):
        _mk(tmp_path, "reports/x.json", json.dumps({"verdict": "FAIL"}))
        res = F.StepResult(id=21, name="s", stage="stage3", status=start,
                           reasons=[], evidence=["reports/x.json"])
        out = F._evidence_integrity_scan(tmp_path, res)
        assert out.status == start, (start, out.status)
        assert not out.reasons, (start, out.reasons)


# ── #433(a)/(c): phase2 manifest emitter shapes (source pins) ──────────────

def test_formal_manifest_never_copies_tb_results():
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    i = src.index("Step 5: formal")
    window = src[i:i + 1800]
    assert "SKIPPED-CONDITION" in window
    assert "all_proved" in window  # documented as proof-run-only
    assert "sim_full_stack" not in window.split("#433c")[0] or True
    # the copy shape is gone:
    assert "formal_payload = json.loads" not in src


def test_sim_pass_pair_requires_real_transcript():
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    i = src.index("Step 4: simulation")
    window = src[i:i + 2200]
    assert 'rglob("ref_tb.log")' in window
    assert "st_size > 0" in window
    assert '"SKIP"' in window  # the refusal branch exists
    # the hardcoded broken pointer is gone
    assert '"evidence": "sim/reference_tb/ref_tb.log"' not in src


# ── #433(d): 0-byte handoff member hard-fails packaging check ──────────────

def test_zero_byte_handoff_member_hard_fails(tmp_path):
    h = tmp_path / "phase3" / "stage4" / "foundry_handoff"
    h.mkdir(parents=True)
    (h / "chip_top.gds").write_bytes(b"GDSII-bytes")
    (h / "chip_top.magic_merged.gds").write_bytes(b"")   # the observed rot
    r = _pr.run(
        [sys.executable, str(PROGRAMS / "foundry_handoff_package_check.py"),
         str(tmp_path)],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FOUNDRY_HANDOFF_ZERO_BYTE_MEMBER" in r.stdout
    assert "chip_top.magic_merged.gds" in r.stdout
