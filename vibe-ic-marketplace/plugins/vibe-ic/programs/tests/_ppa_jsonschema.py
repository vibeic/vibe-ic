"""One place the PPA test tree asks whether a JSON Schema can be applied here.

THE GUARD THAT WAS WRITTEN ONE LEVEL TOO SHALLOW
================================================
`test_ppa_metrics_schema_agreement.py` opens with

    jsonschema = pytest.importorskip(
        "jsonschema",
        reason="jsonschema is not installed, so the published schema was NOT
                checked ... This is a SKIP and not a pass: nothing here
                looked.")

which is exactly the right doctrine and covers exactly one of the two ways the
validator can be unavailable. The other is that jsonschema IS installed and is
too old: `Draft202012Validator` arrived in jsonschema 4.0, and on 3.2.0 the
attribute lookup raises `AttributeError` in the middle of a test.

Measured on this machine (jsonschema 3.2.0), on pristine `e36d81c0a`:

    33 of the 46 shipped ppa test files' failures had this single cause

and every one of them reported as a FAILURE -- which is the verdict the
docstring above forbids, because "I could not check it" and "I checked it and
it was broken" became the same red.

`ppa_contract_check.py` had the identical shape in production: it guarded
`ImportError` and not the version, so an uncaught `AttributeError` propagated
out of `raise SystemExit(main())` and the process exited **1**, which
`PPA_INTERFACES.md` §1 reserves for a finding about the DESIGN. A missing
library was indistinguishable from a broken contract. That one is fixed in the
program; this module is the same fix for the tests.

WHY A SKIP AND NOT A FAILURE, AND WHY IT IS A *DECLARED* SKIP
=============================================================
Because it is true: on a host without a draft-2020-12 validator the published
schema genuinely was not applied, and the honest verdict for "I could not look"
is neither pass nor fail.

But a bare `pytest.skip` is the same lie one level up -- `programs/tests/
test_not_verified_tier.py` exists because an infrastructure-shaped skip that
did not go through `not_verified_tier` is invisible to the roll-up, and "the
run reported no failures" then covers a verification that never happened
(vibe-ic#1128). The skip below therefore carries the tier's SENTINEL and a
REMEDY, so it appears in the not-verified roll-up as an unanswered question
with the command that would answer it, rather than as thirty quiet green
ticks.

RECONCILED 2026-08-21 — THE OTHER HALF OF THIS FIX LANDED IN THE SAME BATCH
===========================================================================
This module probed `jsonschema` directly and SKIPPED when the host had no
draft-2020-12 validator. `_ppa/schema_validation.py` (lane
jsearch2/space-and-feasibility) answers the same question and then does one
more thing: it BUNDLES an engine, so a bare host can still apply the schema.

Merged naively the two coexist and disagree in the worst direction — the tests
behind this marker skip for want of a validator that the tree now ships, and
`test_jsonschema_is_imported_in_exactly_one_place` fails because this file is a
second place `jsonschema` is named.

So the probe MOVED rather than being duplicated. Availability is now asked of
`_ppa/schema_validation.resolve()`, which means:

  * the tests behind `needs_draft_2020_12` RUN on a host with no jsonschema
    installed, against the bundled engine, instead of skipping;
  * the declared-skip doctrine below is unchanged and still fires — but only
    when NEITHER engine can serve, which is the only case where "nothing
    looked" is still true;
  * `jsonschema` is named in exactly one place in the tree, which is the
    property that guard exists to hold.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from not_verified_tier import not_verified_reason  # noqa: E402
from _ppa import schema_validation as _SV  # noqa: E402

#: The minimal schema that asks "can a draft-2020-12 document be validated
#: here?" -- resolved through the ONE module allowed to name `jsonschema`, so
#: this file inherits the version probe, the bundled fallback and the refusal
#: instead of reimplementing the first and missing the second.
_PROBE = {"$schema": "https://json-schema.org/draft/2020-12/schema"}

_ENGINE, _NOTES = _SV.resolve(_PROBE)
HAVE_DRAFT_2020_12 = _ENGINE is not None

_REMEDY = "python3 -m pip install 'jsonschema>=4'"

REASON = not_verified_reason(
    "no draft-2020-12 validator could be resolved here -- neither the "
    "installed jsonschema nor the bundled engine could serve the published "
    "schemas, so none was applied in this session. This is a SKIP and NOT a "
    "pass: nothing looked. " + " ".join(_NOTES),
    _REMEDY)


#: Decorator for a single test that cannot run without a 2020-12 validator.
needs_draft_2020_12 = pytest.mark.skipif(not HAVE_DRAFT_2020_12, reason=REASON)


def require_draft_2020_12():
    """Module-level guard. Returns the resolved ENGINE, or skips the file.

    The return type changed with the reconciliation above: it was the raw
    `jsonschema` module and is now a `_ppa/schema_validation.Engine`, because
    on a bare host there is no module to hand back and there IS a working
    engine. Callers that only need the marker should use
    `needs_draft_2020_12`; the repository has no other caller of this function.
    """
    if not HAVE_DRAFT_2020_12:
        pytest.skip(REASON, allow_module_level=True)
    return _ENGINE
