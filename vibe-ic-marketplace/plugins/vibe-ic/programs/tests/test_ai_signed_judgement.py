"""A program PASS cannot sign its own eight conditional AI judgements."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_compliance_check as audit  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


FILES = {
    "D1": {"phase1/generated_docs/L1_DATASHEET.json": "{}"},
    "1": {"phase2/stage1/fallback_skill.md": "spec-to-rtl",
          "phase2/stage1/rtl/top.v": "module top; endmodule"},
    "4": {"reports/phase2/gates/professional_tb.json":
          '{"dut_kind":"expert_reference"}',
          "phase2/stage1/sim_professional/expert_reference_tb.py": "expected = 1"},
    "5": {"phase2/stage1/formal/formal_authoring_request.json": "{}",
          "phase2/stage1/formal/formal_expert_review.json": "{}"},
    "A1": {"phase3/analog/block/spec_gap.json": "{}",
           "phase3/analog/block/spec.json": "{}"},
    "A2": {"phase3/analog/block/topology_gap.json": "{}",
           "phase3/analog/block/topology.md": "a topology"},
    "A9": {"phase3/mixed_signal/cosim/mixed_signal_results.json": "{}"},
    "36": {"reports/phase3/layout_receipts.json": "{}",
           "waivers.json": '{"waived_steps":[{"id":36}]}'},
}


def _digest(root, names):
    digest = hashlib.sha256()
    for name in sorted(names):
        path = root / name
        rel = name.encode()
        data = path.read_bytes()
        digest.update(len(rel).to_bytes(8, "big"))
        digest.update(rel)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _judge(root, sid, first):
    step = {"id": sid, "name": sid, "stage": "test",
            "required_outputs": [first],
            "gate": {"files_exist": [first]}}
    return audit.check_step(root, step, {})


@pytest.mark.parametrize("sid", FILES)
def test_ai_handoff_needs_receipt_for_exact_current_evidence(tmp_path, sid):
    names = FILES[sid]
    for rel, content in names.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    first = next(iter(names))
    receipt = tmp_path / "reports/audit/ai_judgements" / f"{sid}.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)

    missing = _judge(tmp_path, sid, first)
    assert missing.status == "NOT_MEASURED"
    assert missing.reason_class == "awaiting_signed_judgement"

    signed = {"schema": "vibeic.ai-judgement.v1", "step_id": sid,
              "evidence_sha256": _digest(tmp_path, names), "verdict": "PASS",
              "signed_by": "ic-expert-agent", "judgement": "reviewed this evidence"}
    receipt.write_text(json.dumps(signed))
    credited = _judge(tmp_path, sid, first)
    assert credited.status == "PASS", credited.reasons

    # A changed producer/AI artefact makes the same signature stale.
    (tmp_path / first).write_text(names[first] + (" \n" if sid == "4" else " changed"))
    stale = _judge(tmp_path, sid, first)
    assert stale.status == "NOT_MEASURED"
    assert stale.reason_class == "awaiting_signed_judgement"


def test_program_only_step_has_no_ai_signoff_requirement(tmp_path):
    path = tmp_path / "phase2/stage1/rtl/top.v"
    path.parent.mkdir(parents=True)
    path.write_text("module top; endmodule")
    assert _judge(tmp_path, "1", "phase2/stage1/rtl/top.v").status == "PASS"


def test_checked_in_l_docs_need_a_review_of_the_copied_evidence(tmp_path):
    source = require_repo(
        "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/"
        "stage_phase1_on_pass_review/accept_lpddr5/phase1/generated_docs")
    target = tmp_path / "phase1/generated_docs"
    shutil.copytree(source, target)
    first = next(target.glob("L*.json"))
    rel = first.relative_to(tmp_path).as_posix()
    assert _judge(tmp_path, "D1", rel).status == "NOT_MEASURED"
    import ai_signed_judgement as judgement
    digest = judgement.evidence_sha256(tmp_path, "D1")
    receipt = tmp_path / "reports/audit/ai_judgements/D1.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({
        "schema": judgement.SCHEMA, "step_id": "D1",
        "evidence_sha256": digest, "verdict": "PASS",
        "signed_by": "ic-expert-agent", "judgement": "reviewed copied L documents",
    }))
    assert _judge(tmp_path, "D1", rel).status == "PASS"
    first.write_bytes(first.read_bytes() + b"\n")
    assert _judge(tmp_path, "D1", rel).status == "NOT_MEASURED"










def test_completion_audit_exits_nonzero_while_signature_is_pending(tmp_path):
    doc = tmp_path / "phase1/generated_docs/L1_DATASHEET.json"
    doc.parent.mkdir(parents=True)
    doc.write_text("{}")
    flow = tmp_path / "flow.yaml"
    flow.write_text("steps:\n  - id: D1\n    name: test D1\n"
                    "    stage: stage_phase1\n"
                    "    required_outputs: [phase1/generated_docs/L1_DATASHEET.json]\n"
                    "    gate:\n"
                    "      files_exist: [phase1/generated_docs/L1_DATASHEET.json]\n")
    out = tmp_path / "audit.json"
    cmd = [sys.executable, str(Path(audit.__file__)), str(tmp_path),
           "--flow-def", str(flow), "--strict", "--skip-yosys-gates",
           "--json", str(out)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 1
    assert "Overall: NOT_MEASURED" in run.stdout
    rows = json.loads(out.read_text())["steps"]
    d1 = next(row for row in rows if str(row["id"]) == "D1")
    assert d1["reason_class"] == "awaiting_signed_judgement"


def test_step36_perc_manual_review_also_needs_judgement(tmp_path):
    checklist = tmp_path / "reports/phase3/layout_receipts.json"
    perc = tmp_path / "reports/phase3/perc_equivalent.json"
    for path in (checklist, perc):
        path.parent.mkdir(parents=True, exist_ok=True)
    checklist.write_text('{"release_scope":"RELEASE_CANDIDATE"}')
    perc.write_text('{"categories":[{"status":"MANUAL_REVIEW"}]}')
    row = _judge(tmp_path, "36", checklist.relative_to(tmp_path).as_posix())
    assert row.status == "NOT_MEASURED"
    assert row.reason_class == "awaiting_signed_judgement"


@pytest.mark.parametrize("sid,request_path", [
    (5, "phase2/stage1/formal/formal_authoring_request.json"),
    ("A9", "phase1/analog/analog_block_list.json"),
])
def test_env_unavailable_waiver_stays_disclosed_without_ai_credit(
        tmp_path, sid, request_path):
    path = tmp_path / request_path
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    step = {"id": sid, "name": str(sid), "stage": "test",
            "required_outputs": ["missing.txt"],
            "gate": {"files_exist": ["missing.txt"]}}
    row = audit.check_step(tmp_path, step, {
        sid: {"_env_unavailable": True, "reason": "tool unavailable",
              "approver": "reviewer"}})
    assert row.status == "PASS_WITH_WAIVERS"
    assert any("ENV_UNAVAILABLE waiver applied" in reason
               for reason in row.reasons)
    assert any("grants no AI PASS credit" in reason for reason in row.reasons)


def test_other_waiver_does_not_sign_expert_review(tmp_path):
    checklist = tmp_path / "reports/phase3/layout_receipts.json"
    checklist.parent.mkdir(parents=True)
    checklist.write_text('{"release_scope":"RELEASE_CANDIDATE"}')
    (tmp_path / "waivers.json").write_text('{"waived_steps":[{"id":36}]}')
    step = {"id": "36", "name": "36", "stage": "test",
            "required_outputs": ["reports/phase3/layout_receipts.json"],
            "gate": {"files_exist": ["reports/phase3/layout_receipts.json"]}}
    row = audit.check_step(tmp_path, step, {
        "36": {"reason": "manual waiver", "approver": "reviewer"}})
    assert row.status == "NOT_MEASURED"
    assert row.reason_class == "awaiting_signed_judgement"


# Step36 reviews existing physical exceptions; Step38 owns package publication.
_PHYSICAL_REVIEW_FILES = (
    'reports/phase3/layout_receipts.json', 'phase3/final/metrics.json',
    'reports/phase3/signoff_metrics_aggregate.json', 'waivers.json',
    'reports/phase3/perc_equivalent.json')


def _physical_review_project(root, *, requested=True):
    documents = [
        {'release_scope': 'RELEASE_CANDIDATE', 'gds_sha256': 'a' * 64},
        {'route__drc_errors': 0, '__provenance__': {'route__drc_errors': {'sha256': 'b' * 64}}},
        {'schema': 'vibeic.signoff-metrics.v1', 'keys': 1, 'measured': 1, 'rows': []},
        {'waived_steps': [{'id': 36, 'reason': 'review physical exception'}]} if requested else {},
        {'categories': [{'status': 'MANUAL_REVIEW' if requested else 'PASS'}]}]
    for rel, doc in zip(_PHYSICAL_REVIEW_FILES, documents):
        path = root / rel; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))
    return root


def _physical_review_receipt(root, verdict='PASS'):
    path = root / 'reports/audit/ai_judgements/36.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        'schema': 'vibeic.ai-judgement.v1', 'step_id': '36',
        'evidence_sha256': _digest(root, _PHYSICAL_REVIEW_FILES), 'verdict': verdict,
        'signed_by': 'synthetic-physical-reviewer',
        'judgement': 'Reviewed the synthetic physical exception, metrics and PERC evidence.'}))
    return path


def test_step36_physical_review_survives_later_package_publication(tmp_path):
    import ai_signed_judgement as judgement
    root = _physical_review_project(tmp_path)
    first = _PHYSICAL_REVIEW_FILES[0]
    assert _judge(root, '36', first).status == 'NOT_MEASURED'
    _physical_review_receipt(root)
    assert _judge(root, '36', first).status == 'PASS', 'physical review must not require a future Step38 checklist'
    original = judgement.evidence_sha256(root, '36')
    later = root / 'reports/audit/tapeout_checklist.json'
    later.parent.mkdir(parents=True, exist_ok=True)
    observations = []
    for todo in ('future package not assembled', 'future package inventory refreshed'):
        later.write_text(json.dumps({'verdict': 'PENDING', 'reviewer_todo': [todo]}))
        volatile = root / 'reports/phase3/gates/stage3_compliance.json'
        volatile.parent.mkdir(parents=True, exist_ok=True)
        volatile.write_text(json.dumps({'generated_at': todo}))
        row = _judge(root, '36', first)
        observations.append({'status': row.status, 'digest': judgement.evidence_sha256(root, '36')})
        assert row.status == 'PASS'
        assert judgement.evidence_sha256(root, '36') == original
    (root / 'PHYSICAL_REVIEW_OBSERVATIONS.json').write_text(json.dumps(observations))


def test_later_package_work_does_not_create_a_step36_review_request(tmp_path):
    root = _physical_review_project(tmp_path, requested=False)
    checklist = root / 'reports/audit/tapeout_checklist.json'
    checklist.parent.mkdir(parents=True, exist_ok=True)
    for verdict in ('PENDING', 'PASS_WITH_OPEN_ITEMS'):
        checklist.write_text(json.dumps({'verdict': verdict, 'pending_foundry_items': ['future38'],
                                        'reviewer_todo': ['final-package review']}))
        assert _judge(root, '36', _PHYSICAL_REVIEW_FILES[0]).status == 'PASS', 'Step38 package work must not trigger a new Step36 review'
    (root / 'waivers.json').write_text('{"waived_steps":[{"id":36}]}')
    assert _judge(root, '36', _PHYSICAL_REVIEW_FILES[0]).status == 'NOT_MEASURED'
    (root / 'waivers.json').write_text('{}')
    (root / 'reports/phase3/perc_equivalent.json').write_text('{"categories":[{"status":"MANUAL_REVIEW"}]}')
    assert _judge(root, '36', _PHYSICAL_REVIEW_FILES[0]).status == 'NOT_MEASURED'


def test_step36_material_mutations_missing_layout_and_rejected_review_stay_uncredited(tmp_path):
    import ai_signed_judgement as judgement
    for i, rel in enumerate(_PHYSICAL_REVIEW_FILES):
        root = _physical_review_project(tmp_path / str(i))
        _physical_review_receipt(root)
        assert _judge(root, '36', _PHYSICAL_REVIEW_FILES[0]).status == 'PASS', 'current physical evidence must accept its genuine review'
        path = root / rel
        path.write_bytes(path.read_bytes() + b'\n ')
        assert not judgement.check(root, '36')[0], rel
        assert _judge(root, '36', _PHYSICAL_REVIEW_FILES[0]).status == 'NOT_MEASURED'
    root = _physical_review_project(tmp_path / 'missing-layout')
    _physical_review_receipt(root)
    (root / _PHYSICAL_REVIEW_FILES[0]).unlink()
    assert _judge(root, '36', _PHYSICAL_REVIEW_FILES[0]).status == 'FAIL'
    credit, detail = judgement.check(root, '36')
    assert not credit and 'no AI review output to sign' in detail
    root = _physical_review_project(tmp_path / 'rejected')
    _physical_review_receipt(root, 'FAIL')
    assert judgement.check(root, '36', expected_verdict='FAIL')[0]
    assert not judgement.check(root, '36')[0]
    assert _judge(root, '36', _PHYSICAL_REVIEW_FILES[0]).status == 'NOT_MEASURED'
