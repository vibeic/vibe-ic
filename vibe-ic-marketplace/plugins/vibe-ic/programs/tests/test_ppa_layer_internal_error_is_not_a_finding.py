#!/usr/bin/env python3
"""An internal error is rc=3. It is never rc=1, and never a silent red.

THE PATTERN THIS FILE IS ABOUT, WHICH THIS LAYER REPEATS FOUR TIMES
==================================================================
Somebody writes a guard, states the doctrine correctly in the comment beside
it, and guards one level too shallow. The next case along -- the one that is
the same defect wearing different clothes -- falls straight through.

    ppa_metric_extract.py    guarded `n_docs == 0` because "an empty bundle
                             would read as a clean run". A document that WAS
                             read and held zero records produced the identical
                             empty bundle and exited 0.

    ppa_contract_check.py    guarded `ImportError` on jsonschema because "this
                             is not the schema passing". jsonschema PRESENT but
                             older than 4.0 has no `Draft202012Validator`, so
                             the attribute lookup raised AttributeError,
                             propagated out of `raise SystemExit(main())`, and
                             the process exited 1 -- which §1 reserves for a
                             finding about the DESIGN.

    test_ppa_metrics_        `importorskip("jsonschema")` with a reason saying
    schema_agreement.py      "this is a SKIP and not a pass: nothing here
                             looked". Same version gap; every test in the file
                             FAILED instead of skipping, so "I could not check
                             it" and "I checked it and it was broken" produced
                             the same red.

    ppa_predict_aggregate.py the module docstring cites §2 on numeric sentinels
                             and the CLI estimated from `--cell-count 0`,
                             publishing `0.0 um^2` with rc=0.

MEASURED ON `e36d81c0a` (v1.11.33), on a host carrying jsonschema 3.2.0:
33 of the 46 shipped `test_*ppa*` files' failures had that ONE cause, and every
one of them was a red that said nothing true about the code under test.

WHY rc=1 IS THE SERIOUS HALF
============================
`PPA_INTERFACES.md` §1: "rc=1 is a claim about silicon. Do not use it to mean
'I could not look.'" A missing library reported as 1 means a flow gate blames a
design for the machine it ran on -- and unlike a 2, which a caller may treat as
"nothing to check here", a 1 stops a sign-off with a finding nobody can act on.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_TESTS))

from _ppa_jsonschema import HAVE_DRAFT_2020_12, REASON  # noqa: E402


def _run(args, timeout=120, env=None):
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, timeout=timeout, cwd=str(_PROGRAMS),
                          env=env)


def _a_minimal_contract(tmp_path) -> pathlib.Path:
    p = tmp_path / "contract.json"
    p.write_text(json.dumps({"schema": "vibeic.ppa.contract.v1"}),
                 encoding="utf-8")
    return p


def test_contract_check_never_exits_one_because_of_the_validator(tmp_path):
    """MUTATION ARM for the `Draft202012Validator` guard in
    `ppa_contract_check.schema_findings`.

    Remove the `hasattr(jsonschema, "Draft202012Validator")` branch and, on a
    host with jsonschema < 4, this goes red: the AttributeError escapes
    `raise SystemExit(main())` and the process exits 1.

    On a host WITH jsonschema >= 4 the guard is unreachable and cannot be
    mutated, so this test says so rather than pretending to have checked it --
    which is the file's own subject matter applied to itself.
    """
    if HAVE_DRAFT_2020_12:
        pytest.skip(
            "this host has a draft-2020-12 validator, so the guard under test "
            "is not reachable here and this arm did NOT exercise it. It is "
            "checked on a host with jsonschema < 4. Not a pass.")
    r = _run(["ppa_contract_check.py", "--contract",
              str(_a_minimal_contract(tmp_path))])
    assert "Traceback" not in r.stderr, (
        f"an uncaught exception escaped ppa_contract_check:\n{r.stderr[-800:]}")
    # §1 puts refusals on stderr, so the codes are looked for in BOTH streams.
    # An earlier version of this test read only stdout and reported a red that
    # said nothing true -- the exact failure mode the file is about.
    blob = r.stdout + r.stderr
    assert r.returncode != 1 or "PPA-C-0" in blob, (
        f"ppa_contract_check exited 1 without printing a single PPA-C code, so "
        f"the 1 is an internal error wearing a design finding's exit code. "
        f"§1 reserves 1 for a claim about silicon.\nstderr: {r.stderr[-600:]}")
    assert "Draft202012Validator" not in blob or "[UNDETERMINED]" in blob, (
        "the missing validator was mentioned but no UNDETERMINED finding was "
        "raised, so the shape went unvalidated with nothing saying so")


def test_contract_check_says_the_schema_was_not_applied(tmp_path):
    """The honest half: when the validator is unavailable, the program must
    SAY the shape was not validated, not fall silent about it.

    A refusal that does not name what it could not do is indistinguishable
    from a check that found nothing wrong.
    """
    if HAVE_DRAFT_2020_12:
        pytest.skip("validator present; the unavailable path is not reachable "
                    "here and was NOT exercised. Not a pass.")
    r = _run(["ppa_contract_check.py", "--contract",
              str(_a_minimal_contract(tmp_path))])
    blob = r.stdout + r.stderr
    assert "was NOT validated" in blob, (
        f"the contract's shape went unvalidated and nothing said so:\n"
        f"{blob[-600:]}")
    assert "Draft202012Validator" in blob, (
        "the refusal does not name WHY it could not validate, so a reader "
        "cannot tell a missing library from a malformed schema")


def test_the_jsonschema_capability_is_reported_not_assumed():
    """MUTATION ARM for `_ppa_jsonschema`.

    Delete the `hasattr` term from `HAVE_DRAFT_2020_12` and this goes red on a
    host with jsonschema < 4: the flag claims a capability the host does not
    have, and every test that trusts it fails with an AttributeError instead of
    skipping with a reason.
    """
    import importlib
    try:
        js = importlib.import_module("jsonschema")
    except ImportError:
        assert HAVE_DRAFT_2020_12 is False
        assert "not installed" in REASON
        return
    assert HAVE_DRAFT_2020_12 == hasattr(js, "Draft202012Validator"), (
        f"HAVE_DRAFT_2020_12 is {HAVE_DRAFT_2020_12} but "
        f"hasattr(jsonschema, 'Draft202012Validator') is "
        f"{hasattr(js, 'Draft202012Validator')}")
    assert "SKIP and NOT a pass" in REASON, (
        "the skip reason no longer says a skip is not a pass, which is the "
        "only thing stopping a reader from counting it as one")
    if not HAVE_DRAFT_2020_12:
        # Queried the supported way; `jsonschema.__version__` is deprecated in
        # 4.x and reading it here would emit a warning on every run.
        from importlib.metadata import version
        assert version("jsonschema") in REASON, (
            "the reason does not name the installed version, so a reader "
            "cannot tell this skip from a test that was switched off")


@pytest.mark.parametrize("prog", sorted(p.name for p in
                                        _PROGRAMS.glob("ppa_*.py")))
def test_no_ppa_program_lets_a_traceback_reach_the_exit_code(prog, tmp_path):
    """A layer sweep for the shape above.

    Every program is invoked against a JSON document that parses but is not
    what it wants. That is an ordinary, expected input -- a caller pointed the
    flag at the wrong file -- and it must produce a verdict, not a traceback.
    An uncaught exception exits 1 and §1 reserves 1 for a design finding.
    """
    junk = tmp_path / "junk.json"
    junk.write_text(json.dumps({"not": "what you wanted", "n": [1, 2, 3]}),
                    encoding="utf-8")
    j = str(junk)
    argv = {
        "ppa_area_threshold_check.py": ["--original", j, "--optimized", j,
                                        "--top", "t", "--threshold-pct", "1"],
        "ppa_closure_run.py": [str(tmp_path), "--edge", "32"],
        "ppa_contract_build.py": ["--declaration", j, "--root", str(tmp_path),
                                  "--out", str(tmp_path / "o.json")],
        "ppa_contract_check.py": ["--contract", j],
        # A well-formed JSON that is not a spare plan: it names no `count`, no
        # `instances` and no `tie_off`, so every row must come out
        # NOT_MEASURED with a reason rather than the reader falling over --
        # or, worse, defaulting a missing field to zero.
        "ppa_eco_spare_records.py": ["--spare-plan", j, "--stage",
                                     "post_route"],
        "ppa_feasibility_check.py": ["--candidates", j],
        "ppa_head_to_head_check.py": [j],
        "ppa_measurement_check.py": ["--coverage", j, "--expect", j],
        "ppa_metric_extract.py": ["--records", j],
        "ppa_page_claim_check.py": [j, "--claims", j],
        "ppa_pareto_check.py": ["--candidates", j],
        # A well-formed JSON that is not a search space: the audit must REFUSE
        # it (rc=1 with a [REFUSE] line), never fall over reading it.
        "ppa_pnr_search_space.py": ["--verify", j],
        "ppa_predict_aggregate.py": ["--cell-count", "1"],
        "ppa_problem_integrity_check.py": ["--baseline", j, "--candidate", j],
        "ppa_report_gen.py": [j],
        "ppa_search_run.py": [j],
    }.get(prog)
    if argv is None:
        pytest.fail(f"{prog} has no invocation in this file's table; its "
                    f"traceback arm is untested")
    r = _run([prog, *argv])
    assert "Traceback (most recent call last)" not in r.stderr, (
        f"{prog} let an exception reach the exit code on a well-formed JSON "
        f"document that is not what it wanted. That exits 1, and §1 reserves "
        f"1 for a finding about a design.\n{r.stderr[-700:]}")
    assert r.returncode in (0, 1, 2, 3), (
        f"{prog} exited {r.returncode}, which is not one of the four codes "
        f"PPA_INTERFACES §1 defines")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
