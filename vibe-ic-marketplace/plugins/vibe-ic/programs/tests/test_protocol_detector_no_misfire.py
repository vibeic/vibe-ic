"""Universal protocol-detector no-misfire guard (captured v0.1.93).

THE COMPOUNDING ARTIFACT of the Tier-D/E/F protocol sweeps. Instead of a
hand-written per-tier sweep for each new batch (test_tier_d/e/f_*), this test
AUTO-DISCOVERS every module-level ``is_<stem>`` detector exported by a
``<stem>_protocol_synth.py`` and asserts each fires ONLY on its own benchmark's
content. Any future protocol that follows the convention (module-level
``is_<stem>`` in ``<stem>_protocol_synth.py``) is covered with ZERO new test code.

Why this exists — the v0.1.89 KEY LESSON, re-earned in v0.1.93:
  A content-only protocol detector can silently over-fire on a FOREIGN benchmark
  because the runner enumerates a generic bus vocabulary (``AXI/APB/AHB/Wishbone/
  Avalon/TileLink/OCP/...``) and L9 interface_types regexes that inject protocol
  NAME tokens into other docs' generated L-docs. A detector keyed on a name-token
  alone then fires on docs that merely *list* it as a candidate interface, and —
  because the synth force-overwrites to 0 gated — parity (which excludes
  SHAPE_MISMATCH per R28 and lists per R32) never reveals it. The v0.1.93 sweep
  caught ``is_avalon`` firing on ethercat/hdlc/modbus exactly this way. A
  full-content no-misfire sweep is the only thing that catches it.

Coverage note (honest): only protocols whose detector is a module-level
``is_<stem>`` predicate are auto-covered here. ~47 older protocols keep their
detector INLINE in ``phase1_doc_one_shot_runner.py`` and are NOT importable —
see ORGANIC-20260531-inline-protocol-detectors-not-importable to lift them into
importable predicates so this guard covers all ~57.
"""
import glob
import importlib
import os
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(__file__).resolve().parents[5]
BP = REPO_ROOT / "benchmark_phase1"


def _discover_detectors():
    """{stem: callable} for every <stem>_protocol_synth.py exposing is_<stem>."""
    found = {}
    for p in sorted(PROGRAMS_DIR.glob("*_protocol_synth.py")):
        stem = p.name[: -len("_protocol_synth.py")]
        try:
            mod = importlib.import_module(f"{stem}_protocol_synth")
        except Exception:
            continue
        fn = getattr(mod, f"is_{stem}", None)
        if callable(fn):
            found[stem] = fn
    return found


def _blob_for(b: str) -> str:
    parts = []
    for p in (glob.glob(str(BP / b / "phase1" / "input_doc" / "*"))
              + glob.glob(str(BP / b / "phase1" / "generated_docs" / "*.json"))):
        try:
            parts.append(Path(p).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(parts)


DETECTORS = _discover_detectors()


def test_at_least_the_known_module_level_detectors_are_discovered():
    # Tier-E + Tier-F shipped module-level detectors; guard against an import
    # regression silently emptying the discovery set (which would make the
    # no-misfire test vacuously pass).
    expected = {
        "flexray", "displayport", "jesd204", "smbus_pmbus",   # Tier-E
        "sas", "avalon", "hyperbus", "qspi_ospi", "mipi_spmi_rffe",  # Tier-F
    }
    missing = expected - set(DETECTORS)
    assert not missing, f"expected module-level detectors not discovered: {missing}"


def test_every_detector_is_callable_and_empty_safe():
    for stem, fn in DETECTORS.items():
        assert fn("") is False, f"is_{stem}('') should be False"
        assert fn(None) is False, f"is_{stem}(None) should be False"  # type: ignore[arg-type]


@pytest.mark.skipif(not BP.is_dir(), reason="benchmark_phase1 fixtures absent")
def test_no_detector_fires_on_a_foreign_benchmark():
    """Each auto-discovered detector must fire ONLY on its own benchmark.

    Content SUPERSET (input_doc + every generated L-doc) — stricter than the
    runner's actual blob — so zero foreign fires here ⇒ zero in the runner.
    """
    benches = sorted(d for d in os.listdir(BP) if (BP / d).is_dir() and _blob_for(d))
    blobs = {b: _blob_for(b) for b in benches}
    misfires = []
    own_fires = set()
    for stem, fn in DETECTORS.items():
        for b in benches:
            if fn(blobs[b]):
                if b == stem:
                    own_fires.add(stem)
                else:
                    misfires.append((stem, b))
    assert not misfires, f"protocol detector mis-fires (foreign benchmark): {misfires}"
    # Each detector whose own benchmark dir is present must self-fire.
    for stem in DETECTORS:
        if stem in blobs:
            assert stem in own_fires, f"is_{stem} failed to fire on its own benchmark"
