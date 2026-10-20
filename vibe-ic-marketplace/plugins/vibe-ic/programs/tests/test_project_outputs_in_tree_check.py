#!/usr/bin/env python3
"""Tests for project_outputs_in_tree_check.py — chip-AGNOSTIC volatile-
storage gate.

Covers:
  1. POSITIVE_PASS — RESULT.md / waivers.json / reports/ have no /tmp
                     references.
  2. POSITIVE_FAIL — RESULT.md cites a /tmp/<file> AND that file exists
                     on disk (live external artifact).
  3. SKIP_NON_APPLICABLE — project tree is empty (no scan target files
                     at all → rc 2, a REAL disclosed skip). #619: this used
                     to be "PASS, the SKIP analogue", and the analogue was
                     the defect — the P0 umbrella reads exit codes, so a
                     skip spelled `0` was aggregated as a clean scan.
  4. SKIP_NO_CONSTRUCT — same (covered by #3).
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / \
    "project_outputs_in_tree_check.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


def _nonqualifying_encoding_report(receipt, status='FAIL', role='audit'):
    return {
        'program': 'flow_compliance_check', 'invoked_as': role,
        'invocation': 'prior-measurement-1730000000000',
        'scope': {'stage': '1', 'steps_judged': ['P0']},
        'overall': status, 'gate_execution_ledger': [],
        'steps': [{'id': 'P0', 'status': status, 'gate_records': [{
            'name': 'interface_encoding_audit', 'verdict': 'INCOMPLETE',
            'reason_class': 'EXECUTION_ERROR',
            'evidence': {'exit_code': 0, 'receipt_state': 'NOT_MEASURED',
                         'receipt_detail': f'receipt={receipt} sha256=0123456789abcdef — '
                                           'producer_inconclusive_or_unknown; fresh.'},
        }]}],
    }


def _encoding_producer(project):
    from test_interface_encoding_audit import _CONTEXT_BINDING_SOURCE
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'neutral.v').write_text(_CONTEXT_BINDING_SOURCE)
    output = project / '.vibeic-state/audit_receipts/p0_receipt_test/interface_encoding_audit'
    result = subprocess.run([sys.executable, str(PROG.parent / 'interface_encoding_audit.py'),
        '--rtl-dir', str(rtl), '--top-module', 'neutral', '--out-dir', str(output)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = output / 'encoding_audit_report.json'
    return {'path':str(receipt), 'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}


def _run_owned_storage(project, producer=None):
    env = os.environ.copy()
    env.pop('VIBEIC_P0_ENCODING_PRODUCER', None)
    if producer is not None:
        env['VIBEIC_P0_ENCODING_PRODUCER'] = json.dumps(producer)
    return subprocess.run([sys.executable, str(PROG), str(project), '--auditor-record',
                           'reports/audit/phase23_completion_audit.json'],
                          capture_output=True, text=True, env=env)


@pytest.mark.parametrize('status', ['FAIL', 'NOT_MEASURED'])
@pytest.mark.parametrize('role', ['audit', 'producer'])
def test_nonqualifying_encoding_diagnostic_is_not_a_current_proof_declaration(tmp_path, status, role):
    receipt = Path('/tmp') / ('lost-proof-' + tmp_path.name) / 'encoding_audit_report.json'
    record = tmp_path / 'reports/negative_measurement.json'
    record.parent.mkdir()
    record.write_text(json.dumps(_nonqualifying_encoding_report(receipt, status, role)))
    original = record.read_bytes()
    actual = _run_owned_storage(tmp_path, _encoding_producer(tmp_path))
    assert actual.returncode == 0, actual.stdout + actual.stderr
    assert 'receipt_detail' in actual.stdout
    assert record.read_bytes() == original
    # Standalone forensics still reports the real loss, with no owner context.
    forensic = _run(tmp_path)
    assert forensic.returncode == 1, forensic.stdout + forensic.stderr
    assert str(receipt) in forensic.stdout


@pytest.mark.parametrize('variant', [
    'overall_pass', 'step_pass', 'qualifying_gate', 'qualifying_receipt', 'failed_exit',
    'other_gate', 'other_program', 'empty_invocation', 'malformed_scope', 'missing_ledger',
    'bad_digest', 'stale_source', 'declared_output_same_path', 'declared_output_other_path',
    'duplicate_key', 'malformed_role', 'malformed_overall', 'malformed_step_status',
    'boolean_exit', 'wrong_step', 'other_reason_class',
])
def test_current_or_untyped_proof_paths_remain_storage_failures(tmp_path, variant):
    receipt = Path('/tmp') / ('lost-proof-' + tmp_path.name) / 'encoding_audit_report.json'
    doc = _nonqualifying_encoding_report(receipt)
    gate = doc['steps'][0]['gate_records'][0]
    if variant == 'overall_pass': doc['overall'] = 'PASS'
    elif variant == 'step_pass': doc['steps'][0]['status'] = 'PASS'
    elif variant == 'qualifying_gate': gate['verdict'] = 'PASS'
    elif variant == 'qualifying_receipt': gate['evidence']['receipt_state'] = 'PASS'
    elif variant == 'failed_exit': gate['evidence']['exit_code'] = 1
    elif variant == 'other_gate': gate['name'] = 'other_audit'
    elif variant == 'other_program': doc['program'] = 'other_producer'
    elif variant == 'empty_invocation': doc['invocation'] = ''
    elif variant == 'malformed_scope': doc['scope'] = []
    elif variant == 'missing_ledger': del doc['gate_execution_ledger']
    elif variant == 'bad_digest': gate['evidence']['receipt_detail'] = gate['evidence']['receipt_detail'].replace('0123456789abcdef', 'not-a-digest')
    elif variant == 'stale_source': gate['evidence']['receipt_detail'] = gate['evidence']['receipt_detail'].replace('fresh.', 'source_manifest_stale_or_wrong_root.')
    elif variant == 'declared_output_same_path': doc['outputs'] = [str(receipt)]
    elif variant == 'declared_output_other_path': doc['outputs'] = [str(receipt.with_name('active_native_context.json'))]
    elif variant == 'malformed_role': doc['invoked_as'] = []
    elif variant == 'malformed_overall': doc['overall'] = {}
    elif variant == 'malformed_step_status': doc['steps'][0]['status'] = []
    elif variant == 'boolean_exit': gate['evidence']['exit_code'] = False
    elif variant == 'wrong_step': doc['steps'][0]['id'] = 4
    elif variant == 'other_reason_class': gate['reason_class'] = 'UNKNOWN'
    text = json.dumps(doc)
    if variant == 'duplicate_key': text = text.replace('"overall": "FAIL"', '"overall": "PASS", "overall": "FAIL"')
    record = tmp_path / 'reports/negative_measurement.json'
    record.parent.mkdir()
    record.write_text(text)
    original = record.read_bytes()
    actual = _run_owned_storage(tmp_path, _encoding_producer(tmp_path))
    assert actual.returncode == 1, actual.stdout + actual.stderr
    assert '[FAIL] project_outputs_in_tree_check:' in actual.stdout
    assert record.read_bytes() == original


@pytest.mark.parametrize('damage', ['absent', 'missing_receipt', 'wrong_digest',
    'outside_context', 'prior_context', 'stale_source', 'no_native_proof', 'foreign_project'])
def test_shape_only_history_needs_a_current_bound_encoding_producer(tmp_path, damage):
    record = tmp_path / 'reports/forged-history.json'
    record.parent.mkdir()
    record.write_text(json.dumps(_nonqualifying_encoding_report(
        Path('/tmp/forged-history-with-no-producer/encoding_audit_report.json'))))
    original = record.read_bytes()
    producer = None if damage == 'absent' else _encoding_producer(tmp_path)
    if producer is not None:
        assert _run_owned_storage(tmp_path, producer).returncode == 0
        receipt = Path(producer['path'])
        payload = json.loads(receipt.read_text())
        if damage == 'missing_receipt': receipt.unlink()
        elif damage == 'wrong_digest': producer['sha256'] = '0'*64
        elif damage == 'stale_source':
            with (tmp_path / 'phase2/stage1/rtl/neutral.v').open('a') as f: f.write('// changed source\n')
        elif damage == 'foreign_project':
            producer = _encoding_producer(tmp_path / 'different-project')
        else:
            cfg = payload['configuration']
            if damage == 'outside_context':
                outside = tmp_path / 'outside-context.json'
                outside.write_bytes(Path(cfg['native_context']).read_bytes())
                cfg['native_context'] = str(outside)
                cfg['native_context_sha256'] = hashlib.sha256(outside.read_bytes()).hexdigest()
            elif damage == 'prior_context':
                prior = _encoding_producer(tmp_path / 'prior-project')
                older = json.loads(Path(prior['path']).read_text())['configuration']
                cfg['native_context'] = older['native_context']
                cfg['native_context_sha256'] = older['native_context_sha256']
            elif damage == 'no_native_proof':
                for key in ('native','native_context','native_context_sha256','native_script'):
                    cfg.pop(key, None)
            receipt.write_text(json.dumps(payload,indent=2)+'\n')
            producer['sha256'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
    result = _run_owned_storage(tmp_path, producer)
    assert result.returncode == 1, result.stdout + result.stderr
    assert '[FAIL] project_outputs_in_tree_check:' in result.stdout
    assert record.read_bytes() == original


@pytest.mark.parametrize('workers', [1, 4])
@pytest.mark.parametrize('damage', ['clean', 'prior_context_replay'])
def test_normal_p0_storage_depends_on_actual_current_encoding_producer(tmp_path, monkeypatch, workers, damage):
    import flow_compliance_check as flow
    from test_interface_encoding_audit import _CONTEXT_BINDING_SOURCE
    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'neutral.v').write_text(_CONTEXT_BINDING_SOURCE)
    docs = project / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module':'neutral'}))
    record = project / 'reports/negative_measurement.json'
    record.parent.mkdir()
    record.write_text(json.dumps(_nonqualifying_encoding_report(
        Path('/tmp/old-negative-no-longer-a-current-declaration/encoding_audit_report.json'))))
    original = record.read_bytes()
    prior = _encoding_producer(tmp_path / 'prior-project')
    older = json.loads(Path(prior['path']).read_text())['configuration']
    actual_run = flow._watchdog.run_host_supervised
    calls = []
    def execute(argv, **kw):
        result = actual_run(argv, **kw)
        gate = next((Path(a).stem for a in argv if a.endswith('_check.py') or
                     a.endswith('interface_encoding_audit.py')), '')
        calls.append(gate)
        if gate == 'interface_encoding_audit' and damage != 'clean':
            output = Path(argv[argv.index('--out-dir')+1]) / 'encoding_audit_report.json'
            payload = json.loads(output.read_text())
            payload['configuration']['native_context'] = older['native_context']
            payload['configuration']['native_context_sha256'] = older['native_context_sha256']
            output.write_text(json.dumps(payload,indent=2)+'\n')
        return result  # actual native process result, never an authored verdict
    monkeypatch.setattr(flow._watchdog,'run_host_supervised',execute)
    monkeypatch.setattr(flow,'_compliance_workers',lambda _:workers)
    monkeypatch.setattr(flow,'_STRUCTURAL_RTL_GATES',
                        ('project_outputs_in_tree_check','interface_encoding_audit'))
    records = []
    flow._run_structural_rtl_gates(project,records_out=records)
    assert [r['name'] for r in records] == ['project_outputs_in_tree_check','interface_encoding_audit']
    assert records[0]['verdict'] == ('PASS' if damage == 'clean' else 'FAIL'), records
    assert records[1]['verdict'] == ('PASS' if damage == 'clean' else 'INCOMPLETE'), records
    assert calls.count('interface_encoding_audit') == calls.count('project_outputs_in_tree_check') == 1
    assert record.read_bytes() == original
    if damage == 'clean':
        receipts = list((project / '.vibeic-state/audit_receipts').rglob('encoding_audit_report.json'))
        assert len(receipts) == 1
        observed_digest = records[0]['evidence'].get('encoding_producer',{}).get('sha256')
        assert observed_digest == hashlib.sha256(receipts[0].read_bytes()).hexdigest()


@pytest.fixture
def volatile_project():
    """A project root that really is on a VOLATILE root, whatever TMPDIR says.

    THIS GATE ONLY EVER LOOKS AT PATHS UNDER `/tmp/`, `/var/tmp/`, `/dev/shm/`
    or `/run/` — `_PATH_RE` admits nothing else, and its own PASS line says so
    ("no /tmp / /var/tmp / /dev/shm / /run paths referenced"). A test whose
    SUBJECT is built under pytest's `tmp_path` therefore measures the gate only
    when the harness's TMPDIR happens to be volatile, and measures the harness
    otherwise.

    MEASURED, one variable, same tree (0b8cca0736) and same pinned image
    `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…`:

        TMPDIR unset (basetemp /tmp/pytest-of-…)         19 passed
        TMPDIR=<bind mount>/tmp (non-volatile)            2 failed, 17 passed

    and the two that fell over were exactly the two below. The run had already
    said so in its own words, three lines above the failure —
    `scratch_root_guard: … NOT under a volatile root (/tmp/, /var/tmp/,
    /dev/shm/, /run/) [the external-storage gate cannot see a subject built
    here]`. That INFO line is the discriminator between a defect in this gate
    and an artefact of the measurement shape; this fixture removes the variable
    it is warning about, so the two tests below measure the gate either way.

    Deliberately NOT a change to the gate: the volatile-prefix scope is what
    the gate is FOR, and widening it to fit a harness would be the tail wagging
    the dog. `test_genuine_external_artifact_still_fails_from_a_volatile_
    project` already pins its own subject the same way, for the same reason.
    """
    import shutil
    import tempfile
    d = Path(tempfile.mkdtemp(dir="/tmp", prefix="voltproj-"))
    assert str(d.resolve()).startswith("/tmp/")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# -- Test 1: POSITIVE_PASS — clean project --

def test_positive_pass_clean_project(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Project results\n"
        "All artifacts under reports/ and rtl/ — no volatile paths.\n"
    )
    (tmp_path / "waivers.json").write_text(json.dumps({}))
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "build.json").write_text(json.dumps({
        "status": "PASS", "artifact": "phase2/stage1/rtl/chip_top.sv",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "no /tmp" in r.stdout


# -- Test 2: POSITIVE_FAIL — live /tmp artifact --

def test_positive_fail_live_tmp(tmp_path):
    # Create an artifact in /tmp that actually exists.
    sentinel = Path("/tmp") / f"vibe_test_artifact_{tmp_path.name}.gds"
    sentinel.write_text("# fake GDS\n")
    try:
        (tmp_path / "RESULT.md").write_text(
            f"GDS produced at: {sentinel}\n"
        )
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        assert "live external-storage" in r.stdout
        assert str(sentinel) in r.stdout
    finally:
        try:
            sentinel.unlink()
        except FileNotFoundError:
            pass


# -- Test 3: SKIP_NON_APPLICABLE — empty project (no scan files) --

def test_skip_empty_project(tmp_path):
    """#619 — VERDICT CHANGED HERE, deliberately: rc 0 -> rc 2.

    An empty project is a scan that opened NOTHING, and this file used to call
    that "PASS, the SKIP analogue". The analogue is the bug:
    `gate_zero_denominator_refuses_check` drives every gate against a fresh
    empty project and reported this one as ZERO_DENOMINATOR_EXITS_ZERO, because
    the P0 umbrella reads exit codes and never the prose that honestly said
    `0 file(s) scanned`.

    It is this gate specifically that may not take the `_ZERO_IS_A_PASS` route:
    its subject IS "outputs written outside the tree", and an empty canonical
    tree is that condition's strongest symptom, not evidence against it.
    """
    # Empty project — no RESULT.md, no waivers.json, no reports/.
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout
    assert "read 0 file(s)" in r.stdout
    assert str(tmp_path) in r.stdout, "the refusal must name the tree it read"


# -- Test 4: SKIP_NO_CONSTRUCT — only unrelated files --

def test_skip_unrelated_files(tmp_path):
    """Files exist, but NONE of them is in `_SCAN_GLOBS`, so the scan still
    opened zero declaration files — same verdict as an empty tree (#619). The
    predicate is `scanned == 0`, not `the directory is empty`."""
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.sv").write_text(
        "module top();\nendmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout
    assert "read 0 file(s)" in r.stdout


# -- Test 5: FAIL — dangling /tmp reference (file gone) --

def test_dangling_tmp_reference(tmp_path):
    """Reference to /tmp/<file> that no longer exists → FAIL, stated as one.

    #2084 STRENGTHENED THIS ASSERTION, deliberately: `[WARN]` -> `[FAIL]`.
    The exit code did not move — it has always been 1 here, because
    `fail_count = len(live) + len(dangling)` — but the only tagged line the
    gate emitted for this case was `[WARN]`, so its own output said the worst
    thing present was a warning while it handed the umbrella a blocking exit.
    That is the disagreement #2084 is about, and a dangling reference is the
    WORSE of the two halves: the artefact is already gone, so unlike a live
    one there is nothing left to copy in. The gate now tags it at the
    severity it exits with.
    """
    (tmp_path / "RESULT.md").write_text(
        "# Lost results\n"
        "Used /tmp/dead_artifact_xyz_does_not_exist_anywhere.gds\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    # No live findings, but dangling counted in fail_count.
    assert "[FAIL]" in r.stdout
    assert "[WARN]" not in r.stdout, (
        "a blocking exit may not be topped by a warning")
    assert "dangling external-path" in r.stdout


# -- Test 6: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "Cache: /tmp/build_cache_123/intermediate.json\n"
    )
    rationale = (
        "Build cache lives in /tmp by design — never used as audit "
        "evidence; ticket BUILD-101 documents the cache architecture "
        "and rotation policy."
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "project_artifacts_external_storage_intentional": rationale,
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_WITH_WAIVER]" in r.stdout


# -- Test 7: usage error --

def test_usage_error():
    r = subprocess.run([sys.executable, str(PROG)], capture_output=True,
                       text=True)
    assert r.returncode == 2


# ── R7 (v1.3.50) — a PINNED plugin worktree is a legit plugin source ─────────

def test_r7_pinned_plugin_wt_prefix_passes(tmp_path):
    """A `/tmp/.../wt-*/vibe-ic-marketplace/plugins/vibe-ic/...` reference (real
    plugin.json) is a legit plugin SOURCE — disclosed, NON-blocking (PASS).

    Uses a real volatile prefix (/tmp) because that is what triggered the
    original false positive."""
    import shutil
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-v1350-"))
    try:
        root = volbase / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": "vibe-ic", "version": "1.3.50"}))
        (root / "programs").mkdir()
        src = root / "programs" / "flow_compliance_check.py"
        src.write_text("# pinned plugin program\n")
        (tmp_path / "RESULT.md").write_text(f"Ran gate at: {src}\n")
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout
        assert "pinned plugin-source" in r.stdout
    finally:
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_pinned_plugin_claude_worktrees_passes(tmp_path):
    """The `.claude/worktrees/<wt>/vibe-ic-marketplace/plugins/vibe-ic/...`
    pinning marker variant is also recognised as plugin source (PASS)."""
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="run-"))
    try:
        root = (volbase / ".claude" / "worktrees" / "agent-xyz"
                / "vibe-ic-marketplace" / "plugins" / "vibe-ic")
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text("{}")
        (root / "phase1_phase2_phase3.yaml").write_text("steps: []\n")
        src = root / "phase1_phase2_phase3.yaml"
        (tmp_path / "RESULT.md").write_text(f"config: {src}\n")
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout
        assert "pinned plugin-source" in r.stdout
    finally:
        import shutil
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_genuine_volatile_output_still_fails(tmp_path):
    """A genuine volatile project OUTPUT (real /tmp GDS, NOT a plugin root) must
    STILL FAIL — the R7 exemption must not create a false-negative."""
    import tempfile
    outdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="realrun-"))
    sentinel = outdir / "design.gds"
    sentinel.write_text("# fake GDS\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"GDS produced at: {sentinel}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


def test_r7_anchor_substring_without_plugin_json_fails(tmp_path):
    """A /tmp path that merely CONTAINS the plugin anchor substring but has NO
    `.claude-plugin/plugin.json` is NOT a real plugin root → must FAIL (the hard
    marker gate blocks the false-negative)."""
    import tempfile
    outdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-fake-"))
    fake = (outdir / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "out.gds")
    fake.parent.mkdir(parents=True)
    fake.write_text("# not a plugin\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"Output: {fake}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


def test_r7_dotdot_escape_out_of_plugin_still_fails(tmp_path):
    """§4.05 false-negative guard — a `..`-escape that starts inside a pinned
    plugin worktree but climbs OUT to a genuine volatile output
    (`.../vibe-ic/../../../design.gds`) must NOT be exempted: normalization
    destroys the plugin anchor, so it is (correctly) FLAGGED."""
    import shutil
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-v1350-"))
    try:
        root = volbase / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text("{}")
        # a real output ABOVE the plugin, reached via .. from inside it
        escaped = volbase / "design.gds"
        escaped.write_text("# real volatile output\n")
        cited = root / ".." / ".." / ".." / "design.gds"   # escapes to volbase
        (tmp_path / "RESULT.md").write_text(f"GDS at: {cited}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_intree_dotdot_still_recognised(tmp_path):
    """An IN-TREE `..` that stays under the plugin root
    (`.../vibe-ic/programs/../plugin.json`) is still recognised as plugin
    source (PASS) — the guard only rejects escapes, not in-tree normalization."""
    import shutil
    import tempfile
    volbase = Path(tempfile.mkdtemp(dir="/tmp", prefix="wt-v1350-"))
    try:
        root = volbase / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
        (root / ".claude-plugin").mkdir(parents=True)
        (root / ".claude-plugin" / "plugin.json").write_text("{}")
        (root / "programs").mkdir()
        (root / "phase3_one_shot_runner.py").write_text("# src\n")
        cited = root / "programs" / ".." / "phase3_one_shot_runner.py"
        (tmp_path / "RESULT.md").write_text(f"ran: {cited}\n")
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[PASS]" in r.stdout
        assert "pinned plugin-source" in r.stdout
    finally:
        shutil.rmtree(volbase, ignore_errors=True)


def test_r7_plugin_root_without_pin_marker_fails(tmp_path):
    """A real plugin root (has plugin.json) but with NO worktree/scratch pin
    marker above the anchor is NOT exempted → FAIL. Keeps the exemption narrow."""
    import tempfile
    outdir = Path(tempfile.mkdtemp(dir="/tmp", prefix="plainroot-"))
    root = outdir / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text("{}")
    src = root / "x.py"
    src.write_text("# x\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"ref: {src}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


# ── In-tree self-references (audit self-inflation) ───────────────────────────
# A project audited from a volatile root (the standard way to audit without
# mutating the original) writes its OWN absolute paths into reports/**/*.json.
# Those are in-tree BY DEFINITION; before the fix the gate reported them as
# external storage, so the audit manufactured its own violations.
#
# `tmp_path` is itself under /tmp, so these tests reproduce the real condition
# without simulating it: the project root genuinely IS at a volatile path.

def test_in_tree_self_reference_is_not_external_storage(tmp_path):
    """The defect direction. A report citing the project's OWN absolute path
    must not be an external-storage finding — the file is inside the tree."""
    own = tmp_path / "phase3" / "stage4" / "gds" / "top.gds"
    own.parent.mkdir(parents=True)
    own.write_text("# GDS\n")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "gds_substance.json").write_text(json.dumps({
        "gds": str(own), "status": "PASS",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "external-storage artifact" not in r.stdout


def test_in_tree_self_reference_is_disclosed_not_silent(volatile_project):
    """The exemption must be visible. A silently-dropped class reads as
    'nothing was there' — the gate has to say what it excused.

    The project root must itself be VOLATILE for this class to exist at all:
    an in-tree self-reference is only a candidate finding when the tree is
    somewhere `_PATH_RE` looks. See the `volatile_project` fixture.
    """
    proj = volatile_project
    own = proj / "phase2" / "stage2" / "synth" / "netlist.v"
    own.parent.mkdir(parents=True)
    own.write_text("// netlist\n")
    (proj / "reports").mkdir()
    (proj / "reports" / "synth.json").write_text(json.dumps(
        {"netlist": str(own)}))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "in-tree self-reference" in r.stdout
    assert str(proj) in r.stdout


def test_genuine_external_artifact_still_fails_from_a_volatile_project(
        tmp_path):
    """ANTI-RUBBER-STAMP. The project root is volatile, so a blanket
    'everything under /tmp is fine' rule would pass this — it must not.
    A path OUTSIDE the project is still external storage."""
    import tempfile
    outside = Path(tempfile.mkdtemp(dir="/tmp", prefix="outside-"))
    stray = outside / "chip_top.gds"
    stray.write_text("# real GDS left outside the tree\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"the GDS is at {stray}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        assert str(stray) in r.stdout
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)


def test_symlink_out_of_the_tree_is_still_external(volatile_project):
    """A path that is LEXICALLY inside the project but symlinks OUT of it is
    still external storage — the artifact does not live in the tree. Pins
    that the containment test resolves rather than string-prefixes.

    SCOPE, stated because this test does not cover it and a reader will look:
    the ADMISSION filter (`_PATH_RE`) is a string prefix over the CITED text,
    and only `_inside_project` resolves. So a report citing a lexically-inside
    path that symlinks onto volatile storage is invisible to this gate whenever
    the project root is NOT itself volatile — the ordinary case for a real run
    under `$HOME`. That is a gate hole, not a harness artefact, and it is
    reported separately rather than papered over here; this test's subject is
    the resolution step, and it is pinned on a volatile root so it measures
    that step rather than the harness's TMPDIR.
    """
    proj = volatile_project
    import tempfile
    outside = Path(tempfile.mkdtemp(dir="/tmp", prefix="linktarget-"))
    target = outside / "netlist.v"
    target.write_text("// lives outside\n")
    inside = proj / "steps" / "9_synth"
    inside.mkdir(parents=True)
    link = inside / "netlist.v"
    link.symlink_to(target)
    try:
        (proj / "reports").mkdir()
        (proj / "reports" / "s.json").write_text(json.dumps(
            {"netlist": str(link)}))
        r = _run(proj)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)


def test_project_root_itself_cited_is_in_tree(tmp_path):
    """The boundary case: a report citing the project ROOT (not a child).
    `p == project` must count as inside, not merely `project in p.parents`."""
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "audit.json").write_text(json.dumps(
        {"project": str(tmp_path)}))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


# ── #619 — the refusal must not become a way to duck the scan ────────────────

def test_one_declaration_file_is_enough_to_make_it_answer(tmp_path):
    """THE REFUSAL'S OWN FALSE-POSITIVE GUARD. The moment the scan opens ONE
    file the gate is back on the hook: rc 0, and the count it discloses is 1.
    A refusal that widened past `scanned == 0` would switch the gate off for
    thinly-populated projects."""
    (tmp_path / "RESULT.md").write_text("all artefacts under reports/\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "1 file(s) scanned" in r.stdout


def test_a_real_violation_in_a_one_file_project_is_still_rc_1(tmp_path):
    """THE ANTI-RUBBER-STAMP. rc 2 must not have become the answer for any
    project the gate can still read: the smallest project that CAN carry a
    violation still FAILs on one."""
    import tempfile
    outside = Path(tempfile.mkdtemp(dir="/tmp", prefix="r619-outside-"))
    stray = outside / "chip_top.gds"
    stray.write_text("# a real GDS left outside the tree\n")
    try:
        (tmp_path / "RESULT.md").write_text(f"GDS produced at: {stray}\n")
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        assert str(stray) in r.stdout
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)
