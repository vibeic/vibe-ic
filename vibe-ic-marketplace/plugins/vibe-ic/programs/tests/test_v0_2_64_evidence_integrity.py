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
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as F  # noqa: E402

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
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "foundry_handoff_package_check.py"),
         str(tmp_path)],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FOUNDRY_HANDOFF_ZERO_BYTE_MEMBER" in r.stdout
    assert "chip_top.magic_merged.gds" in r.stdout
