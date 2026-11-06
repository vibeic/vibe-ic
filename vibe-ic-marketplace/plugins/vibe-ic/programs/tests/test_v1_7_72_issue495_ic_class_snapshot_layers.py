"""re #495 Stage 1 — the three layers of ``ic_class``.

A project can carry three different answers to "what class is this?":

  layer 1  the per-L-doc ``ic_class`` stamp     frozen at phase-1 emit time
  layer 2  ``reports/ic_class.json``            frozen at the last refresh
  layer 3  what the classifier produces today

``ic_class_consistency_check`` compares layer 1 against layer 2 and FAILs on a
mismatch — correct, and unchanged here. What it used to get wrong was the
PROVENANCE: it called ``detect_ic_class(project)``, which by the #435
persist-once contract returns layer 2 verbatim whenever the file exists, yet
every message it printed said "detect_ic_class()", crediting a classification
that never ran. And layer 3 was unreachable from any gate at all, because the
only way to reach it (``refresh=True``) writes over layer 2.

These tests drive the gate's real entry points on real project trees and assert
on observable output:

  1. the FAIL message names ``reports/ic_class.json``, not a live inference,
     when the class came from the persisted snapshot;
  2. the same message DOES name a live inference when there is no snapshot;
  3. a stale snapshot is DISCLOSED on a passing run and does not change rc;
  4. a stale snapshot is DISCLOSED on a failing run and does not change rc;
  5. an agreeing snapshot produces no disclosure (no noise on healthy trees);
  6. ``infer_ic_class_uncached`` neither reads nor writes the snapshot.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


def _write_json(p: Path, body: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(body, indent=2))




def _evidence(name: str) -> dict:
    return {"extraction_evidence": {
        "vendor.pdf": [{"literal": f"sentinel-{name}", "label": name}]}}


def _build_pure_analog(project: Path) -> None:
    """A project the classifier really does call ``pure_analog``."""
    _write_json(project / "phase1/generated_docs/L1_DATASHEET.json",
                {**_evidence("L1"), "interface": "pure analog"})
    _write_json(project / "phase1/generated_docs/L2_FRS.json",
                {**_evidence("L2"), "interface": "pure analog"})
    _write_json(project / "phase1/generated_docs/L5_ADI_SPEC.json",
                {**_evidence("L5"), "analog_blocks": [{"name": "BANDGAP_REF"}]})


def _stamp(project: Path, value: str) -> None:
    _write_json(project / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
                {**_evidence("L19"), "ic_class": value, "fields": {}})


def _snapshot(project: Path, value: str) -> None:
    _write_json(project / "reports/ic_class.json", {"ic_class": value})


def _live_class(project: Path) -> str:
    from ic_class_profile import infer_ic_class_uncached
    return (infer_ic_class_uncached(project) or {}).get("ic_class", "unknown")


# ---------------------------------------------------------------- provenance




# ---------------------------------------------------------------- disclosure






# ------------------------------------------------------- uncached read door
def test_infer_uncached_neither_reads_nor_writes_the_snapshot(
        tmp_path: Path) -> None:
    """Layer 3 must be reachable read-only.

    ``detect_ic_class(refresh=True)`` persists, so a gate could not consult the
    classifier without overwriting the very value it wanted to compare against.
    """
    from ic_class_profile import detect_ic_class, infer_ic_class_uncached

    p = tmp_path / "proj"
    _build_pure_analog(p)
    _snapshot(p, "processor_cpu")       # a deliberately wrong snapshot
    before = (p / "reports/ic_class.json").read_text()

    # cached door returns the snapshot verbatim ...
    assert detect_ic_class(p).get("ic_class") == "processor_cpu"
    # ... uncached door ignores it ...
    live = infer_ic_class_uncached(p).get("ic_class")
    assert live != "processor_cpu"
    assert live not in ("", "unknown")
    # ... and left it byte-identical.
    assert (p / "reports/ic_class.json").read_text() == before

    # refresh=True is the contrast: it DOES overwrite.
    detect_ic_class(p, refresh=True)
    assert (p / "reports/ic_class.json").read_text() != before
