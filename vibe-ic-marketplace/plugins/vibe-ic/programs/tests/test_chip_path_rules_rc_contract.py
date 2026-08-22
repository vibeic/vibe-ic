"""The twelve chip-path rules obey ONE rc contract, and a crash is never a finding.

WHY THIS FILE EXISTS SEPARATELY FROM THE TWELVE PER-RULE TESTS
==============================================================
Each rule has its own test asserting its own verdicts. What none of them can
assert is the property the whole FAMILY has to share, because it is about what
happens when the checker itself goes wrong:

    Python exits 1 on an uncaught exception.

rc=1 is this family's code for "I found a defect". So a checker that raises —
a malformed input reaching an unguarded path, a helper import that fails, a
permission error — reports A FINDING it never made, in the one direction that
costs someone real work. The brief this lane implements names it exactly: an
escaped traceback that becomes rc=1 is an unearned claim about silicon.

Every one of the twelve wraps its scan in `try/except -> return 2`. That is easy
to write and easy to break later by moving one line of work outside the guard,
and NOTHING would notice: the checker would keep passing its own tests, because
its own tests exercise the paths that work.

WHAT THIS TEST DOES
===================
For each rule it replaces the scan function with one that raises, calls `main()`,
and requires rc=2. It also requires the failure to be ANNOUNCED rather than
swallowed — a silent 2 is a different defect with the same exit code.

MEASURED, WHICH IS WHY THE FAMILY IS TESTED AND NOT ASSUMED
===========================================================
One of these twelve shipped with a real instance of this class of error:
`every_required_metric_key_has_a_producer` computed its findings BEFORE checking
whether it had read any record, so over an empty corpus it printed nine
"STRUCTURALLY UNPROVABLE ... forever" lines and then returned NOT CHECKED. Its
exit code was correct and its output was an unearned claim, and its own tests
passed throughout, because they asserted the exit code.

chip-AGNOSTIC: exit codes and exception handling. No design, PDK or vendor literal.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

#: rule -> the name of the function that does its scanning.
SCANNERS = {
    "local_clone_does_not_borrow_objects": "audit",
    "prepared_checkout_states_the_revision_it_holds": "audit_source",
    "printed_remedy_runs_as_printed": "audit",
    "declared_basis_matches_the_session_inputs": "audit",
    "pytest_aggregate_carries_its_runtime_identity": "_walk",
    "explicit_argument_outranks_the_environment_pointer": "audit",
    "provenance_value_is_resolved_not_constant": "audit",
    "only_the_declaring_step_writes_its_output": "audit",
    "signoff_report_states_its_stage": "scan",
    "every_required_metric_key_has_a_producer": "evaluate",
    "measurement_only_artefact_is_not_a_verdict_source": "audit",
    "generated_values_state_whether_they_were_read_or_defaulted": "audit",
}


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("rule,scanner", sorted(SCANNERS.items()))
def test_a_crashing_scan_is_not_checked_never_a_finding(rule, scanner, tmp_path):
    """THE NEGATIVE CONTROL for the whole family: make the scan raise."""
    mod = _load(rule)
    assert hasattr(mod, scanner), (
        f"{rule} has no {scanner}() — this map has drifted from the source, and "
        f"a drifted map tests nothing")

    def boom(*a, **k):
        raise RuntimeError("injected: the scan itself blew up")

    setattr(mod, scanner, boom)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = mod.main([str(tmp_path)])
    except Exception as exc:                        # noqa: BLE001
        pytest.fail(f"{rule}: the exception ESCAPED main() "
                    f"({type(exc).__name__}), so the process would exit 1 and a "
                    f"crash would be read as a finding")
    assert rc == 2, (
        f"{rule}: a crashing scan returned rc={rc}. rc=1 is this family's code "
        f"for 'I found a defect', so a crash would be published as one.")
    said = (out.getvalue() + err.getvalue()).upper()
    assert "NOT CHECKED" in said, (
        f"{rule}: returned 2 but never said so — a silent NOT CHECKED is a "
        f"different defect with the same exit code:\n{said[:400]}")


@pytest.mark.parametrize("rule", sorted(SCANNERS))
def test_a_bad_invocation_is_three_not_one(rule, tmp_path):
    """rc=3 exists so 'you pointed me at nothing' cannot be read as a finding."""
    mod = _load(rule)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main([str(tmp_path / "does-not-exist")])
    assert rc == 3, f"{rule}: absent root returned rc={rc}, expected 3"


@pytest.mark.parametrize("rule", sorted(SCANNERS))
def test_an_empty_population_reports_no_finding(rule, tmp_path):
    """An empty tree has no defects for the same reason it has nothing else.

    Pinned across the family because one of the twelve shipped violating it:
    findings computed from a source other than the population being counted, so
    every axis looked unprovable when no record had been read.
    """
    mod = _load(rule)
    (tmp_path / "unrelated.py").write_text("x = 1\n")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = mod.main([str(tmp_path)])
    assert rc == 2, f"{rule}: empty tree returned rc={rc}, expected 2"
    findings = [ln for ln in out.getvalue().splitlines()
                if ln.strip() and not ln.startswith("examined")]
    assert not findings, (
        f"{rule}: an empty tree produced {len(findings)} finding line(s) on "
        f"stdout while returning NOT CHECKED — absence rendered as a "
        f"finding:\n" + "\n".join(findings[:5]))
