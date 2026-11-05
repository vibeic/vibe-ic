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

import pathlib
import sys

import pytest

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_TESTS))

from _ppa_jsonschema import HAVE_DRAFT_2020_12, REASON  # noqa: E402
sys.path.insert(0, str(_PROGRAMS))

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


#: Why this file's "validator unavailable" arm does not run on a normal host.
#: NOT a bare `pytest.skip`: `test_not_verified_tier` exists because an
#: infrastructure-shaped skip that bypasses the tier is invisible to the roll-up,
#: and "the run reported no failures" then covers a question nobody answered.












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




if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
