#!/usr/bin/env python3
"""The canonical Step-4 record must not contradict the run that produced it.

`step_reference_tb`'s connectivity bridge writes `phase2/stage1/sim/results.xml`
— the one path the flow treats as canonical — and its waiver text says
functional verification is "DEFERRED to a per-IC oracle TB". In the SAME Phase-2
pass, `professional_tb_gen` runs FIRST and, when its Tier-3 hook is filled,
closes exactly that deferral with a real cocotb run against the real rtl/.
Nothing reconciled the two, so the canonical record kept saying
`functional_verified=false` while the run's own JUnit transcript said otherwise.

MEASURED, sha256 x sky130A, plugin 1.15.87:

    phase2/stage1/sim/results.xml                 functional_verified=false
    phase2/stage1/sim_professional/*/results.xml  tests=1 failures=0 errors=0

The half that keeps this honest is the REVERSE direction, and most of the cases
below are it: a claim of functional verification is a forgery unless the record
can SHOW the transcript, and every unshowable shape — no pointer, a dangling
pointer, a non-JUnit file, a zero-test result, a failing result — must still be
refused exactly as it was before. Those cases pass on BOTH trees by design.

All fixtures are synthetic; no chip, PDK or vendor literal decides anything.
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cpu_functional_oracle_waiver_check as GATE  # noqa: E402

TRACK_REASON = "class 'widget_engine' verification_track='generic_full_stack'"
TOP = "widget_engine"


def _junit(tests: int, failures: int = 0, errors: int = 0,
           skipped: int = 0) -> str:
    """A cocotb-shaped JUnit document with `tests` testcase elements.

    The count and the elements are kept CONSISTENT on purpose: `parse_junit`
    falls back to counting `<testcase>` when the attribute reads 0, so a
    `tests="0"` suite that still lists a case is not a vacuous result and
    would not exercise the control it looks like it exercises.
    """
    cases = "".join(
        f'<testcase classname="tb_{TOP}" name="oracle{i}" time="1.0"/>'
        for i in range(tests))
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f'<testsuites name="cocotb tests"><testsuite name="tb_{TOP}" '
        f'errors="{errors}" failures="{failures}" skipped="{skipped}" '
        f'tests="{tests}" time="1.0">'
        f"{cases}"
        "</testsuite></testsuites>\n")


def _project(tmp_path: Path, professional: "str | None") -> Path:
    """A project with a completed connectivity transcript, optionally beside a
    professional-TB result."""
    proj = tmp_path / "proj"
    fs = proj / "phase2" / "stage1" / "sim_full_stack" / "run"
    fs.mkdir(parents=True, exist_ok=True)
    transcript = fs / "full_stack.log"
    transcript.write_text(
        "binding widget_engine\nFULL_STACK_TB_CHECKS pass=4 fail=0\n"
        "FULL_STACK_TB_DONE\n", encoding="utf-8")
    if professional is not None:
        pd = proj / "phase2" / "stage1" / "sim_professional" / TOP
        pd.mkdir(parents=True, exist_ok=True)
        (pd / "results.xml").write_text(professional, encoding="utf-8")
    return proj








# ===========================================================================
# forward — the run's own oracle must reach the canonical record
# ===========================================================================


def test_professional_functional_result_does_not_require_connectivity_xml(tmp_path):
    proj = _project(tmp_path, _junit(tests=3))
    rc, detail = GATE._evaluate(proj)
    assert rc == 0, detail
    assert 'professional-TB' in detail
    assert not (proj / 'phase2/stage1/sim/results.xml').exists()


@pytest.mark.parametrize('damage', ['failed_suite', 'unexecuted_case'])
def test_without_connectivity_xml_real_functional_obligations_still_apply(tmp_path, damage):
    proj = _project(tmp_path, _junit(tests=3, failures=int(damage == 'failed_suite')))
    if damage == 'unexecuted_case':
        docs = proj / 'phase1/generated_docs'
        docs.mkdir(parents=True)
        (docs / 'L10_TEST_CASES.json').write_text(json.dumps({
            'test_cases': [{'name': 'independent_case', 'kind': 'functional_vector',
                            'input': {'a': 1}, 'expected': {'y': 1}}]}))
    rc, detail = GATE._evaluate(proj)
    assert rc != 0, detail






















# ===========================================================================
# reverse controls — these must hold on BOTH trees
# ===========================================================================
