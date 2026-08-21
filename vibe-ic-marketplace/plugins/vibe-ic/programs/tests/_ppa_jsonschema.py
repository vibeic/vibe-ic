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
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from not_verified_tier import not_verified_reason  # noqa: E402
from _ppa import schema_validation as _SV  # noqa: E402

# THE REFERENCE LIBRARY, ASKED FOR THROUGH THE ONE PLACE THAT NAMES IT.
# This module used to say `import jsonschema` here. It is not allowed to any
# more, and the rule is not bookkeeping: `_ppa/schema_validation.py` carries
# the version probe, the bundled fallback and the refusal, and a second import
# site is a second place that has to get the version question right — which is
# exactly the shape of the defect this module was written to fix, one level up.
# `test_ppa_schema_validation.test_jsonschema_is_imported_in_exactly_one_place`
# names this file by path when it drifts back.
#
# WHY THE REFERENCE AND NOT `resolve()`. The tests this module guards call
# `jsonschema.Draft202012Validator(...)` THEMSELVES, as an independent
# cross-check on `_ppa/metrics.validate` and on the shipped schemas. Asking
# `resolve()` would hand them the bundled engine on a bare host and the
# cross-check would then be this plugin agreeing with itself. So the question
# stays "is the REFERENCE implementation usable here", and when it is not the
# honest verdict is still the declared skip below.
_js = _SV.reference_library()

def _installed_version():
    """The version, without touching `jsonschema.__version__`.

    That attribute is deprecated in jsonschema 4.x and emits a warning on
    every access, which would put a DeprecationWarning in front of every run
    that imports this module. `importlib.metadata` is the supported query and
    is present on every Python this repository targets.
    """
    if _js is None:
        return None
    try:
        from importlib.metadata import PackageNotFoundError, version
        return version("jsonschema")
    except Exception:                             # pragma: no cover
        return None


_VERSION = _installed_version()
HAVE_DRAFT_2020_12 = _js is not None and hasattr(_js, "Draft202012Validator")

_REMEDY = "python3 -m pip install 'jsonschema>=4'"

if _js is None:
    REASON = not_verified_reason(
        "jsonschema is not installed, so no published schema was applied in "
        "this session. This is a SKIP and NOT a pass: nothing looked.",
        _REMEDY)
else:
    REASON = not_verified_reason(
        f"jsonschema {_VERSION} has no Draft202012Validator (it arrived in "
        f"4.0), so the published draft-2020-12 schemas were NOT applied in "
        f"this session. This is a SKIP and NOT a pass: nothing looked.",
        _REMEDY)

#: Decorator for a single test that cannot run without a 2020-12 validator.
needs_draft_2020_12 = pytest.mark.skipif(not HAVE_DRAFT_2020_12, reason=REASON)


def require_draft_2020_12():
    """Module-level guard. Returns the jsonschema module or skips the file."""
    if not HAVE_DRAFT_2020_12:
        pytest.skip(REASON, allow_module_level=True)
    return _js
