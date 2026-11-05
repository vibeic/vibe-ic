"""Execute the shipped landing bodies and completion writer with bounded probes.

Expensive check programs are stand-ins; dispatch, scope, capture, emit and exact
completion population are the real repository artifacts. No full suite/census
is executed by this selection.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

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


def extract(name, source=None):
    source = LAND.read_text() if source is None else source
    m = re.search(rf'^{name}\(\) \{{.*?^\}}$', source, re.M | re.S)
    assert m, name
    return m.group(0)


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


def plan_shell():
    return subprocess.check_output([sys.executable,
        str(ROOT / 'tools/ci/landing_execution_plan.py'), 'shell'], text=True)


def exercise_plan(tmp_path, *, mutation=''):
    """Run every actual unit body, substituting only costly commands and setup."""
    source = LAND.read_text()
    functions = '\n'.join(m.group(0) for m in re.finditer(
        r'^[a-zA-Z_][a-zA-Z_0-9]*\(\) \{.*?^\}$', source, re.M | re.S))
    work = shlex.quote(str(tmp_path))
    runtime = shlex.quote(str(ROOT))
    script = f'''set -uo pipefail
WORK={work}; ROOT="$WORK"; RUNTIME_ROOT={runtime}
PROGRAMS="$RUNTIME_ROOT/vibe-ic-marketplace/plugins/vibe-ic/programs"
PLUGIN="$PROGRAMS/.."; PJSON="$PLUGIN/.claude-plugin/plugin.json"
LANE_DIR="$WORK/lanes"; mkdir -p "$LANE_DIR"
BASE=HEAD; RANGE=HEAD..HEAD; GK_RANGE_N=1
FAILED=0; LANDING_NEXT=0; LANDING_RECORD_ENABLED=1
LANDING_JOURNAL="$WORK/journal.json"
LANDING_RECORD_TOOL="$RUNTIME_ROOT/tools/ci/landing_completion_record.py"
LANDING_PROGRESS_TOOL=progress-test-stub
LANDING_COMPLETION="$WORK/completion.json"
LANE_WIDTH=1; LANE_LIVE_PIDS=""; LANE_LAUNCHED=""
LANE_WAIT_RC=0; LANE_BROKEN=0; EMIT_RC=0; EMIT_OUT=""
FP=""; WG_BASE=""; GK_HYG_RECORD=""; GK_HYG_SUBJECT=""; GK_REVIEW_SUBJECT=""
GK_HYG=(); GK_HYG_ENV=(); HYGIENE_POOL=1
GK_REVIEW_BUDGET_S=10
{plan_shell()}
{functions}
# Expensive program boundaries only; append remains the real protected writer.
python3() {{
  if [ "$1" = "$LANDING_RECORD_TOOL" ] && [ "${{2:-}}" = append ]; then
    command python3 "$@"
  elif [ "$1" = "$PROGRAMS/gatekeeper_review.py" ]; then
    echo VERDICT: SCOPED_REVIEW_OK
  else
    printf 'probe %s\\n' "$*" >> "$WORK/commands"
  fi
}}
timeout() {{ shift 3; "$@"; }}
env() {{ while [[ "$1" == *=* ]]; do shift; done; "$@"; }}
export -f python3
export LANDING_RECORD_TOOL PROGRAMS WORK
# These suite bodies are the costly boundaries below fn_capture.
run_pytest() {{ echo '  PASS  targeted tests'; }}
run_repo_tools_pytest() {{ echo '  PASS  repo tools tests'; }}
run_unselectable_pytest() {{ echo '  PASS  unselectable tests'; }}
gk_review_subject_prepare() {{ :; }}
gk_review_subject_release() {{ :; }}
{mutation}
landing_plan_dispatch cheap
landing_plan_dispatch before_window
lane_run_window
lane_emit_window
landing_plan_dispatch after_window
printf 'FINISHED=%s FAILED=%s\\n' "$LANDING_NEXT" "$FAILED"
'''
    # The hygiene script boundary is an actual process and gets captured normally.
    # Its real absolute runtime path is intercepted by a shell function only in
    # this bounded harness, never by production's evidence trust path.
    script = script.replace('{mutation}', mutation)
    script = script.replace('export -f python3', '''bash() { printf 'hygiene-producer\\n' >> "$WORK/commands"; return 0; }
export -f python3''')
    return subprocess.run(['bash'], input=script, text=True, capture_output=True,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=30)


def test_real_dispatch_capture_emit_and_append_share_one_plan(tmp_path):
    result = exercise_plan(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = json.loads((tmp_path / 'journal.json').read_text())['gates']
    assert [r['label'] for r in rows] == list(REQUIRED)
    assert 'FINISHED=29 FAILED=0' in result.stdout, result.stdout
    assert (tmp_path / 'commands').read_text().count('hygiene-producer') == 1


@pytest.mark.parametrize('mutation', [
    'landing_unit_cheap_nda_messages() { :; }',
    'landing_unit_cheap_nda_messages() { landing_record "$1" PASS 0 x; landing_record "$1" PASS 0 x; }',
    'landing_unit_cheap_nda_messages() { landing_record foreign PASS 0 x; }',
    'unset -f landing_unit_full_repo_hygiene',
])
def test_missing_duplicate_unexpected_or_missing_handler_stops_parent(tmp_path, mutation):
    result = exercise_plan(tmp_path, mutation=mutation)
    assert result.returncode == 2, result.stdout + result.stderr
    assert '[NORECORD]' in result.stderr
    assert 'FINISHED=' not in result.stdout


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


def connected_landing(tmp_path, *, hygiene_rc=0, hygiene_missing=False):
    programs = tmp_path / 'programs'; programs.mkdir()
    runtime = tmp_path / 'runtime'; (runtime / 'tools/ci').mkdir(parents=True)
    suite = runtime / 'tools/ci/repo_hygiene_gates.sh'
    count = tmp_path / 'producer-count'
    suite.write_text(f'''#!/bin/bash
printf 'run\\n' >> {shlex.quote(str(count))}
record=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = --summary-json ]; then record="$2"; shift; fi
  shift
done
'''+('' if hygiene_missing else '''printf '%s' '{"declared":1,"gates":[{"label":"probe","state":"PASS","seconds":1}]}' > "$record"
''')+f'exit {hygiene_rc}\n')
    wrapper = _REVIEW_WRAPPER.replace('PROGRAMS', repr(str(PROGRAMS))).replace('SCRIPT', repr(str(suite)))
    (programs / 'gatekeeper_review.py').write_text(wrapper)
    # Debt is a display in this harness; the actual ledger policy has separate tests.
    (programs / 'gate_red_since_check.py').write_text('print("debt display")\n')
    names = ['lane_hygiene', 'run_gatekeeper_review', 'run_capture', 'lane_write',
             'lane_reported', 'lane_resolve', 'run_emit', 'run', 'landing_record',
             'landing_output_sha']
    source = LAND.read_text()
    preamble = ''
    if 'landing_plan_dispatch()' in source:
        names += ['landing_plan_dispatch', 'landing_unit_full_repo_hygiene']
        preamble = plan_shell()
    funcs = '\n'.join(extract(n, source) for n in names)
    script = f'''set -uo pipefail
WORK={shlex.quote(str(tmp_path))}; ROOT="$WORK"
RUNTIME_ROOT={shlex.quote(str(runtime))}; PROGRAMS={shlex.quote(str(programs))}
LANE_DIR="$WORK/lanes"; mkdir -p "$LANE_DIR"
GK_HYG_RECORD="$WORK/hygiene.json"; GK_HYG=(--summary-json "$GK_HYG_RECORD"); GK_HYG_ENV=()
GK_REVIEW_RECORD="$WORK/review-hygiene.json"
HYGIENE_POOL=1; LANE_WIDTH=1; GK_REVIEW_BUDGET_S=15; BASE=base
LANE_BROKEN=0; LANE_WAIT_RC=0; EMIT_RC=0; EMIT_OUT=""
LANDING_RECORD_ENABLED=0; FAILED=0; LANDING_NEXT=0
{preamble}
{funcs}
lane_hygiene
'''
    # Full parent ordering is checked by exercise_plan. Here the two connected
    # producers/consumers run without executing unrelated expensive units.
    script += 'LANDING_NEXT=23\nrun_emit "full:repo-hygiene" "repo hygiene gates"\n'
    script += 'LANDING_NEXT=25\nrun "full:gatekeeper-review" "structural review" run_gatekeeper_review\n'
    script += 'printf "FAILED=%s\\n" "$FAILED"\n'
    result = subprocess.run(['bash'], input=script, capture_output=True, text=True, timeout=25)
    return result, count, tmp_path / 'hygiene.json'


def test_connected_real_hygiene_and_review_produce_hygiene_once(tmp_path):
    result, count, _ = connected_landing(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert count.read_text().splitlines() == ['run'], result.stdout + result.stderr
    assert 'SCOPED_REVIEW_OK' in (tmp_path / 'lanes/full:gatekeeper-review.out').read_text()
    assert 'FAILED=0' in result.stdout, result.stdout


def test_new_hygiene_red_still_blocks_parent_with_scoped_success(tmp_path):
    result, count, _ = connected_landing(tmp_path, hygiene_rc=1)
    assert result.returncode == 0, result.stdout + result.stderr
    assert count.read_text().splitlines() == ['run']
    assert 'FAILED=1' in result.stdout, result.stdout


def test_scoped_success_cannot_finish_without_required_hygiene_record(tmp_path, monkeypatch):
    result, _, record = connected_landing(tmp_path, hygiene_missing=True)
    assert result.returncode == 0, result.stdout + result.stderr
    journal = tmp_path / 'journal.json'
    for label in REQUIRED:
        C.append(journal, label=label, state='PASS', returncode=0, output_sha256='a'*64)
    monkeypatch.setattr(C, '_git', lambda *a: 'b'*40)
    for key, value in {'GATEKEEPER_VERIFY_ARM':'A2', 'GATEKEEPER_BASE':'b'*40,
                       'GATEKEEPER_BENCHMARK_DATA_SHA':'c'*40,
                       'VIBEIC_LANDING_PROGRESS_NONCE':'d'*64}.items():
        monkeypatch.setenv(key, value)
    selection = tmp_path / 'selection'; selection.write_text('one\n')
    progress = tmp_path / 'progress'; progress.write_text('{}\n')
    with pytest.raises(C.Refusal, match='hygiene|cannot read'):
        C.finish(journal, failed=0, hygiene_path=record,
                 selection_path=selection, progress_plan_path=progress)
