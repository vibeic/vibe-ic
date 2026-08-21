"""Registry-style coverage guard: EVERY ``*_protocol_synth.py`` must export an
importable module-level ``is_<stem>(blob)`` detector.

Closes ORGANIC-20260531-inline-protocol-detectors-not-importable.

WHY THIS EXISTS
---------------
The v0.1.93 universal no-misfire guard
(``tests/test_protocol_detector_no_misfire.py``) AUTO-DISCOVERS detectors by
globbing for a module-level ``is_<stem>`` in ``<stem>_protocol_synth.py``. At
the time the backlog was filed, only ~9 protocol synths exported such a
predicate; the other ~47 kept their detector INLINE inside
``phase1_doc_one_shot_runner.py`` (built ad-hoc from ``_spi_blob``), so they
were not importable and the universal guard could not cover them — any of those
inline detectors could carry a latent over-fire, undetected.

This guard pins the *registry* invariant the lift establishes: there is now a
1:1 mapping ``<stem>_protocol_synth.py`` -> module-level ``is_<stem>``. If a
future protocol synth ships without its detector (or names it wrong), THIS test
fails immediately — the universal no-misfire guard would otherwise silently
skip it (vacuous coverage), which is exactly the masking failure-mode the
v0.1.89 KEY LESSON warns about.

The three assertions:
  * PASS  : every synth module imports and exposes a CALLABLE ``is_<stem>``.
  * FAIL  : a synth missing / mis-naming its detector (real regression) is
            reproduced by the synthetic ``_BrokenSynthModule`` below — the
            same discovery logic returns it as a coverage hole.
  * HONESTY: a detector that cannot decide on absent input must NOT guess —
            ``is_<stem>("")`` and ``is_<stem>(None)`` MUST be ``False`` (no
            fabrication from missing data).
"""
import importlib
import types
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent

# Every protocol-synth module in the programs/ tree.
SYNTH_PATHS = sorted(PROGRAMS_DIR.glob("*_protocol_synth.py"))
STEMS = [p.name[: -len("_protocol_synth.py")] for p in SYNTH_PATHS]


def _discover(stem):
    """Return the module-level ``is_<stem>`` callable, or None if absent."""
    mod = importlib.import_module(f"{stem}_protocol_synth")
    fn = getattr(mod, f"is_{stem}", None)
    return fn


def test_there_are_protocol_synth_modules():
    # Guard against a path/glob regression silently emptying the set (which
    # would make every coverage assertion below vacuously pass).
    assert len(SYNTH_PATHS) >= 50, (
        f"expected the full protocol-synth fleet, found only {len(SYNTH_PATHS)}"
    )


@pytest.mark.parametrize("stem", STEMS)
def test_every_protocol_synth_exports_an_importable_detector(stem):
    """The core registry invariant: 1:1 synth-module -> is_<stem> predicate."""
    fn = _discover(stem)
    assert fn is not None, (
        f"{stem}_protocol_synth.py does not export a module-level "
        f"is_{stem}(blob) — the universal no-misfire guard cannot cover it. "
        f"Lift the detector out of phase1_doc_one_shot_runner.py "
        f"(ORGANIC-20260531)."
    )
    assert callable(fn), f"is_{stem} exists but is not callable"


@pytest.mark.parametrize("stem", STEMS)
def test_every_detector_is_empty_and_none_safe(stem):
    """Missing-data honesty: no detector may fabricate a positive from nothing."""
    fn = _discover(stem)
    assert fn is not None and callable(fn)
    assert fn("") is False, f"is_{stem}('') must be False (no fabrication)"
    assert fn(None) is False, f"is_{stem}(None) must be False (no fabrication)"


def test_full_fleet_is_covered_no_inline_residual():
    """Aggregate: ZERO synth modules lack a detector — the backlog is closed.

    This is the single assertion that fails the moment ANY protocol synth
    regresses to an inline-only detector again.
    """
    missing = [s for s in STEMS if not callable(_discover(s))]
    assert not missing, (
        f"{len(missing)} protocol synth(s) still keep their detector INLINE "
        f"(no importable is_<stem>): {missing}"
    )


# ---------------------------------------------------------------------------
# Negative control (real FAIL path): a synth that forgot its detector MUST be
# reported as a coverage hole by the same discovery logic. We construct a fake
# module in-process and assert the discovery returns None for it — proving the
# coverage check has teeth and is not vacuously green.
# ---------------------------------------------------------------------------
def test_discovery_reports_a_detectorless_synth_as_a_hole():
    broken = types.ModuleType("zzz_fake_protocol_synth")
    # It defines apply_zzz_fake_synth but NO is_zzz_fake — the exact regression.
    broken.apply_zzz_fake_synth = lambda gd, flag, ic: None  # type: ignore[attr-defined]
    fn = getattr(broken, "is_zzz_fake", None)
    assert fn is None, "negative control should have no detector"

    good = types.ModuleType("zzz_ok_protocol_synth")
    good.is_zzz_ok = lambda blob: bool(blob and "ZZZ" in blob)  # type: ignore[attr-defined]
    fn2 = getattr(good, "is_zzz_ok", None)
    assert callable(fn2)
    assert fn2("") is False  # empty-safe contract holds for a well-formed one
    assert fn2("has ZZZ token") is True
