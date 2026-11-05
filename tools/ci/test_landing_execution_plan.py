"""Execute the shipped landing bodies and completion writer with bounded probes.

Expensive check programs are stand-ins; dispatch, scope, capture, emit and exact
completion population are the real repository artifacts. No full suite/census
is executed by this selection.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get('CXARCH_SUBJECT_ROOT', Path(__file__).resolve().parents[2]))
PROGRAMS = ROOT / 'vibe-ic-marketplace/plugins/vibe-ic/programs'
LAND = ROOT / 'tools/gatekeeper-land.sh'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

C = load('_cx_completion', ROOT / 'tools/ci/landing_completion_record.py')
# Frozen pre-repair executable population, including #2176. This is a control
# against dropping requirements, not production authority.
REQUIRED = tuple(('cheap:' + x) for x in (
    'nda-messages', 'nda-content', 'version', 'agent-scope', 'benchmark-structure',
    'git-prohibition',
    'prose-polarity', 'nested-progress-pin',
    'competing-claims-report', 'worktree-clean', 'scratch-report', 'hygiene-ratchet')) + tuple(
    ('full:' + x) for x in ('write-guard-baseline', 'targeted-tests', 'repo-tools-tests',
    'unselectable-tests', 'census-freshness', 'repo-hygiene',
    'gatekeeper-review', 'write-guard-final',
    'worktree-fingerprint-final', 'completion-record'))




def test_real_2176_protected_append_accepts_the_existing_executable_population(tmp_path):
    accepted = []
    refusal = None
    for unit in REQUIRED:
        try:
            C.append(tmp_path / 'journal.json', label=unit, state='PASS',
                     returncode=0, output_sha256='a' * 64)
            accepted.append(unit)
        except C.Refusal as exc:
            refusal = str(exc)
            break
    assert accepted == list(REQUIRED), (accepted, refusal)










_REVIEW_WRAPPER = r'''
import json, pathlib, subprocess, sys
sys.path.insert(0, PROGRAMS)
import gatekeeper_review as R
# Bound expensive structural dependencies; retain real review, CLI and scope.
for name in list(vars(R)):
    if name.endswith('_gate') and callable(getattr(R, name)):
        setattr(R, name, lambda *a, _name=name, **kw: R.GateResult(_name, 0, 'probe'))
R.role_scope_gate = lambda *a: (R.GateResult('role_scope', 0, 'probe'), False)
R.changed_files = lambda *a: []
R._git_show_json_version = lambda *a: '1.0.1' if a[1] == 'HEAD' else '1.0.0'
R._git_show_marketplace_version = lambda *a: '1.0.1'
def hygiene(repo, **kw):
    record = kw['summary_out']
    rc = subprocess.run(['bash', SCRIPT, '--summary-json', str(record)]).returncode
    return R._hygiene_verdict(json.loads(record.read_text()), rc)
R.repo_hygiene_gate = hygiene
raise SystemExit(R.main(sys.argv[1:]))
'''
